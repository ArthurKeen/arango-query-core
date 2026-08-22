"""Caller-supplied postconditions in the engine retry loop.

Covers the semantics the feature promises: postconditions run only on valid
queries, share the retry budget, feed their correction back into the next
prompt, fail closed on exhaustion, first-violation-wins, a raising check is a
violation (not an outage), the rule is announced once in the system prompt,
and the guardrail gate still runs after. All with fakes — no network.
"""

from __future__ import annotations

from typing import Any

from arango_query_core.nl import (
    GuardrailVerdict,
    NLQueryEngine,
    PostconditionContext,
    PostconditionViolation,
    ValidationResult,
    run_postconditions,
)


class FakeProvider:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> tuple[str, dict[str, int]]:
        self.calls.append((system, user))
        content = self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]
        return content, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


class FakeAdapter:
    """Valid iff the query contains 'SELECT'."""

    language = "sparql"

    def __init__(self, *, allow: bool = True) -> None:
        self._allow = allow

    def grammar_prompt_section(self, schema_context: str) -> str:
        return "## Grammar\nWrite SPARQL only."

    def few_shot_index(self):
        return None

    def grounding_index(self):
        return None

    def predicate_index(self):
        return None

    def validate(self, query: str) -> ValidationResult:
        if "SELECT" in query:
            return ValidationResult(ok=True)
        return ValidationResult(ok=False, error="not a SELECT", code="E_PARSE")

    def repair_hint(self, query: str, failure: ValidationResult) -> str:
        return "Emit a SELECT query."

    def guardrails(self, query: str, context: dict[str, Any]) -> GuardrailVerdict:
        if self._allow:
            return GuardrailVerdict(allowed=True)
        return GuardrailVerdict(allowed=False, reasons=["tenant scope violation"])


class NeedsLimit:
    """Requires a LIMIT clause — a stand-in domain invariant."""

    code = "needs_limit"

    def prompt_section(self) -> str:
        return "INVARIANT: every query MUST include a LIMIT clause."

    def check(self, query: str, *, context: PostconditionContext):
        if "LIMIT" in query.upper():
            return None
        return PostconditionViolation(
            code=self.code, reason="Query has no LIMIT.", suggested_hint="Add LIMIT 100."
        )


def _engine(responses, postconditions=(), *, allow=True, max_retries=2):
    return NLQueryEngine(
        provider=FakeProvider(responses),
        adapter=FakeAdapter(allow=allow),
        postconditions=postconditions,
        max_retries=max_retries,
    )


def test_noop_when_no_postconditions():
    eng = _engine(["SELECT * LIMIT 1"])
    r = eng.generate("q")
    assert r.ok and r.retries == 0 and r.postcondition is None


def test_violation_triggers_retry_then_succeeds():
    eng = _engine(["SELECT *", "SELECT * LIMIT 5"], [NeedsLimit()])
    r = eng.generate("q")
    assert r.ok is True
    assert r.retries == 1
    assert r.query == "SELECT * LIMIT 5"
    assert r.postcondition is None


def test_exhaustion_fails_closed():
    eng = _engine(["SELECT *"], [NeedsLimit()], max_retries=2)
    r = eng.generate("q")
    assert r.ok is False
    assert r.retries == 2
    assert r.query == ""  # a valid-but-rejected query is never returned
    assert r.postcondition is not None and r.postcondition.code == "needs_limit"
    assert "no limit" in r.error.lower() and "needs_limit" in r.error


def test_correction_is_fed_into_the_retry_prompt():
    eng = _engine(["SELECT *", "SELECT * LIMIT 5"], [NeedsLimit()])
    eng.generate("q")
    retry_user = eng.provider.calls[1][1]
    assert "Add LIMIT 100." in retry_user  # the suggested_hint reached the model


def test_first_violation_wins():
    class AlwaysA:
        code = "a"

        def prompt_section(self):
            return ""

        def check(self, query, *, context):
            return PostconditionViolation(code="a", reason="A", suggested_hint="fix A")

    class AlwaysB:
        code = "b"

        def prompt_section(self):
            return ""

        def check(self, query, *, context):
            raise AssertionError("second check must not run when the first fails")

    eng = _engine(["SELECT * LIMIT 1"], [AlwaysA(), AlwaysB()], max_retries=0)
    r = eng.generate("q")
    assert r.ok is False and r.postcondition.code == "a"


def test_raising_check_is_a_violation_not_an_outage():
    class Boom:
        code = "boom"

        def prompt_section(self):
            return ""

        def check(self, query, *, context):
            raise ValueError("kaboom")

    eng = _engine(["SELECT * LIMIT 1"], [Boom()], max_retries=1)
    r = eng.generate("q")  # must not raise
    assert r.ok is False
    assert r.postcondition.code == "boom_error"


def test_prompt_section_rendered_once_in_system_prompt():
    eng = _engine(["SELECT *", "SELECT * LIMIT 5"], [NeedsLimit()])
    eng.generate("q")
    system = eng.provider.calls[0][0]
    assert "INVARIANT: every query MUST include a LIMIT clause." in system
    assert system.count("INVARIANT: every query MUST include a LIMIT clause.") == 1
    # system prefix is stable across attempts (cache-friendly)
    assert eng.provider.calls[0][0] == eng.provider.calls[1][0]


def test_postconditions_only_run_on_valid_queries():
    # First reply is invalid (no SELECT) -> validate fails, postcondition not
    # reached; second reply is valid AND satisfies the postcondition.
    checked: list[str] = []

    class Recorder:
        code = "rec"

        def prompt_section(self):
            return ""

        def check(self, query, *, context):
            checked.append(query)
            return None

    eng = _engine(["nonsense", "SELECT * LIMIT 1"], [Recorder()])
    r = eng.generate("q")
    assert r.ok is True
    assert checked == ["SELECT * LIMIT 1"]  # never ran on the invalid candidate


def test_guardrail_still_gates_after_postconditions():
    eng = _engine(["SELECT * LIMIT 1"], [NeedsLimit()], allow=False)
    r = eng.generate("q")
    assert r.ok is False
    assert "tenant scope" in r.error


def test_run_postconditions_helper_empty_is_none():
    ctx = PostconditionContext(schema_summary="", question="q", attempt=0)
    assert run_postconditions("SELECT 1", None, ctx) is None
    assert run_postconditions("SELECT 1", [], ctx) is None
