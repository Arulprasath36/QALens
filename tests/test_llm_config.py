"""Tests for qara.llm.config (Phase 7)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from qara.llm.config import (
    DEFAULT_CONFIG_TOML,
    LLMConfig,
    config_exists,
    default_config_path,
    load_config,
    provider_display_name,
    save_default_config,
)


# ---------------------------------------------------------------------------
# LLMConfig dataclass
# ---------------------------------------------------------------------------


def test_default_config_is_ollama():
    cfg = LLMConfig()
    assert cfg.provider == "ollama"


def test_is_openai_compatible_ollama():
    cfg = LLMConfig(provider="ollama")
    assert cfg.is_openai_compatible is True


def test_is_openai_compatible_openai():
    cfg = LLMConfig(provider="openai")
    assert cfg.is_openai_compatible is True


def test_is_not_openai_compatible_anthropic():
    cfg = LLMConfig(provider="anthropic")
    assert cfg.is_openai_compatible is False


def test_is_not_openai_compatible_gemini():
    cfg = LLMConfig(provider="gemini")
    assert cfg.is_openai_compatible is False


def test_effective_api_key_from_env(monkeypatch):
    monkeypatch.setenv("QARA_LLM_API_KEY", "test-key-from-env")
    cfg = LLMConfig(api_key="config-key")
    assert cfg.effective_api_key == "test-key-from-env"


def test_effective_api_key_fallback():
    cfg = LLMConfig(api_key="my-key")
    assert "QARA_LLM_API_KEY" not in os.environ or True  # guard
    os.environ.pop("QARA_LLM_API_KEY", None)
    assert cfg.effective_api_key == "my-key"


def test_effective_base_url_returned_as_is():
    cfg = LLMConfig(provider="ollama", base_url="http://localhost:11434/v1")
    assert cfg.effective_base_url == "http://localhost:11434/v1"


def test_effective_base_url_strips_trailing_slash():
    cfg = LLMConfig(provider="ollama", base_url="http://localhost:11434/v1/")
    assert not cfg.effective_base_url.endswith("/")


def test_effective_base_url_falls_back_to_provider_default():
    cfg = LLMConfig(provider="openai", base_url="")
    assert "api.openai.com" in cfg.effective_base_url


# ---------------------------------------------------------------------------
# load_config — from file
# ---------------------------------------------------------------------------


def test_load_config_returns_defaults_when_no_file(tmp_path):
    cfg = load_config(tmp_path / "nonexistent.toml")
    assert cfg.provider == "ollama"


def test_load_config_reads_toml(tmp_path):
    toml_content = """\
[llm]
provider = "openai"
model = "gpt-4o"
api_key = "sk-test"
timeout = 60
max_tokens = 2048
temperature = 0.5
system_prompt = "Be concise."
allow_external = true
"""
    p = tmp_path / "config.toml"
    p.write_text(toml_content, encoding="utf-8")
    cfg = load_config(p)
    assert cfg.provider == "openai"
    assert cfg.model == "gpt-4o"
    assert cfg.api_key == "sk-test"
    assert cfg.timeout == 60
    assert cfg.max_tokens == 2048
    assert abs(cfg.temperature - 0.5) < 0.001
    assert cfg.system_prompt == "Be concise."
    assert cfg.allow_external is True


def test_external_llm_requires_opt_in_by_default():
    cfg = LLMConfig(provider="openai")
    assert cfg.external_llm_allowed is False


def test_external_llm_env_opt_in(monkeypatch):
    monkeypatch.setenv("QARA_ALLOW_EXTERNAL_LLM", "1")
    cfg = LLMConfig(provider="openai")
    assert cfg.external_llm_allowed is True


def test_local_llm_is_allowed_without_opt_in():
    cfg = LLMConfig(provider="ollama")
    assert cfg.external_llm_allowed is True


def test_load_config_env_overrides_provider(tmp_path, monkeypatch):
    p = tmp_path / "config.toml"
    p.write_text("[llm]\nprovider = \"ollama\"\n", encoding="utf-8")
    monkeypatch.setenv("QARA_LLM_PROVIDER", "anthropic")
    cfg = load_config(p)
    assert cfg.provider == "anthropic"


def test_load_config_env_overrides_model(tmp_path, monkeypatch):
    p = tmp_path / "config.toml"
    p.write_text("[llm]\nprovider = \"openai\"\nmodel = \"gpt-4o-mini\"\n", encoding="utf-8")
    monkeypatch.setenv("QARA_LLM_MODEL", "gpt-4o")
    cfg = load_config(p)
    assert cfg.model == "gpt-4o"


def test_load_config_env_overrides_base_url(tmp_path, monkeypatch):
    p = tmp_path / "config.toml"
    p.write_text("[llm]\nprovider = \"custom\"\n", encoding="utf-8")
    monkeypatch.setenv("QARA_LLM_BASE_URL", "http://myserver:8080/v1")
    cfg = load_config(p)
    assert cfg.base_url == "http://myserver:8080/v1"


# ---------------------------------------------------------------------------
# save_default_config
# ---------------------------------------------------------------------------


def test_save_default_config_creates_file(tmp_path):
    path = tmp_path / "config.toml"
    result = save_default_config(path)
    assert result == path
    assert path.exists()
    assert "[llm]" in path.read_text()


def test_save_default_config_does_not_overwrite(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("existing = true\n", encoding="utf-8")
    save_default_config(path)
    assert "existing = true" in path.read_text()


# ---------------------------------------------------------------------------
# config_exists
# ---------------------------------------------------------------------------


def test_config_exists_true(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("", encoding="utf-8")
    assert config_exists(p) is True


def test_config_exists_false(tmp_path):
    assert config_exists(tmp_path / "missing.toml") is False


# ---------------------------------------------------------------------------
# provider_display_name
# ---------------------------------------------------------------------------


def test_provider_display_name_ollama():
    assert "Ollama" in provider_display_name("ollama")


def test_provider_display_name_openai():
    assert "OpenAI" in provider_display_name("openai")


def test_provider_display_name_anthropic():
    assert "Anthropic" in provider_display_name("anthropic")


def test_provider_display_name_unknown():
    assert provider_display_name("myunknown") == "myunknown"
