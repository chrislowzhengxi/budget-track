from __future__ import annotations

from datetime import date

import pandas as pd

from spending_tracker.duplicates import duplicate_key, existing_keys, find_duplicates


def _existing() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Date": pd.Timestamp("2026-09-23"), "Description": "Uber", "Amount": 12.0, "Type": "Expense"},
            {"Date": pd.Timestamp("2026-09-23"), "Description": "Tatte", "Amount": 7.85, "Type": "Expense"},
        ]
    )


def test_duplicate_key_normalises_date_description_and_amount() -> None:
    assert duplicate_key(date(2026, 9, 23), " UBER  ", 12, "Expense") == (
        "2026-09-23",
        "uber",
        12.0,
        "Expense",
    )
    assert duplicate_key(pd.Timestamp("2026-09-23"), "Uber", "12.00", "Expense")[0] == "2026-09-23"
    assert duplicate_key(None, "Uber", None, None) == ("", "uber", 0.0, "")


def test_existing_keys_counts_repeats() -> None:
    frame = pd.concat([_existing(), _existing()], ignore_index=True)

    counts = existing_keys(frame)

    assert counts[("2026-09-23", "uber", 12.0, "Expense")] == 2
    assert existing_keys(pd.DataFrame()) == {}


def test_same_entry_on_the_same_day_warns() -> None:
    warnings = find_duplicates(
        [{"Date": date(2026, 9, 23), "Description": "uber", "Amount": 12, "Type": "Expense"}], _existing()
    )

    assert len(warnings) == 1
    assert warnings[0].source == "workbook"
    assert warnings[0].row_index == 0
    assert "already in the tracker" in warnings[0].message
    assert "Uber" in warnings[0].description or "uber" in warnings[0].description


def test_repeats_inside_one_batch_warn_once() -> None:
    pending = [
        {"Date": date(2026, 9, 24), "Description": "Tatte", "Amount": 7.85, "Type": "Expense"},
        {"Date": date(2026, 9, 24), "Description": "Tatte", "Amount": 7.85, "Type": "Expense"},
        {"Date": date(2026, 9, 24), "Description": "Tatte", "Amount": 7.85, "Type": "Expense"},
    ]

    warnings = find_duplicates(pending, _existing())

    assert [warning.row_index for warning in warnings] == [1, 2]
    assert {warning.source for warning in warnings} == {"batch"}


def test_a_different_date_amount_or_type_is_not_a_duplicate() -> None:
    pending = [
        {"Date": date(2026, 9, 24), "Description": "Uber", "Amount": 12, "Type": "Expense"},
        {"Date": date(2026, 9, 23), "Description": "Uber", "Amount": 12.5, "Type": "Expense"},
        {"Date": date(2026, 9, 23), "Description": "Uber", "Amount": 12, "Type": "Income"},
        {"Date": date(2026, 9, 23), "Description": "Lyft", "Amount": 12, "Type": "Expense"},
    ]

    assert find_duplicates(pending, _existing()) == []


def test_description_differences_that_do_not_matter_are_still_duplicates() -> None:
    pending = [{"Date": date(2026, 9, 23), "Description": "  uber ", "Amount": 12.0, "Type": "Expense"}]

    assert len(find_duplicates(pending, _existing())) == 1


def test_rows_without_a_description_or_amount_are_ignored() -> None:
    pending = [
        {"Date": date(2026, 9, 23), "Description": "", "Amount": 12, "Type": "Expense"},
        {"Date": date(2026, 9, 23), "Description": "Uber", "Amount": 0, "Type": "Expense"},
    ]

    assert find_duplicates(pending, _existing()) == []


def test_find_duplicates_accepts_a_dataframe_and_an_empty_workbook() -> None:
    pending = pd.DataFrame(
        [{"Date": date(2026, 9, 23), "Description": "Uber", "Amount": 12, "Type": "Expense"}]
    )

    assert len(find_duplicates(pending, _existing())) == 1
    assert find_duplicates(pending, pd.DataFrame()) == []


def test_warnings_never_block_saving_by_themselves() -> None:
    # The module only reports; the override path is the caller's decision, so a
    # warning carries everything needed to show and then ignore it.
    warning = find_duplicates(
        [{"Date": date(2026, 9, 23), "Description": "Uber", "Amount": 12, "Type": "Expense"}], _existing()
    )[0]

    assert warning.matches == 1
    assert warning.transaction_date == date(2026, 9, 23)
    assert warning.transaction_type == "Expense"
