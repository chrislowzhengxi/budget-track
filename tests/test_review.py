from __future__ import annotations

from datetime import date
from pathlib import Path
import hashlib
import json

import pytest

from spending_tracker.excel_store import load_transactions
from spending_tracker.historical import Candidate
from spending_tracker.manage import read_audit
from spending_tracker.migration import run_migration
from spending_tracker.review import (
    ACTION_APPROVE,
    ACTION_APPROVE_EDITED,
    AUDIT_APPROVE,
    AUDIT_IGNORE,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    DEFAULT_REVIEW_STATE_PATH,
    STATUS_APPROVED,
    STATUS_IGNORED,
    ReviewError,
    approve_item,
    build_queue,
    forget_decision,
    formula_details,
    ignore_item,
    load_state,
    queue_frame,
    save_state,
    sheet_representative_dates,
    suggest,
)
from spending_tracker.schema import PRECISION_PERIOD, PRECISION_UNKNOWN, TRANSACTION_COLUMNS


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _queue(source: Path, tracker: Path, state: Path):
    return build_queue(source, tracker, state_path=state)


def _candidate(description: str, amount: float, note: str, area: str = "Block", **kwargs) -> Candidate:
    return Candidate(
        description=description,
        amount=amount,
        transaction_type=kwargs.pop("transaction_type", "Expense"),
        source_sheet=kwargs.pop("source_sheet", "25-26"),
        source_reference=kwargs.pop("source_reference", "C10"),
        source_line=kwargs.pop("source_line", f"{description} | {amount}"),
        source_period=kwargs.pop("source_period", "25-26"),
        review_note=note,
        source_area=area,
        **kwargs,
    )


# --- suggestions -----------------------------------------------------------------


def test_default_state_path_lives_in_the_data_directory() -> None:
    assert DEFAULT_REVIEW_STATE_PATH.name == "historical_review.json"
    assert DEFAULT_REVIEW_STATE_PATH.parent.name == "data"


def test_rent_credits_are_suggested_as_income_reimbursements(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Rent!B4")

    assert item.original_description == "Sandra"
    assert item.original_amount == 2400
    assert item.suggestion.transaction_type == "Income"
    assert item.suggestion.description == "Sandra rent reimbursement"
    assert item.suggestion.confidence == CONFIDENCE_HIGH
    assert item.suggestion.category == ""
    assert "Rent column" in item.suggestion.rationale


def test_named_credit_rows_are_suggested_as_income(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    queue = _queue(review_workbook, legacy_tracker, review_state_path)

    nba = queue.get("Spring 25!C5")
    assert (nba.suggestion.transaction_type, nba.suggestion.confidence) == ("Income", CONFIDENCE_HIGH)
    assert nba.suggestion.description == "NBA Pay"

    discover = queue.get("Spring 25!C6")
    assert (discover.suggestion.transaction_type, discover.suggestion.confidence) == (
        "Income",
        CONFIDENCE_HIGH,
    )
    # The description keeps saying it was a credit.
    assert discover.suggestion.description == "Discover Credit"


def test_brokerage_sidebar_rows_are_suggested_as_investments(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Spring 25!F6")

    assert item.suggestion.transaction_type == "Investment"
    assert item.suggestion.confidence == CONFIDENCE_HIGH
    assert item.suggestion.transaction_date == date(2025, 4, 2)
    assert item.suggestion.date_precision == PRECISION_PERIOD


@pytest.mark.parametrize(
    "item_id",
    ["Spring 25!F9", "Spring 25!C7", "Spring 25!C8", "Spring 25!C9"],
)
def test_rows_that_must_not_be_pre_approved_stay_low_confidence(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path, item_id: str
) -> None:
    # Deposit from Uchicago, Draft Kings, Check Adjustment and the formula row.
    item = _queue(review_workbook, legacy_tracker, review_state_path).get(item_id)

    assert item.suggestion.confidence == CONFIDENCE_LOW


def test_a_large_unlabelled_sidebar_figure_is_low_confidence() -> None:
    candidate = _candidate(
        "Wee (11/1)",
        10000.0,
        "Value outside any transaction block (nearest label 'Wee (11/1)'); no date available",
        area="Sidebar",
    )

    suggestion = suggest(candidate)

    assert suggestion.confidence == CONFIDENCE_LOW
    assert suggestion.transaction_type == "Expense"


def test_formula_rows_explain_themselves_and_are_never_suggested() -> None:
    candidate = _candidate("Lost from Tax", 100.96, "Amount cell is a formula (=O8) - may be a reference")

    suggestion = suggest(candidate)

    assert suggestion.confidence == CONFIDENCE_LOW
    assert "formula" in suggestion.rationale.lower()


def test_no_unresolved_row_is_ever_marked_approved_automatically(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    queue = _queue(review_workbook, legacy_tracker, review_state_path)

    assert queue.approved == []
    assert queue.ignored == []
    assert load_state(review_state_path) == {}
    assert not review_state_path.exists()
    # Nothing reached the tracker just by building the queue.
    assert len(load_transactions(legacy_tracker)) == 5


def test_sheet_midpoint_matches_the_date_the_migration_uses(
    historical_workbook: Path, legacy_tracker: Path
) -> None:
    run_migration(historical_workbook, legacy_tracker, output_dir=legacy_tracker.parent, apply=True)

    midpoints = sheet_representative_dates(historical_workbook)
    migrated = load_transactions(legacy_tracker)
    investment = migrated[migrated["Source Reference"] == "I3"].iloc[0]

    assert midpoints["Rent, Income"] == date(2024, 2, 1)
    assert investment["Date"].date() == midpoints["Rent, Income"]
    assert investment["Date Precision"] == PRECISION_PERIOD


def test_formula_details_shows_the_formula_and_referenced_cells(review_workbook: Path) -> None:
    formula, references = formula_details(review_workbook, "Spring 25", "C9")

    assert formula == "=25.67 + 17.84"
    assert references == {}
    assert formula_details(review_workbook, "Spring 25", "C3") == ("", {})
    assert formula_details(review_workbook, "Nope", "C9") == ("", {})


# --- summary ---------------------------------------------------------------------


def test_summary_counts_and_unresolved_amount(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    summary = _queue(review_workbook, legacy_tracker, review_state_path).summary

    assert summary["unresolved"] == 8
    assert summary["high_confidence"] == 4
    assert summary["approved"] == 0
    assert summary["ignored"] == 0
    # The formula row has no cached amount, so it contributes nothing to the total.
    assert summary["unresolved_amount"] == 8160.0


def test_queue_frame_exposes_every_documented_column(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    frame = queue_frame(_queue(review_workbook, legacy_tracker, review_state_path).unresolved)

    for column in [
        "Source Period",
        "Source Sheet",
        "Source Reference",
        "Original description",
        "Original amount",
        "Reason",
        "Suggested Description",
        "Suggested Type",
        "Suggested Category",
        "Suggested Date",
        "Suggested Date Precision",
        "Confidence",
    ]:
        assert column in frame.columns
    assert queue_frame([]).empty


# --- approve ---------------------------------------------------------------------


def test_approve_writes_the_suggested_row_with_provenance(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Rent!B4")

    result = approve_item(item, legacy_tracker, state_path=review_state_path)

    assert result["imported"] is True
    assert result["action"] == ACTION_APPROVE
    transactions = load_transactions(legacy_tracker)
    assert list(transactions.columns) == TRANSACTION_COLUMNS
    row = transactions[transactions["Source Reference"] == "B4"].iloc[0]
    assert row["Description"] == "Sandra rent reimbursement"
    assert row["Amount"] == 2400
    assert row["Type"] == "Income"
    assert row["Category"] == ""
    assert row["Source Sheet"] == "Rent"
    assert row["Source Period"] == "Rent"
    assert row["Source Line"] == item.source_line
    assert row["Date Precision"] == PRECISION_PERIOD
    assert row["Date"].date() == date(2025, 4, 1)
    assert row["Added At"]


def test_approve_creates_a_backup_and_an_audit_entry(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    before = _sha256(legacy_tracker)
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Spring 25!C5")

    result = approve_item(item, legacy_tracker, state_path=review_state_path)

    backup = Path(str(result["backup"]))
    assert backup.exists()
    assert _sha256(backup) == before
    assert backup.parent.name == "backups"
    entry = read_audit(legacy_tracker)[0]
    assert entry["action"] == AUDIT_APPROVE
    assert entry["details"]["item"] == "Spring 25!C5"


def test_approve_can_skip_the_backup(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Spring 25!C5")

    result = approve_item(item, legacy_tracker, state_path=review_state_path, make_backup=False)

    assert result["backup"] is None
    assert not (legacy_tracker.parent / "backups").exists()


def test_edit_then_approve_applies_my_changes(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Spring 25!F9")

    result = approve_item(
        item,
        legacy_tracker,
        overrides={
            "Description": "UChicago deposit",
            "Amount": 5000.0,
            "Type": "Income",
            "Date": date(2025, 4, 15),
            "Date Precision": "Exact",
        },
        state_path=review_state_path,
    )

    assert result["action"] == ACTION_APPROVE_EDITED
    row = load_transactions(legacy_tracker)
    row = row[row["Source Reference"] == "F9"].iloc[0]
    assert row["Description"] == "UChicago deposit"
    assert row["Type"] == "Income"
    assert row["Amount"] == 5000
    assert row["Date"].date() == date(2025, 4, 15)
    assert row["Date Precision"] == "Exact"
    assert row["Category"] == ""  # cleared: categories are for Expense rows only
    assert row["Source Sheet"] == "Spring 25"
    assert row["Source Reference"] == "F9"
    state = load_state(review_state_path)
    assert set(state["Spring 25!F9"]["edited_fields"]) == {"Description", "Type", "Date", "Date Precision"}


def test_edit_and_approve_keeps_a_category_for_expense_rows(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Spring 25!C9")

    approve_item(
        item,
        legacy_tracker,
        overrides={"Amount": 43.51, "Category": "Transportation"},
        state_path=review_state_path,
    )

    row = load_transactions(legacy_tracker)
    row = row[row["Source Reference"] == "C9"].iloc[0]
    assert row["Type"] == "Expense"
    assert row["Amount"] == 43.51
    assert row["Category"] == "Transportation"


def test_approving_without_a_date_is_recorded_as_unknown_precision(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Spring 25!F6")

    approve_item(item, legacy_tracker, overrides={"Date": None}, state_path=review_state_path)

    row = load_transactions(legacy_tracker)
    row = row[row["Source Reference"] == "F6"].iloc[0]
    assert row["Date Precision"] == PRECISION_UNKNOWN


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"Amount": 0}, "greater than zero"),
        ({"Amount": -5}, "greater than zero"),
        ({"Amount": None}, "amount is required"),
        ({"Description": "  "}, "description is required"),
        ({"Type": "Savings"}, "Type must be one of"),
    ],
)
def test_approve_refuses_invalid_input(
    review_workbook: Path,
    legacy_tracker: Path,
    review_state_path: Path,
    overrides: dict,
    message: str,
) -> None:
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Rent!B4")
    before = len(load_transactions(legacy_tracker))

    with pytest.raises(ReviewError, match=message):
        approve_item(item, legacy_tracker, overrides=overrides, state_path=review_state_path)

    assert len(load_transactions(legacy_tracker)) == before
    assert load_state(review_state_path) == {}


def test_a_formula_row_cannot_be_approved_until_i_give_it_an_amount(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Spring 25!C9")

    assert item.original_amount is None
    with pytest.raises(ReviewError, match="amount is required"):
        approve_item(item, legacy_tracker, state_path=review_state_path)


# --- duplicates and idempotency --------------------------------------------------


def test_approving_the_same_item_twice_writes_one_row(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Rent!B4")

    first = approve_item(item, legacy_tracker, state_path=review_state_path)
    second = approve_item(item, legacy_tracker, state_path=review_state_path)

    transactions = load_transactions(legacy_tracker)
    assert first["imported"] is True
    assert second["imported"] is False
    assert second["duplicate"] is True
    assert "already in the tracker" in str(second["message"])
    assert len(transactions[transactions["Source Reference"] == "B4"]) == 1


def test_an_approved_row_leaves_the_queue(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Rent!B4")
    approve_item(item, legacy_tracker, state_path=review_state_path)

    queue = _queue(review_workbook, legacy_tracker, review_state_path)

    assert "Rent!B4" not in {entry.item_id for entry in queue.unresolved}
    assert "Rent!B4" in {entry.item_id for entry in queue.approved}
    assert queue.summary["unresolved"] == 7
    assert queue.summary["approved"] == 1


def test_an_approved_row_stays_out_even_if_the_decision_file_is_lost(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Rent!B4")
    approve_item(item, legacy_tracker, state_path=review_state_path)
    review_state_path.unlink()

    queue = _queue(review_workbook, legacy_tracker, review_state_path)

    # Provenance already in the tracker is enough to keep it out of the queue.
    assert "Rent!B4" in queue.already_in_tracker
    assert "Rent!B4" not in {entry.item_id for entry in queue.unresolved}


def test_reloading_the_queue_is_idempotent(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Spring 25!C5")
    approve_item(item, legacy_tracker, state_path=review_state_path)
    ignore_item(
        _queue(review_workbook, legacy_tracker, review_state_path).get("Spring 25!F9"),
        legacy_tracker,
        note="reference figure",
        state_path=review_state_path,
    )

    first = _queue(review_workbook, legacy_tracker, review_state_path)
    second = _queue(review_workbook, legacy_tracker, review_state_path)
    rows_after_first = len(load_transactions(legacy_tracker))
    third = _queue(review_workbook, legacy_tracker, review_state_path)

    assert first.summary == second.summary == third.summary
    assert [entry.item_id for entry in first.unresolved] == [entry.item_id for entry in second.unresolved]
    assert len(load_transactions(legacy_tracker)) == rows_after_first


def test_the_queue_survives_a_workbook_the_migration_has_fully_processed(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    run_migration(review_workbook, legacy_tracker, output_dir=legacy_tracker.parent, apply=True)

    queue = _queue(review_workbook, legacy_tracker, review_state_path)

    # Migrated rows are not review items, so the queue is unchanged by the migration.
    assert queue.summary["unresolved"] == 8


# --- ignore ----------------------------------------------------------------------


def test_ignore_permanently_keeps_an_item_out_of_the_queue(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Spring 25!F9")
    before = len(load_transactions(legacy_tracker))

    result = ignore_item(item, legacy_tracker, note="deposit, not spending", state_path=review_state_path)

    queue = _queue(review_workbook, legacy_tracker, review_state_path)
    state = load_state(review_state_path)
    assert result["ignored"] is True
    assert state["Spring 25!F9"]["status"] == STATUS_IGNORED
    assert state["Spring 25!F9"]["note"] == "deposit, not spending"
    assert state["Spring 25!F9"]["original_amount"] == 5000.0
    assert "Spring 25!F9" not in {entry.item_id for entry in queue.unresolved}
    assert "Spring 25!F9" in {entry.item_id for entry in queue.ignored}
    assert queue.summary["ignored"] == 1
    assert len(load_transactions(legacy_tracker)) == before  # nothing written
    assert read_audit(legacy_tracker)[0]["action"] == AUDIT_IGNORE


def test_ignore_accepts_a_bare_item_id_and_needs_no_tracker(review_state_path: Path) -> None:
    ignore_item("25-26!Z9", state_path=review_state_path)

    assert load_state(review_state_path)["25-26!Z9"]["status"] == STATUS_IGNORED


def test_an_ignored_item_can_be_restored(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    ignore_item("Spring 25!F9", legacy_tracker, state_path=review_state_path)

    forget_decision("Spring 25!F9", review_state_path)

    queue = _queue(review_workbook, legacy_tracker, review_state_path)
    assert "Spring 25!F9" in {entry.item_id for entry in queue.unresolved}
    assert queue.ignored == []


# --- safety ----------------------------------------------------------------------


def test_the_original_workbook_is_never_written_to(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    before = _sha256(review_workbook)
    before_mtime = review_workbook.stat().st_mtime_ns

    queue = _queue(review_workbook, legacy_tracker, review_state_path)
    approve_item(queue.get("Rent!B4"), legacy_tracker, state_path=review_state_path)
    ignore_item(queue.get("Spring 25!C7"), legacy_tracker, state_path=review_state_path)
    _queue(review_workbook, legacy_tracker, review_state_path)

    assert _sha256(review_workbook) == before
    assert review_workbook.stat().st_mtime_ns == before_mtime


def test_approving_leaves_rows_that_were_already_in_the_tracker_alone(
    review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    before = load_transactions(legacy_tracker)
    item = _queue(review_workbook, legacy_tracker, review_state_path).get("Rent!B4")

    approve_item(item, legacy_tracker, state_path=review_state_path)

    after = load_transactions(legacy_tracker)
    assert len(after) == len(before) + 1
    assert after.head(len(before))["Description"].tolist() == before["Description"].tolist()


def test_state_file_is_readable_and_tolerates_damage(review_state_path: Path) -> None:
    save_state({"a!B1": {"status": STATUS_APPROVED, "at": "now"}}, review_state_path)

    assert json.loads(review_state_path.read_text(encoding="utf-8"))["version"] == 1
    assert load_state(review_state_path)["a!B1"]["status"] == STATUS_APPROVED

    review_state_path.write_text("{not json", encoding="utf-8")
    assert load_state(review_state_path) == {}

    review_state_path.write_text('{"items": {"x": {"status": "Weird"}}}', encoding="utf-8")
    assert load_state(review_state_path) == {}

    assert load_state(review_state_path.parent / "missing.json") == {}
