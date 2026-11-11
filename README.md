# EFRIS Tax Compliance Risk Dashboard

A Python and Streamlit prototype for reviewing fictional EFRIS records from VAT-registered wholesalers and retailers in Uganda. Each finding identifies the rule, the taxpayer, the supporting invoice or stock record and the reason for review. The application does not connect to URA or assess tax liabilities.

## Run on Windows

Open PowerShell in the project folder. The original Windows environment uses Python 3.14.7. For a fresh checkout, create a virtual environment and install the dependencies:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Build the six-month dataset from the supplied January examples, then launch the dashboard:

```powershell
.\.venv\Scripts\python.exe -m src.data_generator
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the Local URL printed by Streamlit. The dashboard uses a dark slate background and white text, including expanded invoice evidence and source tables. Keep **From month: January 2026** and **Through month: June 2026** for the full demonstration. The **Flagged cases** tab has one heading per issue. **VAT misclassification** is open first: all five sales appear together. Select an invoice row to read its explanation, VAT estimate and supporting stocking records. Open **Purchases without sales** to see the invoice pairs and remaining stock. The **Taxpayer priorities** and **Source records** tabs show ranking and underlying transactions. Both CSV downloads follow the selected months. The prebuilt files work without regenerating them.

For a quick look without Python, open `preview/EFRIS_Dashboard_Preview.html` in your browser. It uses the same case rows and explanations as the app, saved for January–June; the date filters and CSV downloads are in the live dashboard. To refresh the saved view after changing your data, run `python -m src.review_view`.

## What the rules check

| Risk check | Decision and evidence |
| --- | --- |
| VAT misclassification | Compare the invoice line or product tax record with the dated reference and supply conditions. Trace a mismatch to the sale where possible. |
| Purchases without sales | Look for purchases on two or more dates with no corresponding sales. Reconcile quantities, returns, own use and closing stock before flagging the pattern. |
| Business-profile mismatch | Compare sold categories with the taxpayer’s declared activity, taking dated diversification and documented asset disposals into account. |
| Possible price understatement | Compare a VAT-exclusive unit price with a range for the same product, unit, period, location, trading level and quality; allow supported discounts. |

Outcomes are **Flagged**, **Not flagged** and **Insufficient data**. Review weights are 40, 25, 15 and 20 points respectively for the rules in the table. Each distinct rule contributes its weight only once per taxpayer, even when it produces several flags. The weights express illustrative review priorities.

## Demonstration data

The January–June 2026 dataset contains **12 fictional taxpayers, 752 distinct invoices and 1,500 invoice lines**. An FDN identifies an invoice; the FDN and line number identify an individual product. There are 764 product tax records, 1,500 price contexts, 17 simulated product references, 34 illustrative price benchmarks and 234 monthly ledger rows. Each of the 39 stock groups covers six consecutive months, with 195 closing-to-opening checks. The 368 simulated wholesale/retail invoice pairs still link each wholesale buyer to the retail seller.

| Risk check | Independent cases | Example to open |
| --- | ---: | --- |
| VAT misclassification | 5 different sales FDNs, each linked to a stocking record | `DEMO-FDN-007`, line 1: cement recorded as exempt; estimated difference UGX 72,000. |
| Purchases without sales | 5 buyer/product/unit groups, each supported by 2 different purchase dates (10 different purchase FDNs) | `SIM-W-0125` and `SIM-W-0311`: DEMO004 bought 8 electric kettles in total, sold none, and held 8 at the end of June. |
| Business-profile mismatch | 5 different sales FDNs | `SIM-R-0093`, line 1: a hardware retailer sold a radio; the records contain no applicable exception. |
| Possible price understatement | 5 different sales FDNs | `SIM-R-0110`, line 1: a chair sold at UGX 49,000 against a simulated retail minimum of UGX 60,000. |

**Where to find all 20:** `generated/six_month/case_register.csv` (one row per case, with FDNs, dates, lines, reasons and available supporting evidence). Appendices A and B in `report/EFRIS_Project_Report.docx` provide a shorter index. Multiple flagged lines on one invoice count only once per issue. A stocking-in flag supports a VAT case. The two purchases supporting an unsold product count as one review pattern. The three sales-based checks use 15 separate invoices.

| Selected period | Distinct cases | Flagged findings | Not flagged | Insufficient data | Total check results |
| --- | ---: | ---: | ---: | ---: | ---: |
| January–June 2026 | 20 | 25 | 5,278 | 0 | 5,303 |
| February 2026 only | 3 | 4 | 903 | 0 | 907 |

The five extra flagged findings in the full period are stocking-in records linked to the five VAT sales. The possible VAT difference is reported only on the sale. An unsold balance can be legitimate stock accumulation; a low price or unusual category likewise calls for a review.

### How the examples were created

`src/demo_scenarios.py` modifies selected fictional transactions in the fixed six-month trade plan before the generator writes the dashboard files. Four extra sales carry an incorrect VAT category, four carry unsupported non-core goods, and four have a unit price below the comparable retail minimum. Four additional resale products were delivered to four buyers on two separate dates; the buyers sold other goods from existing inventory. Non-core merchandise and upstream stocks have explicit simulated opening quantities. Source files in `data/`, risk tolerances, scoring weights and the separate holdout were unchanged. Re-running the generator writes the same files, including the case register.

## Tests and evaluation

Run these commands in a second PowerShell terminal:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe .\evaluate_holdout.py
```

All 69 tests passed with the project’s pinned dependencies. They include checks for distinct invoices, two-date purchase patterns, daily and monthly stock balances, generation from a clean folder, and the grouping of invoices when the selected review months change in Streamlit. On eight separate, pre-labelled fictional rule decisions, the evaluator recorded 4 true positives, 4 true negatives, 0 false positives and 0 false negatives: precision 4/4 and recall 4/4. A ninth case with missing price evidence returned **Insufficient data** and was scored separately. These small constructed cases establish behaviour on those examples, not real-world accuracy.

For a demonstration screenshot on Windows, keep the full period, open **VAT misclassification** and capture its five-invoice list using **Win + Shift + S**. For stock evidence, open **Purchases without sales**, then select the pipe or kettle row to show both purchase FDNs and the closing stock.

## Project files

| Location | Purpose |
| --- | --- |
| `app.py`, `src/review_view.py` | Streamlit screens, issue groups, invoice evidence and exports |
| `assets/dashboard.css`, `.streamlit/config.toml` | Responsive layout, risk colours and native control theme |
| `src/models.py`, `src/repositories.py`, `src/dataset.py` | Validated records, CSV loading and record links |
| `src/risk_rules.py`, `src/risk_engine.py` | Rule interface, four implementations, explanations and review priorities |
| `src/data_generator.py`, `src/demo_scenarios.py` | Reproduce the six-month files and deliberate examples |
| `src/case_register.py` | Review period, grouping of actual rule findings, supporting invoices and CSV export |
| `data/`, `generated/six_month/` | Original examples and references; generated dashboard inputs |
| `tests/` | Original tests plus case coverage, stock continuity, reproducibility and the dashboard workflow |
| `evaluate_holdout.py`, `evaluation/` | Separate holdout decisions and metrics; verification of the displayed counts |
| `report/EFRIS_Project_Report.docx` | Report, results and FDN index for all 20 cases |

EFRIS and VAT background: [URA EFRIS Handbook](https://ura.go.ug/en/efris-handbook/) and [URA Value Added Tax](https://ura.go.ug/en/value-added-tax-vat/).
