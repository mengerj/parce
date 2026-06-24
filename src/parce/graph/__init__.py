"""Graph assembly and cross-source merge.

Reserved for the KG merger (PR 6) that combines per-study
:class:`~parce.models.graph_schema.KnowledgeGraphOutput`s — one per normalized
source — into a single graph deduplicated by ontology ID. Per-study assembly
lives in the source normalizers (``parce.normalize``).
"""
