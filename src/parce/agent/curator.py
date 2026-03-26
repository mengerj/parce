"""Factory for the PARCE bioinformatics curator agent.

Uses ``AzureAIAgentClient`` (Azure AI Foundry provider) so any model
deployed in your Foundry project can be used -- Mistral, GPT-4o,
DeepSeek, Llama, etc. -- by changing a single env var.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from agent_framework import Agent
from agent_framework.azure import AzureAIAgentClient
from azure.identity.aio import AzureCliCredential

from parce.agent.prompts import CURATOR_INSTRUCTIONS
from parce.config.settings import Settings
from parce.tools.geo_fetcher import fetch_geo_metadata


@asynccontextmanager
async def create_curator_agent(
    settings: Settings | None = None,
) -> AsyncIterator[Agent]:
    """Build and yield an Agent configured as a bioinformatics curator.

    This is an async context manager because the Foundry client and
    credential need proper cleanup on exit.

    The agent is returned *without* a baked-in ``response_format`` so
    callers can pass it at ``agent.run()`` time, e.g.::

        result = await agent.run(query, options={"response_format": ExperimentNarrative})

    Parameters
    ----------
    settings:
        Application settings.  When *None*, settings are loaded from the
        environment / ``.env`` file automatically.

    Yields
    ------
    Agent
        A ready-to-run agent wired with the GEO fetcher tool.
    """
    if settings is None:
        settings = Settings()

    async with (
        AzureCliCredential() as credential,
        AzureAIAgentClient(
            project_endpoint=settings.azure_ai_project_endpoint,
            model_deployment_name=settings.azure_ai_model_deployment_name,
            credential=credential,
        ).as_agent(
            name="PARCE",
            instructions=CURATOR_INSTRUCTIONS,
            tools=[fetch_geo_metadata],
        ) as agent,
    ):
        yield agent
