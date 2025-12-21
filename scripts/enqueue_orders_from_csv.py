#!/usr/bin/env python3
"""
Enqueue Shopify CSV export rows as PackChicken jobs.

Usage:
    uv run scripts/enqueue_orders_from_csv.py --csv ../orders_export.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

from packchicken.utils import db
from packchicken.utils.orders_csv import enqueue_orders_from_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Enqueue orders from Shopify CSV exports.")
    parser.add_argument("--csv", help="Path to a Shopify orders CSV; if omitted, reads all CSV in ./ORDERS/")
    args = parser.parse_args()

    db.init_db()
    if args.csv:
        csv_paths = [Path(args.csv)]
    else:
        orders_dir = Path("ORDERS")
        if not orders_dir.exists():
            raise SystemExit("Fant ingen CSV. Opprett en ORDERS/ katalog med eksportfil(er).")
        csv_paths = sorted(orders_dir.glob("*.csv"))
        if not csv_paths:
            raise SystemExit("Ingen CSV-filer i ORDERS/.")

    total_created = 0
    for csv_path in csv_paths:
        if not csv_path.exists():
            print(f"⚠️ Hopper over {csv_path} (finnes ikke)")
            continue
        order_ids = enqueue_orders_from_csv(csv_path)
        total_created += len(order_ids)
        for oid in order_ids:
            print(f"[{csv_path.name}] ✅ La inn jobb for ordre {oid}")
        print(f"[{csv_path.name}] Ferdig: la inn {len(order_ids)} jobber")

    print(f"Totalt lagt inn {total_created} jobber")


if __name__ == "__main__":
    main()
