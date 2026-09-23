#!/usr/bin/env python3
"""Migrate the historical workbook into the tracker's Transactions sheet.

    python3 scripts/migrate_historical.py               # dry run, writes reports only
    python3 scripts/migrate_historical.py --apply       # backs up the tracker, then appends

The historical workbook is only ever read.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spending_tracker.migration import run_migration  # noqa: E402
from spending_tracker.paths import DEFAULT_SOURCE_WORKBOOK, DEFAULT_TRACKER_WORKBOOK  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE_WORKBOOK, help="historical workbook (read-only)")
    parser.add_argument("--tracker", type=Path, default=DEFAULT_TRACKER_WORKBOOK, help="tracker workbook to append to")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"), help="where reports are written")
    parser.add_argument("--apply", action="store_true", help="actually append the Ready rows")
    parser.add_argument("--no-backup", action="store_true", help="skip the timestamped tracker backup")
    parser.add_argument("--no-sidebar", action="store_true", help="ignore values outside transaction blocks")
    args = parser.parse_args()

    result = run_migration(
        source_workbook=args.source,
        tracker_workbook=args.tracker,
        output_dir=args.output_dir,
        apply=args.apply,
        make_backup=not args.no_backup,
        include_sidebar=not args.no_sidebar,
    )
    summary = result.summary

    print(f"Mode:              {'APPLY' if result.applied else 'DRY RUN'}")
    print(f"Source (readonly): {summary['source_workbook']}")
    print(f"Tracker:           {summary['tracker_workbook']}")
    print(f"Blocks detected:   {summary['blocks_detected']}")
    print(f"Rows detected:     {summary['total_rows_detected']}")
    print(f"Blank rows:        {summary['blank_rows_ignored']}")
    print(f"Ready:             {summary['ready_count']}")
    print(f"Needs review:      {summary['needs_review_count']}")
    print(f"Skipped:           {summary['skipped_count']}")
    print(f"Duplicates:        {summary['duplicate_count']}")
    print(f"Migrated now:      {result.migrated}")
    if result.backup_path:
        print(f"Tracker backup:    {result.backup_path}")
    print()
    print("Ready by type:")
    for name, bucket in summary["ready_by_type"].items():
        print(f"  {name:<12} {bucket['rows']:>4} rows  ${bucket['amount']:>12,.2f}")
    print("Ready by period:")
    for name, bucket in summary["ready_by_period"].items():
        print(f"  {name:<22} {bucket['rows']:>4} rows  ${bucket['amount']:>12,.2f}")
    print("Ready by date precision:")
    for name, bucket in summary["ready_by_precision"].items():
        print(f"  {name:<10} {bucket['rows']:>4} rows")
    print()
    print(f"Review CSV:  {result.review_path}")
    print(f"Report CSV:  {result.report_csv_path}")
    print(f"Report MD:   {result.report_md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
