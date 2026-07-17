# Changelog

All notable changes to `arango-query-core` are documented here, per
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Consumers pin
exact versions (contextual-data-fabric CC-9) and re-run their golden /
eval suites on every bump — pre-1.0, **minor** bumps may break the API
and this file must say so explicitly.

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

[0.1.0]: https://github.com/ArthurKeen/arango-query-core/releases/tag/v0.1.0
