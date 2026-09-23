#!/usr/bin/env python3
"""Audit the tracker against the original historical workbook.

    python3 scripts/reconcile_historical.py

Read-only: it opens the original workbook and the tracker for reading and writes
only the two report files under outputs/.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spending_tracker.paths import DEFAULT_SOURCE_WORKBOOK, DEFAULT_TRACKER_WORKBOOK  # noqa: E402
from spending_tracker.reconcile import (  # noqa: E402
    BUCKET_ORDER,
    RECONCILIATION_CSV,
    RECONCILIATION_MD,
    reconcile,
    write_reconciliation_csv,
    write_reconciliation_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE_WORKBOOK)
    parser.add_argument("--tracker", type=Path, default=DEFAULT_TRACKER_WORKBOOK)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args()

    result = reconcile(args.source, args.tracker)

    print(f"Original: {result.source_workbook}")
    print(f"Tracker:  {result.tracker_workbook}")
    print(f"Tracker rows: {result.tracker_rows} ({result.tracker_migrated_rows} migrated)")
    print()
    header = f"{'Period':<20} {'Type':<11} {'orig n':>6} {'orig $':>11} {'mig n':>6} {'mig $':>11} {'excl $':>10} {'diff $':>10}"
    print(header)
    print("-" * len(header))
    for row in result.rows:
        print(
            f"{row['Source Period']:<20} {row['Type']:<11} {row['Original rows']:>6} "
            f"{row['Original amount']:>11,.2f} {row['Migrated rows']:>6} {row['Migrated amount']:>11,.2f} "
            f"{row['Excluded amount']:>10,.2f} {row['Difference']:>10,.2f}"
        )
    print()
    print(f"{'TYPE':<12} {'orig n':>6} {'orig $':>12} {'mig n':>6} {'mig $':>12} {'excl n':>6} {'excl $':>11}")
    for name, bucket in sorted(result.totals_by_type.items()):
        print(
            f"{name:<12} {bucket['original_rows']:>6} {bucket['original_amount']:>12,.2f} "
            f"{bucket['migrated_rows']:>6} {bucket['migrated_amount']:>12,.2f} "
            f"{bucket['excluded_rows']:>6} {bucket['excluded_amount']:>11,.2f}"
        )
    print()
    print("Held back from migration:")
    for name in BUCKET_ORDER:
        items = result.buckets.get(name, [])
        if items:
            total = sum(candidate.amount or 0.0 for candidate in items)
            print(f"  {len(items):>3} row(s)  ${total:>11,.2f}  {name}")
    print()
    print("Reports:")
    print(" ", write_reconciliation_csv(result, args.output_dir / RECONCILIATION_CSV))
    print(" ", write_reconciliation_markdown(result, args.output_dir / RECONCILIATION_MD))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
