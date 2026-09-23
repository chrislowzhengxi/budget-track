from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from spending_tracker.categories import categorize
from spending_tracker.schema import VALID_TYPES

AMOUNT_PATTERN = re.compile(r"(?P<paren>\()?[$]?(?P<amount>\d[\d,]*(?:\.\d{1,2})?)(?(paren)\))")


@dataclass
class ParsedTransaction:
    date: date
    description: str
    amount: Decimal | None
    type: str
    source_line: str
    status: str
    note: str
    category: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "Date": self.date,
            "Description": self.description,
            "Amount": float(self.amount) if self.amount is not None else None,
            "Type": self.type,
            "Category": self.category,
            "Source Line": self.source_line,
            "Status": self.status,
            "Note": self.note,
        }


def parse_lines(
    text: str, default_date: date, user_rules: Mapping[str, str] | None = None
) -> list[ParsedTransaction]:
    return [
        parse_line(line, default_date, user_rules) for line in text.splitlines() if line.strip()
    ]


def parse_line(
    line: str, default_date: date, user_rules: Mapping[str, str] | None = None
) -> ParsedTransaction:
    raw = line.strip()
    matches = list(AMOUNT_PATTERN.finditer(raw))
    if len(matches) != 1:
        return _needs_review(default_date, raw, "Expected exactly one amount.")

    match = matches[0]
    amount = _parse_amount(match.group("amount"))
    if amount is None:
        return _needs_review(default_date, raw, "Amount could not be parsed.")

    description = (raw[: match.start()] + " " + raw[match.end() :]).strip()
    description = _clean_description(description)
    if not description:
        return _needs_review(default_date, raw, "Missing description.")

    transaction_type = _infer_type(description, bool(match.group("paren")))
    title = _title_description(description)
    return ParsedTransaction(
        date=default_date,
        description=title,
        amount=amount,
        type=transaction_type,
        source_line=raw,
        status="Ready",
        note="",
        category=categorize(title, transaction_type, user_rules),
    )


def _parse_amount(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", "")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def _infer_type(description: str, has_parentheses: bool) -> str:
    normalized = description.strip().lower()
    if has_parentheses:
        return "Income"
    if normalized in {"rent"} or normalized.startswith("rent "):
        return "Rent"
    if normalized in {"investment", "investments"} or normalized.startswith(("investment ", "investments ")):
        return "Investment"
    return "Expense"


def _clean_description(description: str) -> str:
    description = re.sub(r"\s+", " ", description)
    return description.strip(" -:\t")


def _title_description(description: str) -> str:
    words = []
    for word in description.split(" "):
        if word.isupper() and len(word) <= 4:
            words.append(word)
        else:
            words.append(word[:1].upper() + word[1:])
    return " ".join(words)


def _needs_review(default_date: date, raw: str, note: str) -> ParsedTransaction:
    return ParsedTransaction(
        date=default_date,
        description=raw,
        amount=None,
        type="Expense",
        source_line=raw,
        status="Needs review",
        note=note,
    )
