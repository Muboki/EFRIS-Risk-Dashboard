# EFRIS Tax Compliance Risk Dashboard

A Python and Streamlit prototype for reviewing fictional EFRIS records from VAT-registered wholesalers and retailers in Uganda. Each finding identifies the rule, the taxpayer, the supporting invoice or stock record and the reason for review. The application does not connect to URA or assess tax liabilities.

## Run on Windows

Open PowerShell in the project folder. The project was tested with Python 3.14.7. For a fresh checkout, create a virtual environment and install the dependencies:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Build the six-month dataset from the supplied January examples, then launch the dashboard:

```powershell
.\.venv\Scripts\python.exe -m src.data_generator
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the Local URL printed by Streamlit. Use **From month** and **Through month** to choose the review period. Review the taxpayer rankings, expand a finding to see its explanation, and download the findings for the selected period as a CSV.

## What the rules check

| Risk check | Decision and evidence |
| --- | --- |
| VAT misclassification | Compare the invoice line or product tax record with the dated reference and supply conditions. Trace a mismatch to the sale where possible. |
| Purchases without sales | Look for purchases on two or more dates with no corresponding sales. Reconcile quantities, returns, own use and closing stock before flagging the pattern. |
| Business-profile mismatch | Compare sold categories with the taxpayer’s declared activity, taking dated diversification and documented asset disposals into account. |
| Possible price understatement | Compare a VAT-exclusive unit price with a range for the same product, unit, period, location, trading level and quality; allow supported discounts. |

Outcomes are **Flagged**, **Not flagged** and **Insufficient data**. Review weights are 40, 25, 15 and 20 points respectively for the rules in the table. Each distinct rule contributes its weight only once per taxpayer, even when it produces several flags. The weights express illustrative review priorities.

## Demonstration data

The January–June 2026 dataset contains 12 fictional taxpayers, 752 unique fiscal document numbers (FDNs), 1,500 invoice lines, 764 product tax records and 162 monthly stock records. An FDN identifies an invoice; the FDN and line number together identify a product line. Each new simulated wholesale-to-retail trade links the wholesale buyer to the retail seller. Wholesalers’ opening balances, price benchmarks, product classifications and transactions are illustrative.

| Selected period | Flagged | Not flagged | Insufficient data | Total check results |
| --- | ---: | ---: | ---: | ---: |
| January–June 2026 | 5 | 5,286 | 0 | 5,291 |
| February 2026 | 0 | 895 | 0 | 895 |

These counts are decisions by the rules, not counts of distinct invoices. For example, DEMO002’s stocking-in error and the related sale are separate findings; the estimated VAT difference of UGX 72,000 is attached only to the sale. Its purchases of 20 unsold pipes give the reviewer a separate stock question.

## Tests and evaluation

Run these commands in a second PowerShell terminal:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe .\evaluate_holdout.py
```

The reported run passed all 61 automated tests. On eight separate, pre-labelled fictional rule decisions, the evaluator recorded 4 true positives, 4 true negatives, 0 false positives and 0 false negatives: precision 4/4 and recall 4/4. A ninth case with missing price evidence returned **Insufficient data** and was scored separately. These small constructed cases establish behaviour on those examples, not real-world accuracy.

## Project files

| Location | Purpose |
| --- | --- |
| `app.py` | Streamlit review screen and CSV download |
| `src/models.py`, `src/repositories.py`, `src/dataset.py` | Validated records, CSV loading and record links |
| `src/risk_rules.py`, `src/risk_engine.py` | Rule interface, four implementations, explanations and review priorities |
| `src/data_generator.py` | Reproducible six-month data generation and verification |
| `data/`, `generated/six_month/` | Original examples and references; generated dashboard inputs |
| `tests/` | Automated tests, including the original labelled examples |
| `evaluate_holdout.py`, `evaluation/` | Separate evaluation, case-level decisions and metric summary |

EFRIS and VAT background: [URA EFRIS Handbook](https://ura.go.ug/en/efris-handbook/) and [URA Value Added Tax](https://ura.go.ug/en/value-added-tax-vat/).
