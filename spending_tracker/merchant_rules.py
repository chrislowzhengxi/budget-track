"""Merchant -> Category rules learned from manual corrections.

A tiny JSON file, no database.  Built-in rules live in
:mod:`spending_tracker.categories`; anything in here overrides them, which is what
makes a correction stick: change "Tatte" from Other to Dining once and future Tatte
rows default to Dining.

The file is a flat mapping of normalised merchant key -> category, so it stays easy
to read and edit by hand:

    {"tatte": "Dining", "quantum": "Dining"}
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import json
from pathlib import Path

from spending_tracker.categories import EXPENSE_CATEGORIES, normalize_merchant
from spending_tracker.paths import DEFAULT_DATA_DIR


DEFAULT_RULES_PATH = DEFAULT_DATA_DIR / "merchant_rules.json"


def load_rules(path: Path | None = None) -> dict[str, str]:
    """Read the rules file.  A missing or malformed file yields no rules."""
    target = Path(path or DEFAULT_RULES_PATH)
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(data, Mapping):
        return {}

    rules: dict[str, str] = {}
    for key, value in data.items():
        merchant = normalize_merchant(key)
        if merchant and isinstance(value, str) and value in EXPENSE_CATEGORIES:
            rules[merchant] = value
    return rules


def save_rules(rules: Mapping[str, str], path: Path | None = None) -> Path:
    target = Path(path or DEFAULT_RULES_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    cleaned = {
        normalize_merchant(key): value
        for key, value in sorted(rules.items())
        if normalize_merchant(key) and value in EXPENSE_CATEGORIES
    }
    target.write_text(json.dumps(cleaned, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def remember_rule(description: object, category: str, path: Path | None = None) -> dict[str, str]:
    """Learn (or update) one merchant rule and return the full rule set."""
    merchant = normalize_merchant(description)
    if not merchant:
        raise ValueError("Cannot learn a rule from an empty description")
    if category not in EXPENSE_CATEGORIES:
        raise ValueError(f"Unknown category: {category!r}")

    rules = load_rules(path)
    rules[merchant] = category
    save_rules(rules, path)
    return rules


def forget_rule(description: object, path: Path | None = None) -> dict[str, str]:
    merchant = normalize_merchant(description)
    rules = load_rules(path)
    rules.pop(merchant, None)
    save_rules(rules, path)
    return rules


def learn_from_corrections(
    corrections: Mapping[object, str], path: Path | None = None, now: datetime | None = None
) -> dict[str, str]:
    """Learn several corrections at once (description -> category)."""
    rules = load_rules(path)
    for description, category in corrections.items():
        merchant = normalize_merchant(description)
        if merchant and category in EXPENSE_CATEGORIES:
            rules[merchant] = category
    save_rules(rules, path)
    return rules


__all__ = [
    "DEFAULT_RULES_PATH",
    "forget_rule",
    "learn_from_corrections",
    "load_rules",
    "remember_rule",
    "save_rules",
]
