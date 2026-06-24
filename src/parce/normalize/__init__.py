"""Normalizers: map a source's :class:`~parce.models.raw_record.RawRecord` into
canonical KG nodes.

A normalizer is deterministic for structured sources (a pure mapping) and
agent-backed for unstructured ones (an LLM constrained to the canonical schema
via ``response_format``). Either way it emits the same
:class:`~parce.models.graph_schema.KnowledgeGraphOutput` contract.
"""
