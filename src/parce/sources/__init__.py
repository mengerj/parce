"""Source adapters: one per external omics repository.

Each adapter discovers and fetches raw records from a repository and hands them
to a normalizer. Network IO in these adapters goes through the shared
``with_retries`` helper in :mod:`parce.sources._retry`.
"""

from __future__ import annotations
