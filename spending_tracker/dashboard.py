from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from spending_tracker.categories import CATEGORY_OTHER
from spending_tracker.schema import PRECISION_EXACT, PRECISION_MONTH, PRECISION_UNKNOWN


SUMMARY_TYPES = ["Expense", "Income", "Rent", "Investment"]
SUMMARY_COLUMNS = ["Expenses", "Income", "Rent", "Investments", "Net cash flow"]


@dataclass(frozen=True)
class DateRange:
    start: date | None
    end: date | None


def filter_transactions(df: pd.DataFrame, date_range: DateRange) -> pd.DataFrame:
    if df.empty or "Date" not in df.columns:
        return df.copy()

    filtered = df.copy()
    filtered["Date"] = pd.to_datetime(filtered["Date"], errors="coerce")
    filtered = filtered.dropna(subset=["Date"])

    if date_range.start is not None:
        filtered = filtered[filtered["Date"].dt.date >= date_range.start]
    if date_range.end is not None:
        filtered = filtered[filtered["Date"].dt.date <= date_range.end]

    return filtered


def summarize_transactions(df: pd.DataFrame) -> dict[str, float]:
    totals = _type_totals(df)
    expenses = totals["Expense"]
    income = totals["Income"]
    rent = totals["Rent"]
    investments = totals["Investment"]
    return {
        "Expenses": expenses,
        "Income": income,
        "Rent": rent,
        "Investments": investments,
        "Net cash flow": income - expenses - rent - investments,
    }


def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Month", *SUMMARY_COLUMNS])

    monthly = df.copy()
    monthly["Date"] = pd.to_datetime(monthly["Date"], errors="coerce")
    monthly["Amount"] = pd.to_numeric(monthly["Amount"], errors="coerce").fillna(0)
    monthly = monthly.dropna(subset=["Date"])
    if monthly.empty:
        return pd.DataFrame(columns=["Month", *SUMMARY_COLUMNS])

    monthly["Month"] = monthly["Date"].dt.to_period("M").astype(str)
    grouped = (
        monthly.pivot_table(index="Month", columns="Type", values="Amount", aggfunc="sum", fill_value=0)
        .rename(columns={"Expense": "Expenses", "Investment": "Investments"})
        .reset_index()
    )

    for column in SUMMARY_COLUMNS:
        if column != "Net cash flow" and column not in grouped.columns:
            grouped[column] = 0.0

    grouped["Net cash flow"] = (
        grouped["Income"] - grouped["Expenses"] - grouped["Rent"] - grouped["Investments"]
    )
    return grouped[["Month", *SUMMARY_COLUMNS]].sort_values("Month", ascending=False).reset_index(drop=True)


def recent_transactions(
    df: pd.DataFrame, limit: int | None, columns: list[str] | None = None
) -> pd.DataFrame:
    selected = columns or ["Date", "Description", "Amount", "Type"]
    if df.empty:
        return pd.DataFrame(columns=selected)

    recent = df.copy()
    recent["Date"] = pd.to_datetime(recent["Date"], errors="coerce")
    recent["Amount"] = pd.to_numeric(recent["Amount"], errors="coerce")
    recent = recent.dropna(subset=["Date"]).sort_values("Date", ascending=False)
    recent = recent[[column for column in selected if column in recent.columns]]
    if limit is not None:
        recent = recent.head(limit)
    return recent.reset_index(drop=True)


def resolve_date_range(option: str, today: date, custom_start: date | None = None, custom_end: date | None = None) -> DateRange:
    if option == "This month":
        start = today.replace(day=1)
        return DateRange(start, today)
    if option == "Last month":
        this_month = today.replace(day=1)
        previous_month_end = this_month - timedelta(days=1)
        previous_month_start = previous_month_end.replace(day=1)
        return DateRange(previous_month_start, previous_month_end)
    if option == "This year":
        return DateRange(today.replace(month=1, day=1), today)
    if option == "Custom date range":
        return DateRange(custom_start, custom_end)
    return DateRange(None, None)


def _type_totals(df: pd.DataFrame) -> dict[str, float]:
    totals = {transaction_type: 0.0 for transaction_type in SUMMARY_TYPES}
    if df.empty:
        return totals

    normalized = df.copy()
    normalized["Amount"] = pd.to_numeric(normalized["Amount"], errors="coerce").fillna(0)
    grouped = normalized.groupby("Type")["Amount"].sum()
    for transaction_type in SUMMARY_TYPES:
        totals[transaction_type] = float(grouped.get(transaction_type, 0.0))
    return totals


# --- V4 analytics -----------------------------------------------------------------

ANALYTIC_PRECISIONS = (PRECISION_EXACT, PRECISION_MONTH)


def _expenses_only(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "Type" not in df.columns:
        return pd.DataFrame(columns=["Date", "Description", "Amount", "Type", "Category"])
    expenses = df[df["Type"].astype(str).str.strip() == "Expense"].copy()
    expenses["Amount"] = pd.to_numeric(expenses["Amount"], errors="coerce").fillna(0.0)
    if "Category" not in expenses.columns:
        expenses["Category"] = ""
    expenses["Category"] = expenses["Category"].fillna("").astype(str).str.strip()
    expenses.loc[expenses["Category"] == "", "Category"] = CATEGORY_OTHER
    return expenses


def filter_by_precision(df: pd.DataFrame, precisions: tuple[str, ...] = ANALYTIC_PRECISIONS) -> pd.DataFrame:
    """Keep rows whose date is precise enough for month-level analysis."""
    if df.empty or "Date Precision" not in df.columns:
        return df.copy()
    return df[df["Date Precision"].astype(str).str.strip().isin(precisions)].copy()


def precision_breakdown(df: pd.DataFrame) -> dict[str, int]:
    if df.empty or "Date Precision" not in df.columns:
        return {}
    counts = df["Date Precision"].astype(str).str.strip().replace("", PRECISION_UNKNOWN).value_counts()
    return {str(key): int(value) for key, value in counts.items()}


def category_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Expense spending per category, largest first, with each share of the total."""
    expenses = _expenses_only(df)
    if expenses.empty:
        return pd.DataFrame(columns=["Category", "Amount", "Share %", "Transactions"])

    grouped = (
        expenses.groupby("Category")["Amount"]
        .agg(["sum", "count"])
        .rename(columns={"sum": "Amount", "count": "Transactions"})
        .reset_index()
    )
    total = float(grouped["Amount"].sum())
    grouped["Share %"] = (grouped["Amount"] / total * 100).round(1) if total else 0.0
    grouped["Amount"] = grouped["Amount"].round(2)
    return grouped.sort_values(["Amount", "Category"], ascending=[False, True])[
        ["Category", "Amount", "Share %", "Transactions"]
    ].reset_index(drop=True)


def monthly_expense_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Expense total per month."""
    expenses = _expenses_only(df)
    if expenses.empty:
        return pd.DataFrame(columns=["Month", "Expenses"])

    expenses["Date"] = pd.to_datetime(expenses["Date"], errors="coerce")
    expenses = expenses.dropna(subset=["Date"])
    if expenses.empty:
        return pd.DataFrame(columns=["Month", "Expenses"])

    expenses["Month"] = expenses["Date"].dt.to_period("M").astype(str)
    trend = expenses.groupby("Month")["Amount"].sum().round(2).reset_index(name="Expenses")
    return trend.sort_values("Month").reset_index(drop=True)


def category_trend(df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    """Month x category expense totals, limited to the biggest categories."""
    expenses = _expenses_only(df)
    if expenses.empty:
        return pd.DataFrame(columns=["Month"])

    expenses["Date"] = pd.to_datetime(expenses["Date"], errors="coerce")
    expenses = expenses.dropna(subset=["Date"])
    if expenses.empty:
        return pd.DataFrame(columns=["Month"])

    top = category_summary(expenses).head(top_n)["Category"].tolist()
    expenses["Month"] = expenses["Date"].dt.to_period("M").astype(str)
    # Keep every month that has expenses, so a month without spending in a top
    # category shows as zero instead of disappearing from the chart.
    all_months = sorted(expenses["Month"].unique())
    pivot = (
        expenses[expenses["Category"].isin(top)]
        .pivot_table(index="Month", columns="Category", values="Amount", aggfunc="sum", fill_value=0.0)
        .reindex(all_months, fill_value=0.0)
        .fillna(0.0)
        .round(2)
        .reset_index(names="Month")
    )
    pivot.columns.name = None
    ordered = ["Month"] + [category for category in top if category in pivot.columns]
    return pivot[ordered].sort_values("Month").reset_index(drop=True)


def expense_metrics(
    df: pd.DataFrame, today: date, precisions: tuple[str, ...] = ANALYTIC_PRECISIONS
) -> dict[str, object]:
    """High level expense metrics.

    Only rows with an Exact or Month date take part, because rows that carry a
    period-level stand-in date would otherwise invent a spike in one month.
    """
    trend = monthly_expense_trend(filter_by_precision(df, precisions))
    if trend.empty:
        return {
            "months_counted": 0,
            "average_monthly": 0.0,
            "highest_month": None,
            "highest_month_amount": 0.0,
            "current_month": 0.0,
            "previous_month": 0.0,
            "month_over_month": None,
            "discretionary": 0.0,
            "total": 0.0,
        }

    amounts = dict(zip(trend["Month"], trend["Expenses"], strict=True))
    current_key = f"{today.year:04d}-{today.month:02d}"
    previous = date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)
    previous_key = f"{previous.year:04d}-{previous.month:02d}"
    current_value = float(amounts.get(current_key, 0.0))
    previous_value = float(amounts.get(previous_key, 0.0))
    highest = trend.loc[trend["Expenses"].idxmax()]

    return {
        "months_counted": len(trend),
        "average_monthly": round(float(trend["Expenses"].mean()), 2),
        "highest_month": str(highest["Month"]),
        "highest_month_amount": round(float(highest["Expenses"]), 2),
        "current_month": round(current_value, 2),
        "previous_month": round(previous_value, 2),
        "month_over_month": round(current_value - previous_value, 2) if previous_value else None,
        # Expense excludes Rent and Investment by construction: they are their own Types.
        "discretionary": round(float(trend["Expenses"].sum()), 2),
        "total": round(float(trend["Expenses"].sum()), 2),
    }


def period_options(df: pd.DataFrame) -> list[str]:
    """Source periods recovered by the historical migration, oldest data first."""
    if df.empty or "Source Period" not in df.columns:
        return []
    periods = df.copy()
    periods["Source Period"] = periods["Source Period"].fillna("").astype(str).str.strip()
    periods = periods[periods["Source Period"] != ""]
    if periods.empty:
        return []
    periods["Date"] = pd.to_datetime(periods["Date"], errors="coerce")
    ordered = periods.groupby("Source Period")["Date"].min().sort_values()
    return [str(name) for name in ordered.index]


def filter_by_period(df: pd.DataFrame, period: str | None) -> pd.DataFrame:
    if not period or df.empty or "Source Period" not in df.columns:
        return df.copy()
    return df[df["Source Period"].fillna("").astype(str).str.strip() == period].copy()


def period_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Type totals per source period, for the school-term view."""
    if df.empty or "Source Period" not in df.columns:
        return pd.DataFrame(columns=["Source Period", *SUMMARY_COLUMNS])

    frame = df.copy()
    frame["Source Period"] = frame["Source Period"].fillna("").astype(str).str.strip()
    frame = frame[frame["Source Period"] != ""]
    if frame.empty:
        return pd.DataFrame(columns=["Source Period", *SUMMARY_COLUMNS])

    frame["Amount"] = pd.to_numeric(frame["Amount"], errors="coerce").fillna(0.0)
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    order = frame.groupby("Source Period")["Date"].min().sort_values()
    grouped = (
        frame.pivot_table(
            index="Source Period", columns="Type", values="Amount", aggfunc="sum", fill_value=0.0
        )
        .rename(columns={"Expense": "Expenses", "Investment": "Investments"})
        .reindex(order.index)
        .reset_index()
    )
    for column in SUMMARY_COLUMNS:
        if column != "Net cash flow" and column not in grouped.columns:
            grouped[column] = 0.0
    grouped["Net cash flow"] = (
        grouped["Income"] - grouped["Expenses"] - grouped["Rent"] - grouped["Investments"]
    )
    return grouped[["Source Period", *SUMMARY_COLUMNS]].round(2)
