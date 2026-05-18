# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest  | ✅        |

QALens is currently pre-1.0. Security fixes are applied to the latest `main` branch only.

---

## Reporting a Vulnerability

If you discover a security vulnerability in QALens, **please do not open a public GitHub issue**.

Report it privately by emailing the maintainers at:

**arulprasath36@gmail.com**

Or use GitHub's [private security advisory](https://github.com/Arulprasath36/QALens/security/advisories/new) feature.

You can expect:
- **Acknowledgment** within 48 hours
- **Assessment and response** within 7 business days
- **Coordinated disclosure** once a fix is available

---

## Scope

QALens has two deployment modes with different attack surfaces:

### CLI mode (local only)
QALens reads test report files from the local filesystem and writes to a local SQLite database.

Primary attack surface:
- **Malicious HTML/JSON report files** — parsed via BeautifulSoup4, lxml, and the stdlib JSON parser. Crafted files could exploit parsing bugs in those libraries.

Mitigations in place:
- Report file types restricted to `.html`, `.htm`, `.json` (whitelist enforced)
- Image attachments validated by magic bytes, not file extension
- No `eval()`, `exec()`, or `subprocess` calls on parsed content
- Secrets redacted from text before LLM submission (`src/qalens/security.py`)
- Database path validated — rejects `file:` URIs, non-database extensions, directory paths

### Server mode (`qalens serve`)
The FastAPI server exposes a local web UI and API. It is designed for
**localhost use by default**. Authentication is disabled unless you configure
token auth or GitHub OAuth.

Additional attack surface:
- **API endpoints** — protected by `QALENS_AUTH_TOKEN`, `qalens serve --auth-token`,
  or GitHub OAuth when configured; unauthenticated only in default localhost mode
- **LLM API calls** — user questions inserted into prompts; a `MAX_LLM_PROMPT_CHARS` limit and prompt-level constraints mitigate injection impact
- **File attachments** — served from paths stored in the database, protected against path traversal via canonical path re-validation

Security controls active in server mode:
- Optional admin bearer-token authentication for `/api/*` routes
- Optional GitHub OAuth sign-in before the app home page loads, with signed
  `HttpOnly` session cookies and user/org allowlists
- CSRF check on all state-mutating requests (POST/PUT/PATCH/DELETE) — validates `Origin`/`Referer` header against `Host`
- Content-Security-Policy: `script-src 'self'`; `object-src 'none'`; `frame-ancestors 'none'`
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`
- LLM endpoint rate-limited to 10 calls / 60 s per client IP
- Query parameter bounds validated on all routes (`ge=`, `le=`, enum whitelists)

---

## Out of Scope

- Social engineering
- Vulnerabilities in third-party dependencies (report to those projects)
- Attacks requiring physical access to the machine running QALens

---

## Production Deployment Checklist

> QALens is designed as a **local developer tool**. If you choose to expose it on a network, work through this checklist first.

Use the standalone [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md) before any
networked deployment. The summary below is kept as a quick reference.

### Authentication & network exposure
- [ ] Set `QALENS_AUTH_TOKEN`, pass `qalens serve --auth-token ...`, or configure
      `QALENS_AUTH_MODE=github` before exposing QALens beyond localhost
- [ ] For GitHub OAuth, set `QALENS_GITHUB_CLIENT_ID`,
      `QALENS_GITHUB_CLIENT_SECRET`, `QALENS_SESSION_SECRET`, and an allowlist via
      `QALENS_ALLOWED_GITHUB_USERS` or `QALENS_ALLOWED_GITHUB_ORGS`
- [ ] Place the server behind a reverse proxy (nginx, Caddy) that enforces
      HTTPS and, when needed, stronger organization auth such as OAuth2 or mTLS
- [ ] Bind `qalens serve` to `127.0.0.1` unless you have explicitly enabled
      QALens auth and network controls
- [ ] Use HTTPS; configure TLS termination at the proxy layer
- [ ] Restrict access by IP allowlist at the network/firewall level

### Secrets & credentials
- [ ] Never embed credentials in git remote URLs (`git remote set-url` to SSH or HTTPS without token)
- [ ] Store the LLM API key in an environment variable or secrets manager — never in source code or `.git/config`
- [ ] Confirm `.env` files are in `.gitignore` and not committed
- [ ] Rotate any API keys that may have been exposed in git history

### Dependency hygiene
- [ ] Run `npm audit --audit-level=high` before deploying; resolve or accept-risk any highs
- [ ] Run `pip-audit` against the Python environment; patch or pin around CVEs
- [ ] Pin production image/runtime versions; avoid floating `^`/`>=` in lock files
- [ ] Enable Dependabot (or Renovate) alerts on the repository

### CI gates (enabled by `.github/workflows/ci.yml`)
- [ ] `npm audit --audit-level=high` — blocks on new high/critical npm CVEs
- [ ] `pip-audit` — scans Python dependency tree for known CVEs
- [ ] `bandit -r src/` — static analysis for common Python security anti-patterns
- [ ] `mypy` strict type-check — catches type confusion bugs before runtime
- [ ] Tests must pass — regression coverage for ingestion and query paths

### Database
- [ ] Keep the SQLite database file outside the web root
- [ ] Set filesystem permissions to `600` (owner read/write only)
- [ ] Back up regularly; the database is the sole source of truth for all ingested reports

### LLM / AI
- [ ] Review what data is sent to the LLM provider — QALens redacts secrets but does send test names, error messages, and stack traces
- [ ] If your test reports contain PII or sensitive system details, evaluate whether LLM features are appropriate for your environment
- [ ] Set and monitor LLM API spend limits

### Logging & monitoring
- [ ] Confirm logs do not capture request bodies (they should not by default)
- [ ] Ship logs to a centralised sink with retention policy
- [ ] Alert on repeated 4xx/5xx or rate-limit hits on `/api/ask`

---

## Acknowledgments

We appreciate responsible disclosure and will credit reporters in release notes unless anonymity is requested.
