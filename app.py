"""Local Streamlit spending tracker.

Reads and writes only the tracker copy of the workbook; the original historical
workbook is read-only input for the one-time migration (scripts/migrate_historical.py).
"""

from __future__ import annotations

from datetime import date
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from spending_tracker.categories import EXPENSE_CATEGORIES, categorize, categorize_frame
from spending_tracker.dashboard import (
    category_summary,
    category_trend,
    expense_metrics,
    filter_by_period,
    filter_transactions,
    monthly_expense_trend,
    monthly_summary,
    period_options,
    period_summary,
    precision_breakdown,
    recent_transactions,
    resolve_date_range,
    summarize_transactions,
)
from spending_tracker.duplicates import find_duplicates
from spending_tracker.excel_store import (
    append_transactions,
    backup_workbook,
    ensure_workbook_copy,
    load_transactions,
    workbook_last_updated,
)
from spending_tracker.export import export_filename, transactions_csv
from spending_tracker.insights import (
    budget_status,
    find_recurring,
    load_settings,
    recurring_frame,
    set_monthly_budget,
)
from spending_tracker.ai_categorizer import ENABLE_ENV_VAR, ai_enabled
from spending_tracker.manage import (
    EDITABLE_COLUMNS,
    delete_transactions,
    read_audit,
    recategorize,
    save_transactions,
    search_transactions,
    update_transaction,
)
from spending_tracker.merchant_rules import (
    DEFAULT_RULES_PATH,
    forget_rule,
    learn_from_corrections,
    load_rules,
)
from spending_tracker.parser import VALID_TYPES, parse_lines
from spending_tracker.paths import DEFAULT_SOURCE_WORKBOOK, DEFAULT_TRACKER_WORKBOOK
from spending_tracker.review import (
    CONFIDENCE_HIGH,
    DEFAULT_REVIEW_STATE_PATH,
    ReviewError,
    approve_item,
    build_queue,
    forget_decision,
    ignore_item,
    queue_frame,
)
from spending_tracker.schema import DATE_PRECISIONS, PRECISION_PERIOD, PRECISION_UNKNOWN


SOURCE_WORKBOOK = Path(os.environ.get("SPENDING_SOURCE_WORKBOOK", str(DEFAULT_SOURCE_WORKBOOK)))
DEFAULT_OUTPUT = Path(os.environ.get("SPENDING_TRACKER_WORKBOOK", str(DEFAULT_TRACKER_WORKBOOK)))
RULES_PATH = Path(os.environ.get("SPENDING_TRACKER_RULES", str(DEFAULT_RULES_PATH)))
SETTINGS_PATH = Path(os.environ.get("SPENDING_TRACKER_SETTINGS", "data/settings.json"))
REVIEW_STATE_PATH = Path(os.environ.get("SPENDING_TRACKER_REVIEW_STATE", str(DEFAULT_REVIEW_STATE_PATH)))

DATE_FILTERS = ["All time", "This month", "Last month", "This year", "Custom date range"]

st.set_page_config(page_title="Spending Tracker", layout="wide")
st.title("Spending Tracker")


@st.cache_data(show_spinner=False)
def _load_dashboard_data(path_text: str, rules_signature: str) -> pd.DataFrame:
    """Tracker rows with blank categories filled in for display."""
    return categorize_frame(load_transactions(Path(path_text)), user_rules=load_rules(RULES_PATH))


def _refresh() -> None:
    _load_dashboard_data.clear()


with st.sidebar:
    st.header("Workbook")
    source_path = Path(st.text_input("Original workbook (read-only)", value=str(SOURCE_WORKBOOK)))
    output_path = Path(st.text_input("Tracker workbook", value=str(DEFAULT_OUTPUT)))
    default_date = st.date_input("Default date", value=date.today())
    updated_at = workbook_last_updated(output_path)
    st.caption(
        f"Tracker last updated {updated_at:%Y-%m-%d %H:%M}" if updated_at else "Tracker not created yet."
    )

user_rules = load_rules(RULES_PATH)
settings = load_settings(SETTINGS_PATH)
transactions = _load_dashboard_data(str(output_path), repr(sorted(user_rules.items())))

(
    dashboard_tab,
    add_tab,
    manage_tab,
    review_tab,
    insights_tab,
    settings_tab,
) = st.tabs(
    [
        "Dashboard",
        "Add Transactions",
        "Transactions / Manage",
        "Historical Review",
        "Insights",
        "Settings",
    ]
)


# --- Dashboard --------------------------------------------------------------------

with dashboard_tab:
    filter_col, period_col, recent_col = st.columns([3, 1, 1])
    with filter_col:
        date_filter = st.segmented_control("Date range", options=DATE_FILTERS, default="All time")
    periods = period_options(transactions)
    with period_col:
        period_choice = (
            st.selectbox("School period", options=["All periods", *periods]) if periods else "All periods"
        )
    with recent_col:
        recent_choice = st.selectbox("Recent rows", options=["Latest 10", "Latest 25", "All"], index=0)

    custom_start = None
    custom_end = None
    if date_filter == "Custom date range":
        custom_start, custom_end = st.date_input(
            "Custom period", value=(date.today().replace(day=1), date.today())
        )

    scoped = filter_by_period(transactions, None if period_choice == "All periods" else period_choice)
    selected_range = resolve_date_range(date_filter or "All time", date.today(), custom_start, custom_end)
    filtered_transactions = filter_transactions(scoped, selected_range)
    summary = summarize_transactions(filtered_transactions)

    metric_cols = st.columns(5)
    for column, label in zip(
        metric_cols, ["Expenses", "Income", "Rent", "Investments", "Net cash flow"], strict=True
    ):
        column.metric(label, f"${summary[label]:,.2f}")

    status = budget_status(filtered_transactions, date.today(), settings)
    if status:
        st.subheader("Monthly Expense Budget")
        budget_cols = st.columns(4)
        budget_cols[0].metric("Budget", f"${status['budget']:,.2f}")
        budget_cols[1].metric("Spent this month", f"${status['spent']:,.2f}")
        budget_cols[2].metric("Remaining", f"${status['remaining']:,.2f}")
        budget_cols[3].metric("Used", f"{status['percent_used']:.1f}%")
        st.progress(min(status["percent_used"] / 100, 1.0))
        if status["over_budget"]:
            st.warning(f"Over budget for {status['month']} by ${-status['remaining']:,.2f}.")
        st.caption("Counting types: " + ", ".join(status["types"]))

    metrics = expense_metrics(filtered_transactions, date.today())
    precision = precision_breakdown(filtered_transactions)
    coarse_rows = sum(count for name, count in precision.items() if name not in {"Exact", "Month"})

    st.subheader("Expense Insights")
    insight_cols = st.columns(4)
    insight_cols[0].metric("Average month", f"${metrics['average_monthly']:,.2f}")
    insight_cols[1].metric(
        "Highest month",
        f"${metrics['highest_month_amount']:,.2f}",
        help=f"Month: {metrics['highest_month']}" if metrics["highest_month"] else None,
    )
    insight_cols[2].metric(
        "This month",
        f"${metrics['current_month']:,.2f}",
        delta=(
            None if metrics["month_over_month"] is None else f"{metrics['month_over_month']:,.2f} vs last month"
        ),
        delta_color="inverse",
    )
    insight_cols[3].metric("Discretionary (excl. Rent & Investments)", f"${metrics['discretionary']:,.2f}")
    st.caption(
        f"Monthly figures use the {metrics['months_counted']} month(s) with Exact or Month date precision."
        + (
            f" {coarse_rows} migrated row(s) only have period-level dates and stay out of monthly figures."
            if coarse_rows
            else ""
        )
    )

    categories = category_summary(filtered_transactions)
    cat_left, cat_right = st.columns([2, 3])
    with cat_left:
        st.subheader("Spending by Category")
        if categories.empty:
            st.info("No expense transactions in this range.")
        else:
            st.dataframe(categories, width="stretch", hide_index=True)
    with cat_right:
        st.subheader("Category Totals")
        if categories.empty:
            st.info("Nothing to chart yet.")
        else:
            st.bar_chart(categories.set_index("Category")["Amount"])

    trend = monthly_expense_trend(filtered_transactions)
    trend_left, trend_right = st.columns(2)
    with trend_left:
        st.subheader("Monthly Expense Trend")
        if trend.empty:
            st.info("No expense history to chart yet.")
        else:
            st.line_chart(trend.set_index("Month")["Expenses"])
    with trend_right:
        st.subheader("Top Categories Over Time")
        category_over_time = category_trend(filtered_transactions, top_n=5)
        if category_over_time.empty or len(category_over_time.columns) < 2:
            st.info("Not enough history for a category trend yet.")
        else:
            st.line_chart(category_over_time.set_index("Month"))

    monthly = monthly_summary(filtered_transactions)
    st.subheader("Monthly Summary")
    if monthly.empty:
        st.info("No transactions found for this date range.")
    else:
        st.dataframe(monthly, width="stretch", hide_index=True)

    if periods:
        st.subheader("By School Period")
        st.dataframe(period_summary(scoped), width="stretch", hide_index=True)

    st.subheader("Recent Transactions")
    limit = {"Latest 10": 10, "Latest 25": 25, "All": None}[recent_choice]
    recent = recent_transactions(
        filtered_transactions,
        limit,
        columns=["Date", "Description", "Amount", "Type", "Category", "Source Period", "Date Precision"],
    )
    if recent.empty:
        st.info("No transactions to show yet.")
    else:
        st.dataframe(recent, width="stretch", hide_index=True)


# --- Add transactions -------------------------------------------------------------

with add_tab:
    st.caption("Paste Notes-style lines, check the preview, then confirm. Nothing is written until you do.")
    sample = "uber 12\ntatte 8.50\nwhole foods 31\nTA (695.56)\nrent 1800\ninvestment 500"
    raw_text = st.text_area("Transactions", value=sample, height=200)

    if st.button("Parse", type="primary"):
        parsed = parse_lines(raw_text, default_date, user_rules)
        st.session_state["transactions_df"] = pd.DataFrame([item.as_dict() for item in parsed])
        st.session_state["duplicates_acknowledged"] = False

    df = st.session_state.get("transactions_df")

    if df is not None and not df.empty:
        st.subheader("Preview")
        edited = st.data_editor(
            df,
            num_rows="dynamic",
            width="stretch",
            column_config={
                "Date": st.column_config.DateColumn("Date", required=True),
                "Description": st.column_config.TextColumn("Description", required=True),
                "Amount": st.column_config.NumberColumn(
                    "Amount", min_value=0.0, step=0.01, format="%.2f", required=True
                ),
                "Type": st.column_config.SelectboxColumn("Type", options=VALID_TYPES, required=True),
                "Category": st.column_config.SelectboxColumn("Category", options=["", *EXPENSE_CATEGORIES]),
                "Status": st.column_config.SelectboxColumn(
                    "Status", options=["Ready", "Needs review"], required=True
                ),
                "Note": st.column_config.TextColumn("Note", disabled=True),
                "Source Line": st.column_config.TextColumn("Source Line", disabled=True),
            },
            disabled=["Note", "Source Line"],
            hide_index=True,
        )
        st.session_state["transactions_df"] = edited

        needs_review = (
            edited["Status"].ne("Ready").any()
            or edited[["Date", "Description", "Amount", "Type"]].isna().any().any()
        )
        if needs_review:
            st.warning("Some rows need review. Correct them and set Status to Ready, or delete the row.")

        warnings = find_duplicates(edited, transactions)
        if warnings:
            st.warning(
                "Possible duplicate(s):\n\n"
                + "\n".join(f"- Row {item.row_index + 1}: {item.message}" for item in warnings)
            )
            acknowledged = st.checkbox(
                "These are genuinely separate transactions - save anyway",
                key="duplicates_acknowledged",
            )
        else:
            acknowledged = True

        remember_preview = st.checkbox(
            "Remember any category I changed here for next time", value=True, key="remember_preview"
        )
        blocked = needs_review or (bool(warnings) and not acknowledged)
        if st.button("Confirm / Add to Excel", disabled=blocked):
            if not output_path.exists() and not source_path.exists():
                st.error(f"Neither the tracker nor the original workbook exists: {source_path}")
            else:
                destination = ensure_workbook_copy(source_path, output_path)
                ready_rows = edited[
                    ["Date", "Description", "Amount", "Type", "Category", "Source Line"]
                ].to_dict("records")
                count = append_transactions(destination, ready_rows)
                if remember_preview:
                    # A category the user changed by hand becomes a rule, so the next
                    # transaction from that merchant defaults to it.
                    corrections = {
                        str(row["Description"]): str(row["Category"])
                        for row in ready_rows
                        if row["Type"] == "Expense"
                        and row["Category"]
                        and row["Category"] != categorize(row["Description"], "Expense", user_rules)
                    }
                    if corrections:
                        learn_from_corrections(corrections, RULES_PATH)
                _refresh()
                st.success(f"Added {count} transaction(s) to {destination}")
                st.session_state.pop("transactions_df", None)
    else:
        st.info("Paste transactions and click Parse.")


# --- Manage -----------------------------------------------------------------------

with manage_tab:
    stored = categorize_frame(load_transactions(output_path), user_rules=user_rules)
    if stored.empty:
        st.info("No transactions in the tracker yet.")
    else:
        search_cols = st.columns([2, 1, 1])
        with search_cols[0]:
            search_text = st.text_input("Search description or source line", value="")
        with search_cols[1]:
            type_filter = st.multiselect("Type", options=VALID_TYPES, default=[])
        with search_cols[2]:
            category_filter = st.multiselect("Category", options=EXPENSE_CATEGORIES, default=[])

        range_cols = st.columns(2)
        with range_cols[0]:
            use_dates = st.checkbox("Filter by date range", value=False)
        start_date = end_date = None
        if use_dates:
            with range_cols[1]:
                start_date, end_date = st.date_input(
                    "Between", value=(date.today().replace(day=1), date.today())
                )

        matches = search_transactions(
            stored,
            text=search_text,
            types=type_filter or None,
            categories=category_filter or None,
            start=start_date,
            end=end_date,
        ).sort_values("Date", ascending=False)

        st.caption(f"{len(matches)} of {len(stored)} transaction(s) match.")
        visible = matches.head(200)
        if visible.empty:
            st.info("Nothing matches those filters.")
        else:
            editor_frame = visible[EDITABLE_COLUMNS].copy()
            editor_frame.insert(0, "Delete", False)
            edited_rows = st.data_editor(
                editor_frame,
                width="stretch",
                column_config={
                    "Delete": st.column_config.CheckboxColumn("Delete"),
                    "Date": st.column_config.DateColumn("Date"),
                    "Description": st.column_config.TextColumn("Description"),
                    "Amount": st.column_config.NumberColumn("Amount", min_value=0.01, step=0.01, format="%.2f"),
                    "Type": st.column_config.SelectboxColumn("Type", options=VALID_TYPES),
                    "Category": st.column_config.SelectboxColumn("Category", options=["", *EXPENSE_CATEGORIES]),
                },
                key="manage_editor",
            )

            edits: dict[object, dict[str, object]] = {}
            for index in edited_rows.index:
                changes = {}
                for column in EDITABLE_COLUMNS:
                    new_value = edited_rows.loc[index, column]
                    old_value = stored.loc[index, column]
                    if pd.isna(new_value) and pd.isna(old_value):
                        continue
                    if str(new_value) != str(old_value):
                        changes[column] = new_value
                if changes:
                    edits[index] = changes
            to_delete = [index for index in edited_rows.index if bool(edited_rows.loc[index, "Delete"])]

            if edits:
                st.info(f"{len(edits)} edit(s) pending.")
            if to_delete:
                st.warning(f"{len(to_delete)} row(s) marked for deletion.")

            action_cols = st.columns(3)
            with action_cols[0]:
                learn = st.checkbox("Remember category corrections for this merchant", value=True)
            with action_cols[1]:
                save_edits = st.button("Save edits", disabled=not edits)
            with action_cols[2]:
                confirm_delete = st.checkbox("I want to delete the marked row(s)", value=False)
                delete_now = st.button("Delete marked", disabled=not (to_delete and confirm_delete))

            if save_edits and edits:
                updated = stored.copy()
                corrections: dict[str, str] = {}
                for index, changes in edits.items():
                    updated = update_transaction(updated, index, changes)
                    if "Category" in changes and str(updated.loc[index, "Type"]) == "Expense":
                        corrections[str(updated.loc[index, "Description"])] = str(changes["Category"])
                save_transactions(
                    output_path, updated, action="edit", details={"rows": len(edits)}
                )
                if learn and corrections:
                    learn_from_corrections(corrections, RULES_PATH)
                _refresh()
                st.success(f"Saved {len(edits)} edit(s).")
                st.rerun()

            if delete_now and to_delete:
                deleted = stored.loc[to_delete, ["Date", "Description", "Amount", "Type"]]
                remaining = delete_transactions(stored, to_delete)
                save_transactions(
                    output_path,
                    remaining,
                    action="delete",
                    details={"rows": len(to_delete), "deleted": deleted.astype(str).to_dict("records")},
                )
                _refresh()
                st.success(f"Deleted {len(to_delete)} transaction(s).")
                st.rerun()

        st.download_button(
            "Download all transactions as CSV",
            data=transactions_csv(stored),
            file_name=export_filename(),
            mime="text/csv",
        )


# --- Historical Review -------------------------------------------------------------

with review_tab:
    st.caption(
        "One-time queue of historical rows the migration held back. Nothing here is "
        "imported until you approve it, and the original workbook is never written to."
    )

    if not source_path.exists():
        st.error(f"Original workbook not found: {source_path}")
    else:

        @st.cache_data(show_spinner=False)
        def _load_review_queue(source_text: str, tracker_text: str, state_text: str, token: int):
            return build_queue(Path(source_text), Path(tracker_text), Path(state_text))

        token = st.session_state.get("review_token", 0)
        queue = _load_review_queue(
            str(source_path), str(output_path), str(REVIEW_STATE_PATH), token
        )
        summary = queue.summary
        session_approved = st.session_state.get("review_approved_this_session", 0)

        summary_cols = st.columns(4)
        summary_cols[0].metric("Unresolved", summary["unresolved"])
        summary_cols[1].metric("Approved this session", session_approved)
        summary_cols[2].metric("Ignored permanently", summary["ignored"])
        summary_cols[3].metric("Total unresolved amount", f"${summary['unresolved_amount']:,.2f}")
        st.caption(
            f"{summary['approved']} row(s) resolved in total, {summary['high_confidence']} unresolved "
            "row(s) carry a high-confidence suggestion. Leaving an item alone keeps it unresolved."
        )

        if not queue.unresolved:
            st.success("Nothing left to review.")
        else:
            only_suggested = st.checkbox(
                "Show only rows with a high-confidence suggestion", value=False, key="review_only_high"
            )
            items = [
                item
                for item in queue.unresolved
                if not only_suggested or item.suggestion.confidence == CONFIDENCE_HIGH
            ]
            st.dataframe(queue_frame(items), width="stretch", hide_index=True)

            for item in items:
                badge = "suggested" if item.suggestion.confidence == CONFIDENCE_HIGH else "needs judgement"
                with st.expander(f"{item.label}  ·  {item.item_id}  ·  {badge}"):
                    left, right = st.columns(2)
                    with left:
                        st.markdown(
                            f"**Source period** {item.source_period}  \n"
                            f"**Source sheet** {item.source_sheet}  \n"
                            f"**Source reference** {item.source_reference} "
                            f"(amount cell {item.amount_reference})  \n"
                            f"**Source text** `{item.source_line}`  \n"
                            f"**Original amount** "
                            + (
                                f"${item.original_amount:,.2f}"
                                if item.original_amount is not None
                                else "none in the cell"
                            )
                        )
                        st.markdown(f"**Held because** {item.reason}")
                        if item.formula:
                            st.markdown(f"**Formula** `{item.formula}`")
                            if item.formula_references:
                                st.markdown(
                                    "**Referenced cells** "
                                    + ", ".join(
                                        f"`{ref}` = {value}"
                                        for ref, value in item.formula_references.items()
                                    )
                                )
                    with right:
                        st.markdown(f"**Suggestion** {item.suggestion.rationale}")

                    suggestion = item.suggestion
                    field_cols = st.columns(3)
                    with field_cols[0]:
                        description = st.text_input(
                            "Description", value=suggestion.description, key=f"rv_desc_{item.item_id}"
                        )
                        amount = st.number_input(
                            "Amount",
                            min_value=0.0,
                            step=0.01,
                            format="%.2f",
                            value=float(suggestion.amount or 0.0),
                            key=f"rv_amount_{item.item_id}",
                        )
                    with field_cols[1]:
                        transaction_type = st.selectbox(
                            "Type",
                            options=VALID_TYPES,
                            index=VALID_TYPES.index(suggestion.transaction_type)
                            if suggestion.transaction_type in VALID_TYPES
                            else 0,
                            key=f"rv_type_{item.item_id}",
                        )
                        category_options = ["", *EXPENSE_CATEGORIES]
                        category = st.selectbox(
                            "Category (Expense only)",
                            options=category_options,
                            index=category_options.index(suggestion.category)
                            if suggestion.category in category_options
                            else 0,
                            key=f"rv_cat_{item.item_id}",
                        )
                    with field_cols[2]:
                        chosen_date = st.date_input(
                            "Date",
                            value=suggestion.transaction_date,
                            key=f"rv_date_{item.item_id}",
                        )
                        precision = st.selectbox(
                            "Date precision",
                            options=DATE_PRECISIONS,
                            index=DATE_PRECISIONS.index(suggestion.date_precision)
                            if suggestion.date_precision in DATE_PRECISIONS
                            else DATE_PRECISIONS.index(PRECISION_UNKNOWN),
                            key=f"rv_prec_{item.item_id}",
                        )

                    if chosen_date is None:
                        st.caption(
                            "Without a date this row will not appear in any dated view. "
                            f"Pick one, or leave precision as {PRECISION_UNKNOWN}."
                        )
                    elif precision == PRECISION_PERIOD:
                        st.caption(
                            "Period precision: the date is a documented stand-in for "
                            f"'{item.source_period}', not a real transaction date."
                        )

                    action_cols = st.columns([1, 1, 2])
                    with action_cols[0]:
                        approve = st.button("Approve", key=f"rv_ok_{item.item_id}", type="primary")
                    with action_cols[1]:
                        skip = st.button("Ignore permanently", key=f"rv_no_{item.item_id}")
                    with action_cols[2]:
                        note = st.text_input(
                            "Note (optional, stored with the decision)", value="", key=f"rv_note_{item.item_id}"
                        )

                    if approve:
                        try:
                            result = approve_item(
                                item,
                                output_path,
                                overrides={
                                    "Description": description,
                                    "Amount": amount,
                                    "Type": transaction_type,
                                    "Category": category,
                                    "Date": chosen_date,
                                    "Date Precision": precision,
                                },
                                state_path=REVIEW_STATE_PATH,
                            )
                        except ReviewError as error:
                            st.error(str(error))
                        else:
                            st.session_state["review_approved_this_session"] = session_approved + (
                                1 if result["imported"] else 0
                            )
                            st.session_state["review_token"] = token + 1
                            _refresh()
                            _load_review_queue.clear()
                            if result["duplicate"]:
                                st.warning(result["message"])
                            else:
                                st.success(result["message"])
                            st.rerun()

                    if skip:
                        ignore_item(item, output_path, note=note, state_path=REVIEW_STATE_PATH)
                        st.session_state["review_token"] = token + 1
                        _load_review_queue.clear()
                        st.success(f"{item.item_id} will stay out of the tracker.")
                        st.rerun()

        if queue.ignored:
            with st.expander(f"Ignored permanently ({len(queue.ignored)})"):
                st.dataframe(queue_frame(queue.ignored), width="stretch", hide_index=True)
                restore = st.selectbox(
                    "Put one back in the queue",
                    options=["", *[item.item_id for item in queue.ignored]],
                    key="review_restore",
                )
                if st.button("Restore to queue", disabled=not restore):
                    forget_decision(restore, REVIEW_STATE_PATH)
                    st.session_state["review_token"] = token + 1
                    _load_review_queue.clear()
                    st.success(f"{restore} is back in the queue.")
                    st.rerun()

        if queue.approved:
            with st.expander(f"Approved ({len(queue.approved)})"):
                st.dataframe(queue_frame(queue.approved), width="stretch", hide_index=True)


# --- Insights ---------------------------------------------------------------------

with insights_tab:
    st.subheader("Likely Recurring Transactions")
    st.caption(
        "Detected from repeated merchants with regular spacing. These are hints, not certainties, "
        "and only transactions with Exact or Month date precision are considered."
    )
    recurring = recurring_frame(find_recurring(transactions))
    if recurring.empty:
        st.info("No clear recurring pattern yet.")
    else:
        st.dataframe(recurring, width="stretch", hide_index=True)

    st.subheader("Date Precision of Stored Rows")
    breakdown = precision_breakdown(transactions)
    if breakdown:
        st.dataframe(
            pd.DataFrame(sorted(breakdown.items()), columns=["Date Precision", "Rows"]),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "Period rows come from the historical migration, where only the school term was known. "
            "Their date is a documented stand-in (the block midpoint)."
        )

    st.subheader("Recent Changes")
    audit = read_audit(output_path, limit=20)
    if not audit:
        st.info("No edits recorded yet.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {"When": entry["at"], "Action": entry["action"], "Details": str(entry["details"])}
                    for entry in audit
                ]
            ),
            width="stretch",
            hide_index=True,
        )


# --- Settings ---------------------------------------------------------------------

with settings_tab:
    st.subheader("Monthly Expense Budget")
    st.caption("Optional. Leave at zero to switch it off - the dashboard then says nothing about budgets.")
    current_budget = float(settings.get("monthly_budget") or 0.0)
    budget_input = st.number_input("Monthly budget", min_value=0.0, step=50.0, value=current_budget)
    include_rent = st.checkbox("Count Rent towards the budget", value=bool(settings.get("budget_include_rent")))
    include_investments = st.checkbox(
        "Count Investments towards the budget", value=bool(settings.get("budget_include_investments"))
    )
    if st.button("Save budget"):
        set_monthly_budget(
            budget_input if budget_input > 0 else None,
            include_rent=include_rent,
            include_investments=include_investments,
            path=SETTINGS_PATH,
        )
        st.success("Budget saved." if budget_input > 0 else "Budget cleared.")
        st.rerun()

    st.subheader("Learned Merchant Rules")
    st.caption(f"Stored in `{RULES_PATH}`. Your corrections beat the built-in rules.")
    if not user_rules:
        st.info("No learned rules yet. Correct a category in Transactions / Manage to create one.")
    else:
        st.dataframe(
            pd.DataFrame(sorted(user_rules.items()), columns=["Merchant", "Category"]),
            width="stretch",
            hide_index=True,
        )
        to_forget = st.selectbox("Forget a rule", options=["", *sorted(user_rules)])
        if st.button("Forget rule", disabled=not to_forget):
            forget_rule(to_forget, RULES_PATH)
            _refresh()
            st.success(f"Forgot rule for {to_forget}.")
            st.rerun()

    st.subheader("Categorisation")
    overwrite = st.checkbox("Overwrite existing categories", value=False)
    if st.button("Re-run categorisation on stored transactions"):
        result = recategorize(output_path, overwrite=overwrite, user_rules=user_rules)
        _refresh()
        st.success(f"Updated {result['changed']} row(s) of {result['rows']}.")

    st.subheader("Backup and Export")
    backup_cols = st.columns(2)
    with backup_cols[0]:
        if st.button("Create workbook backup now"):
            created = backup_workbook(output_path)
            st.success(f"Backup written to {created}" if created else "Nothing to back up yet.")
    with backup_cols[1]:
        st.download_button(
            "Download transactions CSV",
            data=transactions_csv(transactions),
            file_name=export_filename(),
            mime="text/csv",
        )
    updated_at = workbook_last_updated(output_path)
    st.caption(
        f"Tracker workbook last updated {updated_at:%Y-%m-%d %H:%M:%S}."
        if updated_at
        else "Tracker workbook does not exist yet."
    )

    st.subheader("Optional AI Categorisation")
    st.caption(
        "Off by default and not required. Deterministic rules always run first; AI would only ever be "
        f"asked about merchants that stay 'Other'. Enable by setting {ENABLE_ENV_VAR}=1 plus an API key "
        "in your environment - keys are never stored in this project."
    )
    st.write("Status:", "enabled" if ai_enabled() else "disabled")
