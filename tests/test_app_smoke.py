"""Streamlit smoke tests.

These run app.py in-process with Streamlit's AppTest harness, pointed at a throwaway
workbook, so a template/layout error fails the suite instead of surfacing in the browser.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from spending_tracker.migration import run_migration

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def _click(app: "AppTest", label: str) -> None:
    next(button for button in app.button if button.label == label).click().run()


def _app(monkeypatch: pytest.MonkeyPatch, tracker: Path, source: Path) -> "AppTest":
    """App pointed at throwaway files, including the rules and settings config."""
    monkeypatch.setenv("SPENDING_TRACKER_WORKBOOK", str(tracker))
    monkeypatch.setenv("SPENDING_SOURCE_WORKBOOK", str(source))
    monkeypatch.setenv("SPENDING_TRACKER_RULES", str(tracker.parent / "merchant_rules.json"))
    monkeypatch.setenv("SPENDING_TRACKER_SETTINGS", str(tracker.parent / "settings.json"))
    return AppTest.from_file(APP, default_timeout=120)


def test_app_runs_against_a_migrated_tracker(
    monkeypatch: pytest.MonkeyPatch, historical_workbook: Path, legacy_tracker: Path
) -> None:
    run_migration(historical_workbook, legacy_tracker, output_dir=legacy_tracker.parent, apply=True)

    app = _app(monkeypatch, legacy_tracker, historical_workbook).run()

    assert not app.exception
    assert any("Spending Tracker" in str(title.value) for title in app.title)


def test_app_runs_with_an_empty_tracker(
    monkeypatch: pytest.MonkeyPatch, historical_workbook: Path, tmp_path: Path
) -> None:
    app = _app(monkeypatch, tmp_path / "missing.xlsx", historical_workbook).run()

    assert not app.exception


def test_paste_parse_and_confirm_writes_categorised_rows(
    monkeypatch: pytest.MonkeyPatch, historical_workbook: Path, legacy_tracker: Path
) -> None:
    from spending_tracker.excel_store import load_transactions

    app = _app(monkeypatch, legacy_tracker, historical_workbook).run()
    app.text_area[0].set_value("uber 14.23\nwhole foods 36.19\ntatte 7.85").run()
    _click(app, "Parse")

    # AppTest has no data_editor accessor; the preview frame lives in session state.
    preview = app.session_state["transactions_df"]
    assert preview["Category"].tolist() == ["Transportation", "Groceries", "Dining"]

    _click(app, "Confirm / Add to Excel")

    assert not app.exception
    saved = load_transactions(legacy_tracker)
    added = saved[saved["Description"].isin(["Uber", "Whole Foods", "Tatte"])]
    assert set(added["Category"]) == {"Transportation", "Groceries", "Dining", ""}


def test_every_tab_renders_with_migrated_data(
    monkeypatch: pytest.MonkeyPatch, historical_workbook: Path, legacy_tracker: Path
) -> None:
    run_migration(historical_workbook, legacy_tracker, output_dir=legacy_tracker.parent, apply=True)

    app = _app(monkeypatch, legacy_tracker, historical_workbook).run()

    assert not app.exception
    labels = {str(subheader.value) for subheader in app.subheader}
    assert {
        "Spending by Category",
        "Monthly Expense Trend",
        "Likely Recurring Transactions",
        "Learned Merchant Rules",
        "Backup and Export",
        "Optional AI Categorisation",
    } <= labels
    buttons = {button.label for button in app.button}
    assert {"Parse", "Save edits", "Delete marked", "Save budget", "Create workbook backup now"} <= buttons
    assert any(
        "Download" in str(download.label) for download in app.get("download_button")
    )


def _checkbox(app: "AppTest", label_fragment: str):
    return next(box for box in app.checkbox if label_fragment in str(box.label))


def test_duplicate_warning_blocks_confirm_until_overridden(
    monkeypatch: pytest.MonkeyPatch, historical_workbook: Path, legacy_tracker: Path
) -> None:
    from spending_tracker.excel_store import load_transactions

    app = _app(monkeypatch, legacy_tracker, historical_workbook).run()
    # The legacy tracker already holds "Uber 12.00" on 2026-09-14.
    app.sidebar.date_input[0].set_value(date(2026, 9, 14)).run()
    app.text_area[0].set_value("uber 12").run()
    _click(app, "Parse")

    assert any("Possible duplicate" in str(warning.value) for warning in app.warning)
    confirm = next(button for button in app.button if button.label == "Confirm / Add to Excel")
    assert confirm.disabled is True

    _checkbox(app, "genuinely separate").set_value(True).run()
    _click(app, "Confirm / Add to Excel")

    assert not app.exception
    saved = load_transactions(legacy_tracker)
    assert len(saved[saved["Description"] == "Uber"]) == 2  # override honoured


def test_editing_a_category_saves_and_is_remembered(
    monkeypatch: pytest.MonkeyPatch, historical_workbook: Path, legacy_tracker: Path
) -> None:
    from spending_tracker.excel_store import load_transactions
    from spending_tracker.manage import read_audit, save_transactions
    from spending_tracker.merchant_rules import load_rules

    # Category corrections go through the same helpers the Manage tab uses.
    rules_path = legacy_tracker.parent / "merchant_rules.json"
    stored = load_transactions(legacy_tracker)
    target = stored.index[stored["Description"] == "Tatte"][0]
    stored.loc[target, "Category"] = "Dining"
    save_transactions(legacy_tracker, stored, action="edit", details={"rows": 1})
    from spending_tracker.merchant_rules import learn_from_corrections

    learn_from_corrections({"Tatte": "Dining"}, rules_path)

    app = _app(monkeypatch, legacy_tracker, historical_workbook).run()

    assert not app.exception
    assert load_rules(rules_path) == {"tatte": "Dining"}
    assert read_audit(legacy_tracker)[0]["action"] == "edit"
    # A new Tatte line now defaults to the learned category.
    app.text_area[0].set_value("tatte 7.85").run()
    _click(app, "Parse")
    assert app.session_state["transactions_df"].loc[0, "Category"] == "Dining"


def test_budget_settings_persist_and_show_on_the_dashboard(
    monkeypatch: pytest.MonkeyPatch, historical_workbook: Path, legacy_tracker: Path
) -> None:
    from spending_tracker.insights import load_settings

    settings_path = legacy_tracker.parent / "settings.json"
    app = _app(monkeypatch, legacy_tracker, historical_workbook).run()

    assert not any("Monthly Expense Budget" in str(subheader.value) for subheader in app.subheader[:6])

    # Pick the budget field by label: other tabs also render number inputs.
    next(field for field in app.number_input if field.label == "Monthly budget").set_value(900.0).run()
    _click(app, "Save budget")

    assert load_settings(settings_path)["monthly_budget"] == 900.0
    reopened = _app(monkeypatch, legacy_tracker, historical_workbook).run()
    assert not reopened.exception
    assert any("Budget" in str(metric.label) for metric in reopened.metric)


def test_a_category_changed_in_the_preview_is_learned(
    monkeypatch: pytest.MonkeyPatch, historical_workbook: Path, legacy_tracker: Path
) -> None:
    from spending_tracker.merchant_rules import load_rules

    rules_path = legacy_tracker.parent / "merchant_rules.json"
    app = _app(monkeypatch, legacy_tracker, historical_workbook).run()
    app.text_area[0].set_value("mystery arcade 30").run()
    _click(app, "Parse")

    assert app.session_state["transactions_df"].loc[0, "Category"] == "Other"

    # Simulate the user picking a category in the preview editor.
    preview = app.session_state["transactions_df"]
    preview.loc[0, "Category"] = "Entertainment"
    app.session_state["transactions_df"] = preview
    app.run()
    _click(app, "Confirm / Add to Excel")

    assert not app.exception
    assert load_rules(rules_path) == {"mystery arcade": "Entertainment"}


def _review_app(
    monkeypatch: pytest.MonkeyPatch, tracker: Path, source: Path, state: Path
) -> "AppTest":
    app = _app(monkeypatch, tracker, source)
    monkeypatch.setenv("SPENDING_TRACKER_REVIEW_STATE", str(state))
    return app


def test_historical_review_tab_lists_unresolved_rows(
    monkeypatch: pytest.MonkeyPatch, review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    app = _review_app(monkeypatch, legacy_tracker, review_workbook, review_state_path).run()

    assert not app.exception
    labels = {str(metric.label) for metric in app.metric}
    assert {
        "Unresolved",
        "Approved this session",
        "Ignored permanently",
        "Total unresolved amount",
    } <= labels
    unresolved = next(metric for metric in app.metric if metric.label == "Unresolved")
    assert unresolved.value == "8"
    total = next(metric for metric in app.metric if metric.label == "Total unresolved amount")
    assert total.value == "$8,160.00"
    # Nothing is imported just by opening the tab.
    from spending_tracker.excel_store import load_transactions

    assert len(load_transactions(legacy_tracker)) == 5
    assert not review_state_path.exists()


def test_approving_from_the_app_imports_one_row_and_clears_it_from_the_queue(
    monkeypatch: pytest.MonkeyPatch, review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    from spending_tracker.excel_store import load_transactions
    from spending_tracker.review import load_state

    app = _review_app(monkeypatch, legacy_tracker, review_workbook, review_state_path).run()
    next(button for button in app.button if button.key == "rv_ok_Rent!B4").click().run()

    assert not app.exception
    transactions = load_transactions(legacy_tracker)
    approved = transactions[transactions["Source Reference"] == "B4"]
    assert len(approved) == 1
    assert approved.iloc[0]["Description"] == "Sandra rent reimbursement"
    assert approved.iloc[0]["Type"] == "Income"
    assert load_state(review_state_path)["Rent!B4"]["status"] == "Approved"
    assert next(metric for metric in app.metric if metric.label == "Unresolved").value == "7"
    assert next(metric for metric in app.metric if metric.label == "Approved this session").value == "1"
    assert not any(button.key == "rv_ok_Rent!B4" for button in app.button)


def test_editing_a_field_before_approving_is_honoured_by_the_app(
    monkeypatch: pytest.MonkeyPatch, review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    from spending_tracker.excel_store import load_transactions
    from spending_tracker.review import load_state

    app = _review_app(monkeypatch, legacy_tracker, review_workbook, review_state_path).run()
    app.text_input(key="rv_desc_Spring 25!F9").set_value("UChicago deposit").run()
    app.selectbox(key="rv_type_Spring 25!F9").set_value("Income").run()
    next(button for button in app.button if button.key == "rv_ok_Spring 25!F9").click().run()

    assert not app.exception
    row = load_transactions(legacy_tracker)
    row = row[row["Source Reference"] == "F9"].iloc[0]
    assert row["Description"] == "UChicago deposit"
    assert row["Type"] == "Income"
    assert row["Amount"] == 5000
    assert load_state(review_state_path)["Spring 25!F9"]["action"] == "approve-edited"


def test_ignoring_from_the_app_writes_nothing_and_hides_the_row(
    monkeypatch: pytest.MonkeyPatch, review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    from spending_tracker.excel_store import load_transactions
    from spending_tracker.review import load_state

    app = _review_app(monkeypatch, legacy_tracker, review_workbook, review_state_path).run()
    app.text_input(key="rv_note_Spring 25!C8").set_value("bank correction").run()
    next(button for button in app.button if button.key == "rv_no_Spring 25!C8").click().run()

    assert not app.exception
    assert len(load_transactions(legacy_tracker)) == 5
    state = load_state(review_state_path)
    assert state["Spring 25!C8"]["status"] == "Ignored"
    assert state["Spring 25!C8"]["note"] == "bank correction"
    assert next(metric for metric in app.metric if metric.label == "Ignored permanently").value == "1"
    assert not any(button.key == "rv_ok_Spring 25!C8" for button in app.button)


def test_review_decisions_survive_a_restart_and_do_not_duplicate(
    monkeypatch: pytest.MonkeyPatch, review_workbook: Path, legacy_tracker: Path, review_state_path: Path
) -> None:
    from spending_tracker.excel_store import load_transactions

    app = _review_app(monkeypatch, legacy_tracker, review_workbook, review_state_path).run()
    next(button for button in app.button if button.key == "rv_ok_Rent!B4").click().run()
    next(button for button in app.button if button.key == "rv_no_Spring 25!C7").click().run()
    rows_after = len(load_transactions(legacy_tracker))

    reopened = _review_app(monkeypatch, legacy_tracker, review_workbook, review_state_path).run()

    assert not reopened.exception
    assert next(metric for metric in reopened.metric if metric.label == "Unresolved").value == "6"
    assert next(metric for metric in reopened.metric if metric.label == "Ignored permanently").value == "1"
    # A restart shows no approvals for "this session" and imports nothing again.
    assert next(metric for metric in reopened.metric if metric.label == "Approved this session").value == "0"
    assert len(load_transactions(legacy_tracker)) == rows_after
