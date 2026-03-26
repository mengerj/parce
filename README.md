# PARCE

**Programmable Agent for Retrieving Contextualized Experiments**

PARCE is an agentic workflow that fetches public omics data (starting with T-cell transcriptomics from NCBI GEO) and produces structured JSON narratives describing how the data was obtained. Each narrative interleaves human-readable descriptions with URI references to raw data files, making it suitable for training multimodal autoregressive embedding models.

## Architecture

```
User / CLI
    │
    ▼
main.py ──► agent/curator.py ──► AzureAIAgentClient
                                        │
                              ┌─────────┴─────────┐
                              │  Azure AI Foundry  │
                              │  (any model)       │
                              └─────────┬─────────┘
                                        │
                            ┌───────────┼───────────┐
                            ▼           │           ▼
                    tool_call:          │    structured output:
                 geo_fetcher.py         │    ExperimentNarrative
                    (tools/)            │       (models/)
                            │           │
                            ▼           │
                     metadata JSON ─────┘
```

The agent uses **Azure AI Foundry** as its model gateway. Any model deployed in your Foundry project -- Mistral, GPT-4o, DeepSeek, Llama, etc. -- can be used by changing a single environment variable (`AZURE_AI_MODEL_DEPLOYMENT_NAME`). Tools, prompts, and Pydantic output schemas remain unchanged.

### Directory Structure

```
parce/
├── pyproject.toml              # Dependencies and build config
├── .env.example                # Template for required env vars
├── src/
│   └── parce/
│       ├── main.py             # Entry point
│       ├── agent/
│       │   ├── curator.py      # Agent factory (AzureAIAgentClient)
│       │   └── prompts.py      # System prompts
│       ├── tools/
│       │   └── geo_fetcher.py  # GEO metadata fetcher (stub)
│       ├── models/
│       │   └── narrative.py    # Pydantic output schemas
│       └── config/
│           └── settings.py     # Env-based configuration
├── data_pipelines/             # Future: Spark / ADLS scripts
├── data/                       # Local test data (gitignored)
└── tests/
    └── test_models.py
```

**Key design decisions:**

- **src-layout** prevents accidental imports from the project root.
- **agent/** is decoupled from **tools/** so new data sources (e.g. TCellAtlas, SRA) are added as new tool files without touching orchestration logic.
- **models/** schemas serve double duty: structured output for the agent (`response_format`) and validation for downstream consumers.
- **data_pipelines/** lives at the repo root because Spark jobs are submitted independently from the Python package.

## Prerequisites

- Python 3.11+
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) installed
- An [Azure AI Foundry](https://learn.microsoft.com/en-us/azure/ai-foundry/what-is-ai-foundry) project with at least one model deployed (e.g. Mistral Large, GPT-4o, DeepSeek-R1)

## Local Setup

### 1. Authenticate with Azure

```bash
az login
```

This lets `AzureCliCredential` obtain tokens for your Foundry project without managing API keys.

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your Foundry project endpoint and deployment name:

```
AZURE_AI_PROJECT_ENDPOINT=https://<your-resource>.services.ai.azure.com/api/projects/<project-id>
AZURE_AI_MODEL_DEPLOYMENT_NAME=mistral-large
```

The project endpoint is found in your Azure AI Foundry project settings page.

### 3. Install

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

> **Note:** The `agent-framework` packages are currently in pre-release. If installation fails, run:
> ```bash
> pip install agent-framework agent-framework-azure-ai --pre
> pip install -e ".[dev]"
> ```

### 4. Run the agent

```bash
parce
# or
python -m parce.main
```

The agent will fetch mock metadata for GSE164378 and return a structured `ExperimentNarrative` JSON.

### 5. Run tests

```bash
pytest
```

## Switching Models

Because PARCE uses Azure AI Foundry as a model gateway, swapping the underlying LLM is a one-line change in `.env`:

```bash
# Mistral
AZURE_AI_MODEL_DEPLOYMENT_NAME=mistral-large

# OpenAI
AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-4o

# DeepSeek
AZURE_AI_MODEL_DEPLOYMENT_NAME=DeepSeek-R1

# Meta Llama
AZURE_AI_MODEL_DEPLOYMENT_NAME=Meta-Llama-3-70B
```

The deployment name must match a model you have deployed in your Foundry project's model catalog. No code changes are required -- all providers produce a standard `Agent` with the same interface.

For models **not** in the Azure AI Foundry catalog (e.g. Anthropic Claude), the Microsoft Agent Framework provides dedicated providers (`AnthropicChatClient`) with an identical agent interface.

## Future Roadmap

### Data Engineering Pipelines (`data_pipelines/`)

- **FASTQ-to-Parquet** conversion using PySpark on Azure Databricks
- **Azure Data Lake Storage Gen2** integration for persisting narratives and raw genomic data at scale
- Batch orchestration for processing large T-cell transcriptomics datasets

### Additional Data Sources

- **TCellAtlas** fetcher tool
- **SRA** direct metadata fetcher
- **CellxGene** Census integration

### Embedding Model Training

The structured narratives produced by PARCE will serve as training data for a multimodal autoregressive embedding model that jointly learns from experimental metadata and raw omics signals.
