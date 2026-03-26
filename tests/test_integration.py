"""Integration tests that verify the Azure AI Foundry connection.

These tests require:
  1. A valid .env (or exported env vars) with AZURE_AI_PROJECT_ENDPOINT
  2. An active ``az login`` session

Run them explicitly with:
    pytest -m integration
"""

from __future__ import annotations

import pytest
from azure.identity.aio import AzureCliCredential

from parce.config.settings import Settings

pytestmark = pytest.mark.integration


class TestSettings:
    """Verify that the .env / environment is configured correctly."""

    def test_settings_load(self):
        """Settings can be instantiated from the environment."""
        settings = Settings()
        assert settings.azure_ai_project_endpoint.startswith("https://")
        assert len(settings.azure_ai_model_deployment_name) > 0


class TestAzureCredential:
    """Verify that ``az login`` credentials work."""

    async def test_credential_get_token(self):
        """AzureCliCredential can obtain a token for the Azure AI scope."""
        async with AzureCliCredential() as credential:
            token = await credential.get_token(
                "https://cognitiveservices.azure.com/.default"
            )
            assert token.token
            assert len(token.token) > 0


class TestAgentCreation:
    """Verify the agent can be created against the live Foundry project."""

    async def test_create_narrative_agent(self):
        """The narrative agent context manager yields a usable Agent."""
        from parce.agent.curator import create_narrative_agent

        async with create_narrative_agent() as agent:
            assert agent is not None
            assert agent.name == "PARCE"
