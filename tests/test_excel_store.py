from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
import pandas as pd

from spending_tracker.excel_store import (
    HEADERS,
    TRANSACTIONS_SHEET,
    append_transactions,
    ensure_workbook_copy,
    load_transactions,
)


def _create_source_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Existing"
    sheet["A1"] = "Do not touch"
    sheet["B2"] = 42
    workbook.save(path)


def test_ensure_workbook_copy_creates_parent_and_preserves_source(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    output = tmp_path / "nested" / "copy.xlsx"
    _create_source_workbook(source)

    result = ensure_workbook_copy(source, output)

    assert result == output
    assert output.exists()
    source_wb = load_workbook(source)
    output_wb = load_workbook(output)
    assert source_wb.sheetnames == ["Existing"]
    assert output_wb.sheetnames == ["Existing"]
    assert output_wb["Existing"]["A1"].value == "Do not touch"


def test_ensure_workbook_copy_does_not_overwrite_existing_output(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    output = tmp_path / "copy.xlsx"
    _create_source_workbook(source)
    _create_source_workbook(output)
    output_wb = load_workbook(output)
    output_wb["Existing"]["A1"] = "Already edited"
    output_wb.save(output)

    ensure_workbook_copy(source, output)

    reloaded = load_workbook(output)
    assert reloaded["Existing"]["A1"].value == "Already edited"


def test_append_transactions_creates_transactions_sheet_without_changing_existing_sheet(tmp_path: Path) -> None:
    workbook_path = tmp_path / "spending.xlsx"
    _create_source_workbook(workbook_path)

    rows = [
        {
            "Date": date(2026, 9, 14),
            "Description": "Uber",
            "Amount": 12.0,
            "Type": "Expense",
            "Source Line": "uber 12",
        },
        {
            "Date": date(2026, 9, 14),
            "Description": "TA",
            "Amount": 695.56,
            "Type": "Income",
            "Source Line": "TA (695.56)",
        },
    ]

    count = append_transactions(workbook_path, rows)

    assert count == 2
    workbook = load_workbook(workbook_path)
    assert workbook["Existing"]["A1"].value == "Do not touch"
    assert TRANSACTIONS_SHEET in workbook.sheetnames

    sheet = workbook[TRANSACTIONS_SHEET]
    assert [sheet.cell(1, column).value for column in range(1, 7)] == HEADERS
    assert sheet["A2"].value == datetime(2026, 9, 14)
    assert [sheet.cell(2, column).value for column in range(2, 6)] == ["Uber", 12, "Expense", "uber 12"]
    assert sheet["A3"].value == datetime(2026, 9, 14)
    assert [sheet.cell(3, column).value for column in range(2, 6)] == ["TA", 695.56, "Income", "TA (695.56)"]
    assert sheet["F2"].value
    assert sheet["A2"].number_format == "yyyy-mm-dd"
    assert sheet["C2"].number_format == "0.00"
    assert "TransactionsTable" in sheet.tables
    assert sheet.tables["TransactionsTable"].ref == "A1:F3"


def test_append_transactions_appends_to_existing_transactions_sheet_and_expands_table(tmp_path: Path) -> None:
    workbook_path = tmp_path / "spending.xlsx"
    _create_source_workbook(workbook_path)

    first_count = append_transactions(
        workbook_path,
        [
            {
                "Date": date(2026, 9, 14),
                "Description": "Rent",
                "Amount": 1800,
                "Type": "Rent",
                "Source Line": "rent 1800",
            }
        ],
    )
    second_count = append_transactions(
        workbook_path,
        [
            {
                "Date": date(2026, 9, 15),
                "Description": "Investment",
                "Amount": 500,
                "Type": "Investment",
                "Source Line": "investment 500",
            }
        ],
    )

    workbook = load_workbook(workbook_path)
    sheet = workbook[TRANSACTIONS_SHEET]
    assert first_count == 1
    assert second_count == 1
    assert sheet.max_row == 3
    assert sheet["B2"].value == "Rent"
    assert sheet["B3"].value == "Investment"
    assert sheet.tables["TransactionsTable"].ref == "A1:F3"


def test_append_transactions_with_no_rows_does_not_create_sheet(tmp_path: Path) -> None:
    workbook_path = tmp_path / "spending.xlsx"
    _create_source_workbook(workbook_path)

    count = append_transactions(workbook_path, [])

    workbook = load_workbook(workbook_path)
    assert count == 0
    assert TRANSACTIONS_SHEET not in workbook.sheetnames


def test_load_transactions_returns_empty_frame_when_workbook_is_missing(tmp_path: Path) -> None:
    transactions = load_transactions(tmp_path / "missing.xlsx")

    assert list(transactions.columns) == HEADERS
    assert transactions.empty


def test_load_transactions_returns_empty_frame_when_sheet_is_missing(tmp_path: Path) -> None:
    workbook_path = tmp_path / "spending.xlsx"
    _create_source_workbook(workbook_path)

    transactions = load_transactions(workbook_path)

    assert list(transactions.columns) == HEADERS
    assert transactions.empty


def test_load_transactions_reads_dates_and_numeric_amounts_without_modifying_workbook(tmp_path: Path) -> None:
    workbook_path = tmp_path / "spending.xlsx"
    _create_source_workbook(workbook_path)
    before_mtime = workbook_path.stat().st_mtime_ns
    append_transactions(
        workbook_path,
        [
            {
                "Date": date(2026, 9, 14),
                "Description": "Uber",
                "Amount": 12,
                "Type": "Expense",
                "Source Line": "uber 12",
            }
        ],
    )
    after_write_mtime = workbook_path.stat().st_mtime_ns

    transactions = load_transactions(workbook_path)
    after_read_mtime = workbook_path.stat().st_mtime_ns

    assert after_write_mtime >= before_mtime
    assert after_read_mtime == after_write_mtime
    assert len(transactions) == 1
    assert transactions.loc[0, "Date"] == pd.Timestamp("2026-09-14")
    assert transactions.loc[0, "Amount"] == 12
    assert transactions.loc[0, "Description"] == "Uber"
    assert transactions.loc[0, "Type"] == "Expense"
