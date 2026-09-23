# budget-track

Local Streamlit spending tracker over an Excel workbook. Paste Notes-style lines,
review them, confirm, and they land in a standardized `Transactions` sheet that the
dashboard, categories and insights all read from.

## Run

```bash
python3 -m streamlit run app.py
```

Tabs: **Dashboard**, **Add Transactions**, **Transactions / Manage**, **Historical
Review**, **Insights**, **Settings**.

## Workbooks

| Path | Role |
| --- | --- |
| `/Users/chrislowzx/Downloads/Expenses/Chris 2023-2025 Spendings.xlsx` | original history, **read-only** |
| `outputs/Chris 2023-2025 Spendings - tracker copy.xlsx` | the tracker the app reads and writes |
| `outputs/backups/` | timestamped copies made before every write |

The original workbook is never opened for writing, by the app or by any script.

## Transaction schema

`Date | Description | Amount | Type | Category | Source Line | Source Period |
Source Sheet | Source Reference | Date Precision | Added At`

Amounts are stored positive. `Type` is one of Expense, Income, Rent, Investment, and
net cash flow is `Income - Expenses - Rent - Investments`. `Category` applies to
Expense rows only.

`Date Precision` records how well the date is known:

| Value | Meaning |
| --- | --- |
| `Exact` | the source had a real transaction date |
| `Month` | only a month was known (e.g. "Rent+ Aug."); stored as the 1st |
| `Period` | only a school term was known; stored as that block's midpoint as a sortable stand-in |
| `Unknown` | no date information; never auto-migrated |

Month-level analytics use only `Exact` and `Month` rows so period stand-ins cannot
invent a spike.

## One-time historical migration

```bash
python3 scripts/migrate_historical.py            # dry run, writes reports only
python3 scripts/migrate_historical.py --apply    # backs up the tracker, then appends
```

Only `Ready`/high-confidence rows are migrated. Formula amounts, negative amounts,
undatable rows and anything outside a recognized transaction block go to
`outputs/historical_migration_review.csv` for you to look at. Re-running migrates
nothing new: a row's identity is its source sheet + cell.

Reports: `outputs/historical_migration_report.md`, `...report.csv`, and a timestamped
archive of each applied run.

A block that holds no dates at all (the Investments block) borrows the midpoint of the
dated rows on its own sheet and keeps `Date Precision = Period`.

## Auditing the migration

```bash
python3 scripts/reconcile_historical.py
```

Compares the original workbook with the tracker per Source Period and Type - raw cell
sums, extracted candidates and rows actually present - and writes
`outputs/historical_reconciliation.{csv,md}`, including every row held back from
migration grouped by reason. Read-only apart from those two report files.

## Historical Review

The **Historical Review** tab is a one-time queue of the rows the migration held back
(formula amounts, credits recorded as negatives, sidebar values). For each row it shows
the source period, sheet, cell, raw source text, original amount, why it was held, and
a prefilled suggestion; formula rows also show the formula and the cells it references.

Four actions per row: **Approve** (writes the row shown, after a backup, with its
provenance and date precision intact), edit any field and then approve, **Ignore
permanently**, or simply leave it alone. Nothing is ever approved automatically -
suggestions are marked *suggested* only where the source is unambiguous (a negative in
a Rent column is a reimbursement, a sidebar entry named after a brokerage is an
investment); everything else says *needs judgement*.

Decisions live in `data/historical_review.json`. An approved row also stops appearing
because its source cell is now in the tracker, so reloading is idempotent and approving
twice writes one row. Ignored rows can be restored from the tab.

## Categories

```bash
python3 scripts/categorize_transactions.py             # fill blank categories
python3 scripts/categorize_transactions.py --overwrite # redo every Expense row
```

Rules live in `spending_tracker/categories.py` (deterministic, case-insensitive,
longest match wins). Corrections you make in the app are remembered in
`data/merchant_rules.json` and override the built-in rules.

## Local config

| File | Contents |
| --- | --- |
| `data/merchant_rules.json` | learned merchant -> category rules |
| `data/settings.json` | optional monthly Expense budget |
| `data/historical_review.json` | approve / ignore decisions from the Historical Review tab |
| `outputs/transaction_audit.log` | one JSON line per edit/delete/save |

## Optional AI (off by default)

`spending_tracker/ai_categorizer.py` is a seam, not a dependency: deterministic rules
always run first, and a provider is only consulted for merchants that stay `Other`,
and only when `SPENDING_TRACKER_AI=1` plus an API key is set in the environment. The
bundled provider declines every request, so no network call happens. API keys are
never read from or written to this project.

## Tests

```bash
python3 -m pytest -q
```

Tests only ever touch workbooks built under `tmp_path`; they never read or write the
real workbooks or `data/` config.
