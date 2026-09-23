from __future__ import annotations

import csv
from datetime import date, datetime
from io import StringIO
from pathlib import Path

import pandas as pd

from spending_tracker.ai_categorizer import (
    API_KEY_ENV_VARS,
    ENABLE_ENV_VAR,
    DisabledProvider,
    ai_enabled,
    categorize_with_fallback,
)
from spending_tracker.export import export_filename, export_frame, transactions_csv, write_csv
from spending_tracker.schema import TRANSACTION_COLUMNS


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Date": pd.Timestamp("2026-09-23"),
                "Description": "Uber",
                "Amount": 12.349,
                "Type": "Expense",
                "Category": "Transportation",
                "Source Line": "uber 12.35",
                "Source Period": "",
                "Source Sheet": "",
                "Source Reference": "",
                "Date Precision": "Exact",
                "Added At": "2026-09-23 10:00:00",
            },
            {
                "Date": None,
                "Description": "IBKR",
                "Amount": 5000,
                "Type": "Investment",
                "Category": "",
                "Source Line": "IBKR | 5000",
                "Source Period": "25-26",
                "Source Sheet": "25-26",
                "Source Reference": "AB3",
                "Date Precision": "Unknown",
                "Added At": "2026-09-23 10:00:00",
            },
        ]
    )


def test_export_frame_uses_schema_order_and_iso_dates() -> None:
    exported = export_frame(_frame())

    assert list(exported.columns) == TRANSACTION_COLUMNS
    assert exported.loc[0, "Date"] == "2026-09-23"
    assert exported.loc[1, "Date"] == ""
    assert exported.loc[0, "Amount"] == 12.35


def test_transactions_csv_round_trips() -> None:
    rows = list(csv.DictReader(StringIO(transactions_csv(_frame()))))

    assert len(rows) == 2
    assert rows[0]["Description"] == "Uber"
    assert rows[0]["Category"] == "Transportation"
    assert rows[1]["Source Reference"] == "AB3"
    assert list(rows[0]) == TRANSACTION_COLUMNS


def test_transactions_csv_handles_a_legacy_frame_without_new_columns() -> None:
    frame = pd.DataFrame(
        [{"Date": date(2026, 9, 23), "Description": "Uber", "Amount": 12, "Type": "Expense"}]
    )

    rows = list(csv.DictReader(StringIO(transactions_csv(frame))))

    assert rows[0]["Category"] == ""
    assert rows[0]["Date Precision"] == "Exact"


def test_export_filename_is_dated() -> None:
    assert export_filename(datetime(2026, 9, 23, 12, 0, 0)) == "transactions-20260923.csv"


def test_write_csv_creates_the_file(tmp_path: Path) -> None:
    target = write_csv(_frame(), tmp_path / "nested" / "out.csv")

    assert target.exists()
    assert target.read_text(encoding="utf-8").splitlines()[0].startswith("Date,Description,Amount")


def test_transactions_csv_on_empty_input() -> None:
    text = transactions_csv(pd.DataFrame())

    assert text.splitlines()[0] == ",".join(TRANSACTION_COLUMNS)


def test_ai_is_disabled_unless_explicitly_enabled_with_a_key() -> None:
    assert ai_enabled({}) is False
    assert ai_enabled({ENABLE_ENV_VAR: "1"}) is False
    assert ai_enabled({API_KEY_ENV_VARS[0]: "sk-test"}) is False
    assert ai_enabled({ENABLE_ENV_VAR: "0", API_KEY_ENV_VARS[0]: "sk-test"}) is False
    assert ai_enabled({ENABLE_ENV_VAR: "1", API_KEY_ENV_VARS[0]: "sk-test"}) is True
    assert ai_enabled({ENABLE_ENV_VAR: "true", API_KEY_ENV_VARS[1]: "sk-test"}) is True


def test_deterministic_rules_always_win_and_no_provider_is_called() -> None:
    class ExplodingProvider:
        def suggest(self, merchant: str, categories: list[str]) -> str | None:
            raise AssertionError("the provider must not be consulted for a known merchant")

    env = {ENABLE_ENV_VAR: "1", API_KEY_ENV_VARS[0]: "sk-test"}
    assert categorize_with_fallback("Uber", provider=ExplodingProvider(), env=env) == "Transportation"
    assert (
        categorize_with_fallback("Tatte", user_rules={"tatte": "Groceries"}, provider=ExplodingProvider(), env=env)
        == "Groceries"
    )


def test_provider_is_not_consulted_while_ai_is_disabled() -> None:
    class ExplodingProvider:
        def suggest(self, merchant: str, categories: list[str]) -> str | None:
            raise AssertionError("no API call may happen when AI is disabled")

    assert categorize_with_fallback("Mystery", provider=ExplodingProvider(), env={}) == "Other"


def test_enabled_provider_can_resolve_an_unknown_merchant() -> None:
    class Provider:
        def __init__(self) -> None:
            self.seen: list[str] = []

        def suggest(self, merchant: str, categories: list[str]) -> str | None:
            self.seen.append(merchant)
            return "Entertainment"

    provider = Provider()
    env = {ENABLE_ENV_VAR: "1", API_KEY_ENV_VARS[0]: "sk-test"}

    assert categorize_with_fallback("Mystery Arcade", provider=provider, env=env) == "Entertainment"
    # Only the merchant name is handed over - no dates, amounts or history.
    assert provider.seen == ["Mystery Arcade"]


def test_provider_failures_and_nonsense_answers_fall_back_to_other() -> None:
    class Failing:
        def suggest(self, merchant: str, categories: list[str]) -> str | None:
            raise RuntimeError("network down")

    class Nonsense:
        def suggest(self, merchant: str, categories: list[str]) -> str | None:
            return "Spaceships"

    env = {ENABLE_ENV_VAR: "1", API_KEY_ENV_VARS[0]: "sk-test"}
    assert categorize_with_fallback("Mystery", provider=Failing(), env=env) == "Other"
    assert categorize_with_fallback("Mystery", provider=Nonsense(), env=env) == "Other"
    assert categorize_with_fallback("Mystery", provider=DisabledProvider(), env=env) == "Other"


def test_non_expense_types_never_reach_the_provider() -> None:
    class ExplodingProvider:
        def suggest(self, merchant: str, categories: list[str]) -> str | None:
            raise AssertionError("income rows have no expense category")

    env = {ENABLE_ENV_VAR: "1", API_KEY_ENV_VARS[0]: "sk-test"}
    assert categorize_with_fallback("Mystery", "Income", provider=ExplodingProvider(), env=env) == ""


def test_no_api_key_appears_in_the_source() -> None:
    source = Path("spending_tracker/ai_categorizer.py").read_text(encoding="utf-8")

    assert "sk-" not in source
    assert "api_key=" not in source
