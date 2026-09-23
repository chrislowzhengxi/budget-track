"""Optional AI fallback for merchants the deterministic rules cannot place.

The tracker works fully without this module.  It exists so that AI categorisation
can be added later without touching the rest of the app, and it is wired to be
inert by default:

* deterministic rules (built-in + learned) always run first;
* the AI provider is only consulted for transactions that came back as ``Other``;
* nothing happens unless ``SPENDING_TRACKER_AI=1`` **and** an API key is present in
  the environment - keys are never read from or written to source or config files;
* any error, timeout or unexpected answer falls back to ``Other``;
* only the merchant description is ever passed to a provider, never dates, amounts
  or any other part of the transaction history.

The bundled provider is a stub: :class:`DisabledProvider` always declines.  Point
``provider`` at your own implementation of :class:`CategoryProvider` to enable it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from typing import Protocol, runtime_checkable

from spending_tracker.categories import CATEGORY_OTHER, EXPENSE_CATEGORIES, categorize


ENABLE_ENV_VAR = "SPENDING_TRACKER_AI"
API_KEY_ENV_VARS = ("ANTHROPIC_API_KEY", "SPENDING_TRACKER_AI_KEY")


@runtime_checkable
class CategoryProvider(Protocol):
    """Suggests a category for a merchant name, or None to decline."""

    def suggest(self, merchant: str, categories: Sequence[str]) -> str | None:  # pragma: no cover - protocol
        ...


class DisabledProvider:
    """Default provider: never suggests anything, never makes a network call."""

    def suggest(self, merchant: str, categories: Sequence[str]) -> str | None:
        return None


def ai_enabled(env: Mapping[str, str] | None = None) -> bool:
    """True only when explicitly switched on *and* a key is available."""
    environment = env if env is not None else os.environ
    if str(environment.get(ENABLE_ENV_VAR, "")).strip().lower() not in {"1", "true", "yes", "on"}:
        return False
    return any(str(environment.get(name, "")).strip() for name in API_KEY_ENV_VARS)


def categorize_with_fallback(
    description: object,
    transaction_type: object = "Expense",
    user_rules: Mapping[str, str] | None = None,
    provider: CategoryProvider | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Deterministic categorisation, with an optional AI second opinion for ``Other``."""
    category = categorize(description, transaction_type, user_rules)
    if category != CATEGORY_OTHER:
        return category
    if not ai_enabled(env):
        return category

    try:
        suggestion = (provider or DisabledProvider()).suggest(str(description or ""), EXPENSE_CATEGORIES)
    except Exception:  # noqa: BLE001 - a provider failure must never break saving
        return CATEGORY_OTHER
    if isinstance(suggestion, str) and suggestion in EXPENSE_CATEGORIES:
        return suggestion
    return CATEGORY_OTHER


__all__ = [
    "API_KEY_ENV_VARS",
    "ENABLE_ENV_VAR",
    "CategoryProvider",
    "DisabledProvider",
    "ai_enabled",
    "categorize_with_fallback",
]
