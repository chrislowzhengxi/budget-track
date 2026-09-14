from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


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


def recent_transactions(df: pd.DataFrame, limit: int | None) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Date", "Description", "Amount", "Type"])

    recent = df.copy()
    recent["Date"] = pd.to_datetime(recent["Date"], errors="coerce")
    recent["Amount"] = pd.to_numeric(recent["Amount"], errors="coerce")
    recent = recent.dropna(subset=["Date"]).sort_values("Date", ascending=False)
    recent = recent[["Date", "Description", "Amount", "Type"]]
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
