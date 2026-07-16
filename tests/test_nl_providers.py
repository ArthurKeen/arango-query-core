"""Provider plumbing: env-based resolution and the Anthropic cache split.

Network paths are exercised in the consuming repos' integration suites;
here we pin the pure logic every consumer relies on.
"""

from __future__ import annotations

import pytest

from arango_query_core.nl import (
    AnthropicProvider,
    OpenAIProvider,
    OpenRouterProvider,
    get_llm_provider,
    split_system_for_anthropic_cache,
)

_ENV_KEYS = (
    "LLM_PROVIDER",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_no_keys_resolves_to_none() -> None:
    assert get_llm_provider() is None


def test_autodetect_priority_openai_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k2")
    assert isinstance(get_llm_provider(), OpenAIProvider)


def test_explicit_provider_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k2")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert isinstance(get_llm_provider(), AnthropicProvider)


def test_explicit_provider_without_key_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    assert get_llm_provider() is None


def test_openrouter_autodetect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert isinstance(get_llm_provider(), OpenRouterProvider)


def test_cache_split_at_examples_boundary() -> None:
    system = "PRELUDE\nSCHEMA\n## Examples\nQ: hi\n```\nSELECT 1\n```"
    blocks = split_system_for_anthropic_cache(system)
    assert len(blocks) == 2
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[0]["text"].endswith("SCHEMA")
    assert blocks[1]["text"].startswith("## Examples")
    assert "cache_control" not in blocks[1]


def test_cache_split_without_boundary_caches_everything() -> None:
    blocks = split_system_for_anthropic_cache("PRELUDE ONLY")
    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_cache_split_empty_system() -> None:
    blocks = split_system_for_anthropic_cache("")
    assert blocks == [{"type": "text", "text": "", "cache_control": {"type": "ephemeral"}}]
