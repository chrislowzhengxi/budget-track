from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

from openpyxl import load_workbook
from openpyxl.styles import Font
from openpyxl.worksheet.table import Table, TableStyleInfo


TRANSACTIONS_SHEET = "Transactions"
HEADERS = ["Date", "Description", "Amount", "Type", "Source Line", "Added At"]


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
                row["Date"],
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
