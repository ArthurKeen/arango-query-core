"""Engine behaviour arango-cypher-py needed to drop its own NL loop
(arango-solutions-org/arango-cypher#24), one issue each:

* #7 — the query is found in a fenced block anywhere in the response;
* #8 — an adapter's optional ``normalize`` seam repairs a candidate before
  validation;
* #9 — ``retry_provider_errors`` lets a provider call that raised use the
  retry budget instead of aborting generation;
* #10 — ``generate(user_hint=...)`` adds a hint to the first user message.

Fakes follow ``tests/test_nl_engine.py``: a scripted provider and an adapter
that accepts any query containing ``SELECT``.
"""

from __future__ import annotations

import logging

import pytest
from test_nl_engine import FakeAdapter  # tests/ is on sys.path (pytest rootdir import)

from arango_query_core.nl import NLQueryEngine
from arango_query_core.nl.engine import _strip_code_fence

GOOD = "SELECT ?s WHERE { ?s ?p ?o }"


class ScriptedProvider:
    """Answers in order; an ``Exception`` in the script is raised instead."""

    def __init__(self, *answers: str | Exception) -> None:
        self._answers = list(answers)
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> tuple[str, dict[str, int]]:
        self.calls.append((system, user))
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cached_tokens": 0}


# --- #7: the fenced query, wherever it is ---------------------------------------


@pytest.mark.parametrize(
    ("response", "query"),
    [
        (f"Here is the query:\n```sparql\n{GOOD}\n```\nIt lists every triple.", GOOD),
        (f"```\n{GOOD}\n```", GOOD),
        (f"First:\n```sparql\n{GOOD}\n```\nOr:\n```sparql\nASK {{}}\n```", GOOD),
        (f"```sparql\n{GOOD}", GOOD),  # a fence that is never closed
        (GOOD, GOOD),  # no fence at all
    ],
    ids=["prose-around", "untagged", "first-of-two", "unclosed", "bare"],
)
def test_the_query_is_found_wherever_the_fence_is(response: str, query: str) -> None:
    assert _strip_code_fence(response, "sparql") == query


def test_prose_before_the_fence_costs_no_retry() -> None:
    provider = ScriptedProvider(f"Sure! Here you go:\n```sparql\n{GOOD}\n```")
    result = NLQueryEngine(provider=provider, adapter=FakeAdapter()).generate("everything")
    assert result.ok and result.query == GOOD and result.retries == 0
    assert len(provider.calls) == 1


# --- #8: the normalize seam ------------------------------------------------------


class NormalizingAdapter(FakeAdapter):
    """Repairs a lowercase keyword the validator would reject."""

    def __init__(self, *, fail: bool = False) -> None:
        super().__init__()
        self.seen: list[str] = []
        self._fail = fail

    def normalize(self, query: str) -> str:
        self.seen.append(query)
        if self._fail:
            raise ValueError("normalizer bug")
        return query.replace("select", "SELECT")


def test_a_normalized_candidate_is_what_is_validated_and_returned() -> None:
    adapter = NormalizingAdapter()
    provider = ScriptedProvider("```sparql\nselect ?s WHERE { ?s ?p ?o }\n```")
    result = NLQueryEngine(provider=provider, adapter=adapter).generate("everything")
    assert result.ok and result.query == GOOD and result.retries == 0
    assert adapter.seen == ["select ?s WHERE { ?s ?p ?o }"]  # after the fence is stripped


def test_a_retry_quotes_the_normalized_candidate() -> None:
    adapter = NormalizingAdapter()
    provider = ScriptedProvider("ask {}", GOOD)
    NLQueryEngine(provider=provider, adapter=adapter, max_retries=1).generate("everything")
    assert "```sparql\nask {}\n```" in provider.calls[1][1]


def test_a_normalize_that_raises_keeps_the_candidate(caplog: pytest.LogCaptureFixture) -> None:
    provider = ScriptedProvider(GOOD)
    with caplog.at_level(logging.WARNING):
        result = NLQueryEngine(provider=provider, adapter=NormalizingAdapter(fail=True)).generate(
            "everything"
        )
    assert result.ok and result.query == GOOD
    assert "normalizer bug" in caplog.text


# --- #9: provider failures and the retry budget ---------------------------------


def test_by_default_a_provider_failure_propagates() -> None:
    provider = ScriptedProvider(TimeoutError("timed out"), GOOD)
    with pytest.raises(TimeoutError):
        NLQueryEngine(provider=provider, adapter=FakeAdapter()).generate("everything")
    assert len(provider.calls) == 1


def test_opted_in_a_failed_call_uses_one_attempt() -> None:
    provider = ScriptedProvider(TimeoutError("timed out"), GOOD)
    engine = NLQueryEngine(provider=provider, adapter=FakeAdapter(), retry_provider_errors=True)
    result = engine.generate("everything")
    assert result.ok and result.query == GOOD
    assert (result.provider_errors, result.retries, result.total_tokens) == (1, 1, 15)
    assert provider.calls[1][1] == "everything"  # nothing to repair yet: the plain question again


def test_opted_in_every_call_failing_reraises_the_last_error() -> None:
    provider = ScriptedProvider(TimeoutError("first"), ConnectionError("second"), RuntimeError("third"))
    engine = NLQueryEngine(
        provider=provider, adapter=FakeAdapter(), max_retries=2, retry_provider_errors=True
    )
    with pytest.raises(RuntimeError, match="third"):
        engine.generate("everything")
    assert len(provider.calls) == 3


def test_opted_in_a_failure_after_a_bad_candidate_reports_that_candidate() -> None:
    provider = ScriptedProvider("ask {}", TimeoutError("timed out"))
    engine = NLQueryEngine(
        provider=provider, adapter=FakeAdapter(), max_retries=1, retry_provider_errors=True
    )
    result = engine.generate("everything")
    assert not result.ok and result.error == "not a SELECT" and result.provider_errors == 1


# --- #10: a hint on the first user message ---------------------------------------


def test_a_user_hint_rides_on_the_first_message_only() -> None:
    provider = ScriptedProvider("ask {}", GOOD)
    engine = NLQueryEngine(provider=provider, adapter=FakeAdapter(), max_retries=1)
    result = engine.generate("everything", user_hint="Your previous query timed out. Add LIMIT.")
    assert result.ok
    assert provider.calls[0][1] == "everything\n\nYour previous query timed out. Add LIMIT."
    assert "timed out" not in provider.calls[1][1]


def test_a_user_hint_leaves_the_system_prompt_alone() -> None:
    plain, hinted = ScriptedProvider(GOOD), ScriptedProvider(GOOD)
    NLQueryEngine(provider=plain, adapter=FakeAdapter()).generate("everything")
    NLQueryEngine(provider=hinted, adapter=FakeAdapter()).generate("everything", user_hint="hint")
    assert plain.calls[0][0] == hinted.calls[0][0]
