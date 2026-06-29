"""Azure-backed structured-extraction agent (the only Azure-touching module).

:class:`AzureExtractionAgent` is the concrete
:class:`~parce.agent.base.StructuredExtractor`: it sends free-text metadata to a
model deployed in an Azure AI Foundry project and constrains the reply to a
Pydantic schema via ``response_format`` — structured output only, never prose
(docs/ARCHITECTURE.md §3). It is used by the agent-backed normalizers (GEO, later
PRIDE) and, optionally, as the ontology resolver's LLM fallback.

The ``agent-framework`` API is async; this module bridges it to the **synchronous**
:class:`~parce.agent.base.StructuredExtractor` contract with ``asyncio.run`` so the
normalizers and the resolver stay synchronous. Credentials come from
``AzureCliCredential`` (an ``az login`` session) plus the project endpoint /
deployment in :class:`~parce.config.settings.Settings`. Nothing here runs at
import time, so importing the module needs no Azure session — only calling
:meth:`AzureExtractionAgent.extract` does (covered by the marked integration
tests, not unit CI).
"""

from __future__ import annotations

import asyncio
import logging

from agent_framework.azure import AzureAIAgentClient
from azure.identity.aio import AzureCliCredential
from pydantic import BaseModel, ConfigDict

from parce.agent.base import SchemaT, StructuredExtractor
from parce.config.settings import Settings
from parce.ontology import FACET_ONTOLOGY, Facet, ResolvedTerm
from parce.ontology.resolver import LlmFallback

logger = logging.getLogger(__name__)


class AzureExtractionAgent:
    """Structured extractor backed by an Azure AI Foundry model deployment.

    ``settings`` defaults to ``Settings()`` (loaded from the environment / ``.env``);
    pass an explicit instance in tests. ``temperature`` defaults to 0 for
    reproducible extraction.
    """

    def __init__(self, settings: Settings | None = None, *, temperature: float = 0.0) -> None:
        self._settings = settings if settings is not None else Settings()
        self._temperature = temperature

    def extract(self, instructions: str, content: str, response_model: type[SchemaT]) -> SchemaT:
        """Fill ``response_model`` from ``content`` (synchronous façade over async)."""
        return asyncio.run(self._aextract(instructions, content, response_model))

    async def _aextract(
        self, instructions: str, content: str, response_model: type[SchemaT]
    ) -> SchemaT:
        async with (
            AzureCliCredential() as credential,
            AzureAIAgentClient(
                project_endpoint=self._settings.azure_ai_project_endpoint,
                model_deployment_name=self._settings.azure_ai_model_deployment_name,
                credential=credential,
            ).as_agent(name="PARCE-extractor", instructions=instructions) as agent,
        ):
            result = await agent.run(
                content,
                response_format=response_model,
                options={"temperature": self._temperature},
            )

        # ``result.value`` is the parsed model when the backend honours
        # ``response_format``; otherwise fall back to validating ``result.text``.
        value = getattr(result, "value", None)
        if isinstance(value, response_model):
            return value
        text = (getattr(result, "text", None) or "").strip()
        if not text:
            raise ValueError("Extraction agent returned neither a structured value nor text")
        return response_model.model_validate_json(text)


# -- ontology resolver LLM fallback -------------------------------------------


class _FallbackTerm(BaseModel):
    """The shape the LLM returns when asked to ground one hard free-text string."""

    model_config = ConfigDict(extra="ignore")

    ontology_id: str | None = None
    name: str | None = None


_FALLBACK_INSTRUCTIONS = (
    "You map a single free-text experiment-design term to one ontology term. "
    "Return the term's CURIE (e.g. 'UBERON:0002048') in ontology_id and its label "
    "in name, using ONLY the requested ontology. If you are not confident the term "
    "exists in that ontology, return null for both fields — never invent an ID."
)


def make_ontology_fallback(extractor: StructuredExtractor) -> LlmFallback:
    """Adapt a :class:`StructuredExtractor` into the resolver's LLM-fallback hook.

    The resolver calls this only for strings its deterministic OLS lookups could
    not map (``llm_fallback`` is ``None`` by default, so wiring this in is opt-in).
    The result is accepted only when the returned CURIE carries the facet's
    expected ontology prefix, so a wrong-ontology or hallucinated ID is dropped
    rather than grounded.
    """

    def _fallback(text: str, facet: Facet) -> ResolvedTerm | None:
        primary = FACET_ONTOLOGY[facet].primary
        content = (
            f"Ontology: {primary.prefix} ({primary.title})\nFacet: {facet.value}\nTerm: {text}"
        )
        try:
            result = extractor.extract(_FALLBACK_INSTRUCTIONS, content, _FallbackTerm)
        except Exception as exc:
            logger.warning("LLM ontology fallback failed for %r (%s): %s", text, facet, exc)
            return None
        if result.ontology_id and result.ontology_id.startswith(f"{primary.prefix}:"):
            return ResolvedTerm(ontology_id=result.ontology_id, name=result.name or text)
        logger.info("LLM fallback returned no usable term for %r (%s)", text, facet)
        return None

    return _fallback
