"""Authentication helpers for the QA Lens web server."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlencode

import httpx
from fastapi.responses import HTMLResponse, RedirectResponse

if TYPE_CHECKING:
    from fastapi import Request

AUTH_MODE_ENV = "QALENS_AUTH_MODE"
AUTH_TOKEN_ENV = "QALENS_AUTH_TOKEN"
GITHUB_CLIENT_ID_ENV = "QALENS_GITHUB_CLIENT_ID"
GITHUB_CLIENT_SECRET_ENV = "QALENS_GITHUB_CLIENT_SECRET"
GITHUB_CALLBACK_URL_ENV = "QALENS_GITHUB_CALLBACK_URL"
GITHUB_ALLOWED_USERS_ENV = "QALENS_ALLOWED_GITHUB_USERS"
GITHUB_ALLOWED_ORGS_ENV = "QALENS_ALLOWED_GITHUB_ORGS"
GITHUB_ADMIN_USERS_ENV = "QALENS_ADMIN_GITHUB_USERS"
SESSION_SECRET_ENV = "QALENS_SESSION_SECRET"

SESSION_COOKIE_NAME = "qalens_session"
OAUTH_STATE_COOKIE_NAME = "qalens_oauth_state"
SESSION_TTL_SECONDS = 8 * 60 * 60
_OAUTH_STATE_TTL = 600  # 10 minutes

AuthMode = Literal["none", "token", "github"]

# In-process OAuth state store: avoids cookie-domain mismatches (localhost vs 127.0.0.1).
# Values are expiry timestamps; entries are pruned lazily on each new registration.
_oauth_state_store: dict[str, float] = {}


def _register_oauth_state(state: str) -> None:
    now = time.time()
    _oauth_state_store[state] = now + _OAUTH_STATE_TTL
    expired = [k for k, v in _oauth_state_store.items() if v < now]
    for k in expired:
        del _oauth_state_store[k]


def _consume_oauth_state(state: str) -> bool:
    """Return True and remove the state token if it is valid and unexpired."""
    exp = _oauth_state_store.pop(state, None)
    return exp is not None and exp > time.time()


@dataclass(frozen=True)
class AuthConfig:
    """Resolved authentication configuration for a QA Lens server."""

    mode: AuthMode
    token: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_callback_url: str | None = None
    session_secret: str | None = None
    allowed_github_users: frozenset[str] = frozenset()
    allowed_github_orgs: frozenset[str] = frozenset()
    admin_github_users: frozenset[str] = frozenset()


@dataclass(frozen=True)
class GitHubUser:
    """Authenticated GitHub user details stored in the QA Lens session."""

    login: str
    name: str | None
    avatar_url: str | None
    html_url: str | None


def resolve_auth_config(auth_token: str | None = None) -> AuthConfig:
    """Resolve auth mode from CLI arguments and environment variables."""
    explicit_mode = os.environ.get(AUTH_MODE_ENV, "").strip().lower()
    token = resolve_auth_token(auth_token)
    if explicit_mode == "github":
        return AuthConfig(
            mode="github",
            token=token,
            github_client_id=_env_value(GITHUB_CLIENT_ID_ENV),
            github_client_secret=_env_value(GITHUB_CLIENT_SECRET_ENV),
            github_callback_url=_env_value(GITHUB_CALLBACK_URL_ENV),
            session_secret=_env_value(SESSION_SECRET_ENV),
            allowed_github_users=_csv_env(GITHUB_ALLOWED_USERS_ENV),
            allowed_github_orgs=_csv_env(GITHUB_ALLOWED_ORGS_ENV),
            admin_github_users=_csv_env(GITHUB_ADMIN_USERS_ENV),
        )
    if explicit_mode == "token":
        return AuthConfig(mode="token", token=token)
    if explicit_mode and explicit_mode != "none":
        return AuthConfig(mode="none")
    if token:
        return AuthConfig(mode="token", token=token)
    return AuthConfig(mode="none")


def resolve_auth_token(auth_token: str | None = None) -> str | None:
    """Return the configured admin token, if one is set."""
    token = auth_token if auth_token is not None else os.environ.get(AUTH_TOKEN_ENV)
    token = (token or "").strip()
    return token or None


def bearer_token_from_request(request: Request) -> str | None:
    """Extract a bearer token from the request Authorization header."""
    header = request.headers.get("authorization", "").strip()
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()


def request_has_valid_token(request: Request, expected_token: str | None) -> bool:
    """Return True when auth is disabled or the request has the expected token."""
    if expected_token is None:
        return True
    provided = bearer_token_from_request(request)
    return provided is not None and hmac.compare_digest(provided, expected_token)


def request_user(request: Request, config: AuthConfig) -> GitHubUser | None:
    """Return the GitHub user from the signed session cookie, when valid."""
    if config.mode != "github" or not config.session_secret:
        return None
    payload = _verify_session(request.cookies.get(SESSION_COOKIE_NAME), config.session_secret)
    if payload is None:
        return None
    login = str(payload.get("login", "")).strip()
    if not login:
        return None
    return GitHubUser(
        login=login,
        name=_optional_str(payload.get("name")),
        avatar_url=_optional_str(payload.get("avatar_url")),
        html_url=_optional_str(payload.get("html_url")),
    )


def request_is_authenticated(request: Request, config: AuthConfig) -> bool:
    """Return whether the request is authenticated under the configured mode."""
    if config.mode == "none":
        return True
    if config.mode == "token":
        return request_has_valid_token(request, config.token)
    return request_user(request, config) is not None


def is_admin_user(request: Request, config: AuthConfig) -> bool:
    """Return whether the requester has admin (Settings) access.

    - none / token mode: anyone who is authenticated is an admin.
    - github mode: if QALENS_ADMIN_GITHUB_USERS is set, only those logins are
      admins; otherwise every authenticated GitHub user is an admin.
    """
    if not request_is_authenticated(request, config):
        return False
    if config.mode != "github":
        return True
    if not config.admin_github_users:
        return True
    user = request_user(request, config)
    if user is None:
        return False
    return user.login.strip().lower() in config.admin_github_users


def github_config_ready(config: AuthConfig) -> bool:
    """Return whether all mandatory GitHub OAuth settings are present."""
    return bool(
        config.github_client_id
        and config.github_client_secret
        and config.session_secret
    )


def github_start_response(request: Request, config: AuthConfig) -> RedirectResponse:
    """Return a redirect response to GitHub's OAuth authorization endpoint."""
    if config.mode != "github" or not github_config_ready(config):
        return RedirectResponse("/login?error=github_auth_not_configured", status_code=303)
    state = secrets.token_urlsafe(32)
    _register_oauth_state(state)
    # Omit redirect_uri so GitHub uses the registered callback URL directly.
    # Sending a redirect_uri that doesn't byte-for-byte match the registered
    # one (e.g. localhost vs 127.0.0.1) causes the "not associated" error.
    params = urlencode({
        "client_id": config.github_client_id,
        "scope": "read:user read:org",
        "state": state,
    })
    return RedirectResponse(
        f"https://github.com/login/oauth/authorize?{params}",
        status_code=303,
    )


async def github_callback_response(request: Request, config: AuthConfig) -> RedirectResponse:
    """Handle the GitHub OAuth callback and set a QA Lens session cookie."""
    if config.mode != "github" or not github_config_ready(config):
        return RedirectResponse("/login?error=github_auth_not_configured", status_code=303)

    state = request.query_params.get("state", "")
    if not state or not _consume_oauth_state(state):
        return RedirectResponse("/login?error=invalid_oauth_state", status_code=303)

    code = request.query_params.get("code", "")
    if not code:
        return RedirectResponse("/login?error=missing_oauth_code", status_code=303)

    callback = config.github_callback_url or str(request.url_for("github_callback"))
    try:
        user, orgs = await _fetch_github_identity(code=code, callback_url=callback, config=config)
    except httpx.HTTPError:
        return RedirectResponse("/login?error=github_oauth_failed", status_code=303)

    if not _github_user_allowed(user.login, orgs, config):
        return RedirectResponse("/login?error=github_user_not_allowed", status_code=303)

    payload = {
        "login": user.login,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "html_url": user.html_url,
        "iat": int(time.time()),
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
    }
    response = RedirectResponse("/", status_code=303)
    _set_cookie(
        response,
        SESSION_COOKIE_NAME,
        _sign_session(payload, config.session_secret or ""),
        max_age=SESSION_TTL_SECONDS,
        secure=callback.startswith("https://"),
    )
    return response


def logout_response() -> RedirectResponse:
    """Clear QA Lens auth cookies and return to the login page."""
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(OAUTH_STATE_COOKIE_NAME, path="/")
    return response


def login_page(config: AuthConfig, error: str | None = None) -> HTMLResponse:
    """Return a server-rendered GitHub sign-in page."""
    configured = github_config_ready(config)
    error_html = (
        f"""<div class="alert" role="alert">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8Z" fill="currentColor"/>
        <path d="M7.25 5a.75.75 0 0 1 1.5 0v3.25a.75.75 0 0 1-1.5 0V5Zm.75 5.5a.875.875 0 1 1 0 1.75.875.875 0 0 1 0-1.75Z" fill="currentColor"/>
      </svg>
      {_html_escape(_login_error_message(error))}
    </div>"""
        if error
        else ""
    )
    disabled_attr = "" if configured else " disabled"
    misconfigured_banner = (
        """<div class="misconfigured" role="alert">
      GitHub OAuth environment variables are not set on this server.
      Contact your administrator.
    </div>"""
        if not configured
        else ""
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sign in — QA Lens</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    @keyframes bg-shift {{
      0%   {{ background-position: 0% 50%; }}
      50%  {{ background-position: 100% 50%; }}
      100% {{ background-position: 0% 50%; }}
    }}
    :root {{
      --bg:      #f1f5f9;
      --card:    #ffffff;
      --border:  #e2e8f0;
      --text:    #0f172a;
      --muted:   #64748b;
      --subtle:  #94a3b8;
      --accent:  #6366f1;
      --btn-bg:  #0f172a;
      --btn-fg:  #ffffff;
      --err-bg:  #fef2f2;
      --err-fg:  #b91c1c;
      --err-bd:  #fecaca;
      --warn-bg: #fffbeb;
      --warn-fg: #92400e;
      --warn-bd: #fde68a;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg:      #020617;
        --card:    #0f172a;
        --border:  #1e293b;
        --text:    #f1f5f9;
        --muted:   #94a3b8;
        --subtle:  #64748b;
        --accent:  #818cf8;
        --btn-bg:  #6366f1;
        --btn-fg:  #ffffff;
        --err-bg:  #1c0a0a;
        --err-fg:  #fca5a5;
        --err-bd:  #7f1d1d;
        --warn-bg: #1c1400;
        --warn-fg: #fcd34d;
        --warn-bd: #78350f;
      }}
    }}
    body {{
      margin: 0;
      min-height: 100dvh;
      display: grid;
      place-items: center;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--text);
      background: linear-gradient(
        135deg,
        var(--bg) 0%,
        color-mix(in srgb, var(--accent) 6%, var(--bg)) 50%,
        var(--bg) 100%
      );
      background-size: 400% 400%;
      animation: bg-shift 14s ease infinite;
    }}
    .card {{
      width: min(400px, calc(100vw - 32px));
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 20px;
      box-shadow: 0 24px 60px rgb(0 0 0 / 0.10), 0 1px 3px rgb(0 0 0 / 0.06);
      padding: 36px 32px 28px;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 28px;
    }}
    .brand-name {{
      font-size: 20px;
      font-weight: 800;
      letter-spacing: -0.5px;
      color: var(--text);
    }}
    .brand-name span {{ color: var(--accent); }}
    h1 {{
      margin: 0 0 6px;
      font-size: 26px;
      font-weight: 700;
      line-height: 1.2;
      letter-spacing: -0.4px;
    }}
    .tagline {{
      margin: 0 0 24px;
      font-size: 14px;
      color: var(--muted);
      line-height: 1.6;
    }}
    hr {{
      border: none;
      border-top: 1px solid var(--border);
      margin: 0 0 24px;
    }}
    .btn {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      width: 100%;
      padding: 13px 18px;
      border-radius: 12px;
      background: var(--btn-bg);
      color: var(--btn-fg);
      font-size: 15px;
      font-weight: 700;
      text-decoration: none;
      transition: opacity .15s, transform .1s;
      user-select: none;
    }}
    .btn:hover  {{ opacity: .88; transform: translateY(-1px); }}
    .btn:active {{ opacity: 1;   transform: translateY(0); }}
    .btn[disabled] {{
      pointer-events: none;
      opacity: .4;
      cursor: not-allowed;
    }}
    .alert {{
      display: flex;
      align-items: flex-start;
      gap: 8px;
      margin-top: 16px;
      padding: 11px 13px;
      border: 1px solid var(--err-bd);
      border-radius: 10px;
      background: var(--err-bg);
      color: var(--err-fg);
      font-size: 13.5px;
      line-height: 1.5;
    }}
    .alert svg {{ flex-shrink: 0; margin-top: 1px; }}
    .misconfigured {{
      margin-top: 16px;
      padding: 11px 13px;
      border: 1px solid var(--warn-bd);
      border-radius: 10px;
      background: var(--warn-bg);
      color: var(--warn-fg);
      font-size: 13px;
      line-height: 1.5;
    }}
    .footer {{
      margin-top: 20px;
      text-align: center;
      font-size: 12px;
      color: var(--subtle);
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="brand">
      <svg width="32" height="32" viewBox="0 0 32 32" fill="none" aria-hidden="true">
        <rect width="32" height="32" rx="8" fill="#6366f1"/>
        <path d="M8 22 L16 10 L24 22" stroke="white" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
        <circle cx="16" cy="10" r="2.2" fill="white"/>
        <circle cx="8"  cy="22" r="2.2" fill="white"/>
        <circle cx="24" cy="22" r="2.2" fill="white"/>
      </svg>
      <span class="brand-name">QA Lens</span>
    </div>

    <h1>Sign in to QA Lens</h1>
    <p class="tagline">Test intelligence. Failure analysis. Root cause &mdash; all in one place.</p>

    <hr>

    <a class="btn" href="/auth/github/start"{disabled_attr} aria-disabled="{'true' if not configured else 'false'}">
      <svg width="20" height="20" viewBox="0 0 98 96" aria-hidden="true" fill="var(--btn-fg)">
        <path fill-rule="evenodd" clip-rule="evenodd" d="M48.854 0C21.839 0 0 22 0 49.217c0 21.756 13.993 40.172 33.405 46.69 2.427.49 3.316-1.059 3.316-2.362 0-1.141-.08-5.052-.08-9.127-13.59 2.934-16.42-5.867-16.42-5.867-2.184-5.704-5.42-7.17-5.42-7.17-4.448-3.015.324-3.015.324-3.015 4.934.326 7.523 5.052 7.523 5.052 4.367 7.496 11.404 5.378 14.235 4.074.404-3.178 1.699-5.378 3.074-6.6-10.839-1.141-22.243-5.378-22.243-24.283 0-5.378 1.94-9.778 5.014-13.2-.485-1.222-2.184-6.275.486-13.038 0 0 4.125-1.304 13.426 5.052a46.97 46.97 0 0 1 12.214-1.63c4.125 0 8.33.571 12.213 1.63 9.302-6.356 13.427-5.052 13.427-5.052 2.67 6.763.97 11.816.485 13.038 3.155 3.422 5.015 7.822 5.015 13.2 0 18.905-11.404 23.06-22.324 24.283 1.78 1.548 3.316 4.481 3.316 9.126 0 6.6-.08 11.897-.08 13.526 0 1.304.89 2.853 3.316 2.364 19.412-6.52 33.405-24.935 33.405-46.691C97.707 22 75.788 0 48.854 0Z"/>
      </svg>
      Continue with GitHub
    </a>

    {error_html}{misconfigured_banner}

    <p class="footer">Your access is managed by your GitHub account.</p>
  </div>
</body>
</html>"""
    return HTMLResponse(html)


async def _fetch_github_identity(
    *,
    code: str,
    callback_url: str,
    config: AuthConfig,
) -> tuple[GitHubUser, frozenset[str]]:
    async with httpx.AsyncClient(timeout=15) as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": config.github_client_id,
                "client_secret": config.github_client_secret,
                "code": code,
                "redirect_uri": callback_url,
            },
        )
        token_response.raise_for_status()
        access_token = str(token_response.json().get("access_token", ""))
        if not access_token:
            raise httpx.HTTPStatusError(
                "GitHub did not return an access token.",
                request=token_response.request,
                response=token_response,
            )

        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        user_response = await client.get("https://api.github.com/user", headers=headers)
        user_response.raise_for_status()
        user_data = user_response.json()
        user = GitHubUser(
            login=str(user_data.get("login", "")),
            name=_optional_str(user_data.get("name")),
            avatar_url=_optional_str(user_data.get("avatar_url")),
            html_url=_optional_str(user_data.get("html_url")),
        )

        orgs: frozenset[str] = frozenset()
        if config.allowed_github_orgs:
            org_response = await client.get("https://api.github.com/user/orgs", headers=headers)
            org_response.raise_for_status()
            orgs = frozenset(
                str(item.get("login", "")).strip().lower()
                for item in org_response.json()
                if item.get("login")
            )
        return user, orgs


def _github_user_allowed(user: str, orgs: frozenset[str], config: AuthConfig) -> bool:
    allowed_users = config.allowed_github_users
    allowed_orgs = config.allowed_github_orgs
    if not allowed_users and not allowed_orgs:
        return True
    normalized_user = user.strip().lower()
    if normalized_user in allowed_users:
        return True
    return bool(allowed_orgs.intersection(orgs))


def _sign_session(payload: dict[str, Any], secret: str) -> str:
    body = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64url(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def _verify_session(token: str | None, secret: str) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = _b64url(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64url_decode(body))
    except (ValueError, TypeError):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return None
    return payload if isinstance(payload, dict) else None


def _set_cookie(
    response: RedirectResponse,
    name: str,
    value: str,
    *,
    max_age: int,
    secure: bool,
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _env_value(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _csv_env(name: str) -> frozenset[str]:
    return frozenset(
        item.strip().lower()
        for item in os.environ.get(name, "").split(",")
        if item.strip()
    )


def _optional_str(value: object) -> str | None:
    return str(value) if value else None


def _login_error_message(error: str | None) -> str:
    messages = {
        "github_auth_not_configured": "GitHub authentication is not configured on this server.",
        "invalid_oauth_state": "The GitHub sign-in session expired. Try again.",
        "missing_oauth_code": "GitHub did not return a sign-in code. Try again.",
        "github_oauth_failed": "GitHub sign-in failed. Try again.",
        "github_user_not_allowed": "Your GitHub account is not allowed to access this QA Lens server.",
    }
    return messages.get(error or "", "Sign-in failed. Try again.")


def _html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
