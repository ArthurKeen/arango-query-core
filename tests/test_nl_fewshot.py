"""Few-shot index: corpus loading (canonical + legacy keys), retrieval,
prompt-section rendering, and graceful degradation."""

from __future__ import annotations

from pathlib import Path

from arango_query_core.nl import FewShotIndex


def _write_corpus(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_loads_canonical_query_key(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path,
        "c.yml",
        """
version: 1
examples:
  - question: "Find a person by name"
    query: 'SELECT ?p WHERE { ?p ex:name "Tom" }'
""",
    )
    index = FewShotIndex.from_corpus_files([corpus])
    assert index.examples == [("Find a person by name", 'SELECT ?p WHERE { ?p ex:name "Tom" }')]


def test_loads_legacy_cypher_and_sparql_keys(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path,
        "c.yml",
        """
examples:
  - question: "q1"
    cypher: "MATCH (n) RETURN n"
  - question: "q2"
    sparql: "SELECT * WHERE { ?s ?p ?o }"
""",
    )
    index = FewShotIndex.from_corpus_files([corpus])
    assert dict(index.examples) == {
        "q1": "MATCH (n) RETURN n",
        "q2": "SELECT * WHERE { ?s ?p ?o }",
    }


# NOTE: BM25's IDF is non-positive for terms appearing in ≥ half the
# corpus, and rank_bm25 epsilon-floors those — so corpora below ~3
# documents retrieve nothing. Tests use 3+ examples on purpose; real
# corpora are far larger.


def test_retrieval_ranks_by_relevance(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path,
        "c.yml",
        """
examples:
  - question: "count all movies released after a year"
    query: "Q_MOVIES"
  - question: "list every person and their friends"
    query: "Q_FRIENDS"
  - question: "total orders per customer segment"
    query: "Q_ORDERS"
""",
    )
    index = FewShotIndex.from_corpus_files([corpus])
    top = index.retrieve("how many movies came out after 2000?", k=1)
    assert top and top[0][1] == "Q_MOVIES"


def test_format_prompt_section_tags_fence_with_language(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path,
        "c.yml",
        """
examples:
  - question: "find all people"
    query: "SELECT ?p WHERE { ?p a ex:Person }"
  - question: "movies by year"
    query: "Q2"
  - question: "orders by customer"
    query: "Q3"
""",
    )
    index = FewShotIndex.from_corpus_files([corpus])
    section = index.format_prompt_section("find all people", k=1, language="sparql")
    assert section.startswith("## Examples")
    assert "```sparql" in section


def test_empty_or_missing_corpus_degrades_to_noop(tmp_path: Path) -> None:
    empty = _write_corpus(tmp_path, "empty.yml", "examples: []\n")
    index = FewShotIndex.from_corpus_files([empty, tmp_path / "missing.yml"])
    assert index.examples == []
    assert index.retrieve("anything") == []
    assert index.format_prompt_section("anything") == ""
