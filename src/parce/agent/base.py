"""The :class:`StructuredExtractor` contract.

An extractor is the single boundary between an agent-backed normalizer and a Large
Language Model. It does exactly one thing: take free-text metadata plus a target
Pydantic schema and return a populated, validated instance of that schema — the
*structured extraction* job the LLM is boxed into (docs/ARCHITECTURE.md §3). It
never returns prose.

Normalizers depend on this narrow, **synchronous** Protocol rather than on a
concrete Azure client, so they can be driven entirely offline in unit tests by
injecting a deterministic fake. The real implementation
(:class:`~parce.agent.extraction.AzureExtractionAgent`) bridges to the async
``agent-framework`` API internally; that async complexity never leaks past this
contract.
"""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

#: The schema an extraction call fills. Bound to ``BaseModel`` so the extractor
#: can validate the model's output against it via ``response_format``.
SchemaT = TypeVar("SchemaT", bound=BaseModel)


@runtime_checkable
class StructuredExtractor(Protocol):
    """Fills a Pydantic schema from free text via an LLM (structured output only)."""

    def extract(self, instructions: str, content: str, response_model: type[SchemaT]) -> SchemaT:
        """Return ``response_model`` populated from ``content`` under ``instructions``.

        ``instructions`` is the system prompt (what to extract and the design-only
        constraints); ``content`` is the free-text metadata to read. The result is
        a validated ``response_model`` instance — never narrative text.
        """
        ...
