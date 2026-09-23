from __future__ import annotations

from datetime import date

import pandas as pd

from spending_tracker.dashboard import (
    DateRange,
    category_summary,
    category_trend,
    expense_metrics,
    filter_by_period,
    filter_by_precision,
    filter_transactions,
    monthly_expense_trend,
    period_options,
    period_summary,
    precision_breakdown,
)
from spending_tracker.schema import PRECISION_EXACT, PRECISION_MONTH, PRECISION_PERIOD


def _frame() -> pd.DataFrame:
    rows = [
        # Fall 25 (exact dates)
        ("2025-10-02", "Uber", 20.0, "Expense", "Transportation", "Fall 25", PRECISION_EXACT),
        ("2025-10-05", "Whole Foods", 80.0, "Expense", "Groceries", "Fall 25", PRECISION_EXACT),
        ("2025-10-06", "Tatte", 10.0, "Expense", "Dining", "Fall 25", PRECISION_EXACT),
        ("2025-10-10", "Rent", 1400.0, "Rent", "", "Fall 25", PRECISION_EXACT),
        ("2025-10-12", "TA", 700.0, "Income", "", "Fall 25", PRECISION_EXACT),
        ("2025-10-15", "IBKR", 500.0, "Investment", "", "Fall 25", PRECISION_EXACT),
        # November: bigger month
        ("2025-11-03", "Tatte", 40.0, "Expense", "Dining", "Fall 25", PRECISION_EXACT),
        ("2025-11-09", "Amazon", 110.0, "Expense", "Shopping", "Fall 25", PRECISION_EXACT),
        # A month-precision row still counts
        ("2025-11-01", "Rent+ Nov", 60.0, "Rent", "", "Fall 25", PRECISION_MONTH),
        # Period-precision rows must not distort monthly analytics
        ("2025-12-15", "Mystery Diner", 900.0, "Expense", "Other", "Winter 26", PRECISION_PERIOD),
    ]
    return pd.DataFrame(
        rows,
        columns=["Date", "Description", "Amount", "Type", "Category", "Source Period", "Date Precision"],
    ).assign(Date=lambda frame: pd.to_datetime(frame["Date"]))


def test_category_summary_sorts_descending_with_shares() -> None:
    summary = category_summary(_frame())

    assert summary["Category"].tolist() == [
        "Other",
        "Shopping",
        "Groceries",
        "Dining",
        "Transportation",
    ]
    assert summary.loc[0, "Amount"] == 900.0
    assert summary["Amount"].sum() == 1160.0
    assert summary.loc[0, "Share %"] == round(900 / 1160 * 100, 1)
    assert round(summary["Share %"].sum(), 1) == 100.0
    assert summary.loc[summary["Category"] == "Dining", "Transactions"].item() == 2


def test_category_summary_ignores_non_expense_types() -> None:
    summary = category_summary(_frame())

    assert "Rent" not in summary["Category"].tolist()
    assert summary["Amount"].sum() == 1160.0  # rent, income and investments excluded


def test_category_summary_labels_blank_categories_as_other() -> None:
    frame = pd.DataFrame(
        [{"Date": pd.Timestamp("2026-01-01"), "Description": "?", "Amount": 5.0, "Type": "Expense", "Category": ""}]
    )

    summary = category_summary(frame)

    assert summary.loc[0, "Category"] == "Other"
    assert summary.loc[0, "Share %"] == 100.0


def test_category_summary_handles_empty_input() -> None:
    summary = category_summary(pd.DataFrame())

    assert summary.empty
    assert list(summary.columns) == ["Category", "Amount", "Share %", "Transactions"]


def test_monthly_expense_trend_totals_expenses_per_month() -> None:
    trend = monthly_expense_trend(_frame())

    assert trend["Month"].tolist() == ["2025-10", "2025-11", "2025-12"]
    assert trend["Expenses"].tolist() == [110.0, 150.0, 900.0]


def test_category_trend_keeps_only_the_biggest_categories() -> None:
    trend = category_trend(_frame(), top_n=2)

    assert trend["Month"].tolist() == ["2025-10", "2025-11", "2025-12"]
    assert [column for column in trend.columns if column != "Month"] == ["Other", "Shopping"]
    assert trend.loc[trend["Month"] == "2025-11", "Shopping"].item() == 110.0


def test_filter_by_precision_drops_period_level_rows() -> None:
    filtered = filter_by_precision(_frame())

    assert len(filtered) == 9
    assert PRECISION_PERIOD not in set(filtered["Date Precision"])


def test_precision_breakdown_counts_each_precision() -> None:
    assert precision_breakdown(_frame()) == {
        PRECISION_EXACT: 8,
        PRECISION_MONTH: 1,
        PRECISION_PERIOD: 1,
    }


def test_expense_metrics_uses_only_precise_dates() -> None:
    metrics = expense_metrics(_frame(), date(2025, 11, 20))

    # The 900.00 period-precision row is excluded, so December is not counted.
    assert metrics["months_counted"] == 2
    assert metrics["average_monthly"] == 130.0
    assert metrics["highest_month"] == "2025-11"
    assert metrics["highest_month_amount"] == 150.0
    assert metrics["current_month"] == 150.0
    assert metrics["previous_month"] == 110.0
    assert metrics["month_over_month"] == 40.0
    assert metrics["discretionary"] == 260.0


def test_expense_metrics_handles_january_rollover() -> None:
    frame = pd.DataFrame(
        [
            {
                "Date": pd.Timestamp("2025-12-10"),
                "Description": "Tatte",
                "Amount": 30.0,
                "Type": "Expense",
                "Category": "Dining",
                "Date Precision": PRECISION_EXACT,
            },
            {
                "Date": pd.Timestamp("2026-01-10"),
                "Description": "Uber",
                "Amount": 50.0,
                "Type": "Expense",
                "Category": "Transportation",
                "Date Precision": PRECISION_EXACT,
            },
        ]
    )

    metrics = expense_metrics(frame, date(2026, 1, 15))

    assert metrics["current_month"] == 50.0
    assert metrics["previous_month"] == 30.0
    assert metrics["month_over_month"] == 20.0


def test_expense_metrics_handles_empty_input() -> None:
    metrics = expense_metrics(pd.DataFrame(), date(2026, 1, 1))

    assert metrics["months_counted"] == 0
    assert metrics["average_monthly"] == 0.0
    assert metrics["highest_month"] is None
    assert metrics["month_over_month"] is None


def test_analytics_respect_the_active_date_filter() -> None:
    filtered = filter_transactions(_frame(), DateRange(date(2025, 11, 1), date(2025, 11, 30)))

    summary = category_summary(filtered)
    trend = monthly_expense_trend(filtered)
    assert summary["Amount"].sum() == 150.0
    assert trend["Month"].tolist() == ["2025-11"]
    assert expense_metrics(filtered, date(2025, 11, 20))["months_counted"] == 1


def test_period_options_are_ordered_by_first_transaction() -> None:
    assert period_options(_frame()) == ["Fall 25", "Winter 26"]
    assert period_options(pd.DataFrame()) == []


def test_filter_by_period_selects_one_period() -> None:
    filtered = filter_by_period(_frame(), "Winter 26")

    assert len(filtered) == 1
    assert filtered.iloc[0]["Description"] == "Mystery Diner"
    assert len(filter_by_period(_frame(), None)) == 10


def test_period_summary_totals_each_type_per_period() -> None:
    summary = period_summary(_frame())

    fall = summary[summary["Source Period"] == "Fall 25"].iloc[0]
    winter = summary[summary["Source Period"] == "Winter 26"].iloc[0]
    assert fall["Expenses"] == 260.0
    assert fall["Income"] == 700.0
    assert fall["Rent"] == 1460.0
    assert fall["Investments"] == 500.0
    assert fall["Net cash flow"] == 700.0 - 260.0 - 1460.0 - 500.0
    assert winter["Expenses"] == 900.0


def test_period_summary_handles_frames_without_periods() -> None:
    frame = pd.DataFrame([{"Date": pd.Timestamp("2026-01-01"), "Amount": 5.0, "Type": "Expense"}])

    assert period_summary(frame).empty
