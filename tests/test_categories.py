from __future__ import annotations

import pandas as pd
import pytest

from spending_tracker.categories import (
    CATEGORY_OTHER,
    EXPENSE_CATEGORIES,
    MERCHANT_RULES,
    categorize,
    categorize_frame,
    normalize_merchant,
)


@pytest.mark.parametrize(
    ("description", "category"),
    [
        ("Uber", "Transportation"),
        ("Lyft", "Transportation"),
        ("MBTA", "Transportation"),
        ("Divvy", "Transportation"),
        ("Parking", "Transportation"),
        ("Whole Foods", "Groceries"),
        ("Trader Joe's", "Groceries"),
        ("Costco", "Groceries"),
        ("Tatte", "Dining"),
        ("Chipotle", "Dining"),
        ("Starbucks", "Dining"),
        ("CVS", "Health"),
        ("Walgreens", "Health"),
        ("Amazon", "Shopping"),
        ("Target", "Shopping"),
        ("Claude", "Subscriptions"),
        ("Lin Alg course", "Education"),
        ("May Utils", "Utilities"),
        ("Bulls Net", "Entertainment"),
        ("Hotel Indigo", "Travel"),
    ],
)
def test_merchant_rules_cover_the_documented_examples(description: str, category: str) -> None:
    assert categorize(description) == category


@pytest.mark.parametrize("description", ["UBER", "uber", "UbEr", "  uber  ", "Uber "])
def test_matching_is_case_and_whitespace_insensitive(description: str) -> None:
    assert categorize(description) == "Transportation"


def test_punctuation_does_not_break_matching() -> None:
    assert categorize("Trader Joe's ") == "Groceries"
    assert categorize("TRADER JOES") == "Groceries"
    assert categorize("Dick's ") == "Shopping"
    assert categorize("Elephant & Castle") == "Dining"


@pytest.mark.parametrize(
    "description",
    [
        "Uberto Hardware",  # not Uber
        "Steak",  # "tea" must not match inside another word
        "Team Dinner Fund",
        "Gaston",  # "gas" must not match inside another word
        "Pubkey Supplies",
        "Mystery Merchant",
    ],
)
def test_partial_words_do_not_trigger_false_positives(description: str) -> None:
    assert categorize(description) == CATEGORY_OTHER


def test_longest_matching_rule_wins() -> None:
    assert categorize("Whole Foods + MCD") == "Groceries"
    assert categorize("Grand Palace + MCD") == "Dining"
    assert categorize("Costco Meds") == "Health"
    assert categorize("Costco") == "Groceries"


def test_unknown_expenses_fall_back_to_other() -> None:
    assert categorize("Completely New Merchant") == CATEGORY_OTHER
    assert categorize("") == CATEGORY_OTHER
    assert categorize(None) == CATEGORY_OTHER


@pytest.mark.parametrize("transaction_type", ["Income", "Rent", "Investment"])
def test_non_expense_types_are_never_given_an_expense_category(transaction_type: str) -> None:
    assert categorize("Uber", transaction_type) == ""
    assert categorize("Whole Foods", transaction_type) == ""


def test_user_rules_take_precedence_over_built_in_rules() -> None:
    assert categorize("Tatte", "Expense", {"tatte": "Groceries"}) == "Groceries"
    assert categorize("Tatte Bakery", "Expense", {"tatte": "Groceries"}) == "Groceries"
    assert categorize("Uber", "Expense", {"tatte": "Groceries"}) == "Transportation"
    assert categorize("Mystery", "Expense", {"mystery": "Entertainment"}) == "Entertainment"


def test_user_rules_ignore_blank_entries() -> None:
    assert categorize("Tatte", "Expense", {"": "Groceries", "tatte": ""}) == "Dining"


def test_every_rule_points_at_a_known_category() -> None:
    for pattern, category in MERCHANT_RULES:
        assert category in EXPENSE_CATEGORIES, pattern
    assert len(EXPENSE_CATEGORIES) == 11  # ten standard plus Subscriptions


def test_normalize_merchant() -> None:
    assert normalize_merchant("Trader Joe's ") == "trader joe s"
    assert normalize_merchant("  WHOLE   FOODS  ") == "whole foods"
    assert normalize_merchant(None) == ""


def test_categorize_frame_fills_blanks_and_keeps_manual_corrections() -> None:
    frame = pd.DataFrame(
        [
            {"Description": "Uber", "Type": "Expense", "Category": ""},
            {"Description": "Tatte", "Type": "Expense", "Category": "Groceries"},
            {"Description": "TA", "Type": "Income", "Category": ""},
            {"Description": "Rent", "Type": "Rent", "Category": "Shopping"},
        ]
    )

    result = categorize_frame(frame)

    assert result.loc[0, "Category"] == "Transportation"
    assert result.loc[1, "Category"] == "Groceries"  # manual correction untouched
    assert result.loc[2, "Category"] == ""
    assert result.loc[3, "Category"] == ""  # non-expense categories are cleared


def test_categorize_frame_can_overwrite_on_request() -> None:
    frame = pd.DataFrame([{"Description": "Tatte", "Type": "Expense", "Category": "Groceries"}])

    result = categorize_frame(frame, overwrite=True)

    assert result.loc[0, "Category"] == "Dining"


def test_categorize_frame_adds_the_column_when_missing() -> None:
    frame = pd.DataFrame([{"Description": "Uber", "Type": "Expense"}])

    result = categorize_frame(frame)

    assert result.loc[0, "Category"] == "Transportation"


def test_categorize_frame_handles_empty_input() -> None:
    assert categorize_frame(pd.DataFrame()).empty
