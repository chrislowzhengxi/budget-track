from __future__ import annotations

from datetime import date
from pathlib import Path

from spending_tracker.historical import (
    CONFIDENCE_HIGH,
    STATUS_NEEDS_REVIEW,
    STATUS_READY,
    STATUS_SKIPPED,
    Candidate,
    clean_text,
    extract,
    find_blocks,
    inspect_workbook,
    looks_like_aggregate,
    month_date_near_block,
    month_from_description,
)
from spending_tracker.schema import (
    PRECISION_EXACT,
    PRECISION_MONTH,
    PRECISION_PERIOD,
    PRECISION_UNKNOWN,
    TRANSACTION_COLUMNS,
)


def _by_reference(candidates: list[Candidate]) -> dict[str, Candidate]:
    return {f"{candidate.source_sheet}!{candidate.source_reference}": candidate for candidate in candidates}


def test_inspect_workbook_finds_every_block_with_type_and_period(historical_workbook: Path) -> None:
    blocks = inspect_workbook(historical_workbook)

    described = {
        (block.sheet, block.transaction_type, block.period, block.date_column is not None) for block in blocks
    }
    assert described == {
        ("23-24 Fall, Winter", "Expense", "Fall 23", True),
        ("23-24 Fall, Winter", "Expense", "Winter 24", True),
        ("Rent, Income", "Rent", "Rent, Income", False),
        ("Rent, Income", "Income", "Rent, Income", True),
        ("Rent, Income", "Investment", "Rent, Income", False),
        ("Undated", "Investment", "Undated", False),
    }


def test_expense_rows_are_extracted_with_type_and_amount(historical_workbook: Path) -> None:
    candidates = _by_reference(extract(historical_workbook).candidates)

    whole_foods = candidates["23-24 Fall, Winter!C4"]
    assert whole_foods.description == "Whole Foods"
    assert whole_foods.amount == 31.5
    assert whole_foods.transaction_type == "Expense"
    assert whole_foods.status == STATUS_READY
    assert whole_foods.confidence == CONFIDENCE_HIGH
    assert whole_foods.date == date(2023, 10, 5)
    assert whole_foods.date_precision == PRECISION_EXACT
    assert candidates["23-24 Fall, Winter!J3"].description == "Tatte"
    assert candidates["23-24 Fall, Winter!J3"].amount == 8.5


def test_income_rows_are_extracted_from_the_income_block(historical_workbook: Path) -> None:
    candidate = _by_reference(extract(historical_workbook).candidates)["Rent, Income!F3"]

    assert candidate.description == "TA"
    assert candidate.amount == 695.56
    assert candidate.transaction_type == "Income"
    assert candidate.status == STATUS_READY
    assert candidate.date == date(2024, 2, 15)


def test_rent_rows_use_the_date_from_the_sources_column(historical_workbook: Path) -> None:
    candidate = _by_reference(extract(historical_workbook).candidates)["Rent, Income!B3"]

    assert candidate.transaction_type == "Rent"
    assert candidate.description == "Rent"
    assert candidate.amount == 1400
    assert candidate.date == date(2024, 2, 1)
    assert candidate.date_precision == PRECISION_EXACT
    assert candidate.status == STATUS_READY


def test_investment_rows_fall_back_to_the_sheet_midpoint(historical_workbook: Path) -> None:
    """A block with no dates of its own borrows the midpoint of its sheet.

    The Investments block records a merchant and an amount but never a date, so the
    transaction is certain while the day is not: it keeps Period precision and says
    which midpoint stood in.
    """
    candidate = _by_reference(extract(historical_workbook).candidates)["Rent, Income!I3"]

    assert candidate.transaction_type == "Investment"
    assert candidate.description == "IBKR"
    assert candidate.amount == 5000
    assert candidate.date == date(2024, 2, 1)  # midpoint of the dated rows on that sheet
    assert candidate.date_precision == PRECISION_PERIOD
    assert candidate.status == STATUS_READY
    assert candidate.confidence == CONFIDENCE_HIGH
    assert "midpoint of dated rows on sheet 'Rent, Income'" in candidate.review_note


def test_rows_on_a_sheet_without_any_date_stay_unknown_and_need_review(
    historical_workbook: Path,
) -> None:
    candidate = _by_reference(extract(historical_workbook).candidates)["Undated!A3"]

    assert candidate.transaction_type == "Investment"
    assert candidate.amount == 1000
    assert candidate.date is None
    assert candidate.date_precision == PRECISION_UNKNOWN
    assert candidate.status == STATUS_NEEDS_REVIEW
    assert "No date information anywhere on sheet 'Undated'" in candidate.review_note


def test_header_cells_never_become_transactions(historical_workbook: Path) -> None:
    candidates = extract(historical_workbook).candidates

    descriptions = {candidate.description.lower() for candidate in candidates}
    assert "sources" not in descriptions
    assert "date" not in descriptions
    assert "expenses" not in descriptions
    assert not any(candidate.source_reference in {"C2", "D2", "B2", "J2", "K2"} for candidate in candidates)


def test_total_rows_are_skipped(historical_workbook: Path) -> None:
    candidate = _by_reference(extract(historical_workbook).candidates)["23-24 Fall, Winter!C9"]

    assert candidate.status == STATUS_SKIPPED
    assert "total" in candidate.review_note.lower()


def test_sidebar_total_formulas_are_never_candidates(historical_workbook: Path) -> None:
    candidates = extract(historical_workbook).candidates

    references = {f"{candidate.source_sheet}!{candidate.source_reference}" for candidate in candidates}
    assert "23-24 Fall, Winter!G2" not in references
    assert "23-24 Fall, Winter!F2" not in references


def test_formula_amounts_are_flagged_for_review_and_not_ready(historical_workbook: Path) -> None:
    candidate = _by_reference(extract(historical_workbook).candidates)["23-24 Fall, Winter!C7"]

    assert candidate.status == STATUS_NEEDS_REVIEW
    assert "formula" in candidate.review_note.lower()


def test_blank_rows_are_ignored_and_counted(historical_workbook: Path) -> None:
    extraction = extract(historical_workbook)

    references = {f"{candidate.source_sheet}!{candidate.source_reference}" for candidate in extraction.candidates}
    assert "23-24 Fall, Winter!C11" not in references
    assert extraction.blank_rows_ignored > 0


def test_rows_missing_an_amount_or_description_are_skipped(historical_workbook: Path) -> None:
    candidates = _by_reference(extract(historical_workbook).candidates)

    assert candidates["23-24 Fall, Winter!C10"].status == STATUS_SKIPPED
    assert "amount" in candidates["23-24 Fall, Winter!C10"].review_note.lower()
    assert candidates["23-24 Fall, Winter!C13"].status == STATUS_SKIPPED
    assert "zero" in candidates["23-24 Fall, Winter!C13"].review_note.lower()


def test_negative_amounts_are_flagged_and_retyped_as_credits(historical_workbook: Path) -> None:
    candidates = _by_reference(extract(historical_workbook).candidates)

    refund = candidates["23-24 Fall, Winter!C8"]
    assert refund.transaction_type == "Income"
    assert refund.amount == 25
    assert refund.status == STATUS_NEEDS_REVIEW
    assert "negative" in refund.review_note.lower()

    roommate = candidates["Rent, Income!B5"]
    assert roommate.transaction_type == "Income"
    assert roommate.amount == 700
    assert roommate.status == STATUS_NEEDS_REVIEW


def test_values_outside_a_block_are_flagged_as_sidebar_candidates(historical_workbook: Path) -> None:
    candidate = _by_reference(extract(historical_workbook).candidates)["Rent, Income!L2"]

    assert candidate.source_area == "Sidebar"
    assert candidate.description == "Deposit from school"
    assert candidate.amount == 2500
    assert candidate.status == STATUS_NEEDS_REVIEW


def test_sidebar_scan_can_be_disabled(historical_workbook: Path) -> None:
    candidates = extract(historical_workbook, include_sidebar=False).candidates

    assert all(candidate.source_area == "Block" for candidate in candidates)


def test_provenance_is_preserved_for_every_candidate(historical_workbook: Path) -> None:
    for candidate in extract(historical_workbook).candidates:
        assert candidate.source_sheet
        assert candidate.source_reference
        assert candidate.source_period
        row = candidate.as_row()
        assert set(row) == set(TRANSACTION_COLUMNS)
        assert row["Source Sheet"] == candidate.source_sheet
        assert row["Source Reference"] == candidate.source_reference


def test_source_line_keeps_the_raw_row_text(historical_workbook: Path) -> None:
    candidates = _by_reference(extract(historical_workbook).candidates)

    assert candidates["23-24 Fall, Winter!C3"].source_line == "N/A | Uber | 12"
    assert candidates["23-24 Fall, Winter!C4"].source_line == "2023-10-05 | Whole Foods | 31.5"


def test_undated_rows_fall_back_to_the_block_midpoint_with_period_precision(
    historical_workbook: Path,
) -> None:
    candidate = _by_reference(extract(historical_workbook).candidates)["23-24 Fall, Winter!C3"]

    assert candidate.date_precision == PRECISION_PERIOD
    assert candidate.date in {date(2023, 10, 5), date(2023, 10, 7)}
    assert candidate.status == STATUS_READY
    assert "block midpoint" in candidate.review_note


def test_month_named_in_the_description_gives_month_precision(historical_workbook: Path) -> None:
    candidate = _by_reference(extract(historical_workbook).candidates)["Rent, Income!B4"]

    assert candidate.description == "Rent+ Mar"
    assert candidate.date == date(2024, 3, 1)
    assert candidate.date_precision == PRECISION_MONTH
    assert candidate.status == STATUS_READY


def test_text_dates_such_as_question_marks_do_not_become_exact_dates(historical_workbook: Path) -> None:
    candidate = _by_reference(extract(historical_workbook).candidates)["23-24 Fall, Winter!J4"]

    assert candidate.date_precision == PRECISION_PERIOD
    assert candidate.date == date(2024, 1, 10)


def test_repeated_purchases_are_kept_as_separate_candidates(historical_workbook: Path) -> None:
    candidates = _by_reference(extract(historical_workbook).candidates)

    first = candidates["23-24 Fall, Winter!C3"]
    second = candidates["23-24 Fall, Winter!C6"]
    assert (first.description, first.amount, first.date) == (second.description, second.amount, second.date)
    assert first.source_reference != second.source_reference


def test_month_from_description_only_fires_on_a_single_month_token() -> None:
    assert month_from_description("Rent+ Aug.") == 8
    assert month_from_description("May Utils") == 5
    assert month_from_description("march") == 3
    assert month_from_description("Marchetti") is None
    assert month_from_description("Mays Diner") is None
    assert month_from_description("Jan and Feb") is None
    assert month_from_description("Whole Foods") is None


def test_month_date_near_block_picks_the_year_closest_to_the_block() -> None:
    block = [date(2025, 10, 1), date(2026, 5, 1)]

    assert month_date_near_block(8, block) == date(2025, 8, 1)
    assert month_date_near_block(1, block) == date(2026, 1, 1)
    assert month_date_near_block(4, block) == date(2026, 4, 1)
    assert month_date_near_block(5, []) is None


def test_looks_like_aggregate_recognises_summary_labels() -> None:
    for label in ["Total", "total ", "Subtotal", "Average", "Balance", "Estimate", "Actual Spent", "Sources"]:
        assert looks_like_aggregate(label), label
    for label in ["Uber", "Whole Foods", "Totally Chocolate", "Netflix", ""]:
        assert not looks_like_aggregate(label), label


def test_clean_text_normalises_non_breaking_spaces_and_dates() -> None:
    assert clean_text("\xa0Expenses\xa0") == "Expenses"
    assert clean_text("  Whole   Foods ") == "Whole Foods"
    assert clean_text(date(2024, 1, 2)) == "2024-01-02"
    assert clean_text(12.0) == "12"
    assert clean_text(None) == ""


def test_clean_text_trims_excel_float_noise() -> None:
    # Cached formula results such as =217.97-154.2 come back as 63.77000000000001.
    assert clean_text(63.77000000000001) == "63.77"
    assert clean_text(12.5) == "12.5"
    assert clean_text(95.72999999999999) == "95.73"


def test_extraction_never_opens_the_workbook_for_writing(historical_workbook: Path) -> None:
    before = historical_workbook.read_bytes()

    extract(historical_workbook)

    assert historical_workbook.read_bytes() == before
