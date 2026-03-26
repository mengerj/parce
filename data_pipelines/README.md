# Data Pipelines

This directory is reserved for future data engineering scripts.

## Planned Scope

- **FASTQ-to-Parquet conversion** using PySpark on Azure Databricks
- **ADLS Gen2 I/O utilities** for reading/writing experiment narratives and raw genomic data
- **Batch orchestration** scripts for processing large-scale T-cell transcriptomics datasets

These pipelines will consume the structured JSON narratives produced by the PARCE agent
and transform raw omics data into analysis-ready formats.
