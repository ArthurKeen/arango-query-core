"""Engine loop: happy path, validate→repair retries, guardrail refusal,
fence stripping, and cross-retry usage accounting — all with fake
providers/adapters (no network, no transpiler)."""

from __future__ import annotations

from typing import Any

from arango_query_core.nl import (
    GuardrailVerdict,
    NLQueryEngine,
    ValidationResult,
)
from arango_query_core.nl.fewshot import FewShotIndex, _NoopRetriever


class FakeProvider:
    """Scripted provider: returns canned responses in order."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> tuple[str, dict[str, int]]:
        self.calls.append((system, user))
        content = self._responses.pop(0)
        return content, {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cached_tokens": 2,
        }


class FakeAdapter:
    """Minimal QueryLanguageAdapter: valid iff the query contains 'SELECT'."""

    language = "sparql"

    def __init__(self, *, allow: bool = True) -> None:
        self._allow = allow
        self.repair_calls: list[str] = []

    def grammar_prompt_section(self, schema_context: str) -> str:
        return f"## Grammar\nWrite SPARQL only.\n{schema_context}".strip()

    def few_shot_index(self) -> FewShotIndex | None:
        return FewShotIndex(_NoopRetriever(), examples=[])

    def grounding_index(self):
        return None

    def validate(self, query: str) -> ValidationResult:
        if "SELECT" in query:
            return ValidationResult(ok=True)
        return ValidationResult(ok=False, error="not a SELECT", code="E_PARSE")

    def repair_hint(self, query: str, failure: ValidationResult) -> str:
        self.repair_calls.append(query)
        return "Emit a SELECT query."

    def guardrails(self, query: str, context: dict[str, Any]) -> GuardrailVerdict:
        if self._allow:
            return GuardrailVerdict(allowed=True)
        return GuardrailVerdict(allowed=False, reasons=["tenant scope violation"])


def test_happy_path_first_attempt() -> None:
    engine = NLQueryEngine(provider=FakeProvider(["SELECT ?s WHERE { ?s ?p ?o }"]), adapter=FakeAdapter())
    result = engine.generate("show everything")
    assert result.ok and result.query == "SELECT ?s WHERE { ?s ?p ?o }"
    assert result.retries == 0
    assert result.total_tokens == 15


def test_repair_loop_recovers_and_accumulates_usage() -> None:
    provider = FakeProvider(["MATCH (n) RETURN n", "SELECT ?s WHERE { ?s ?p ?o }"])
    adapter = FakeAdapter()
    engine = NLQueryEngine(provider=provider, adapter=adapter, max_retries=2)
    result = engine.generate("show everything")
    assert result.ok and result.retries == 1
    # Usage summed across both attempts.
    assert result.total_tokens == 30 and result.cached_tokens == 4
    # The retry prompt carried the adapter's corrective hint.
    assert adapter.repair_calls == ["MATCH (n) RETURN n"]
    assert "Emit a SELECT query." in provider.calls[1][1]


def test_retries_exhausted_reports_last_failure() -> None:
    provider = FakeProvider(["bad1", "bad2", "bad3"])
    engine = NLQueryEngine(provider=provider, adapter=FakeAdapter(), max_retries=2)
    result = engine.generate("show everything")
    assert not result.ok and result.query == ""
    assert result.error == "not a SELECT"
    assert result.retries == 2


def test_guardrail_refusal_is_surfaced_not_silent() -> None:
    engine = NLQueryEngine(
        provider=FakeProvider(["SELECT ?s WHERE { ?s ?p ?o }"]),
        adapter=FakeAdapter(allow=False),
    )
    result = engine.generate("show everything")
    assert not result.ok
    assert "tenant scope violation" in result.error
    assert result.guardrail is not None and not result.guardrail.allowed


def test_fenced_response_is_stripped() -> None:
    fenced = "```sparql\nSELECT ?s WHERE { ?s ?p ?o }\n```"
    engine = NLQueryEngine(provider=FakeProvider([fenced]), adapter=FakeAdapter())
    result = engine.generate("show everything")
    assert result.ok and result.query == "SELECT ?s WHERE { ?s ?p ?o }"


def test_system_prompt_contains_grammar_section() -> None:
    provider = FakeProvider(["SELECT ?s WHERE { ?s ?p ?o }"])
    engine = NLQueryEngine(provider=provider, adapter=FakeAdapter())
    engine.generate("show everything", schema_context="Classes: Person")
    system = provider.calls[0][0]
    assert "## Grammar" in system and "Classes: Person" in system
