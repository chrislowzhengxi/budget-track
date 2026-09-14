# budget-track

Simple local spending tracker for turning Notes-style entries into rows in an
Excel workbook copy.

## Run

```bash
python3 -m streamlit run app.py
```

The app reads the original workbook at:

`/Users/chrislowzx/Downloads/Expenses/Chris 2023-2025 Spendings.xlsx`

By default it writes to:

`outputs/Chris 2023-2025 Spendings - tracker copy.xlsx`

The original workbook is not modified.
