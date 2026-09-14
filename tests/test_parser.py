from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from spending_tracker.parser import parse_line, parse_lines


DEFAULT_DATE = date(2026, 9, 14)


@pytest.mark.parametrize(
    ("line", "description", "amount"),
    [
        ("uber 12", "Uber", Decimal("12.00")),
        ("12 uber", "Uber", Decimal("12.00")),
        ("uber 12.5", "Uber", Decimal("12.50")),
        ("uber 12.50", "Uber", Decimal("12.50")),
        ("uber $12", "Uber", Decimal("12.00")),
        ("uber $12.50", "Uber", Decimal("12.50")),
        ("$12 uber", "Uber", Decimal("12.00")),
        ("$12.50 uber", "Uber", Decimal("12.50")),
        ("whole foods 31", "Whole Foods", Decimal("31.00")),
        ("whole foods 31.99", "Whole Foods", Decimal("31.99")),
        ("whole foods 1,200", "Whole Foods", Decimal("1200.00")),
        ("whole foods 1,200.50", "Whole Foods", Decimal("1200.50")),
        ("1,200.50 whole foods", "Whole Foods", Decimal("1200.50")),
        ("coffee 0.99", "Coffee", Decimal("0.99")),
        ("parking 5", "Parking", Decimal("5.00")),
        ("tatte 8.5", "Tatte", Decimal("8.50")),
    ],
)
def test_normal_expense_parser_cases(line: str, description: str, amount: Decimal) -> None:
    transaction = parse_line(line, DEFAULT_DATE)

    assert transaction.description == description
    assert transaction.amount == amount
    assert transaction.type == "Expense"
    assert transaction.status == "Ready"


@pytest.mark.parametrize(
    ("line", "description", "amount"),
    [
        ("TA (695.56)", "TA", Decimal("695.56")),
        ("(695.56) TA", "TA", Decimal("695.56")),
        ("refund (25)", "Refund", Decimal("25.00")),
        ("(25) refund", "Refund", Decimal("25.00")),
        ("salary (1,200)", "Salary", Decimal("1200.00")),
        ("(1,200.50) salary", "Salary", Decimal("1200.50")),
        ("reimbursement (12.75)", "Reimbursement", Decimal("12.75")),
    ],
)
def test_parentheses_indicate_positive_income(line: str, description: str, amount: Decimal) -> None:
    transaction = parse_line(line, DEFAULT_DATE)

    assert transaction.description == description
    assert "(" not in transaction.description
    assert ")" not in transaction.description
    assert str(amount) not in transaction.description
    assert transaction.amount == amount
    assert transaction.amount > 0
    assert transaction.type == "Income"
    assert transaction.status == "Ready"


@pytest.mark.parametrize(
    ("line", "description", "amount"),
    [
        ("rent 1800", "Rent", Decimal("1800.00")),
        ("Rent 1800", "Rent", Decimal("1800.00")),
        ("RENT 1800", "RENT", Decimal("1800.00")),
        ("rent $1,800", "Rent", Decimal("1800.00")),
        ("rent september 1800", "Rent September", Decimal("1800.00")),
        ("rent ashdown 1800", "Rent Ashdown", Decimal("1800.00")),
    ],
)
def test_rent_cases(line: str, description: str, amount: Decimal) -> None:
    transaction = parse_line(line, DEFAULT_DATE)

    assert transaction.description == description
    assert transaction.amount == amount
    assert transaction.type == "Rent"
    assert transaction.status == "Ready"


def test_restaurant_without_amount_is_flagged_not_classified_as_rent() -> None:
    transaction = parse_line("restaurant", DEFAULT_DATE)

    assert transaction.description == "restaurant"
    assert transaction.amount is None
    assert transaction.type == "Expense"
    assert transaction.status == "Needs review"
    assert transaction.note == "Expected exactly one amount."


@pytest.mark.parametrize(
    ("line", "description", "amount"),
    [
        ("investment 500", "Investment", Decimal("500.00")),
        ("investments $1,200.50", "Investments", Decimal("1200.50")),
        ("investment brokerage 250", "Investment Brokerage", Decimal("250.00")),
    ],
)
def test_investment_cases(line: str, description: str, amount: Decimal) -> None:
    transaction = parse_line(line, DEFAULT_DATE)

    assert transaction.description == description
    assert transaction.amount == amount
    assert transaction.type == "Investment"
    assert transaction.status == "Ready"


@pytest.mark.parametrize(
    ("line", "note"),
    [
        ("", "Expected exactly one amount."),
        ("just words", "Expected exactly one amount."),
        ("uber 12 13", "Expected exactly one amount."),
        ("12", "Missing description."),
        ("$12", "Missing description."),
    ],
)
def test_uncertain_lines_are_flagged_for_review(line: str, note: str) -> None:
    transaction = parse_line(line, DEFAULT_DATE)

    assert transaction.amount is None or transaction.description == line
    assert transaction.type == "Expense"
    assert transaction.status == "Needs review"
    assert transaction.note == note


def test_parse_lines_skips_blank_lines() -> None:
    transactions = parse_lines("uber 12\n\n  \ntatte 8.5", DEFAULT_DATE)

    assert [transaction.description for transaction in transactions] == ["Uber", "Tatte"]
    assert [transaction.status for transaction in transactions] == ["Ready", "Ready"]


def test_as_dict_keeps_date_object_for_streamlit_date_editor() -> None:
    transaction = parse_line("uber 12", DEFAULT_DATE)

    data = transaction.as_dict()

    assert data["Date"] == DEFAULT_DATE
    assert isinstance(data["Date"], date)
