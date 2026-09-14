from __future__ import annotations

from datetime import date

import pandas as pd

from spending_tracker.dashboard import (
    DateRange,
    filter_transactions,
    monthly_summary,
    recent_transactions,
    resolve_date_range,
    summarize_transactions,
)


def _transactions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Date": date(2026, 9, 1), "Description": "TA", "Amount": 1000, "Type": "Income"},
            {"Date": date(2026, 9, 2), "Description": "Uber", "Amount": 12, "Type": "Expense"},
            {"Date": date(2026, 9, 3), "Description": "Rent", "Amount": 1800, "Type": "Rent"},
            {"Date": date(2026, 9, 4), "Description": "Investment", "Amount": 500, "Type": "Investment"},
            {"Date": date(2026, 10, 5), "Description": "Whole Foods", "Amount": 31, "Type": "Expense"},
            {"Date": date(2026, 10, 6), "Description": "Salary", "Amount": 1200, "Type": "Income"},
        ]
    )


def test_summarize_transactions_handles_empty_data() -> None:
    summary = summarize_transactions(pd.DataFrame())

    assert summary == {
        "Expenses": 0.0,
        "Income": 0.0,
        "Rent": 0.0,
        "Investments": 0.0,
        "Net cash flow": 0.0,
    }


def test_summarize_transactions_calculates_type_totals_and_net_cash_flow() -> None:
    summary = summarize_transactions(_transactions())

    assert summary["Expenses"] == 43
    assert summary["Income"] == 2200
    assert summary["Rent"] == 1800
    assert summary["Investments"] == 500
    assert summary["Net cash flow"] == -143


def test_filter_transactions_uses_inclusive_start_and_end_dates() -> None:
    filtered = filter_transactions(_transactions(), DateRange(date(2026, 9, 2), date(2026, 9, 4)))

    assert filtered["Description"].tolist() == ["Uber", "Rent", "Investment"]


def test_recent_transactions_sorts_newest_first_and_limits_rows() -> None:
    recent = recent_transactions(_transactions(), 2)

    assert recent["Description"].tolist() == ["Salary", "Whole Foods"]
    assert list(recent.columns) == ["Date", "Description", "Amount", "Type"]


def test_recent_transactions_can_return_all_rows() -> None:
    recent = recent_transactions(_transactions(), None)

    assert len(recent) == 6
    assert recent.iloc[0]["Description"] == "Salary"


def test_monthly_summary_aggregates_each_type_and_net_cash_flow() -> None:
    monthly = monthly_summary(_transactions())

    september = monthly[monthly["Month"] == "2026-09"].iloc[0]
    october = monthly[monthly["Month"] == "2026-10"].iloc[0]

    assert september["Expenses"] == 12
    assert september["Income"] == 1000
    assert september["Rent"] == 1800
    assert september["Investments"] == 500
    assert september["Net cash flow"] == -1312
    assert october["Expenses"] == 31
    assert october["Income"] == 1200
    assert october["Net cash flow"] == 1169


def test_resolve_date_range_options() -> None:
    today = date(2026, 9, 14)

    assert resolve_date_range("All time", today) == DateRange(None, None)
    assert resolve_date_range("This month", today) == DateRange(date(2026, 9, 1), today)
    assert resolve_date_range("Last month", today) == DateRange(date(2026, 8, 1), date(2026, 8, 31))
    assert resolve_date_range("This year", today) == DateRange(date(2026, 1, 1), today)
    assert resolve_date_range("Custom date range", today, date(2026, 9, 1), date(2026, 12, 31)) == DateRange(
        date(2026, 9, 1), date(2026, 12, 31)
    )
