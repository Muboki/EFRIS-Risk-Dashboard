"""Streamlit dashboard for reviewing fictional wholesale and retail EFRIS records."""
from calendar import monthrange
from csv import Error as CSVError
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from src.case_register import COLUMNS, FIRST, LAST, build_register, run_review
from src.dataset import EFRISDataset
from src.review_view import STYLES, grouped_cases, header, lead, metric_band, period_label, ranking
from src.risk_engine import RiskEngine

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="EFRIS Risk Dashboard", page_icon=":material/receipt_long:", layout="wide")
st.html(STYLES)
try:
    dataset = EFRISDataset(ROOT / "generated" / "six_month")
except (OSError, ValueError, CSVError) as error:
    st.error(f"Could not load EFRIS records: {error}")
    st.stop()
if not dataset.taxpayers:
    st.warning("The taxpayer dataset is empty.")
    st.stop()

st.html(header(dataset))

months = [date(FIRST.year, m, 1) for m in range(FIRST.month, LAST.month + 1)]
info, start_col, end_col = st.columns([1.3, 1, 1], vertical_alignment="center")
with info:
    st.markdown("**Review period**")
    st.caption("The dates apply to cases, rankings and exports.")
review_start = start_col.selectbox("From month", months, format_func=lambda d: d.strftime("%B %Y"), key="review_from")
end_options = [m for m in months if m >= review_start]
last_month = end_col.selectbox("Through month", end_options, index=len(end_options) - 1,
                               format_func=lambda d: d.strftime("%B %Y"), key="review_through")
review_end = last_month.replace(day=monthrange(last_month.year, last_month.month)[1])

period = run_review(dataset, review_start, review_end)
results = period.findings
cases = build_register(dataset, period)
label = period_label(review_start, review_end)
st.html(metric_band(cases, period))
if not dataset.product_tax_records:
    st.warning("No registration or stocking records were supplied. The VAT check covers invoice lines only.")

case_tab, priority_tab, source_tab = st.tabs(["Flagged cases", "Taxpayer priorities", "Source records"])
with case_tab:
    st.html(lead(label, "Flagged cases by issue",
                 "Open an issue to see all its invoices together. Select an invoice row to see why it was flagged."))
    st.html(grouped_cases(dataset, period, cases))
    n_support = sum(r.status == "Flagged" and r.record_type in ("Stocking-in", "Registration") for r in results)
    if n_support:
        noun = "record" if n_support == 1 else "records"
        st.caption(f"{n_support} flagged product classification {noun} included in the finding total. "
                   "Linked stocking entries are shown as supporting evidence for the sale.")
    st.caption("These are fictional records. A flag calls for review and does not prove wrongdoing.")
    review_rows = [{**asdict(r), "related_fdns": "; ".join(r.related_fdns)}
                   for r in results if r.status in ("Flagged", "Insufficient data")]
    if cases or review_rows:
        case_export, finding_export = st.columns(2)
        if cases:
            case_export.download_button(
                "Download case register (CSV)",
                pd.DataFrame(cases, columns=list(COLUMNS)).to_csv(index=False).encode("utf-8-sig"),
                file_name="efris_case_register.csv", mime="text/csv", icon=":material/download:",
                help="One row per distinct case for the selected months.", key="download_cases",
            )
        if review_rows:
            finding_export.download_button(
                f"Download {len(review_rows)} findings for review (CSV)",
                pd.DataFrame(review_rows, dtype=object).to_csv(index=False).encode("utf-8-sig"),
                file_name="efris_review_findings.csv", mime="text/csv", icon=":material/download:",
                help="Includes supporting product classifications and records with insufficient data.", key="download_findings",
            )

with priority_tab:
    st.html(lead(label, "Taxpayers by review priority",
                 "Each flagged check contributes its weight once per taxpayer. Points help prioritise a review; they are not a probability of fraud."))
    priorities = RiskEngine.rank_for_review(results)
    if priorities:
        st.html(ranking(dataset, priorities))
        with st.expander("Scores and contributing checks"):
            st.dataframe([{
                "Taxpayer ID": item.taxpayer_id, "Business name": dataset.taxpayers_by_id[item.taxpayer_id].business_name,
                "Flagged findings": item.flagged_findings, "Review points": item.total_points,
                "Points by check": " + ".join(f"{name} ({points})" for name, points in item.rule_points),
            } for item in priorities], hide_index=True, width="stretch")
    else:
        st.info("No taxpayers have flagged findings to rank for this period.")

with source_tab:
    st.html(lead("Full dataset", "Source records",
                 "Browse the six-month dataset. An FDN identifies one invoice; its line numbers identify the separate products."))
    with st.expander(f"Taxpayers · {len(dataset.taxpayers):,}", expanded=True):
        st.dataframe([asdict(t) for t in dataset.taxpayers], hide_index=True, width="stretch",
                     column_config={"taxpayer_id":"Taxpayer ID", "business_name":"Business name",
                                    "business_type":"Business type", "business_activity":"Business activity",
                                    "vat_registered":"VAT registered"})
    with st.expander(f"Invoices · {len(dataset.documents):,}"):
        st.dataframe([{"FDN": d.fdn, "Date": d.issue_date,
                       "Seller": dataset.taxpayers_by_id[d.seller_id].business_name,
                       "Buyer": dataset.taxpayers_by_id[d.buyer_id].business_name if d.buyer_id else "Not identified"}
                      for d in dataset.documents], hide_index=True, width="stretch")
    with st.expander(f"Product lines · {len(dataset.lines):,}"):
        st.dataframe([{
            "FDN": line.fdn, "Line number": line.line_number, "Product code": line.product_code,
            "Unit": line.unit, "Quantity": float(line.quantity), "Unit price excluding VAT (UGX)": float(line.unit_price),
            "VAT category": line.vat_category, "Net amount (UGX)": float(line.net_amount),
            "Recorded VAT (UGX)": float(line.vat_amount), "Total including VAT (UGX)": float(line.total_amount),
        } for line in dataset.lines], hide_index=True, width="stretch")
