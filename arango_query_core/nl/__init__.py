"""Language-agnostic NL→query engine (providers, few-shot retrieval, seams).

Extracted from ``arango_cypher.nl2cypher`` so ``nl2cypher``,
``nl2sparql``, and the contextual-data-fabric's NL front-end share one
engine instead of maintaining three forks. Language-specific behavior
enters exclusively through :class:`~arango_query_core.nl.seams.QueryLanguageAdapter`.
"""

from .engine import NLQueryEngine, NLResult
from .fewshot import BM25Retriever, FewShotIndex, Retriever
from .providers import (
    AnthropicProvider,
    LLMProvider,
    OpenAIProvider,
    OpenRouterProvider,
    get_llm_provider,
    split_system_for_anthropic_cache,
)
from .seams import GuardrailVerdict, QueryLanguageAdapter, ValidationResult

__all__ = [
    "AnthropicProvider",
    "BM25Retriever",
    "FewShotIndex",
    "GuardrailVerdict",
    "LLMProvider",
    "NLQueryEngine",
    "NLResult",
    "OpenAIProvider",
    "OpenRouterProvider",
    "QueryLanguageAdapter",
    "Retriever",
    "ValidationResult",
    "get_llm_provider",
    "split_system_for_anthropic_cache",
]
