"""Synthetic workbook fixtures.

Every test builds its own workbook under tmp_path; no test ever reads or writes the
real historical workbook or the real tracker copy.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook
import pytest

from spending_tracker.schema import LEGACY_COLUMNS


def _write(ws, cells: dict[str, object]) -> None:
    for reference, value in cells.items():
        ws[reference] = value


@pytest.fixture
def historical_workbook(tmp_path: Path) -> Path:
    """A small stand-in for the real workbook: side-by-side blocks, totals, notes.

    Sheet "23-24 Fall, Winter"
        B/C/D  Fall 23 expenses (mixed exact / "N/A" dates, a formula, a credit,
               a total row, a description-only row, an amount-only row, a blank
               row, a zero)
        I/J/K  Winter 24 expenses
        F/G    sidebar totals (must be ignored)
    Sheet "Rent, Income"
        B/C    Rent (two column block: the Sources column holds the date)
        E/F/G  Income
        I/J    Investments (no dates in the block, but the sheet has some)
        L      a bare sidebar value
    Sheet "Undated"
        A/B    Investments on a sheet with no dates anywhere
    """
    path = tmp_path / "historical.xlsx"
    wb = Workbook()

    terms = wb.active
    terms.title = "23-24 Fall, Winter"
    _write(
        terms,
        {
            "B1": "Fall 23",
            "B2": "Date",
            "C2": "Sources",
            "D2": "\xa0Expenses\xa0",
            "F2": "Total",
            "G2": "=SUM(D:D)",
            "B3": "N/A",
            "C3": "Uber",
            "D3": 12,
            "B4": datetime(2023, 10, 5),
            "C4": "Whole Foods ",
            "D4": 31.5,
            "B5": datetime(2023, 10, 7),
            "C5": "Trader Joe's",
            "D5": 20,
            "E5": "*shared with Andrew",
            "B6": "N/A",
            "C6": "Uber",
            "D6": 12,
            "C7": "Magnolia, Osaka",
            "D7": "=10+5",
            "C8": "Refund",
            "D8": -25,
            "C9": "Total",
            "D9": 100,
            "C10": "Mystery row",
            "D12": 99,
            "C13": "Zero row",
            "D13": 0,
            "I1": "Winter 24",
            "I2": "Date",
            "J2": "Sources",
            "K2": "\xa0Expenses\xa0",
            "I3": datetime(2024, 1, 10),
            "J3": "Tatte",
            "K3": 8.5,
            "I4": "?",
            "J4": "Chipotle",
            "K4": 13.25,
        },
    )

    other = wb.create_sheet("Rent, Income")
    _write(
        other,
        {
            "B1": "Rent",
            "B2": "Sources",
            "C2": "\xa0Expenses\xa0",
            "B3": datetime(2024, 2, 1),
            "C3": 1400,
            "B4": "Rent+ Mar",
            "C4": 75,
            "B5": "Sandra",
            "C5": -700,
            "E1": "Income",
            "E2": "Date",
            "F2": "Sources",
            "G2": "\xa0Expenses\xa0",
            "E3": datetime(2024, 2, 15),
            "F3": "TA",
            "G3": 695.56,
            "I1": "Investments",
            "I2": "Sources",
            "J2": "\xa0Expenses\xa0",
            "I3": "IBKR",
            "J3": 5000,
            "L1": "Deposit from school",
            "L2": 2500,
        },
    )
    undated = wb.create_sheet("Undated")
    _write(
        undated,
        {
            "A1": "Investments",
            "A2": "Sources",
            "B2": "\xa0Expenses\xa0",
            "A3": "IBKR",
            "B3": 1000,
        },
    )
    wb.save(path)
    return path


@pytest.fixture
def legacy_tracker(tmp_path: Path) -> Path:
    """A pre-V3 tracker workbook: original sheets plus a six column Transactions sheet."""
    path = tmp_path / "tracker-legacy.xlsx"
    wb = Workbook()
    original = wb.active
    original.title = "24-25 Fall, Winter"
    original["B1"] = "Fall 24"

    ws = wb.create_sheet("Transactions")
    ws.append(LEGACY_COLUMNS)
    ws.append([date(2026, 9, 14), "Uber", 12, "Expense", "uber 12", "2026-09-14 14:21:51"])
    ws.append([date(2026, 9, 14), "Tatte", 8.5, "Expense", "tatte 8.50", "2026-09-14 14:21:51"])
    ws.append([date(2026, 9, 14), "TA", 695.56, "Income", "TA (695.56)", "2026-09-14 14:21:51"])
    ws.append([date(2026, 9, 14), "Rent", 1800, "Rent", "rent 1800", "2026-09-14 14:21:51"])
    ws.append([date(2026, 9, 14), "Investment", 500, "Investment", "investment 500", "2026-09-14 14:21:51"])
    wb.save(path)
    return path


@pytest.fixture
def empty_tracker(tmp_path: Path) -> Path:
    """A workbook with the historical sheets but no Transactions sheet yet."""
    path = tmp_path / "tracker-empty.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "24-25 Fall, Winter"
    ws["B1"] = "Fall 24"
    wb.save(path)
    return path


@pytest.fixture
def review_workbook(tmp_path: Path) -> Path:
    """A workbook shaped around the review cases: credits, a formula and sidebar values.

    Sheet "Spring 25"
        B/C/D  expenses, including negative credits and a formula amount
        F/G    sidebar labels with bare values (a brokerage transfer, a deposit)
    Sheet "Rent"
        B/C    two column Rent block with a roommate reimbursement
    """
    path = tmp_path / "review-source.xlsx"
    wb = Workbook()

    spring = wb.active
    spring.title = "Spring 25"
    _write(
        spring,
        {
            "B1": "Spring 25",
            "B2": "Date",
            "C2": "Sources",
            "D2": "\xa0Expenses\xa0",
            "B3": datetime(2025, 4, 2),
            "C3": "Whole Foods",
            "D3": 40.0,
            "B4": datetime(2025, 4, 20),
            "C4": "Uber",
            "D4": 12.0,
            "C5": "NBA Pay",
            "D5": -330,
            "C6": "Discover Credit",
            "D6": -100,
            "C7": "Draft Kings",
            "D7": -100,
            "C8": "Check Adjustment",
            "D8": -10,
            "C9": "Uber to Lakers",
            "D9": "=25.67 + 17.84",
            "F5": "Robinhood",
            "F6": 220,
            "F8": "Deposit from Uchicago",
            "F9": 5000,
        },
    )

    rent = wb.create_sheet("Rent")
    _write(
        rent,
        {
            "B1": "Rent",
            "B2": "Sources",
            "C2": "\xa0Expenses\xa0",
            "B3": datetime(2025, 4, 1),
            "C3": 1400,
            "B4": "Sandra",
            "C4": -2400,
        },
    )
    wb.save(path)
    return path


@pytest.fixture
def review_state_path(tmp_path: Path) -> Path:
    """Decision file inside tmp_path; the real data/historical_review.json is untouched."""
    return tmp_path / "historical_review.json"
