"""Settings route handlers for the QA Lens FastAPI server."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from qalens.artifacts.config import ArtifactConfig
from qalens.db.schema import default_db_path
from qalens.llm.config import (
    _PROVIDER_DEFAULTS,
    LLMConfig,
    default_config_path,
    load_config,
    provider_display_name,
)
from qalens.security import (
    EXTERNAL_LLM_OPT_IN_ENV,
    LOCAL_LLM_PROVIDERS,
    MAX_LLM_PROMPT_CHARS,
    SUPPORTED_IMAGE_MIME_TYPES,
    is_local_llm_endpoint,
)

if TYPE_CHECKING:
    from pathlib import Path as PathType
    from qalens.server.auth import AuthConfig


class LLMSettingsPatch(BaseModel):
    """Editable LLM settings accepted from the UI."""

    enabled: bool | None = None
    provider: str | None = Field(default=None, max_length=40)
    base_url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    api_key: str | None = Field(default=None, max_length=2_000)
    timeout: int | None = Field(default=None, ge=5, le=600)
    max_tokens: int | None = Field(default=None, ge=128, le=65_536)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    system_prompt: str | None = Field(default=None, max_length=8_000)
    allow_external: bool | None = None


def make_settings_router(
    db_path: str | PathType | None,
    config_path: str | PathType | None,
    auth_config: AuthConfig | None = None,
) -> APIRouter:
    """Return an :class:`~fastapi.APIRouter` with settings endpoints."""
    from qalens.server.auth import is_admin_user

    router = APIRouter()

    def _require_admin(request: Request) -> None:
        if auth_config is not None and not is_admin_user(request, auth_config):
            raise HTTPException(status_code=403, detail="Settings access requires admin privileges.")

    @router.get("/api/settings", tags=["settings"])
    async def get_settings(request: Request) -> dict[str, Any]:
        """Return runtime settings and editable LLM configuration."""
        _require_admin(request)
        cfg_path = _resolve_config_path(config_path)
        try:
            cfg = load_config(cfg_path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Cannot load config: {exc}") from exc

        artifact_defaults = ArtifactConfig()
        db_display_path = _resolve_db_display_path(db_path)

        return {
            "runtime": {
                "database_path": str(db_display_path),
                "database_source": "default" if db_path is None else "serve flag",
                "config_path": str(cfg_path),
                "config_exists": cfg_path.exists(),
            },
            "llm": _llm_payload(cfg),
            "artifacts": {
                "mode": artifact_defaults.mode.value,
                "max_screenshots_per_failure": artifact_defaults.max_screenshots_per_failure,
                "max_screenshot_bytes": artifact_defaults.max_screenshot_bytes,
                "max_total_screenshot_bytes_per_run": (
                    artifact_defaults.max_total_screenshot_bytes_per_run
                ),
                "storage_dir": (
                    str(artifact_defaults.storage_dir)
                    if artifact_defaults.storage_dir is not None
                    else str(Path.home() / ".qalens" / "artifacts")
                ),
                "supported_image_mime_types": sorted(SUPPORTED_IMAGE_MIME_TYPES),
                "svg_enabled": False,
            },
            "security": {
                "external_llm_opt_in_env": EXTERNAL_LLM_OPT_IN_ENV,
                "external_llm_env_enabled": _env_flag_enabled(EXTERNAL_LLM_OPT_IN_ENV),
                "local_llm_providers": sorted(LOCAL_LLM_PROVIDERS),
                "max_llm_prompt_chars": MAX_LLM_PROMPT_CHARS,
                "redaction_enabled": True,
                "untrusted_data_wrappers_enabled": True,
            },
            "owner_mapping": {
                "active_path": None,
                "source": "ingest flag",
                "editable": False,
            },
        }

    @router.patch("/api/settings/llm", tags=["settings"])
    async def update_llm_settings(request: Request, payload: LLMSettingsPatch) -> dict[str, Any]:
        """Update safe LLM fields in ``config.toml`` and return fresh settings."""
        _require_admin(request)
        cfg_path = _resolve_config_path(config_path)
        try:
            cfg = load_config(cfg_path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Cannot load config: {exc}") from exc

        if payload.provider is not None:
            provider = payload.provider.strip().lower()
            if provider not in _PROVIDER_DEFAULTS:
                allowed = ", ".join(sorted(_PROVIDER_DEFAULTS))
                raise HTTPException(
                    status_code=422,
                    detail=f"Unsupported provider. Allowed: {allowed}.",
                )
            cfg.provider = provider
            defaults = _PROVIDER_DEFAULTS.get(provider, {})
            if payload.model is None:
                cfg.model = str(defaults.get("model", cfg.model))
            if payload.base_url is None:
                cfg.base_url = str(defaults.get("base_url", cfg.base_url))

        if payload.enabled is not None:
            cfg.enabled = payload.enabled
        if payload.base_url is not None:
            cfg.base_url = payload.base_url.strip()
        if payload.model is not None:
            cfg.model = payload.model.strip() or "default"
        if payload.api_key is not None:
            cfg.api_key = payload.api_key
        if payload.timeout is not None:
            cfg.timeout = payload.timeout
        if payload.max_tokens is not None:
            cfg.max_tokens = payload.max_tokens
        if payload.temperature is not None:
            cfg.temperature = payload.temperature
        if payload.system_prompt is not None:
            cfg.system_prompt = payload.system_prompt
        if payload.allow_external is not None:
            cfg.allow_external = payload.allow_external

        try:
            _write_llm_config(cfg_path, cfg)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Cannot save config: {exc}") from exc

        refreshed = load_config(cfg_path)
        return {"llm": _llm_payload(refreshed), "runtime": {"config_path": str(cfg_path)}}

    return router


def _resolve_config_path(config_path: str | PathType | None) -> Path:
    return Path(config_path).expanduser() if config_path is not None else default_config_path()


def _resolve_db_display_path(db_path: str | PathType | None) -> str | Path:
    if db_path is None:
        return default_db_path()
    if str(db_path) == ":memory:":
        return ":memory:"
    return Path(db_path).expanduser().resolve(strict=False)


def _llm_payload(cfg: LLMConfig) -> dict[str, Any]:
    return {
        "enabled": cfg.enabled,
        "provider": cfg.provider,
        "provider_display": provider_display_name(cfg.provider),
        "base_url": cfg.base_url,
        "effective_base_url": cfg.effective_base_url,
        "model": cfg.model,
        "timeout": cfg.timeout,
        "max_tokens": cfg.max_tokens,
        "temperature": cfg.temperature,
        "allow_external": cfg.allow_external,
        "external_llm_allowed": cfg.external_llm_allowed,
        "endpoint_is_local": is_local_llm_endpoint(cfg.effective_base_url),
        "api_key_configured": bool(cfg.api_key),
        "api_key_env_configured": bool(os.environ.get("QALENS_LLM_API_KEY")),
        "system_prompt": cfg.system_prompt,
        "provider_options": [
            {
                "value": provider,
                "label": provider_display_name(provider),
                "local": provider in LOCAL_LLM_PROVIDERS,
            }
            for provider in sorted(_PROVIDER_DEFAULTS)
        ],
    }


def _env_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _write_llm_config(config_path: Path, cfg: LLMConfig) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# QA Lens LLM configuration\n",
        "# Managed by QA Lens Settings UI or `qalens llm-config`.\n",
        "\n",
        "[llm]\n",
        f"enabled = {_toml_bool(cfg.enabled)}\n",
        f'provider = "{_toml_escape(cfg.provider)}"\n',
        f'base_url = "{_toml_escape(cfg.base_url)}"\n',
        f'model = "{_toml_escape(cfg.model)}"\n',
        f'api_key = "{_toml_escape(cfg.api_key)}"\n',
        f"timeout = {cfg.timeout}\n",
        f"max_tokens = {cfg.max_tokens}\n",
        f"temperature = {cfg.temperature}\n",
        f'system_prompt = "{_toml_escape(cfg.system_prompt)}"\n',
        f"allow_external = {_toml_bool(cfg.allow_external)}\n",
    ]
    config_path.write_text("".join(lines), encoding="utf-8")
    config_path.chmod(0o600)


def _toml_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"
