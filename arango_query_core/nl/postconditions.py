"""Caller-supplied semantic postconditions for the NL→query retry loop.

The engine already runs two kinds of check through its generate → validate →
retry loop: the adapter's ``validate`` seam (parse + translate — is the query
*well formed*?) and its ``guardrails`` seam (deployment policy — is it
*allowed*?). Both catch a query that is broken or forbidden.

Postconditions catch a third, more dangerous class: a query that parses,
translates, and returns *plausible* results while being **semantically wrong**
— aggregating over the wrong rows, resolving to the wrong collection, dropping
a required filter. No syntactic check sees it and no human sees it in a demo.

A postcondition is a caller-supplied invariant. It rides the *same* retry
budget as parse and translate: the model is told the rule up front (via
:meth:`Postcondition.prompt_section`, rendered once into the cacheable system
prefix), and a violation is fed back into the next prompt exactly like a
validation failure — so the loop gets a chance to *correct* the query rather
than just reject it, and fails closed when the budget is spent.

Semantics (mirrors ``nl2cypher``'s original, language-agnostic here):

* Postconditions run **after** the adapter's ``validate`` succeeds — a retry is
  only ever spent on an already-valid query.
* The **first** violation wins; checks are not accumulated. One clear, specific
  correction beats a pile of them.
* A check that **raises** is treated as a violation, not an error — a broken
  postcondition must not turn a safety mechanism into an outage. Fail closed.
* :meth:`Postcondition.prompt_section` renders **once**; it must not vary
  between attempts or provider-side prompt caching is defeated.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "PostconditionViolation",
    "PostconditionContext",
    "Postcondition",
    "run_postconditions",
    "postcondition_prompt_sections",
]


@dataclass(frozen=True)
class PostconditionViolation:
    """Why a generated query failed a caller invariant.

    Structurally compatible with any other guardrail-style rejection the loop
    understands: ``reason``, ``suggested_hint`` and ``code`` are all it reads,
    so a violation from an unrelated check can be surfaced through the same
    path without inheritance.
    """

    reason: str
    """What is wrong, in one sentence. Fed into the retry prompt first."""
    suggested_hint: str
    """How to fix it. Also fed into the retry prompt, after ``reason``."""
    code: str = "postcondition_violation"
    """Stable identifier for telemetry / assertions, e.g. ``"time_windowed"``."""


@dataclass(frozen=True)
class PostconditionContext:
    """What a check is given besides the query itself.

    Passed as a single object so a future field does not change every
    implementer's signature. ``mapping`` is intentionally ``Any`` — the shared
    engine does not depend on any one repo's schema-bundle type; a consumer
    passes whatever its checks need (e.g. a ``MappingBundle``).
    """

    schema_summary: str
    question: str
    attempt: int
    mapping: Any = None


@runtime_checkable
class Postcondition(Protocol):
    """A caller-supplied check on a generated query."""

    code: str
    """Stable identifier, e.g. ``"analog_conditional"``."""

    def check(
        self,
        query: str,
        *,
        context: PostconditionContext,
    ) -> PostconditionViolation | None:
        """Return ``None`` to accept, or a violation to trigger a retry."""
        ...

    def prompt_section(self) -> str:
        """Text injected into the system prompt so the model is told the rule
        up front rather than only corrected after breaking it.

        Return ``""`` to contribute nothing. Rendered once per call — must not
        vary between attempts, or provider-side prompt caching is defeated.
        """
        ...


def run_postconditions(
    query: str,
    postconditions: Sequence[Postcondition] | None,
    context: PostconditionContext,
) -> PostconditionViolation | None:
    """Run *postconditions* in order, returning the first violation.

    A check that raises is treated as a violation rather than being allowed to
    abort the translation: a broken check must not be able to turn a safety
    mechanism into an outage, and failing closed is the conservative reading.
    """
    if not postconditions:
        return None

    for pc in postconditions:
        code = getattr(pc, "code", pc.__class__.__name__)
        try:
            violation = pc.check(query, context=context)
        except Exception as exc:  # noqa: BLE001 - see docstring; fail closed
            return PostconditionViolation(
                code=f"{code}_error",
                reason=f"Postcondition {code!r} raised {type(exc).__name__}: {exc}",
                suggested_hint="Simplify the query; the check could not evaluate it.",
            )
        if violation is not None:
            return violation
    return None


def postcondition_prompt_sections(
    postconditions: Sequence[Postcondition] | None,
) -> list[str]:
    """Collect non-empty ``prompt_section()`` output, in caller order.

    Rendered once into the cacheable system prefix by the engine, so a check
    that raises here (a broken ``prompt_section``) is skipped rather than
    aborting the whole generation.
    """
    if not postconditions:
        return []
    sections: list[str] = []
    for pc in postconditions:
        try:
            section = pc.prompt_section()
        except Exception:  # noqa: BLE001 - a broken section must not abort generation
            continue
        if section and section.strip():
            sections.append(section.strip())
    return sections
