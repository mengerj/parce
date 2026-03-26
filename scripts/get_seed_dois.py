#!/usr/bin/env python
"""Discover seed DOIs from the CELLxGENE Census datasets table.

Connects to the Census, filters for datasets that have a collection_doi,
and prints 5 DOIs sorted by total cell count (descending) along with
dataset count and cell totals.

Usage:
    python scripts/get_seed_dois.py
"""

from __future__ import annotations

import cellxgene_census


def main() -> None:
    print("Opening CELLxGENE Census...")
    census = cellxgene_census.open_soma()

    try:
        datasets = census["census_info"]["datasets"].read().concat().to_pandas()

        with_doi = datasets[datasets["collection_doi"].notna() & (datasets["collection_doi"] != "")]

        summary = (
            with_doi.groupby("collection_doi")
            .agg(
                dataset_count=("dataset_id", "count"),
                total_cells=("dataset_total_cell_count", "sum"),
                collection_name=("collection_name", "first"),
            )
            .sort_values("total_cells", ascending=False)
        )

        print(f"\nFound {len(summary)} unique DOIs across {len(with_doi)} datasets.\n")
        print("Top 5 DOIs by total cell count:\n")
        print(f"{'DOI':<45} {'Datasets':>8} {'Cells':>12}  Collection")
        print("-" * 110)

        for doi, row in summary.head(5).iterrows():
            name = row["collection_name"][:40] if isinstance(row["collection_name"], str) else ""
            print(f"{doi:<45} {row['dataset_count']:>8} {row['total_cells']:>12,}  {name}")

    finally:
        census.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
