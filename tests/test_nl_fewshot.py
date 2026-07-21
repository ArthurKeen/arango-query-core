"""Few-shot index: corpus loading (canonical + legacy keys), retrieval,
prompt-section rendering, and graceful degradation."""

from __future__ import annotations

import sys
import zlib
from pathlib import Path

import numpy as np
import pytest

from arango_query_core.nl import DenseRetriever, FewShotIndex


def _write_corpus(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


_FAKE_DIM = 16


class _FakeEncoder:
    """Deterministic bag-of-words "embedding" — no torch, no network.

    Hashes each whitespace/word token into one of ``_FAKE_DIM`` buckets and
    L2-normalizes the resulting vector, so texts sharing words end up with
    higher cosine similarity — enough signal to exercise DenseRetriever's
    ranking logic without a real model.
    """

    def __call__(self, texts: list[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), _FAKE_DIM), dtype=float)
        for row, text in enumerate(texts):
            for token in text.lower().split():
                # zlib.crc32 is process-stable, unlike the builtin hash() whose
                # per-process PYTHONHASHSEED randomization made this "deterministic"
                # encoder non-deterministic (test_dense_retrieval_ranks_by_relevance
                # flaked ~25% of runs).
                vectors[row, zlib.crc32(token.encode()) % _FAKE_DIM] += 1.0
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms


class _ConstantEncoder:
    """Fake encoder returning the SAME vector for every input text.

    Used to test tie-break-by-index: when all candidates score identically,
    the earlier-indexed example must win.
    """

    def __call__(self, texts: list[str]) -> np.ndarray:
        return np.ones((len(texts), _FAKE_DIM), dtype=float) / (_FAKE_DIM**0.5)


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


def test_dense_retrieval_ranks_by_relevance() -> None:
    examples = [
        ("count all movies released after a year", "Q_MOVIES"),
        ("list every person and their friends", "Q_FRIENDS"),
        ("total orders per customer segment", "Q_ORDERS"),
    ]
    retriever = DenseRetriever(examples, encoder=_FakeEncoder())
    top = retriever.retrieve("how many movies came out after a year?", k=1)
    assert top and top[0][1] == "Q_MOVIES"


def test_dense_ties_break_by_index() -> None:
    examples = [
        ("first example", "Q_FIRST"),
        ("second example", "Q_SECOND"),
    ]
    retriever = DenseRetriever(examples, encoder=_ConstantEncoder())
    top = retriever.retrieve("anything", k=1)
    assert top == [("first example", "Q_FIRST")]


def test_dense_empty_examples_returns_empty() -> None:
    retriever = DenseRetriever([], encoder=_FakeEncoder())
    assert retriever.retrieve("anything") == []


def test_from_corpus_files_dense_mode_hard_raises_without_st(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = _write_corpus(
        tmp_path,
        "c.yml",
        """
examples:
  - question: "find all people"
    query: "Q1"
""",
    )
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(ImportError, match="sentence-transformers"):
        FewShotIndex.from_corpus_files([corpus], mode="dense")


def test_from_corpus_files_auto_mode_degrades_to_bm25(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    index = FewShotIndex.from_corpus_files([corpus], mode="auto")
    top = index.retrieve("how many movies came out after 2000?", k=1)
    assert top and top[0][1] == "Q_MOVIES"
    assert index.format_prompt_section("anything") == ""
