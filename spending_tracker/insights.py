"""Recurring transaction detection and the optional monthly Expense budget.

Both are deliberately simple and deterministic: the recurring finder groups
transactions by normalised merchant and looks at the gaps between them, and the
budget is a number in a small JSON file.  Nothing here claims certainty - the label
is "Likely recurring".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import statistics

import pandas as pd

from spending_tracker.categories import normalize_merchant
from spending_tracker.paths import DEFAULT_DATA_DIR
from spending_tracker.schema import PRECISION_EXACT, PRECISION_MONTH


DEFAULT_SETTINGS_PATH = DEFAULT_DATA_DIR / "settings.json"

RECURRING_LABEL = "Likely recurring"
MIN_OCCURRENCES = 3
CADENCES = (
    ("Weekly", 7, 3),
    ("Every 2 weeks", 14, 4),
    ("Monthly", 30, 8),
    ("Quarterly", 91, 15),
    ("Yearly", 365, 40),
)


@dataclass(frozen=True)
class RecurringSeries:
    merchant: str
    transaction_type: str
    occurrences: int
    typical_amount: float
    average_gap_days: float
    cadence: str
    first_seen: date
    last_seen: date
    label: str = RECURRING_LABEL

    def as_row(self) -> dict[str, object]:
        return {
            "Merchant": self.merchant,
            "Type": self.transaction_type,
            "Typical amount": self.typical_amount,
            "Cadence": self.cadence,
            "Typical gap (days)": round(self.average_gap_days, 1),
            "Occurrences": self.occurrences,
            "Last seen": self.last_seen.isoformat(),
            "Confidence": self.label,
        }


def _cadence_for(gap: float) -> str | None:
    """Name of the recognised cadence nearest ``gap``, or None.

    Anything that does not land near a familiar cadence is left out rather than
    reported as "about every 260 days", which would look like a finding but is noise.
    """
    for name, days, tolerance in CADENCES:
        if abs(gap - days) <= tolerance:
            return name
    return None


NOMINAL_MONTH_DAYS = 30.4


def _month_index(value: date) -> int:
    return value.year * 12 + value.month


def classify_cadence(days: list[date], min_occurrences: int = MIN_OCCURRENCES) -> tuple[str, float] | None:
    """Cadence name and typical gap in days, or None when the spacing is not regular.

    Monthly series are recognised from month coverage rather than from the gaps
    between individual charges, because a monthly bill often picks up extra small
    entries (a utility top-up alongside the rent) that would blur the gaps.
    """
    if len(days) < min_occurrences:
        return None

    months = sorted({_month_index(day) for day in days})
    span = months[-1] - months[0] + 1
    if len(months) >= min_occurrences and span >= min_occurrences and len(months) / span >= 0.75:
        month_gaps = [later - earlier for earlier, later in zip(months, months[1:], strict=False)]
        typical_months = statistics.median(month_gaps) if month_gaps else 1
        gap_days = float(typical_months) * NOMINAL_MONTH_DAYS
        name = _cadence_for(gap_days)
        return (name, gap_days) if name else None

    gaps = [
        (later - earlier).days for earlier, later in zip(days, days[1:], strict=False) if later > earlier
    ]
    if len(gaps) < min_occurrences - 1:
        return None

    median_gap = statistics.median(gaps)
    if median_gap <= 0:
        return None
    tolerance = max(2.0, median_gap * 0.3)
    close = sum(1 for gap in gaps if abs(gap - median_gap) <= tolerance)
    if close / len(gaps) < 0.6:
        return None
    name = _cadence_for(median_gap)
    return (name, float(median_gap)) if name else None


def find_recurring(
    df: pd.DataFrame,
    min_occurrences: int = MIN_OCCURRENCES,
    precisions: tuple[str, ...] = (PRECISION_EXACT, PRECISION_MONTH),
) -> list[RecurringSeries]:
    """Merchants that show up on a steady cadence.

    Only rows with a usable date take part, and a series needs at least
    ``min_occurrences`` dated transactions with regular spacing.
    """
    if df is None or df.empty:
        return []

    frame = df.copy()
    if "Date Precision" in frame.columns:
        precision = frame["Date Precision"].fillna("").astype(str).str.strip()
        frame = frame[precision.isin(precisions) | precision.eq("")]
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame["Amount"] = pd.to_numeric(frame["Amount"], errors="coerce")
    frame = frame.dropna(subset=["Date", "Amount"])
    if frame.empty:
        return []

    frame["Merchant"] = frame["Description"].map(normalize_merchant)
    frame = frame[frame["Merchant"] != ""]

    series: list[RecurringSeries] = []
    for (merchant, transaction_type), group in frame.groupby(["Merchant", "Type"], sort=True):
        group = group.sort_values("Date")
        days = sorted({value.date() for value in group["Date"]})
        cadence = classify_cadence(days, min_occurrences)
        if cadence is None:
            continue

        cadence_name, gap_days = cadence
        series.append(
            RecurringSeries(
                merchant=str(group["Description"].mode().iat[0]),
                transaction_type=str(transaction_type),
                occurrences=len(days),
                typical_amount=round(float(group["Amount"].median()), 2),
                average_gap_days=gap_days,
                cadence=cadence_name,
                first_seen=days[0],
                last_seen=days[-1],
            )
        )

    series.sort(key=lambda item: (-item.occurrences, item.merchant))
    return series


def recurring_frame(series: list[RecurringSeries]) -> pd.DataFrame:
    columns = [
        "Merchant",
        "Type",
        "Typical amount",
        "Cadence",
        "Typical gap (days)",
        "Occurrences",
        "Last seen",
        "Confidence",
    ]
    if not series:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame([item.as_row() for item in series])[columns]


# --- budget ----------------------------------------------------------------------


def load_settings(path: Path | None = None) -> dict[str, object]:
    target = Path(path or DEFAULT_SETTINGS_PATH)
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(data) if isinstance(data, Mapping) else {}


def save_settings(settings: Mapping[str, object], path: Path | None = None) -> Path:
    target = Path(path or DEFAULT_SETTINGS_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(settings), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def set_monthly_budget(
    amount: float | None, include_rent: bool = False, include_investments: bool = False, path: Path | None = None
) -> dict[str, object]:
    """Store (or clear, with ``amount=None``) the optional monthly Expense budget."""
    settings = load_settings(path)
    if amount is None:
        settings.pop("monthly_budget", None)
        settings.pop("budget_include_rent", None)
        settings.pop("budget_include_investments", None)
    else:
        if amount <= 0:
            raise ValueError("Budget must be greater than zero")
        settings["monthly_budget"] = round(float(amount), 2)
        settings["budget_include_rent"] = bool(include_rent)
        settings["budget_include_investments"] = bool(include_investments)
    save_settings(settings, path)
    return settings


def budget_status(
    df: pd.DataFrame, today: date, settings: Mapping[str, object] | None = None
) -> dict[str, object] | None:
    """Budget vs spending for the month containing ``today``.

    Returns None when no budget is configured, so the app can stay quiet.
    Rent and Investments are excluded unless the settings opt them in.
    """
    settings = dict(settings or {})
    budget = settings.get("monthly_budget")
    if not budget:
        return None

    types = ["Expense"]
    if settings.get("budget_include_rent"):
        types.append("Rent")
    if settings.get("budget_include_investments"):
        types.append("Investment")

    spent = 0.0
    if df is not None and not df.empty:
        frame = df.copy()
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
        frame["Amount"] = pd.to_numeric(frame["Amount"], errors="coerce").fillna(0.0)
        month = frame[
            frame["Type"].astype(str).isin(types)
            & (frame["Date"].dt.year == today.year)
            & (frame["Date"].dt.month == today.month)
        ]
        spent = float(month["Amount"].sum())

    budget_value = round(float(budget), 2)
    spent = round(spent, 2)
    return {
        "budget": budget_value,
        "types": types,
        "spent": spent,
        "remaining": round(budget_value - spent, 2),
        "percent_used": round(spent / budget_value * 100, 1) if budget_value else 0.0,
        "over_budget": spent > budget_value,
        "month": f"{today.year:04d}-{today.month:02d}",
    }


__all__ = [
    "DEFAULT_SETTINGS_PATH",
    "MIN_OCCURRENCES",
    "RECURRING_LABEL",
    "RecurringSeries",
    "budget_status",
    "classify_cadence",
    "find_recurring",
    "load_settings",
    "recurring_frame",
    "save_settings",
    "set_monthly_budget",
]
