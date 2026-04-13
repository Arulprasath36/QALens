"""LLM provider configuration for ARI.

Configuration is stored in ``~/.qara/config.toml`` and loaded lazily on first
use.  Users can also override any field via environment variables.

Example ``~/.qara/config.toml``::

    [llm]
    provider  = "ollama"
    base_url  = "http://localhost:11434/v1"
    model     = "llama3.2"
    api_key   = ""
    timeout   = 120
    max_tokens = 1024
    temperature = 0.2

Supported providers
-------------------
* ``ollama``      — local Ollama server (OpenAI-compatible)
* ``openai``      — OpenAI API
* ``azure``       — Azure OpenAI (set ``base_url`` to your Azure endpoint)
* ``lmstudio``    — LM Studio local server (OpenAI-compatible)
* ``anthropic``   — Anthropic Claude API
* ``gemini``      — Google Gemini API
* ``custom``      — any OpenAI-compatible endpoint (set ``base_url``)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# TOML loading — stdlib tomllib (3.11+) or tomli back-port for 3.10
# ---------------------------------------------------------------------------

try:
    import tomllib  # type: ignore[import]
except ImportError:  # Python 3.10
    try:
        import tomli as tomllib  # type: ignore[import, no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Defaults per provider
# ---------------------------------------------------------------------------

_PROVIDER_DEFAULTS: dict[str, dict] = {
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.2",
        "api_key": "",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key": "",
    },
    "azure": {
        "base_url": "",  # must be set by user
        "model": "gpt-4o",
        "api_key": "",
    },
    "lmstudio": {
        "base_url": "http://localhost:1234/v1",
        "model": "local-model",
        "api_key": "lm-studio",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "model": "claude-3-haiku-20240307",
        "api_key": "",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com",
        "model": "gemini-2.0-flash",
        "api_key": "",
    },
    "custom": {
        "base_url": "http://localhost:8080/v1",
        "model": "default",
        "api_key": "",
    },
}

_OPENAI_COMPATIBLE = {"ollama", "openai", "azure", "lmstudio", "custom"}

DEFAULT_CONFIG_TOML = """\
# QARA LLM configuration
# Run `ari llm-config` to interactively set up a provider.

[llm]
# Provider: ollama | openai | azure | lmstudio | anthropic | gemini | custom
provider    = "ollama"

# API base URL (leave blank to use provider default)
base_url    = "http://localhost:11434/v1"

# Model name
model       = "llama3.2"

# API key (leave blank for local providers like Ollama / LM Studio)
api_key     = ""

# Request timeout in seconds
timeout     = 120

# Maximum tokens to generate
max_tokens  = 2048

# Sampling temperature (0.0 = deterministic, 1.0 = creative)
temperature = 0.2

# Optional system prompt override (leave blank for QARA default)
system_prompt = ""
"""


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


@dataclass
class LLMConfig:
    """Runtime LLM configuration.

    Attributes:
        provider: Lowercase provider identifier.
        base_url: API base URL.
        model: Model name/identifier.
        api_key: API key (empty string for local providers).
        timeout: HTTP request timeout in seconds.
        max_tokens: Maximum tokens to generate.
        temperature: Sampling temperature.
        system_prompt: Optional system prompt override.
    """

    provider: str = "ollama"
    base_url: str = "http://localhost:11434/v1"
    model: str = "llama3.2"
    api_key: str = ""
    timeout: int = 120
    max_tokens: int = 2048
    temperature: float = 0.2
    system_prompt: str = ""

    @property
    def is_openai_compatible(self) -> bool:
        """Return ``True`` if this provider uses the OpenAI chat completions API."""
        return self.provider in _OPENAI_COMPATIBLE

    @property
    def effective_api_key(self) -> str:
        """Return the API key, preferring the ``QARA_LLM_API_KEY`` env var."""
        return os.environ.get("QARA_LLM_API_KEY", self.api_key)

    @property
    def effective_base_url(self) -> str:
        """Return the base URL, applying provider defaults when blank."""
        if self.base_url:
            return self.base_url.rstrip("/")
        return (_PROVIDER_DEFAULTS.get(self.provider, {}).get("base_url", "")).rstrip("/")


# ---------------------------------------------------------------------------
# Config path helpers
# ---------------------------------------------------------------------------


def default_config_path() -> Path:
    """Return the default path to ``~/.qara/config.toml``, creating the dir."""
    config_dir = Path.home() / ".qara"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.toml"


def config_exists(path: Path | None = None) -> bool:
    """Return ``True`` if the config file exists."""
    return (path or default_config_path()).exists()


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------


def load_config(path: Path | None = None) -> LLMConfig:
    """Load :class:`LLMConfig` from a TOML file.

    If the file does not exist the built-in defaults are returned (Ollama).
    Environment variable ``QARA_LLM_PROVIDER`` overrides the provider field
    after loading.

    Args:
        path: Path to the TOML config file.  ``None`` = ``~/.qara/config.toml``.

    Returns:
        A populated :class:`LLMConfig`.
    """
    config_path = path or default_config_path()

    raw: dict = {}
    if config_path.exists():
        if tomllib is None:
            raise RuntimeError(
                "Cannot read config.toml — install 'tomli' for Python 3.10: "
                "pip install tomli"
            )
        with open(config_path, "rb") as fh:
            raw = tomllib.load(fh).get("llm", {})

    # Apply provider defaults first, then overlay file values
    provider = raw.get("provider", "ollama").lower()
    defaults = _PROVIDER_DEFAULTS.get(provider, {})

    cfg = LLMConfig(
        provider=provider,
        base_url=raw.get("base_url", defaults.get("base_url", "")),
        model=raw.get("model", defaults.get("model", "default")),
        api_key=raw.get("api_key", defaults.get("api_key", "")),
        timeout=int(raw.get("timeout", 120)),
        max_tokens=int(raw.get("max_tokens", 2048)),
        temperature=float(raw.get("temperature", 0.2)),
        system_prompt=raw.get("system_prompt", ""),
    )

    # Environment overrides
    if env_provider := os.environ.get("QARA_LLM_PROVIDER"):
        cfg.provider = env_provider.lower()
    if env_model := os.environ.get("QARA_LLM_MODEL"):
        cfg.model = env_model
    if env_url := os.environ.get("QARA_LLM_BASE_URL"):
        cfg.base_url = env_url

    return cfg


def save_default_config(path: Path | None = None) -> Path:
    """Write the default ``config.toml`` template to disk.

    Does **not** overwrite an existing file.

    Args:
        path: Destination path.  ``None`` = ``~/.qara/config.toml``.

    Returns:
        The path that was written (or already existed).
    """
    config_path = path or default_config_path()
    if not config_path.exists():
        config_path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
        config_path.chmod(0o600)
    return config_path


def provider_display_name(provider: str) -> str:
    """Return a friendly display name for a provider identifier."""
    names = {
        "ollama": "Ollama (local)",
        "openai": "OpenAI",
        "azure": "Azure OpenAI",
        "lmstudio": "LM Studio (local)",
        "anthropic": "Anthropic Claude",
        "gemini": "Google Gemini",
        "custom": "Custom OpenAI-compatible",
    }
    return names.get(provider.lower(), provider)
