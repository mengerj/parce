"""PARCE entry point.

Run with:
    python -m parce.main
or, after ``pip install -e .``:
    parce
"""

from __future__ import annotations

import asyncio
import json
import re

from pydantic import ValidationError

from parce.agent.curator import create_curator_agent
from parce.models.narrative import ExperimentNarrative


def _extract_json(text: str) -> str:
    """Pull the first JSON object out of ``text``, ignoring markdown fences."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    raw = re.search(r"\{.*\}", text, re.DOTALL)
    if raw:
        return raw.group(0)
    return text


async def run() -> None:
    query = (
        "Fetch and describe the experiment GSE164378 "
        "focusing on T-cell transcriptomics."
    )
    print(f"User: {query}\n")

    async with create_curator_agent() as agent:
        result = await agent.run(query)

        try:
            narrative = ExperimentNarrative.model_validate_json(
                _extract_json(result.text)
            )
            print("Structured narrative:\n")
            print(json.dumps(narrative.model_dump(), indent=2))
        except (ValidationError, json.JSONDecodeError) as exc:
            print("Could not parse structured output, raw response:\n")
            print(result.text)
            print(f"\nParse error: {exc}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
