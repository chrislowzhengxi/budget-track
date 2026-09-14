from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from spending_tracker.dashboard import (
    filter_transactions,
    monthly_summary,
    recent_transactions,
    resolve_date_range,
    summarize_transactions,
)
from spending_tracker.excel_store import append_transactions, ensure_workbook_copy, load_transactions
from spending_tracker.parser import VALID_TYPES, parse_lines


SOURCE_WORKBOOK = Path("/Users/chrislowzx/Downloads/Expenses/Chris 2023-2025 Spendings.xlsx")
DEFAULT_OUTPUT = Path("outputs/Chris 2023-2025 Spendings - tracker copy.xlsx")


st.set_page_config(page_title="Spending Tracker", layout="wide")
st.title("Spending Tracker")

st.caption("Review cash flow from your tracker workbook, then paste Notes-style entries when you want to add transactions.")

with st.sidebar:
    st.header("Workbook")
    source_path = Path(st.text_input("Original workbook", value=str(SOURCE_WORKBOOK)))
    output_path = Path(st.text_input("Output workbook", value=str(DEFAULT_OUTPUT)))
    default_date = st.date_input("Default date", value=date.today())

@st.cache_data(show_spinner=False)
def _load_dashboard_data(path_text: str) -> pd.DataFrame:
    return load_transactions(Path(path_text))


st.header("Dashboard")
transactions = _load_dashboard_data(str(output_path))

filter_col, recent_col = st.columns([3, 1])
with filter_col:
    date_filter = st.segmented_control(
        "Date range",
        options=["All time", "This month", "Last month", "This year", "Custom date range"],
        default="All time",
    )
with recent_col:
    recent_choice = st.selectbox("Recent rows", options=["Latest 10", "Latest 25", "All"], index=0)

custom_start = None
custom_end = None
if date_filter == "Custom date range":
    custom_start, custom_end = st.date_input(
        "Custom period",
        value=(date.today().replace(day=1), date.today()),
    )

selected_range = resolve_date_range(date_filter, date.today(), custom_start, custom_end)
filtered_transactions = filter_transactions(transactions, selected_range)
summary = summarize_transactions(filtered_transactions)

metric_cols = st.columns(5)
for column, label in zip(
    metric_cols,
    ["Expenses", "Income", "Rent", "Investments", "Net cash flow"],
    strict=True,
):
    column.metric(label, f"${summary[label]:,.2f}")

monthly = monthly_summary(filtered_transactions)
left, right = st.columns([3, 2])
with left:
    st.subheader("Monthly Summary")
    if monthly.empty:
        st.info("No transactions found for this date range.")
    else:
        st.dataframe(monthly, use_container_width=True, hide_index=True)
with right:
    st.subheader("Monthly Expenses")
    if monthly.empty:
        st.info("No expense history to chart yet.")
    else:
        chart_data = monthly.sort_values("Month")[["Month", "Expenses"]].set_index("Month")
        st.bar_chart(chart_data)

st.subheader("Recent Transactions")
limit = {"Latest 10": 10, "Latest 25": 25, "All": None}[recent_choice]
recent = recent_transactions(filtered_transactions, limit)
if recent.empty:
    st.info("No transactions to show yet.")
else:
    st.dataframe(recent, use_container_width=True, hide_index=True)

st.header("Add Transactions")
sample = "uber 12\ntatte 8.50\nwhole foods 31\nTA (695.56)\nrent 1800\ninvestment 500"
raw_text = st.text_area("Transactions", value=sample, height=220)

if st.button("Parse", type="primary"):
    parsed = parse_lines(raw_text, default_date)
    st.session_state["transactions_df"] = pd.DataFrame([item.as_dict() for item in parsed])

df = st.session_state.get("transactions_df")

if df is not None and not df.empty:
    st.subheader("Preview")
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Date": st.column_config.DateColumn("Date", required=True),
            "Description": st.column_config.TextColumn("Description", required=True),
            "Amount": st.column_config.NumberColumn("Amount", min_value=0.0, step=0.01, format="%.2f", required=True),
            "Type": st.column_config.SelectboxColumn("Type", options=VALID_TYPES, required=True),
            "Status": st.column_config.SelectboxColumn("Status", options=["Ready", "Needs review"], required=True),
            "Note": st.column_config.TextColumn("Note", disabled=True),
            "Source Line": st.column_config.TextColumn("Source Line", disabled=True),
        },
        disabled=["Note", "Source Line"],
        hide_index=True,
    )
    st.session_state["transactions_df"] = edited

    needs_review = edited["Status"].ne("Ready").any() or edited[["Date", "Description", "Amount", "Type"]].isna().any().any()
    if needs_review:
        st.warning("Some rows need review. Correct them and set Status to Ready, or delete the row.")

    if st.button("Confirm / Add to Excel", disabled=needs_review):
        if not source_path.exists():
            st.error(f"Original workbook not found: {source_path}")
        else:
            destination = ensure_workbook_copy(source_path, output_path)
            ready_rows = edited[["Date", "Description", "Amount", "Type", "Source Line"]].to_dict("records")
            count = append_transactions(destination, ready_rows)
            _load_dashboard_data.clear()
            st.success(f"Added {count} transaction(s) to {destination}")
else:
    st.info("Paste transactions and click Parse.")
