from datetime import date

from src.dataset import EFRISDataset
from src.risk_engine import RiskEngine
from src.risk_rules import PurchaseSalesRule
from dataclasses import replace
from decimal import Decimal


def test_repeated_purchases_without_sales_are_flagged(
    purchase_dataset: EFRISDataset,
) -> None:
    rule = PurchaseSalesRule(
        date(2026, 1, 1),
        date(2026, 1, 31),
    )

    results = RiskEngine([rule]).run(purchase_dataset)

    assert len(results) == 2

    results_by_taxpayer = {
        result.taxpayer_id: result
        for result in results
    }

    buyer_result = results_by_taxpayer["TEST001"]

    assert buyer_result.status == "Flagged"
    assert buyer_result.record_type == "Stock review"
    assert buyer_result.product_code == "TEST-PROD-001"
    assert buyer_result.related_fdns == (
        "TEST-PURCHASE-001",
        "TEST-PURCHASE-002",
    )
    assert buyer_result.estimated_vat_difference is None

    supplier_result = results_by_taxpayer["SUPPLIER001"]

    assert supplier_result.status == "Not flagged"

def test_invoices_on_one_date_are_not_repeated_purchases(
    purchase_dataset: EFRISDataset,
) -> None:
    updated = replace(
        purchase_dataset.documents_by_fdn["TEST-PURCHASE-002"],
        issue_date=date(2026, 1, 5),
    )

    purchase_dataset.documents = [
        updated if document.fdn == updated.fdn else document
        for document in purchase_dataset.documents
    ]
    purchase_dataset.documents_by_fdn[updated.fdn] = updated

    rule = PurchaseSalesRule(date(2026, 1, 1), date(2026, 1, 31))
    results = RiskEngine([rule]).run(purchase_dataset)

    buyer_result = next(
        result for result in results
        if result.taxpayer_id == "TEST001"
    )

    assert buyer_result.status == "Not flagged"
    assert buyer_result.related_fdns == (
        "TEST-PURCHASE-001",
        "TEST-PURCHASE-002",
    )


def test_missing_stock_records_produce_insufficient_data(
    purchase_dataset: EFRISDataset,
) -> None:
    purchase_dataset.stock_records = [
        record for record in purchase_dataset.stock_records
        if record.taxpayer_id != "TEST001"
    ]

    rule = PurchaseSalesRule(date(2026, 1, 1), date(2026, 1, 31))
    results = RiskEngine([rule]).run(purchase_dataset)

    buyer_result = next(
        result for result in results
        if result.taxpayer_id == "TEST001"
    )

    assert buyer_result.status == "Insufficient data"
    assert buyer_result.estimated_vat_difference is None

def test_invoice_stock_quantity_mismatch_is_insufficient(
    purchase_dataset: EFRISDataset,
) -> None:
    purchase_dataset.stock_records = [
        replace(
            record,
            purchases=Decimal("5"),
            closing_stock=Decimal("5"),
        )
        if record.taxpayer_id == "TEST001"
        else record
        for record in purchase_dataset.stock_records
    ]

    rule = PurchaseSalesRule(date(2026, 1, 1), date(2026, 1, 31))
    results = RiskEngine([rule]).run(purchase_dataset)

    buyer_result = next(
        result for result in results
        if result.taxpayer_id == "TEST001"
    )

    assert buyer_result.status == "Insufficient data"


def test_fully_returned_purchases_are_not_flagged(
    purchase_dataset: EFRISDataset,
) -> None:
    for index, record in enumerate(purchase_dataset.stock_records):
        if record.taxpayer_id == "TEST001":
            purchase_dataset.stock_records[index] = replace(
                record,
                supplier_returns=Decimal("4"),
                closing_stock=Decimal("0"),
            )
        elif record.taxpayer_id == "SUPPLIER001":
            purchase_dataset.stock_records[index] = replace(
                record,
                customer_returns=Decimal("4"),
                closing_stock=Decimal("4"),
            )

    rule = PurchaseSalesRule(date(2026, 1, 1), date(2026, 1, 31))
    results = RiskEngine([rule]).run(purchase_dataset)

    assert len(results) == 2
    assert all(result.status == "Not flagged" for result in results)