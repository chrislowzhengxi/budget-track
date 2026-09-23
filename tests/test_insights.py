from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from spending_tracker.insights import (
    DEFAULT_SETTINGS_PATH,
    RECURRING_LABEL,
    budget_status,
    classify_cadence,
    find_recurring,
    load_settings,
    recurring_frame,
    save_settings,
    set_monthly_budget,
)
from spending_tracker.schema import PRECISION_EXACT, PRECISION_PERIOD


@pytest.fixture
def settings_path(tmp_path: Path) -> Path:
    """Settings file inside tmp_path; the real user settings are never touched."""
    return tmp_path / "settings.json"


def _monthly_rows(description: str, amount: float, months: int, transaction_type: str = "Expense") -> list[dict]:
    return [
        {
            "Date": pd.Timestamp(date(2026, month, 1)),
            "Description": description,
            "Amount": amount,
            "Type": transaction_type,
            "Category": "Other",
            "Date Precision": PRECISION_EXACT,
        }
        for month in range(1, months + 1)
    ]


def test_classify_cadence_recognises_regular_spacing() -> None:
    weekly = [date(2026, 1, 1) + timedelta(days=7 * n) for n in range(5)]
    biweekly = [date(2026, 1, 1) + timedelta(days=14 * n) for n in range(4)]
    monthly = [date(2026, month, 1) for month in range(1, 6)]

    assert classify_cadence(weekly) == ("Weekly", 7.0)
    assert classify_cadence(biweekly) == ("Every 2 weeks", 14.0)
    assert classify_cadence(monthly)[0] == "Monthly"


def test_classify_cadence_rejects_noise_and_short_series() -> None:
    assert classify_cadence([date(2026, 1, 1), date(2026, 1, 3), date(2026, 5, 20), date(2026, 11, 2)]) is None
    assert classify_cadence([date(2026, 1, 1), date(2026, 2, 1)]) is None
    assert classify_cadence([]) is None
    # An irregular ~21 day gap is not a familiar cadence, so it is not reported.
    assert classify_cadence([date(2026, 1, 1), date(2026, 1, 22), date(2026, 2, 12)]) is None


def test_find_recurring_detects_monthly_rent() -> None:
    frame = pd.DataFrame(_monthly_rows("Rent", 1400.0, 6, "Rent") + _monthly_rows("Netflix", 15.49, 5))

    series = {item.merchant: item for item in find_recurring(frame)}

    assert series["Rent"].cadence == "Monthly"
    assert series["Rent"].typical_amount == 1400.0
    assert series["Rent"].occurrences == 6
    assert series["Rent"].transaction_type == "Rent"
    assert series["Rent"].label == RECURRING_LABEL
    assert series["Rent"].last_seen == date(2026, 6, 1)
    assert series["Netflix"].cadence == "Monthly"


def test_find_recurring_tolerates_extra_charges_in_a_monthly_series() -> None:
    frame = pd.DataFrame(
        _monthly_rows("Rent", 1400.0, 5, "Rent")
        + [
            {
                "Date": pd.Timestamp("2026-03-14"),
                "Description": "Rent",
                "Amount": 25.0,
                "Type": "Rent",
                "Category": "",
                "Date Precision": PRECISION_EXACT,
            }
        ]
    )

    series = find_recurring(frame)

    assert series[0].cadence == "Monthly"
    assert series[0].typical_amount == 1400.0


def test_find_recurring_ignores_one_off_and_irregular_merchants() -> None:
    frame = pd.DataFrame(
        [
            {
                "Date": pd.Timestamp("2026-01-05"),
                "Description": "Boka",
                "Amount": 283.0,
                "Type": "Expense",
                "Category": "Dining",
                "Date Precision": PRECISION_EXACT,
            },
            {
                "Date": pd.Timestamp("2026-04-19"),
                "Description": "Boka",
                "Amount": 190.0,
                "Type": "Expense",
                "Category": "Dining",
                "Date Precision": PRECISION_EXACT,
            },
        ]
    )

    assert find_recurring(frame) == []


def test_find_recurring_skips_rows_without_reliable_dates() -> None:
    frame = pd.DataFrame(
        [
            dict(row, **{"Date Precision": PRECISION_PERIOD})
            for row in _monthly_rows("Quantum", 11.63, 6)
        ]
    )

    assert find_recurring(frame) == []


def test_recurring_frame_columns_and_empty_case() -> None:
    frame = recurring_frame(find_recurring(pd.DataFrame(_monthly_rows("Netflix", 15.49, 4))))

    assert list(frame.columns) == [
        "Merchant",
        "Type",
        "Typical amount",
        "Cadence",
        "Typical gap (days)",
        "Occurrences",
        "Last seen",
        "Confidence",
    ]
    assert frame.loc[0, "Confidence"] == RECURRING_LABEL
    assert recurring_frame([]).empty
    assert find_recurring(pd.DataFrame()) == []


def test_default_settings_path_is_in_the_data_directory() -> None:
    assert DEFAULT_SETTINGS_PATH.name == "settings.json"
    assert DEFAULT_SETTINGS_PATH.parent.name == "data"


def test_budget_status_is_none_until_a_budget_is_configured(settings_path: Path) -> None:
    frame = pd.DataFrame(_monthly_rows("Tatte", 10.0, 2))

    assert budget_status(frame, date(2026, 2, 10), load_settings(settings_path)) is None
    assert budget_status(frame, date(2026, 2, 10), {}) is None
    assert budget_status(frame, date(2026, 2, 10), {"monthly_budget": 0}) is None


def test_budget_status_reports_spent_remaining_and_percent(settings_path: Path) -> None:
    set_monthly_budget(500.0, path=settings_path)
    frame = pd.DataFrame(
        [
            {"Date": pd.Timestamp("2026-02-03"), "Description": "Tatte", "Amount": 100.0, "Type": "Expense"},
            {"Date": pd.Timestamp("2026-02-20"), "Description": "Uber", "Amount": 25.0, "Type": "Expense"},
            {"Date": pd.Timestamp("2026-01-20"), "Description": "Uber", "Amount": 60.0, "Type": "Expense"},
            {"Date": pd.Timestamp("2026-02-01"), "Description": "Rent", "Amount": 1400.0, "Type": "Rent"},
            {"Date": pd.Timestamp("2026-02-01"), "Description": "IBKR", "Amount": 500.0, "Type": "Investment"},
        ]
    )

    status = budget_status(frame, date(2026, 2, 14), load_settings(settings_path))

    assert status["budget"] == 500.0
    assert status["spent"] == 125.0  # rent and investments excluded, January excluded
    assert status["remaining"] == 375.0
    assert status["percent_used"] == 25.0
    assert status["over_budget"] is False
    assert status["types"] == ["Expense"]
    assert status["month"] == "2026-02"


def test_budget_can_include_rent_and_investments_when_asked(settings_path: Path) -> None:
    set_monthly_budget(2000.0, include_rent=True, include_investments=True, path=settings_path)
    frame = pd.DataFrame(
        [
            {"Date": pd.Timestamp("2026-02-03"), "Description": "Tatte", "Amount": 100.0, "Type": "Expense"},
            {"Date": pd.Timestamp("2026-02-01"), "Description": "Rent", "Amount": 1400.0, "Type": "Rent"},
            {"Date": pd.Timestamp("2026-02-01"), "Description": "IBKR", "Amount": 600.0, "Type": "Investment"},
        ]
    )

    status = budget_status(frame, date(2026, 2, 14), load_settings(settings_path))

    assert status["spent"] == 2100.0
    assert status["over_budget"] is True
    assert status["remaining"] == -100.0
    assert status["types"] == ["Expense", "Rent", "Investment"]


def test_budget_can_be_cleared_and_rejects_bad_values(settings_path: Path) -> None:
    set_monthly_budget(300.0, path=settings_path)

    assert load_settings(settings_path)["monthly_budget"] == 300.0

    set_monthly_budget(None, path=settings_path)
    assert "monthly_budget" not in load_settings(settings_path)

    with pytest.raises(ValueError, match="greater than zero"):
        set_monthly_budget(-5, path=settings_path)


def test_settings_survive_a_reload_and_ignore_a_broken_file(settings_path: Path) -> None:
    save_settings({"monthly_budget": 400.0, "other": "keep"}, settings_path)

    assert load_settings(settings_path) == {"monthly_budget": 400.0, "other": "keep"}

    set_monthly_budget(450.0, path=settings_path)
    assert load_settings(settings_path)["other"] == "keep"

    settings_path.write_text("{oops", encoding="utf-8")
    assert load_settings(settings_path) == {}


def test_budget_status_handles_an_empty_frame(settings_path: Path) -> None:
    set_monthly_budget(100.0, path=settings_path)

    status = budget_status(pd.DataFrame(), date(2026, 2, 1), load_settings(settings_path))

    assert status["spent"] == 0.0
    assert status["percent_used"] == 0.0
