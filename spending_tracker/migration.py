"""One-time migration of the historical workbook into the normalized Transactions sheet.

Design rules:

* the historical workbook is opened read-only and is never a write target;
* only ``Ready``/``High`` candidates are appended automatically - everything else
  lands in a review CSV;
* the tracker workbook is backed up before it is touched;
* migration is idempotent: a row's provenance (source sheet + cell) is its identity,
  so re-running adds nothing.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
import re

import pandas as pd

from spending_tracker.excel_store import (
    append_transactions,
    backup_workbook,
    load_transactions,
    upgrade_workbook_schema,
)
from spending_tracker.historical import (
    CONFIDENCE_HIGH,
    STATUS_NEEDS_REVIEW,
    STATUS_READY,
    STATUS_SKIPPED,
    BlockSpec,
    Candidate,
    extract,
)
from spending_tracker.schema import PRECISION_EXACT, PRECISION_MONTH, PRECISION_PERIOD, PRECISION_UNKNOWN


DEFAULT_OUTPUT_DIR = Path("outputs")
REVIEW_FILENAME = "historical_migration_review.csv"
REPORT_CSV_FILENAME = "historical_migration_report.csv"
REPORT_MD_FILENAME = "historical_migration_report.md"

REPORT_COLUMNS = [
    "Status",
    "Confidence",
    "Date",
    "Date Precision",
    "Description",
    "Amount",
    "Type",
    "Category",
    "Source Period",
    "Source Sheet",
    "Source Reference",
    "Source Area",
    "Source Line",
    "Review Note",
]


def normalize_description(value: object) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def provenance_identity(source_sheet: object, source_reference: object) -> tuple[str, str] | None:
    sheet = "" if source_sheet is None else str(source_sheet).strip()
    reference = "" if source_reference is None else str(source_reference).strip()
    if not sheet or not reference:
        return None
    return (sheet, reference)


def content_identity(
    transaction_date: object, description: object, amount: object, transaction_type: object
) -> tuple[str, str, float, str]:
    if isinstance(transaction_date, (datetime, pd.Timestamp)):
        date_text = transaction_date.date().isoformat()
    elif isinstance(transaction_date, date):
        date_text = transaction_date.isoformat()
    elif transaction_date is None or transaction_date != transaction_date:
        date_text = ""
    else:
        date_text = str(transaction_date)
    try:
        amount_value = round(float(amount), 2)
    except (TypeError, ValueError):
        amount_value = 0.0
    return (
        date_text,
        normalize_description(description),
        amount_value,
        "" if transaction_type is None else str(transaction_type).strip(),
    )


def existing_identities(frame: pd.DataFrame) -> tuple[set[tuple[str, str]], set[tuple[str, str, float, str]]]:
    """Identities already present in the tracker.

    A migrated row is identified by its source cell, which is unique, so re-running the
    migration matches on provenance.  Content identity is only collected for rows that
    carry no provenance - i.e. transactions typed in by hand - so that a historical row
    the user had already entered manually is not imported twice.  Content is deliberately
    *not* used for provenance-carrying rows: repeated purchases ("Quantum 11.63" three
    times in one term) share a content identity but are separate transactions.
    """
    provenance: set[tuple[str, str]] = set()
    content: set[tuple[str, str, float, str]] = set()
    if frame is None or frame.empty:
        return provenance, content

    for record in frame.to_dict("records"):
        identity = provenance_identity(record.get("Source Sheet"), record.get("Source Reference"))
        if identity is not None:
            provenance.add(identity)
        else:
            content.add(
                content_identity(
                    record.get("Date"), record.get("Description"), record.get("Amount"), record.get("Type")
                )
            )
    return provenance, content


def candidate_provenance(candidate: Candidate) -> tuple[str, str] | None:
    return provenance_identity(candidate.source_sheet, candidate.source_reference)


def candidate_content(candidate: Candidate) -> tuple[str, str, float, str]:
    return content_identity(
        candidate.date, candidate.description, candidate.amount, candidate.transaction_type
    )


def is_auto_migratable(candidate: Candidate) -> bool:
    return (
        candidate.status == STATUS_READY
        and candidate.confidence == CONFIDENCE_HIGH
        and candidate.amount is not None
        and candidate.amount > 0
        and bool(candidate.description)
        and candidate.date is not None
    )


@dataclass
class MigrationPlan:
    """Result of the dry run: what would be migrated, reviewed, skipped, deduped."""

    candidates: list[Candidate]
    to_migrate: list[Candidate]
    duplicates: list[Candidate]
    needs_review: list[Candidate]
    skipped: list[Candidate]
    blocks: list[BlockSpec] = field(default_factory=list)
    blank_rows_ignored: int = 0
    source_workbook: str = ""
    tracker_workbook: str = ""

    @property
    def summary(self) -> dict[str, object]:
        return summarize(self)


def dry_run(source_workbook: Path, tracker_workbook: Path, include_sidebar: bool = True) -> MigrationPlan:
    """Build the migration plan without writing anything anywhere."""
    extraction = extract(source_workbook, include_sidebar=include_sidebar)
    existing = load_transactions(tracker_workbook)
    known_provenance, known_content = existing_identities(existing)

    to_migrate: list[Candidate] = []
    duplicates: list[Candidate] = []
    needs_review: list[Candidate] = []
    skipped: list[Candidate] = []
    seen_provenance: set[tuple[str, str]] = set()

    for candidate in extraction.candidates:
        if candidate.status == STATUS_SKIPPED:
            skipped.append(candidate)
            continue
        if not is_auto_migratable(candidate):
            needs_review.append(candidate)
            continue

        provenance = candidate_provenance(candidate)
        already_migrated = provenance is not None and provenance in known_provenance
        entered_by_hand = candidate_content(candidate) in known_content
        same_source_cell = provenance is not None and provenance in seen_provenance
        if already_migrated or entered_by_hand or same_source_cell:
            duplicates.append(candidate)
            continue

        if provenance is not None:
            seen_provenance.add(provenance)
        to_migrate.append(candidate)

    return MigrationPlan(
        candidates=extraction.candidates,
        to_migrate=to_migrate,
        duplicates=duplicates,
        needs_review=needs_review,
        skipped=skipped,
        blocks=extraction.blocks,
        blank_rows_ignored=extraction.blank_rows_ignored,
        source_workbook=str(source_workbook),
        tracker_workbook=str(tracker_workbook),
    )


def _totals_by(candidates: list[Candidate], key) -> dict[str, dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for candidate in candidates:
        bucket = grouped.setdefault(key(candidate), {"rows": 0, "amount": 0.0})
        bucket["rows"] += 1
        bucket["amount"] = round(bucket["amount"] + (candidate.amount or 0.0), 2)
    return dict(sorted(grouped.items()))


def summarize(plan: MigrationPlan) -> dict[str, object]:
    ready = plan.to_migrate
    precision_counts: dict[str, int] = {}
    for candidate in plan.candidates:
        precision_counts[candidate.date_precision] = precision_counts.get(candidate.date_precision, 0) + 1

    ambiguous_examples = [
        {
            "Source": f"{candidate.source_sheet}!{candidate.source_reference}",
            "Description": candidate.description,
            "Amount": candidate.amount,
            "Type": candidate.transaction_type,
            "Review Note": candidate.review_note,
        }
        for candidate in plan.needs_review[:10]
    ]

    return {
        "source_workbook": plan.source_workbook,
        "tracker_workbook": plan.tracker_workbook,
        "blocks_detected": len(plan.blocks),
        "block_descriptions": [block.describe() for block in plan.blocks],
        "total_rows_detected": len(plan.candidates),
        "blank_rows_ignored": plan.blank_rows_ignored,
        "ready_count": len(ready),
        "needs_review_count": len(plan.needs_review),
        "skipped_count": len(plan.skipped),
        "duplicate_count": len(plan.duplicates),
        "ready_by_type": _totals_by(ready, lambda candidate: candidate.transaction_type),
        "ready_by_period": _totals_by(ready, lambda candidate: candidate.source_period),
        "ready_by_precision": _totals_by(ready, lambda candidate: candidate.date_precision),
        "all_by_precision": precision_counts,
        "ready_total_amount": round(sum(candidate.amount or 0.0 for candidate in ready), 2),
        "ambiguous_examples": ambiguous_examples,
    }


def _report_rows(candidates: list[Candidate], status_override: str | None = None) -> list[dict[str, object]]:
    rows = []
    for candidate in candidates:
        row = candidate.as_report_row()
        if status_override:
            row["Status"] = status_override
        row["Date"] = candidate.date.isoformat() if candidate.date else ""
        rows.append({column: row.get(column, "") for column in REPORT_COLUMNS})
    return rows


def _write_csv(path: Path, rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_review_csv(plan: MigrationPlan, path: Path) -> Path:
    """Rows a human has to look at: never-migrated candidates."""
    return _write_csv(path, _report_rows(plan.needs_review) + _report_rows(plan.skipped))


def write_report_csv(plan: MigrationPlan, path: Path) -> Path:
    rows = (
        _report_rows(plan.to_migrate, status_override="Migrated")
        + _report_rows(plan.duplicates, status_override="Duplicate (already migrated)")
        + _report_rows(plan.needs_review)
        + _report_rows(plan.skipped)
    )
    return _write_csv(path, rows)


def write_report_markdown(plan: MigrationPlan, path: Path, applied: bool, backup: Path | None = None) -> Path:
    summary = plan.summary
    lines: list[str] = []
    lines.append("# Historical migration report")
    lines.append("")
    lines.append(f"- Generated: {datetime.now().replace(microsecond=0).isoformat(sep=' ')}")
    lines.append(f"- Mode: {'applied' if applied else 'dry run'}")
    lines.append(f"- Source workbook (read-only): `{plan.source_workbook}`")
    lines.append(f"- Tracker workbook: `{plan.tracker_workbook}`")
    if backup:
        lines.append(f"- Tracker backup: `{backup}`")
    lines.append("")
    lines.append("## Counts")
    lines.append("")
    lines.append(f"- Transaction blocks detected: {summary['blocks_detected']}")
    lines.append(f"- Candidate rows detected: {summary['total_rows_detected']}")
    lines.append(f"- Blank rows ignored inside blocks: {summary['blank_rows_ignored']}")
    lines.append(f"- Ready (auto-migrated): {summary['ready_count']}")
    lines.append(f"- Needs review (not migrated): {summary['needs_review_count']}")
    lines.append(f"- Skipped (not transactions): {summary['skipped_count']}")
    lines.append(f"- Duplicates suppressed: {summary['duplicate_count']}")
    lines.append(f"- Ready dollar total: ${summary['ready_total_amount']:,.2f}")
    lines.append("")
    lines.append("## Blocks discovered")
    lines.append("")
    for description in summary["block_descriptions"]:
        lines.append(f"- {description}")
    lines.append("")
    for title, key in (
        ("Ready rows by Type", "ready_by_type"),
        ("Ready rows by Source Period", "ready_by_period"),
        ("Ready rows by Date Precision", "ready_by_precision"),
    ):
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| Key | Rows | Amount |")
        lines.append("| --- | ---: | ---: |")
        for name, bucket in summary[key].items():
            lines.append(f"| {name} | {bucket['rows']} | ${bucket['amount']:,.2f} |")
        lines.append("")
    lines.append("## Date precision across all detected rows")
    lines.append("")
    for name, count in sorted(summary["all_by_precision"].items()):
        lines.append(f"- {name}: {count}")
    lines.append("")
    lines.append("## Ambiguous row examples (first 10 needing review)")
    lines.append("")
    for example in summary["ambiguous_examples"]:
        amount = example["Amount"]
        amount_text = f"${amount:,.2f}" if isinstance(amount, (int, float)) else "(no amount)"
        lines.append(
            f"- `{example['Source']}` {example['Description']!r} "
            f"{amount_text} [{example['Type']}] - {example['Review Note']}"
        )
    lines.append("")
    lines.append("## Date handling")
    lines.append("")
    lines.append(
        f"- `{PRECISION_EXACT}`: the source row had a real date; it is used as-is."
    )
    lines.append(
        f"- `{PRECISION_MONTH}`: only a month was recorded (e.g. \"Rent+ Aug.\"); stored as the 1st "
        "of that month, with the year chosen from the dates present in the same block."
    )
    lines.append(
        f"- `{PRECISION_PERIOD}`: only the school term / block was known; stored as the midpoint of the "
        "dated rows in that block purely so the row can be sorted and filtered."
    )
    lines.append(
        f"- `{PRECISION_UNKNOWN}`: no date information at all; these rows are never auto-migrated."
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@dataclass
class MigrationResult:
    plan: MigrationPlan
    migrated: int
    duplicates: int
    needs_review: int
    skipped: int
    backup_path: Path | None
    review_path: Path
    report_csv_path: Path
    report_md_path: Path
    applied: bool

    @property
    def summary(self) -> dict[str, object]:
        return self.plan.summary


def run_migration(
    source_workbook: Path,
    tracker_workbook: Path,
    output_dir: Path | None = None,
    apply: bool = False,
    make_backup: bool = True,
    include_sidebar: bool = True,
) -> MigrationResult:
    """Dry run (default) or apply the historical migration.

    The source workbook is only ever read.  Raises ValueError if the tracker and the
    source are the same file, so the historical workbook can never be written to.
    """
    source_workbook = Path(source_workbook)
    tracker_workbook = Path(tracker_workbook)
    if source_workbook.resolve() == tracker_workbook.resolve():
        raise ValueError(
            "Refusing to migrate into the historical workbook; pass a separate tracker copy."
        )
    if not source_workbook.exists():
        raise FileNotFoundError(f"Historical workbook not found: {source_workbook}")

    directory = Path(output_dir or DEFAULT_OUTPUT_DIR)
    plan = dry_run(source_workbook, tracker_workbook, include_sidebar=include_sidebar)

    backup_path: Path | None = None
    migrated = 0
    if apply and plan.to_migrate:
        if make_backup:
            backup_path = backup_workbook(tracker_workbook)
        upgrade_workbook_schema(tracker_workbook)
        migrated = append_transactions(
            tracker_workbook, [candidate.as_row() for candidate in plan.to_migrate]
        )

    review_path = write_review_csv(plan, directory / REVIEW_FILENAME)
    report_csv_path = write_report_csv(plan, directory / REPORT_CSV_FILENAME)
    report_md_path = write_report_markdown(
        plan, directory / REPORT_MD_FILENAME, applied=apply, backup=backup_path
    )
    if migrated:
        # Keep an immutable record of what this apply actually wrote; the files above
        # are regenerated by every later run.
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        archive = directory / f"{Path(REPORT_MD_FILENAME).stem}-{stamp}.md"
        archive.write_text(report_md_path.read_text(encoding="utf-8"), encoding="utf-8")

    return MigrationResult(
        plan=plan,
        migrated=migrated,
        duplicates=len(plan.duplicates),
        needs_review=len(plan.needs_review),
        skipped=len(plan.skipped),
        backup_path=backup_path,
        review_path=review_path,
        report_csv_path=report_csv_path,
        report_md_path=report_md_path,
        applied=apply,
    )


__all__ = [
    "MigrationPlan",
    "MigrationResult",
    "REPORT_COLUMNS",
    "REPORT_CSV_FILENAME",
    "REPORT_MD_FILENAME",
    "REVIEW_FILENAME",
    "candidate_content",
    "candidate_provenance",
    "content_identity",
    "dry_run",
    "existing_identities",
    "is_auto_migratable",
    "normalize_description",
    "provenance_identity",
    "run_migration",
    "summarize",
    "write_report_csv",
    "write_report_markdown",
    "write_review_csv",
]
