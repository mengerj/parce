"""Factory for the PARCE narrative agent.

Uses ``AzureAIAgentClient`` (Azure AI Foundry provider) so any model
deployed in your Foundry project can be used -- GPT-4o, Mistral,
DeepSeek, Llama, etc. -- by changing a single env var.

In the hybrid architecture the agent's sole job is to generate an
experimental narrative from provided context.  All tool calling and
KG construction happens in Python.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from agent_framework import Agent
from agent_framework.azure import AzureAIAgentClient
from azure.identity.aio import AzureCliCredential

from parce.agent.prompts import NARRATIVE_INSTRUCTIONS
from parce.config.settings import Settings


@asynccontextmanager
async def create_narrative_agent(
    settings: Settings | None = None,
) -> AsyncIterator[Agent]:
    """Build and yield an Agent configured as a narrative writer.

    The agent receives publication abstract + structured ontology context
    and returns a ``NarrativeOutput`` via ``response_format``.

    Parameters
    ----------
    settings:
        Application settings.  When *None*, settings are loaded from the
        environment / ``.env`` file automatically.

    Yields
    ------
    Agent
        A ready-to-run agent that produces a narrative string.
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
            instructions=NARRATIVE_INSTRUCTIONS,
        ) as agent,
    ):
        yield agent
