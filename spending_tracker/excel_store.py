from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import shutil

from openpyxl import load_workbook
from openpyxl.styles import Font
from openpyxl.worksheet.table import Table, TableStyleInfo
import pandas as pd


TRANSACTIONS_SHEET = "Transactions"
HEADERS = ["Date", "Description", "Amount", "Type", "Source Line", "Added At"]


def empty_transactions_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=HEADERS).astype(
        {
            "Description": "object",
            "Amount": "float64",
            "Type": "object",
            "Source Line": "object",
            "Added At": "object",
        }
    )


def load_transactions(workbook_path: Path) -> pd.DataFrame:
    if not workbook_path.exists():
        return empty_transactions_frame()

    wb = load_workbook(workbook_path, read_only=True, data_only=True)
    if TRANSACTIONS_SHEET not in wb.sheetnames:
        return empty_transactions_frame()

    ws = wb[TRANSACTIONS_SHEET]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return empty_transactions_frame()

    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    records = [dict(zip(headers, row)) for row in rows[1:] if any(value is not None for value in row)]
    df = pd.DataFrame(records)

    for header in HEADERS:
        if header not in df.columns:
            df[header] = pd.NA

    df = df[HEADERS]
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
    df["Description"] = df["Description"].fillna("").astype(str)
    df["Type"] = df["Type"].fillna("").astype(str)
    df["Source Line"] = df["Source Line"].fillna("").astype(str)
    df["Added At"] = df["Added At"].fillna("").astype(str)
    return df


def ensure_workbook_copy(source_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not output_path.exists():
        shutil.copy2(source_path, output_path)
    return output_path


def append_transactions(workbook_path: Path, rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0

    wb = load_workbook(workbook_path)
    ws = _get_or_create_transactions_sheet(wb)
    added_at = datetime.now().replace(microsecond=0).isoformat(sep=" ")

    for row in rows:
        ws.append(
            [
                _normalize_excel_date(row["Date"]),
                row["Description"],
                float(row["Amount"]),
                row["Type"],
                row.get("Source Line", ""),
                added_at,
            ]
        )

    _format_sheet(ws)
    wb.save(workbook_path)
    return len(rows)


def _normalize_excel_date(value: object) -> object:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date") and callable(value.date):
        return value.date()
    return value


def _get_or_create_transactions_sheet(wb):
    if TRANSACTIONS_SHEET in wb.sheetnames:
        ws = wb[TRANSACTIONS_SHEET]
        if ws.max_row == 0 or ws["A1"].value is None:
            ws.append(HEADERS)
        return ws

    ws = wb.create_sheet(TRANSACTIONS_SHEET)
    ws.append(HEADERS)
    _format_sheet(ws)
    return ws


def _format_sheet(ws) -> None:
    for cell in ws[1]:
        cell.font = Font(bold=True)

    widths = {
        "A": 14,
        "B": 28,
        "C": 12,
        "D": 14,
        "E": 30,
        "F": 22,
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    for row in ws.iter_rows(min_row=2, min_col=3, max_col=3):
        for cell in row:
            cell.number_format = "0.00"

    for row in ws.iter_rows(min_row=2, min_col=1, max_col=1):
        for cell in row:
            cell.number_format = "yyyy-mm-dd"

    ref = f"A1:F{max(ws.max_row, 2)}"
    if "TransactionsTable" not in ws.tables:
        table = Table(displayName="TransactionsTable", ref=ref)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        ws.add_table(table)
    else:
        ws.tables["TransactionsTable"].ref = ref
