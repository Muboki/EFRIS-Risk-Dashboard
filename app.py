from csv import Error as CSVError
from dataclasses import asdict
from pathlib import Path
import pandas as pd
from calendar import monthrange
from copy import copy

import streamlit as st

from src.dataset import EFRISDataset
from src.risk_engine import RiskEngine
from src.risk_rules import (
    BusinessActivityRule,
    PurchaseSalesRule,
    VATClassificationRule,
    PriceDeviationRule,
)

from datetime import date


st.set_page_config(
    page_title="EFRIS Risk Dashboard",
    layout="wide",
)

st.title("EFRIS Tax Compliance Risk Dashboard")

st.write(
    "Review potential tax compliance risks for "
    "VAT-registered wholesalers and retailers."
)

st.info(
    "This prototype uses fictional taxpayer data. "
    "Flagged transactions require review and do not prove wrongdoing."
)

data_folder = Path(__file__).resolve().parent / "generated" / "six_month"

try:
    dataset = EFRISDataset(data_folder)
except (OSError, ValueError, CSVError) as error:
    st.error(f"Could not load EFRIS records: {error}")
    st.stop()

if not dataset.taxpayers:
    st.warning("The taxpayer dataset is empty.")
    st.stop()

taxpayer_column, invoice_column, line_column = st.columns(3)

taxpayer_column.metric("Taxpayers", len(dataset.taxpayers))
invoice_column.metric("Invoices", len(dataset.documents))
line_column.metric("Product lines", len(dataset.lines))

st.subheader("Taxpayer records")

st.dataframe(
    [asdict(taxpayer) for taxpayer in dataset.taxpayers],
    hide_index=True,
    column_config={
        "taxpayer_id": "Taxpayer ID",
        "business_name": "Business name",
        "business_type": "Business type",
        "business_activity": "Business activity",
        "vat_registered": "VAT registered",
    },
)

st.subheader("Invoice records")

invoice_rows = []

for document in dataset.documents:
    seller = dataset.taxpayers_by_id[document.seller_id]

    if document.buyer_id is not None:
        buyer_name = dataset.taxpayers_by_id[
            document.buyer_id
        ].business_name
    else:
        buyer_name = "Not identified"

    invoice_rows.append(
        {
            "FDN": document.fdn,
            "Date": document.issue_date,
            "Seller": seller.business_name,
            "Buyer": buyer_name,
        }
    )

st.dataframe(
    invoice_rows,
    hide_index=True,
)

st.subheader("Invoice product lines")

product_rows = []

for line in dataset.lines:
    product_rows.append(
        {
            "FDN": line.fdn,
            "Line number": line.line_number,
            "Product code": line.product_code,
            "Unit": line.unit,
            "Quantity": float(line.quantity),
            "Unit price excluding VAT (UGX)": float(line.unit_price),
            "VAT category": line.vat_category,
            "Net amount (UGX)": float(line.net_amount),
            "Recorded VAT (UGX)": float(line.vat_amount),
            "Total including VAT (UGX)": float(line.total_amount),
        }
    )

st.dataframe(
    product_rows,
    hide_index=True,
)

st.subheader("Compliance risk results")
st.write(
    "Counts represent check results. "
    "The purchases-without-sales review covers 1–31 January 2026."
)

st.write(
    "VAT differences are calculated on invoice lines to avoid "
    "counting the same amount twice."
)

if not dataset.product_tax_records:
    st.warning(
        "No registration or stocking-in records were supplied. "
        "The VAT classification results cover invoice lines only."
    )

st.subheader("Review period")
st.caption("Choose the months to include in the findings, rankings and CSV download.")

months = [date(2026, month, 1) for month in range(1, 7)]
left, right = st.columns(2)

review_start = left.selectbox(
    "From month", months, format_func=lambda d: d.strftime("%B %Y")
)
end_options = [month for month in months if month >= review_start]
last_month = right.selectbox(
    "Through month", end_options, index=len(end_options) - 1,
    format_func=lambda d: d.strftime("%B %Y"),
)
review_end = last_month.replace(day=monthrange(last_month.year, last_month.month)[1])

# Keep earlier evidence, such as the supplier invoice for a later stocking-in.
# Exclude transactions after the selected end date.
invoice_dates = {doc.fdn: doc.issue_date for doc in dataset.documents}
review_data = copy(dataset)
review_data.documents = [
    doc for doc in dataset.documents if doc.issue_date <= review_end
]
review_data.lines = [
    line for line in dataset.lines if invoice_dates[line.fdn] <= review_end
]
review_data.price_contexts = [
    ctx for ctx in dataset.price_contexts if invoice_dates[ctx.fdn] <= review_end
]
review_data.product_tax_records = [
    rec for rec in dataset.product_tax_records if rec.record_date <= review_end
]
review_data.stock_records = [
    row for row in dataset.stock_records if row.period_end <= review_end
]

engine = RiskEngine([
    VATClassificationRule(),
    PurchaseSalesRule(review_start, review_end),
    BusinessActivityRule(),
    PriceDeviationRule(),
])

tax_record_dates = {
    rec.record_id: rec.record_date for rec in review_data.product_tax_records
}
risk_results = []

for result in engine.run(review_data):
    if result.record_type == "Stock review":
        # This rule already evaluated exactly the selected months.
        risk_results.append(result)
        continue

    # Date each finding by its own invoice or product tax record.
    finding_date = tax_record_dates.get(result.record_id or "")
    if finding_date is None:
        finding_date = invoice_dates.get(result.fdn or "")
    if finding_date is None:
        st.error(f"Could not identify the date of a finding for {result.taxpayer_id}.")
        st.stop()

    if review_start <= finding_date <= review_end:
        risk_results.append(result)

review_rows = [
    {**asdict(result), "related_fdns": "; ".join(result.related_fdns)}
    for result in risk_results
    if result.status in ("Flagged", "Insufficient data")
]

if review_rows:
    review_report = pd.DataFrame(review_rows, dtype=object)
    st.download_button(
        label=f"Download {len(review_rows)} findings for review (CSV)",
        data=review_report.to_csv(index=False).encode("utf-8-sig"),
        file_name="efris_review_findings.csv",
        mime="text/csv",
    )

flagged_results = [
    result for result in risk_results
    if result.status == "Flagged"
]

insufficient_results = [
    result for result in risk_results
    if result.status == "Insufficient data"
]

not_flagged_count = sum(
    result.status == "Not flagged"
    for result in risk_results
)

flagged_column, clear_column, missing_column = st.columns(3)

flagged_column.metric("Flagged findings", len(flagged_results))
clear_column.metric("Not flagged", not_flagged_count)
missing_column.metric("Insufficient data", len(insufficient_results))

st.subheader("Taxpayers by review priority")
st.caption(
    "Each flagged risk check contributes points once per taxpayer. "
    "The points are illustrative and help officers decide which cases "
    "to review first."
)

priorities = engine.rank_for_review(risk_results)

if priorities:
    priority_rows = [
        {
            "Taxpayer ID": item.taxpayer_id,
            "Business name": dataset.taxpayers_by_id[
                item.taxpayer_id
            ].business_name,
            "Flagged findings": item.flagged_findings,
            "Review points": item.total_points,
            "Points by check": " + ".join(
                f"{name} ({points})"
                for name, points in item.rule_points
            ),
        }
        for item in priorities
    ]

    st.dataframe(priority_rows, hide_index=True)
else:
    st.info("No taxpayers have flagged findings to rank.")

review_results = flagged_results + insufficient_results

if review_results:
    risk_rows = []

    for result in review_results:
        taxpayer = dataset.taxpayers_by_id[result.taxpayer_id]

        risk_rows.append(
            {
                "Risk check": result.rule_name,
                "Record type": result.record_type,
                "Record ID": result.record_id,
                "Taxpayer ID": result.taxpayer_id,
                "Business name": taxpayer.business_name,
                "Invoice FDN": result.fdn,
                "Invoice line": result.line_number,
                "Product code": result.product_code,
                "Status": result.status,
                "Estimated VAT difference (UGX)": (
                    float(result.estimated_vat_difference)
                    if result.estimated_vat_difference is not None
                    else None
                ),
            }
        )

    st.dataframe(risk_rows, hide_index=True)

    st.subheader("Finding details")

    for result in review_results:
        identifier = result.record_id or (
            f"{result.fdn}, line {result.line_number}"
        )

        with st.expander(
            f"{result.rule_name} | {result.record_type}: {identifier}"
        ):
            st.write(f"Taxpayer: {result.taxpayer_id}")
            st.write(f"Product: {result.product_code}")
            st.write(f"Status: {result.status}")
            st.write(result.reason)

            if result.source_fdn is not None:
                st.write(
                    f"Source purchase invoice: {result.source_fdn}, "
                    f"line {result.source_line_number}."
                )
            elif result.record_type == "Stocking-in":
                st.write(
                    "Source purchase invoice details were not supplied."
                )

            if (
                result.record_type != "Invoice line"
                and result.related_fdns
            ):
                label = (
                    "Related purchase invoices: "
                    if result.record_type == "Stock review"
                    else "Matching sales: "
                )
                st.write(label + ", ".join(result.related_fdns))

            if result.estimated_vat_difference is not None:
                st.write(
                    "Estimated VAT difference: UGX "
                    f"{result.estimated_vat_difference:,.2f}"
                )

elif risk_results:
    st.info("No findings require review under the current checks.")
else:
    st.info("No eligible records were found for the current checks.")
