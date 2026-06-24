"""Azure extraction agent (structured output only).

Reserved for the GEO/PRIDE extraction normalizers (PR 5+): an LLM constrained by
``response_format`` to emit the canonical KG schema from free-text metadata. The
legacy narrative agent that once lived here was removed in PR 3 — the LLM never
writes prose. See docs/ARCHITECTURE.md §3.
"""
