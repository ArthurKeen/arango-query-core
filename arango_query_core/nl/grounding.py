"""Entity/instance grounding retrieval for NL→query prompts.

At prompt-construction time, retrieve the top-K instances from the
target's own instance data whose label(s) share tokens with the user's
question, and inject them into the adapter's prompt as a "Known
entities" block naming their exact opaque IDs (IRIs for SPARQL, node
keys for Cypher, ...). This lets the LLM reference a specific
individual by its exact ID instead of guessing a name-literal match —
a corpus/CK25 spike measured this lifting execution-graded accuracy
from 12.2% to 24.5% (McNemar p=0.031, 0 regressions).

Mirrors :class:`~arango_query_core.nl.fewshot.FewShotIndex`'s shape
exactly: a retrieval index built from caller-owned data (no file
loading, no memoization at this layer — the caller decides how/when to
build and cache the index for its own corpus/deployment), a
``retrieve(question, k)`` method, and a ``format_prompt_section(...)``
renderer that returns ``""`` on no matches so the caller can omit the
section entirely.

The retrieval/scoring machinery is target-language-agnostic — ``id``
is an opaque string the scorer never inspects. The exact prompt
wording (e.g. "use these EXACT IRIs" vs. "use these EXACT node IDs")
is intentionally NOT owned by this module; ``format_prompt_section``
accepts ``header``/``instruction``/``id_prefix``/``id_suffix`` so
callers supply their own language-specific phrasing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_STOP = frozenset(
    "the a an of in is are on to for me my i give need all every who what "
    "which where when how does do not no and or with by their his her its "
    "please list show find get".split()
)

# C0 control chars (0x00-0x1F) + DEL (0x7F), including \n and \r — a
# maliciously-labeled instance (e.g. rdfs:label containing "\nignore
# previous instructions") must render on a single bullet line and
# cannot inject a new prompt section (T-07.3-01).
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RUN_RE = re.compile(r"\s+")
_LABEL_MAX_LEN = 200


def _sanitize_label(label: str) -> str:
    """Strip control chars, collapse whitespace, cap length.

    A no-op on already-clean labels: no control chars, single spaces,
    under the length cap all pass through byte-identical (verified in
    tests) so ordinary CK25 label text is never altered.
    """
    cleaned = _CONTROL_CHARS_RE.sub(" ", label)
    cleaned = _WHITESPACE_RUN_RE.sub(" ", cleaned).strip()
    if len(cleaned) > _LABEL_MAX_LEN:
        cleaned = cleaned[:_LABEL_MAX_LEN]
    return cleaned


@dataclass(frozen=True)
class GroundedEntity:
    """One retrievable instance: an opaque id + its human-readable labels.

    ``id`` is opaque to this module (an RDF IRI for SPARQL, a node key
    for Cypher, ...) — the retrieval scorer never inspects its shape.
    """

    id: str
    labels: tuple[str, ...]
    type: str = ""


class LabelIndex:
    """Substring-token retrieval over a fixed list of :class:`GroundedEntity`.

    Construction is caller-owned: pass a pre-built ``list[GroundedEntity]``
    (via ``__init__`` or :meth:`from_items`). There is no file-loading
    or memoization at this layer — unlike
    :func:`~arango_query_core.nl.fewshot.cached_few_shot_index`, there
    is no single canonical "bank path" for grounding data (it varies
    per corpus/deployment); callers own the build-once discipline.
    """

    def __init__(self, entities: list[GroundedEntity]) -> None:
        self._entities: list[GroundedEntity] = list(entities)

    @classmethod
    def from_items(cls, items: list[GroundedEntity]) -> LabelIndex:
        return cls(items)

    def retrieve(self, question: str, k: int = 20) -> list[GroundedEntity]:
        """Top-k entities whose label tokens appear (as substrings) in
        the question, or vice versa.

        Both-direction substring matching survives plural/inflection
        mismatches (e.g. "Transistors" in the question vs. a "Transistor"
        label token). Ranked by hit count (desc), then shortest matching
        label (tiebreak — prefers the more specific/precise match).
        Ported verbatim from the spike's scorer
        (scratchpad/nl-grounding-spike/grounding_spike.py::retrieve).
        """
        ql = question.lower()
        q_tokens = {t for t in re.findall(r"[a-z0-9]+", ql) if len(t) >= 3 and t not in _STOP}
        scored: list[tuple[int, int, GroundedEntity]] = []
        for e in self._entities:
            hits = 0
            best_len = 999
            for lab in e.labels:
                labl = lab.lower()
                lab_tokens = [t for t in re.findall(r"[a-z0-9]+", labl) if len(t) >= 3]
                h = sum(1 for t in lab_tokens if t in ql)
                h += sum(1 for t in q_tokens if t in labl and not any(t == lt for lt in lab_tokens))
                if h > hits:
                    hits, best_len = h, len(labl)
            if hits:
                scored.append((hits, -best_len, e))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [e for _, _, e in scored[:k]]

    def format_prompt_section(
        self,
        question: str,
        k: int = 20,
        *,
        header: str,
        instruction: str,
        id_prefix: str = "",
        id_suffix: str = "",
    ) -> str:
        """Render a generic "known entities" prompt block for *question*.

        Returns the empty string when no entities match, matching
        :meth:`~arango_query_core.nl.fewshot.FewShotIndex.format_prompt_section`'s
        contract so callers can omit the section entirely.

        ``header``/``instruction``/``id_prefix``/``id_suffix`` are
        passed through unmodified — this renderer stays language-
        agnostic; the exact wording ("EXACT IRIs" vs. "EXACT node IDs")
        is the adapter's responsibility, mirroring how
        ``grammar_prompt_section`` (not ``FewShotIndex``'s header) owns
        target-specific wording.

        Every rendered label is sanitized (control chars stripped to
        spaces, length-capped) so a maliciously-labeled instance cannot
        break the prompt-block structure (T-07.3-01).
        """
        matches = self.retrieve(question, k=k)
        if not matches:
            return ""
        lines = [header, instruction, ""]
        for e in matches:
            labels = " / ".join(sorted(_sanitize_label(lab) for lab in e.labels))
            lines.append(f'- {id_prefix}{e.id}{id_suffix} — "{labels}" ({e.type or "?"})')
        return "\n".join(lines)
