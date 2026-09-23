#!/usr/bin/env python3
"""Fill in the Category column of the tracker workbook using the deterministic rules.

    python3 scripts/categorize_transactions.py            # only blank categories
    python3 scripts/categorize_transactions.py --overwrite # re-run every Expense row
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spending_tracker.manage import recategorize  # noqa: E402
from spending_tracker.paths import DEFAULT_TRACKER_WORKBOOK  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tracker", type=Path, default=DEFAULT_TRACKER_WORKBOOK)
    parser.add_argument("--overwrite", action="store_true", help="replace existing categories too")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    result = recategorize(
        args.tracker,
        overwrite=args.overwrite,
        make_backup=not args.no_backup,
    )
    print(f"Rows:    {result['rows']}")
    print(f"Changed: {result['changed']}")
    print(f"Written: {result['written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
