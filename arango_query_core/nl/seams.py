"""The adapter seams — everything language-specific about an NL→query pipeline.

The engine (:mod:`arango_query_core.nl.engine`) is target-language-
agnostic: it assembles prompts, retrieves few-shot examples, calls the
LLM provider, and drives the validate→repair retry loop. Everything it
cannot know without committing to a query language is delegated to a
:class:`QueryLanguageAdapter` — exactly the five seams identified when
the engine was carved out of ``arango_cypher.nl2cypher`` (see
``arango-sparql-py/docs/architecture/proposals/nl-engine-extraction.md``):

1. the target-grammar prompt section,
2. the few-shot corpus,
3. the syntax validator,
4. the repair rules keyed on validator errors,
5. the guardrail checks (e.g. tenant-scope AST validation).

Adapters live NEXT TO their transpilers (``arango_cypher.nl2cypher``,
``arango_sparql.nl2sparql``), never in this package: validating a
generated query requires the transpiler stack, and importing one here
would either create a dependency cycle (both transpilers depend on
this package) or force every consumer to install both query stacks.
The dependency points one way — adapters hand the engine callables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .fewshot import FewShotIndex


@dataclass
class ValidationResult:
    """Outcome of an adapter's syntax/translatability check (seam 3).

    ``ok`` — the generated query parses (and, when the adapter chooses
    to check deeper, translates). ``error`` carries the parser or
    translator message verbatim; the engine feeds it to
    :meth:`QueryLanguageAdapter.repair_hint` on retry. ``code`` is the
    adapter's stable machine-readable error code when one exists
    (e.g. ``E_SPARQL_PARSE``).
    """

    ok: bool
    error: str = ""
    code: str = ""


@dataclass
class GuardrailVerdict:
    """Outcome of an adapter's guardrail pass (seam 5).

    ``allowed`` gates whether the generated query may be returned at
    all; ``reasons`` explains a refusal (surfaced to the caller, never
    silently dropped). Adapters implement whatever checks their
    deployment requires — tenant-scope AST validation being the
    canonical example — and the engine treats the verdict as opaque.
    """

    allowed: bool
    reasons: list[str] = field(default_factory=list)


@runtime_checkable
class QueryLanguageAdapter(Protocol):
    """The five language-specific seams, as one injectable object.

    ``language`` is the lowercase tag used for fenced code blocks and
    telemetry (``"cypher"``, ``"sparql"``). All other members map
    one-to-one onto the numbered seams in the module docstring.
    """

    language: str

    def grammar_prompt_section(self, schema_context: str) -> str:
        """Seam 1 — the system-prompt section that teaches the target
        grammar and any house rules (conceptual-schema-only vocabulary,
        forbidden constructs, output format contract). ``schema_context``
        is the engine-rendered conceptual-schema summary the section may
        embed or reference."""
        ...

    def few_shot_index(self) -> FewShotIndex | None:
        """Seam 2 — the curated corpus for this language, or ``None``
        to run zero-shot."""
        ...

    def validate(self, query: str) -> ValidationResult:
        """Seam 3 — parse (and optionally translate) the candidate."""
        ...

    def repair_hint(self, query: str, failure: ValidationResult) -> str:
        """Seam 4 — turn a validation failure into the corrective
        instruction appended to the retry prompt. Return the empty
        string to retry with the bare error message."""
        ...

    def guardrails(self, query: str, context: dict[str, Any]) -> GuardrailVerdict:
        """Seam 5 — deployment guardrails over the *validated* query
        (tenant scope, write-op refusal, …). ``context`` carries
        request-scoped facts the adapter's checks need (e.g.
        ``{"tenant_id": …}``)."""
        ...
