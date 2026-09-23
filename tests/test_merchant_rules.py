from __future__ import annotations

from pathlib import Path

import pytest

from spending_tracker.categories import categorize
from spending_tracker.merchant_rules import (
    DEFAULT_RULES_PATH,
    forget_rule,
    learn_from_corrections,
    load_rules,
    remember_rule,
    save_rules,
)


@pytest.fixture
def rules_path(tmp_path: Path) -> Path:
    """Rules file inside tmp_path; the real user file is never touched."""
    return tmp_path / "merchant_rules.json"


def test_default_rules_path_is_in_the_data_directory() -> None:
    assert DEFAULT_RULES_PATH.name == "merchant_rules.json"
    assert DEFAULT_RULES_PATH.parent.name == "data"


def test_load_rules_returns_nothing_when_the_file_is_missing(rules_path: Path) -> None:
    assert load_rules(rules_path) == {}


def test_remember_rule_learns_a_correction(rules_path: Path) -> None:
    rules = remember_rule("Tatte", "Dining", rules_path)

    assert rules == {"tatte": "Dining"}
    assert load_rules(rules_path) == {"tatte": "Dining"}
    assert rules_path.read_text(encoding="utf-8").startswith("{")


def test_learned_rule_changes_future_categorisation(rules_path: Path) -> None:
    assert categorize("Mystery Diner") == "Other"

    remember_rule("Mystery Diner", "Dining", rules_path)

    assert categorize("Mystery Diner", "Expense", load_rules(rules_path)) == "Dining"
    assert categorize("Mystery Diner Downtown", "Expense", load_rules(rules_path)) == "Dining"


def test_user_rules_override_built_in_rules(rules_path: Path) -> None:
    remember_rule("Tatte", "Groceries", rules_path)

    assert categorize("Tatte") == "Dining"  # built-in
    assert categorize("Tatte", "Expense", load_rules(rules_path)) == "Groceries"


def test_relearning_a_merchant_replaces_the_old_category(rules_path: Path) -> None:
    remember_rule("Quantum", "Shopping", rules_path)
    rules = remember_rule("Quantum", "Dining", rules_path)

    assert rules == {"quantum": "Dining"}


def test_forget_rule_removes_it(rules_path: Path) -> None:
    remember_rule("Tatte", "Groceries", rules_path)

    assert forget_rule("Tatte", rules_path) == {}
    assert categorize("Tatte", "Expense", load_rules(rules_path)) == "Dining"
    assert forget_rule("never seen", rules_path) == {}


def test_learn_from_corrections_handles_several_at_once(rules_path: Path) -> None:
    rules = learn_from_corrections({"Tatte": "Dining", "Quantum ": "Dining", "Nope": "Not a category"}, rules_path)

    assert rules == {"tatte": "Dining", "quantum": "Dining"}


def test_invalid_input_is_rejected(rules_path: Path) -> None:
    with pytest.raises(ValueError, match="empty description"):
        remember_rule("   ", "Dining", rules_path)
    with pytest.raises(ValueError, match="Unknown category"):
        remember_rule("Tatte", "Snacks", rules_path)


def test_unknown_categories_and_bad_files_are_ignored(rules_path: Path) -> None:
    save_rules({"tatte": "Dining", "uber": "Nonsense"}, rules_path)
    assert load_rules(rules_path) == {"tatte": "Dining"}

    rules_path.write_text("not json at all", encoding="utf-8")
    assert load_rules(rules_path) == {}

    rules_path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_rules(rules_path) == {}


def test_rules_file_is_human_readable(rules_path: Path) -> None:
    remember_rule("Tatte", "Dining", rules_path)

    text = rules_path.read_text(encoding="utf-8")
    assert '"tatte": "Dining"' in text
    assert text.endswith("\n")
