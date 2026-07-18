# arango-query-core — Product Requirements Document

**Status:** Active development · **v0.1.0**
**Last updated:** 2026-07-17
**Owner:** arango-query-core maintainers

> This PRD governs the standalone `arango-query-core` distribution. The
> design source of record for the extraction that created this repo is
> [`arango-sparql-py/docs/architecture/proposals/nl-engine-extraction.md`](https://github.com/arango-solutions/arango-sparql-py/blob/main/docs/architecture/proposals/nl-engine-extraction.md)
> (Accepted — step 1 shipped 2026-07-16). Where this PRD and that
> proposal disagree, this PRD wins for current intent; the proposal wins
> for historical rationale. The consuming products' PRDs
> ([`arango-cypher-py/docs/PRD.md`](https://github.com/ArthurKeen/arango-cypher-py/blob/main/docs/PRD.md),
> arango-sparql-py) govern everything language-specific.

---

## 1. Executive summary

`arango-query-core` is the **shared conceptual-model and NL substrate**
for the ArangoDB query transpilers — `arango-cypher-py` (Cypher→AQL)
and `arango-sparql-py` (SPARQL→AQL) — and, through them, the
contextual-data-fabric's federated query engine. It exists so that
three consumers pin **one versioned artifact** instead of forking the
same code three ways.

It ships two things:

1. **The conceptual↔physical model contract** — `MappingBundle` and its
   resolver, wire-format parsing, hashing, OWL/Turtle round-trip, plus
   AQL fragment types, safe execution helpers, an extension registry,
   and the shared error base.
2. **A language-agnostic NL→query engine** — LLM provider abstraction
   (OpenAI / OpenRouter / Anthropic with prompt caching), BM25 few-shot
   retrieval, and the generate→validate→repair loop, with everything
   language-specific delegated to a five-seam `QueryLanguageAdapter`
   protocol implemented *next to* each transpiler, never here.

### 1.1 Defining decisions (confirmed 2026-07-16)

- **Adapters stay in their transpiler repos.** `nl2cypher` lives in
  arango-cypher-py, `nl2sparql` in arango-sparql-py. Validating a
  generated query requires the transpiler stack; importing one here
  would create a dependency cycle or force consumers to install both
  query languages. Dependencies point one way: transpilers → this
  package.
- **Zero hard dependencies.** The core installs with no runtime deps;
  rdflib, requests, PyYAML, and rank_bm25 are lazily imported behind
  the `owl` and `nl` extras. A consumer that only needs
  `MappingBundle` pays for nothing else.
- **One distribution, not two.** The distribution name stays
  `arango-query-core` even though it now also carries the NL engine —
  conceptual-model identity is signaled at the subpackage level
  (`arango_query_core.nl`), not by minting a second artifact.
- **PyPI publication.** v0.1.0 was published 2026-07-17 (decision:
  claim the name while the `nl2cypher` re-point was in flight),
  superseding the proposal's publish-after-re-point gate. The gate now
  applies to *subsequent* releases: any seam-API change forced by the
  re-point ships as 0.2.0 with an explicit changelog break notice, and
  consumers keep pinning exact versions.
- **Behavioral reference.** The code was seeded verbatim from
  arango-cypher-py @ `5a1392b`; that repo's NL eval suite is the
  non-regression gate for the re-point.

## 2. Problem statement

Three engines were about to exist: the mature `nl2cypher` engine
(~7.5k LOC) in arango-cypher-py, a stub port in arango-sparql-py whose
TODO said "port the LLM provider abstraction, BM25 fewshot index, and
tenant guardrail", and the fabric's M5 WP-D1 plan to harvest nl2cypher
and "swap ~5 seams to emit SPARQL". Likewise `MappingBundle` shipped
inside arango-cypher-py's wheel, forcing the SPARQL leg to transitively
depend on the Cypher repo. Extracting the shared substrate while the
port was a stub and the harvest hadn't started was the cheapest moment
to prevent a three-way fork.

## 3. Goals / non-goals

### Goals

- One pinned artifact carrying the conceptual-model contract and the
  NL engine, consumed by both transpilers and the fabric.
- A small, stable public API: the package `__all__` plus the five-seam
  `QueryLanguageAdapter` protocol. Stability of the seam list is the
  product; churn here multiplies into release + pin-bump work across
  every consumer (see §6).
- Safety invariants preserved from the source repo: bind parameters
  throughout, regex-validated collection names before any string
  interpolation into AQL, guardrail verdicts surfaced (never silently
  dropped).

### Non-goals

- **Per-language adapters** (grammar prompts, few-shot corpora,
  validators, repair rules, guardrail AST checks) — these live with
  their transpilers.
- **Entity resolution beyond the extracted interface**, transpilation
  itself, HTTP surfaces, CLIs, UIs — all product-repo concerns.
- **Schema inference** — `arangodb-schema-analyzer` remains canonical;
  this package only defines the bundle format it feeds.

## 4. Package architecture

| Module / subpackage | Purpose |
| --- | --- |
| `mapping` | `MappingBundle`, `MappingResolver`, `MappingSource`, `PropertyInfo`, `IndexInfo`, `RelationshipStats`; `mapping_from_wire_dict`, `mapping_hash`; collection-name grammar guard (`COLLECTION_NAME_RE`, `is_valid_collection_name`) |
| `owl_turtle` / `owl_rdflib` | OWL/Turtle ⇄ MappingBundle round-trip; rdflib parser behind the `owl` extra (import degrades to `None` without it) |
| `aql` | `AqlFragment`, `AqlQuery` value types |
| `exec` | `AqlExecutor` protocol, `safe_execute` (bind-var reference checking), `explain_aql` |
| `extensions` | `ExtensionRegistry` / `ExtensionPolicy` for `arango.*` extension functions |
| `errors` | `CoreError` shared base |
| `nl.engine` | `NLQueryEngine` — prompt assembly, few-shot retrieval, provider call, generate→validate→repair loop; `NLResult` |
| `nl.providers` | `LLMProvider` protocol; OpenAI / OpenRouter / Anthropic implementations (Anthropic with prompt-cache system-block splitting); env-driven `get_llm_provider` |
| `nl.fewshot` | `FewShotIndex` over `(question, query)` pairs (legacy corpus keys accepted), `BM25Retriever` (rank_bm25 behind the `nl` extra) |
| `nl.seams` | `QueryLanguageAdapter` — the five language-specific seams: (1) grammar prompt section, (2) few-shot corpus, (3) syntax validator, (4) repair rules keyed on validator errors, (5) guardrail checks. Plus `ValidationResult`, `GuardrailVerdict` |

## 5. Requirements

- **R1 — Dependency-free core.** `pip install arango-query-core` must
  succeed and import with zero runtime dependencies. Optional
  capability arrives only via extras: `[owl]` (rdflib), `[nl]`
  (requests, PyYAML, rank_bm25).
- **R2 — Python ≥ 3.11**, tested on 3.11 and 3.12 in CI.
- **R3 — Safe-by-construction AQL surfaces.** No user input is ever
  string-interpolated into AQL; collection names embedded into AQL are
  regex-validated first (`is_valid_collection_name`); `safe_execute`
  cross-checks that declared bind vars are actually referenced.
- **R4 — Language-agnostic engine.** Nothing under `arango_query_core`
  may import a transpiler or assume a target query language beyond the
  adapter's `language` tag. The engine treats validation and guardrail
  results as opaque adapter verdicts.
- **R5 — Deterministic contract types.** `mapping_hash` over a bundle
  is stable across processes (canonical JSON) so consumers can use it
  for cache keys and change detection.
- **R6 — Quality gates.** ruff (lint + format), mypy, and pytest run in
  CI on every push/PR; all three must pass before a release is tagged.

## 6. Versioning & release policy

Consumed as a **pinned artifact** under the fabric's pin-everything
policy (contextual-data-fabric CC-9): consumers pin exact versions and
re-run their golden/eval suites on every bump — arango-cypher-py's NL
eval suite and arango-sparql-py's `RUN_EVAL=1` harness are the gates.
Consequences:

- Every release is deliberate: a version bump costs a release plus
  2–3 downstream pin bumps. Batch changes; keep the seam API stable.
- Tag releases `vX.Y.Z`; maintain `CHANGELOG.md` (Keep-a-Changelog
  style). Pre-1.0, minor bumps may break the API but the changelog
  must say so explicitly.
- Published on PyPI as of v0.1.0 (2026-07-17); consumers pin exact
  PyPI versions (git tags remain as a fallback pin).

## 7. Current state (2026-07-16)

Extraction **step 1 shipped**: this repo, seeded verbatim from
arango-cypher-py @ `5a1392b` (mapping / OWL round-trip / aql / exec /
extensions with their five test modules) plus the new
`arango_query_core.nl` engine (providers verbatim; few-shot generalized
to `(question, query)` pairs; five-seam protocol; repair loop).
78 tests, ruff + mypy + pytest green in CI, sdist/wheel build clean.

## 8. Roadmap (extraction steps 2–4)

1. ~~Carve `arango-query-core` into its own repo/distribution.~~ ✅
2. **Re-point `nl2cypher`** at this core; arango-cypher-py's NL eval
   suite is the non-regression gate. Seam changes it forces ship as
   0.2.0.
3. **Implement `nl2sparql`** directly as the second adapter in
   arango-sparql-py (no interim engine port); its `RUN_EVAL=1` eval
   harness is the gate there.
4. **Hand fabric WP-D1** the core + adapter pins.

Later (from arango-cypher-py PRD §12.3): resolver-adjacent pieces may
migrate here once both transpilers consume the published artifact.

## 9. Risks

- **Seam churn.** Every engine change is a release + 2–3 pin bumps.
  Mitigation: the public surface is deliberately the seam list — small
  and stable.
- **Guardrails don't fully extract.** AST validators are
  language-specific; the split is interface-in-core
  (`GuardrailVerdict`), implementation-in-adapter. A weak adapter
  guardrail is a consumer-repo bug, but this package must never make
  one easy to bypass (verdicts gate returns; refusals carry reasons).
- **Single-maintainer coordination** across three consuming repos.
  Mitigation: this PRD + the changelog are the coordination surface.
