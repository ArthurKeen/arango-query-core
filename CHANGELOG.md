# Changelog

All notable changes to `arango-query-core` are documented here, per
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Consumers pin
exact versions (contextual-data-fabric CC-9) and re-run their golden /
eval suites on every bump — pre-1.0, **minor** bumps may break the API
and this file must say so explicitly.

## [0.2.0] - 2026-08-23

### BREAKING

- `QueryLanguageAdapter` grows from five seams to **eight** — seams 6-8
  (`grounding_index`/`grounding_prompt_section`,
  `predicate_index`/`predicate_prompt_section`,
  `path_index`/`path_prompt_section`) are now called *unconditionally*
  by `NLQueryEngine._system_prompt`. An adapter missing any of the
  eight methods raises `AttributeError` at prompt-build time — there
  is no `hasattr` fallback. Existing adapters must implement the three
  new methods (returning `None` from the `*_index()` half is a valid
  "run ungrounded" no-op, mirroring seam 2's `few_shot_index() -> None`
  contract) before bumping their pin past this release.

### Added

- **Seam 6 — entity/instance grounding** (`nl.grounding.LabelIndex` /
  `GroundedEntity`): retrieves matching instances from the target data
  and injects their exact IDs into the prompt, so the model references
  a specific entity instead of guessing a name-literal match. Measured
  lifting execution-graded accuracy from 12.2% to 24.5% on a CK25 spike
  (McNemar p=0.031, 0 regressions).
- **Seam 7 — predicate/schema-convention grounding**
  (`nl.grounding.PredicateIndex` / `GroundedPredicate`): a distilled
  usage cheat-sheet for TBox predicates (domain/range/kind/derived
  usage shape) instead of making the model infer conventions from raw
  `rdfs:domain`/`rdfs:range` triples. Renders the predicate's **IRI
  local name** as the identifier to emit (human label demoted to a
  gloss) — fixes models inventing predicates from the label instead of
  using the real vocabulary term (9/10 previously-invented-predicate
  CK25 cases corrected, 0 regressions).
- **Seam 8 — relationship-path grounding** (`nl.pathindex.ClassPathIndex`
  / `ClassPath`): bounded shortest predicate paths between two
  seam-6/7-anchored classes over the TBox's own class-connectivity
  graph — fixes the model grounding the right entity but inventing a
  predicate path that executes to an empty result set.
- **Caller-supplied postconditions** (`nl.postconditions`): a
  language-agnostic mechanism for enforcing semantic invariants a
  generated query must satisfy — the class of bug that `validate()`
  and `guardrails()` both miss (a well-formed, allowed query that is
  nonetheless semantically wrong). Rides the same generate→validate→
  retry budget; fails closed on exhaustion rather than returning a
  plausible-but-wrong query. `NLQueryEngine` gains `postconditions` /
  `postcondition_mapping`.
- **`nl.synthbank`** — a query-first synthetic few-shot template
  catalog (`SHAPE_CATALOG`, `ShapeTemplate`): 9 ontology-agnostic
  compositional query shapes (lookup, value_object, category_filter,
  scalar_count, grouped_aggregation, top_n, offset, negation, two_hop),
  promoted out of arango-sparql-py's eval-side bank generator so
  onboarding callers and a future Cypher front-end share one catalog.
- **`DenseRetriever`** (`nl.fewshot`, `dense` extra): cosine-similarity
  few-shot retrieval over sentence embeddings, as an alternative to
  BM25. Pinned model + revision hash for reproducible ranking.
  `FewShotIndex.from_corpus_files(..., mode=...)` dispatches between
  `"dense"` (hard-raises if unavailable), `"bm25"`, and `"auto"`
  (dense → BM25 → no-op, never raises — the default, preserving prior
  behavior for existing callers). `cached_few_shot_index` memoizes the
  expensive dense build per (bank path, mode).
- New `dense` extra (`sentence-transformers>=3.0`); `py.typed` marker.

### Fixed

- `PredicateIndex.format_prompt_section` rendered a predicate's
  `rdfs:label` as the identifier to emit; now renders the IRI local
  name (see seam 7 above).

146 tests (up from 78 at 0.1.0); ruff (lint + format) and mypy clean.

## [0.1.0] - 2026-07-17

Initial standalone release — extraction step 1 (see `docs/PRD.md`).

### Added

- Conceptual↔physical model contract, seeded verbatim from
  arango-cypher-py @ `5a1392b`: `MappingBundle`, `MappingResolver`,
  `mapping_from_wire_dict`, `mapping_hash`, collection-name grammar
  guard, OWL/Turtle ⇄ bundle round-trip (`owl` extra), AQL fragment
  types, `safe_execute` / `explain_aql`, extension registry,
  `CoreError` base — with their five test modules.
- `arango_query_core.nl` — language-agnostic NL→query engine:
  `NLQueryEngine` (generate→validate→repair loop), LLM providers
  (OpenAI / OpenRouter / Anthropic with prompt caching), BM25 few-shot
  retrieval over `(question, query)` pairs (`nl` extra), and the
  five-seam `QueryLanguageAdapter` protocol (`nl.seams`).
- Zero hard runtime dependencies; `owl` / `nl` / `dev` extras.
- CI: ruff (lint + format), mypy, pytest on Python 3.11 / 3.12.

[0.2.0]: https://github.com/ArthurKeen/arango-query-core/releases/tag/v0.2.0
[0.1.0]: https://github.com/ArthurKeen/arango-query-core/releases/tag/v0.1.0
