"""Source adapters: one per repository, isolating all network IO.

Each adapter implements :class:`~parce.sources.base.SourceAdapter` and turns a
query into source-shaped :class:`~parce.models.raw_record.RawRecord` objects. It
never produces canonical nodes — that is the normalizer's job.
"""
