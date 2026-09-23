"""Deterministic expense categorisation.

Category is kept separate from Type: only ``Expense`` rows get a category, because
Rent, Income and Investment are already their own buckets on the dashboard.

Matching is case-insensitive, punctuation-insensitive and whole-word, and the
*longest* matching pattern wins, so "whole foods + mcd" lands in Groceries while
"grand palace + mcd" lands in Dining, and a specific rule such as "costco meds"
beats the generic "costco".  No LLM is involved.
"""

from __future__ import annotations

from collections.abc import Mapping
import re

import pandas as pd


CATEGORY_OTHER = "Other"

# Ten standard categories plus Subscriptions, which the real history justifies
# (repeating ESPN / Claude / Capital One charges).
EXPENSE_CATEGORIES = [
    "Dining",
    "Groceries",
    "Transportation",
    "Shopping",
    "Health",
    "Entertainment",
    "Travel",
    "Utilities",
    "Education",
    "Subscriptions",
    CATEGORY_OTHER,
]

# (pattern, category).  Patterns are matched as whole words against the normalised
# description; add a longer pattern to override a shorter one.
MERCHANT_RULES: tuple[tuple[str, str], ...] = (
    # Transportation
    ("uber", "Transportation"),
    ("ubers", "Transportation"),
    ("lyft", "Transportation"),
    ("mbta", "Transportation"),
    ("divvy", "Transportation"),
    ("bluebike", "Transportation"),
    ("blue bike", "Transportation"),
    ("metra", "Transportation"),
    ("ventra", "Transportation"),
    ("t train", "Transportation"),
    ("train", "Transportation"),
    ("bus", "Transportation"),
    ("taxi", "Transportation"),
    ("parking", "Transportation"),
    ("gas", "Transportation"),
    ("toll", "Transportation"),
    ("car rental", "Transportation"),
    # Groceries
    ("whole foods", "Groceries"),
    ("trader joe", "Groceries"),
    ("trader joes", "Groceries"),
    ("costco", "Groceries"),
    ("costco groceries", "Groceries"),
    ("weee", "Groceries"),
    ("wee", "Groceries"),
    ("h mart", "Groceries"),
    ("88 mart", "Groceries"),
    ("88 market", "Groceries"),
    ("jewel", "Groceries"),
    ("aldi", "Groceries"),
    ("safeway", "Groceries"),
    ("kroger", "Groceries"),
    ("grocer", "Groceries"),
    ("groceries", "Groceries"),
    ("hp produce", "Groceries"),
    ("produce", "Groceries"),
    ("vegetables", "Groceries"),
    ("milk", "Groceries"),
    ("bread", "Groceries"),
    ("target milk", "Groceries"),
    # Dining
    ("mcd", "Dining"),
    ("mcdonald", "Dining"),
    ("mcdonalds", "Dining"),
    ("taco bell", "Dining"),
    ("tacos", "Dining"),
    ("chipotle", "Dining"),
    ("starbucks", "Dining"),
    ("dunkin", "Dining"),
    ("dunkins", "Dining"),
    ("tatte", "Dining"),
    ("sweetgreen", "Dining"),
    ("panda express", "Dining"),
    ("poke", "Dining"),
    ("burrito", "Dining"),
    ("buritto", "Dining"),
    ("beach", "Dining"),  # "Burrito Beach", abbreviated to "Beach" in the workbook
    ("quesadilla", "Dining"),
    ("quaesadilla", "Dining"),
    ("quantum", "Dining"),
    ("hutch", "Dining"),
    ("medici", "Dining"),
    ("malatang", "Dining"),
    ("dim sum", "Dining"),
    ("hotpot", "Dining"),
    ("ramen", "Dining"),
    ("noodles", "Dining"),
    ("pho", "Dining"),
    ("sushi", "Dining"),
    ("boba", "Dining"),
    ("tea", "Dining"),
    ("coffee", "Dining"),
    ("latte", "Dining"),
    ("croissant", "Dining"),
    ("donut", "Dining"),
    ("donuts", "Dining"),
    ("bagel", "Dining"),
    ("cake", "Dining"),
    ("levain", "Dining"),
    ("magnolia", "Dining"),
    ("canes", "Dining"),
    ("culver", "Dining"),
    ("culvers", "Dining"),
    ("wendy", "Dining"),
    ("whataburger", "Dining"),
    ("arby", "Dining"),
    ("waffle house", "Dining"),
    ("shake shack", "Dining"),
    ("wingstop", "Dining"),
    ("halal guys", "Dining"),
    ("chicken rice", "Dining"),
    ("chicken curry", "Dining"),
    ("asada", "Dining"),
    ("empanada", "Dining"),
    ("lobster", "Dining"),
    ("bbq", "Dining"),
    ("pub", "Dining"),
    ("cafe", "Dining"),
    ("café", "Dining"),
    ("restaurant", "Dining"),
    ("grubhub", "Dining"),
    ("doordash", "Dining"),
    ("fantuan", "Dining"),
    ("paks", "Dining"),
    ("strings", "Dining"),
    ("kikuya", "Dining"),
    ("tary", "Dining"),
    ("small cheval", "Dining"),
    ("elephant castle", "Dining"),
    ("eto", "Dining"),
    ("el bueno", "Dining"),
    ("grill", "Dining"),
    ("kabob", "Dining"),
    # Health
    ("cvs", "Health"),
    ("walgreens", "Health"),
    ("pharmacy", "Health"),
    ("meds", "Health"),
    ("costco meds", "Health"),
    ("tylenol", "Health"),
    ("covid", "Health"),
    ("eye drop", "Health"),
    ("eyedrop", "Health"),
    ("polident", "Health"),
    ("aveeno", "Health"),
    ("moisturizer", "Health"),
    ("insect repellent", "Health"),
    ("health insurance", "Health"),
    ("dentist", "Health"),
    ("doctor", "Health"),
    ("clinic", "Health"),
    ("haircut", "Health"),
    # Shopping
    ("amazon", "Shopping"),
    ("target", "Shopping"),
    ("temu", "Shopping"),
    ("walmart", "Shopping"),
    ("ali express", "Shopping"),
    ("aliexpress", "Shopping"),
    ("lululemon", "Shopping"),
    ("sephora", "Shopping"),
    ("dick s", "Shopping"),
    ("uniqlo", "Shopping"),
    ("ikea", "Shopping"),
    ("staples", "Shopping"),
    ("macbook", "Shopping"),
    ("jo malone", "Shopping"),
    ("phone case", "Shopping"),
    ("phone stand", "Shopping"),
    ("wallet", "Shopping"),
    ("jerseys", "Shopping"),
    ("merch", "Shopping"),
    ("air fryer", "Shopping"),
    ("air purifier", "Shopping"),
    ("brita", "Shopping"),
    ("dutch oven", "Shopping"),
    ("monitor", "Shopping"),
    ("batteries", "Shopping"),
    ("soap", "Shopping"),
    ("tide pods", "Shopping"),
    ("clorox", "Shopping"),
    ("samsonite", "Shopping"),
    ("usps", "Shopping"),
    ("postcards", "Shopping"),
    # Entertainment
    ("ktv", "Entertainment"),
    ("cso", "Entertainment"),
    ("bulls", "Entertainment"),
    ("nuggets", "Entertainment"),
    ("blackhawks", "Entertainment"),
    ("united center", "Entertainment"),
    ("harry potter", "Entertainment"),
    ("galloping ghost", "Entertainment"),
    ("flyover", "Entertainment"),
    ("ice skate", "Entertainment"),
    ("bet365", "Entertainment"),
    ("draft kings", "Entertainment"),
    ("oac", "Entertainment"),
    ("camping", "Entertainment"),
    ("museum", "Entertainment"),
    ("concert", "Entertainment"),
    ("movie", "Entertainment"),
    ("theater", "Entertainment"),
    # Travel
    ("flight", "Travel"),
    ("airline", "Travel"),
    ("airlines", "Travel"),
    ("hotel", "Travel"),
    ("airbnb", "Travel"),
    ("hostel", "Travel"),
    ("amtrak", "Travel"),
    ("baggage", "Travel"),
    ("oac trip", "Travel"),
    # Utilities
    ("utils", "Utilities"),
    ("utilities", "Utilities"),
    ("electric", "Utilities"),
    ("comed", "Utilities"),
    ("internet", "Utilities"),
    ("wifi", "Utilities"),
    ("phone bill", "Utilities"),
    ("water bill", "Utilities"),
    ("gas bill", "Utilities"),
    # Education
    ("course", "Education"),
    ("tuition", "Education"),
    ("textbook", "Education"),
    ("school", "Education"),
    ("registration fee", "Education"),
    # Subscriptions
    ("espn", "Subscriptions"),
    ("claude", "Subscriptions"),
    ("netflix", "Subscriptions"),
    ("spotify", "Subscriptions"),
    ("chatgpt", "Subscriptions"),
    ("icloud", "Subscriptions"),
    ("hulu", "Subscriptions"),
    ("subscription", "Subscriptions"),
    ("capital one", "Subscriptions"),
)


def normalize_merchant(description: object) -> str:
    """Lowercase, strip punctuation, collapse whitespace: the matching key."""
    text = "" if description is None else str(description)
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-zÀ-ɏ]+", " ", text.lower())).strip()


def _compiled_rules() -> list[tuple[str, str, re.Pattern[str]]]:
    return [
        (pattern, category, re.compile(rf"(?<!\w){re.escape(pattern)}(?!\w)"))
        for pattern, category in MERCHANT_RULES
    ]


_RULES = _compiled_rules()


def _match(text: str, rules: list[tuple[str, str, re.Pattern[str]]]) -> str | None:
    best: tuple[int, str] | None = None
    for pattern, category, compiled in rules:
        if compiled.search(text) and (best is None or len(pattern) > best[0]):
            best = (len(pattern), category)
    return best[1] if best else None


def _match_user_rules(text: str, user_rules: Mapping[str, str]) -> str | None:
    best: tuple[int, str] | None = None
    for key, category in user_rules.items():
        normalized_key = normalize_merchant(key)
        if not normalized_key or not category:
            continue
        if re.search(rf"(?<!\w){re.escape(normalized_key)}(?!\w)", text) and (
            best is None or len(normalized_key) > best[0]
        ):
            best = (len(normalized_key), category)
    return best[1] if best else None


def categorize(
    description: object,
    transaction_type: object = "Expense",
    user_rules: Mapping[str, str] | None = None,
) -> str:
    """Category for one transaction.

    Non-Expense types get an empty category.  User rules (learned from manual
    corrections) are checked before the built-in rules; anything unmatched is ``Other``.
    """
    if str(transaction_type).strip() != "Expense":
        return ""

    text = normalize_merchant(description)
    if not text:
        return CATEGORY_OTHER

    if user_rules:
        learned = _match_user_rules(text, user_rules)
        if learned:
            return learned

    return _match(text, _RULES) or CATEGORY_OTHER


def categorize_frame(
    df: pd.DataFrame,
    overwrite: bool = False,
    user_rules: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Fill the Category column.

    Existing non-blank categories are kept unless ``overwrite`` is True, so a manual
    correction survives re-categorisation.  Non-Expense rows are always blanked.
    """
    if df is None or df.empty:
        return df.copy() if df is not None else df

    frame = df.copy()
    if "Category" not in frame.columns:
        frame["Category"] = ""
    frame["Category"] = frame["Category"].fillna("").astype(str).str.strip()

    is_expense = frame["Type"].astype(str).str.strip().eq("Expense")
    frame.loc[~is_expense, "Category"] = ""

    target = is_expense if overwrite else is_expense & frame["Category"].eq("")
    if target.any():
        frame.loc[target, "Category"] = [
            categorize(description, "Expense", user_rules)
            for description in frame.loc[target, "Description"]
        ]
    return frame


__all__ = [
    "CATEGORY_OTHER",
    "EXPENSE_CATEGORIES",
    "MERCHANT_RULES",
    "categorize",
    "categorize_frame",
    "normalize_merchant",
]
