# arango-query-core

Shared conceptual-model and NL substrate for the ArangoDB query
transpilers — [`arango-cypher-py`](https://github.com/ArthurKeen/arango-cypher-py)
(Cypher→AQL) and [`arango-sparql-py`](https://github.com/arango-solutions/arango-sparql-py)
(SPARQL→AQL) — and, through them, the contextual-data-fabric's
federated query engine.

Carved out of `arango-cypher-py` (which previously shipped
`arango_query_core` inside its own wheel) so both transpilers and the
fabric pin one artifact instead of forking the same code three ways.

## What's here

| Subpackage / module | Purpose |
| --- | --- |
| `arango_query_core.mapping` | `MappingBundle` — the conceptual↔physical model contract (entities, relationships, physical annotations) shared by both transpilers and the analyzers' CSI pipeline |
| `arango_query_core.owl_turtle` / `owl_rdflib` | OWL/Turtle ⇄ MappingBundle round-trip (rdflib optional, via the `owl` extra) |
| `arango_query_core.aql` / `exec` / `extensions` / `errors` | AQL fragment types, safe execution helpers, extension registry, error base |
| `arango_query_core.nl` | Language-agnostic NL→query engine: LLM providers (OpenAI / OpenRouter / Anthropic with prompt caching), BM25 few-shot retrieval, and the generate→validate→repair loop |
| `arango_query_core.nl.seams` | `QueryLanguageAdapter` — the five language-specific seams an adapter implements (grammar prompt, corpus, validator, repair rules, guardrails) |

## What's deliberately NOT here

The per-language adapters. `nl2cypher` (in arango-cypher-py) and
`nl2sparql` (in arango-sparql-py) implement `QueryLanguageAdapter`
next to their transpilers, because validating a generated query
requires the transpiler stack — importing one here would create a
dependency cycle or force consumers to install both query languages.
Dependencies point one way: transpilers → this package.

## Install

```bash
pip install arango-query-core            # mapping/aql core, zero deps
pip install "arango-query-core[owl]"     # + rdflib OWL round-trip
pip install "arango-query-core[nl]"      # + NL engine runtime deps
```

## Versioning

Consumed as a pinned artifact (contextual-data-fabric CC-9): consumers
pin exact versions and re-run their golden suites on every bump.
Pre-PyPI, pin a git tag.
