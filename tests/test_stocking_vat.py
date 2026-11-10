from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.dataset import EFRISDataset
from src.risk_engine import RiskEngine
from src.risk_rules import VATClassificationRule


def test_correct_stocking_records_are_not_flagged(
    stocking_dataset: EFRISDataset,
) -> None:
    """Accept correctly classified purchases, stock and sales."""
    results = RiskEngine([VATClassificationRule()]).run(stocking_dataset)

    assert len(results) == 3
    assert all(result.status == "Not flagged" for result in results)


@pytest.mark.parametrize("category", ["Exempt", "Zero-rated"])
def test_stock_misclassification_links_sales_without_double_counting(
    stocking_dataset: EFRISDataset,
    category: str,
) -> None:
    """Preserve purchase/sale links without duplicating the VAT difference."""
    stocking_dataset.product_tax_records[0] = replace(
        stocking_dataset.product_tax_records[0],
        vat_category=category,
    )

    stocking_dataset.lines[0] = replace(
        stocking_dataset.lines[0],
        vat_category=category,
        vat_amount=Decimal("0.00"),
    )

    results = RiskEngine([VATClassificationRule()]).run(stocking_dataset)
    flagged = [r for r in results if r.status == "Flagged"]

    invoice_result = next(
        r for r in results if r.fdn == "TEST-FDN-001"
    )
    stock_result = next(
        r for r in results if r.record_id == "TEST-STK-001"
    )

    assert len(flagged) == 2
    assert invoice_result.status == "Flagged"
    assert stock_result.status == "Flagged"
    assert stock_result.record_type == "Stocking-in"
    assert stock_result.taxpayer_id == "TEST001"
    assert stock_result.source_fdn == "TEST-PURCHASE-001"
    assert stock_result.source_line_number == 1
    assert stock_result.related_fdns == ("TEST-FDN-001",)
    assert stock_result.estimated_vat_difference is None

    total_difference = sum(
        (
            r.estimated_vat_difference
            for r in results
            if r.estimated_vat_difference is not None
        ),
        Decimal("0.00"),
    )

    assert total_difference == Decimal("360.00")


def test_stock_error_does_not_imply_omitted_sales_vat(
    stocking_dataset: EFRISDataset,
) -> None:
    """Flag incorrect stock classification when sales VAT is correct."""
    stocking_dataset.product_tax_records[0] = replace(
        stocking_dataset.product_tax_records[0],
        vat_category="Exempt",
    )

    results = RiskEngine([VATClassificationRule()]).run(stocking_dataset)
    flagged = [r for r in results if r.status == "Flagged"]

    assert len(flagged) == 1
    assert flagged[0].record_id == "TEST-STK-001"
    assert flagged[0].related_fdns == ()
    assert flagged[0].estimated_vat_difference is None

    assert all(
        r.estimated_vat_difference in (None, Decimal("0.00"))
        for r in results
    )


def test_reference_must_cover_stocking_date(
    stocking_dataset: EFRISDataset,
) -> None:
    """A reference valid for the later sale may not cover stocking-in."""
    stocking_dataset.product_references[0] = replace(
        stocking_dataset.product_references[0],
        valid_from=date(2026, 1, 6),
    )

    results = RiskEngine([VATClassificationRule()]).run(stocking_dataset)
    stock_result = next(
        r for r in results if r.record_id == "TEST-STK-001"
    )

    assert stock_result.status == "Insufficient data"
    assert stock_result.estimated_vat_difference is None


def test_missing_stock_supply_conditions(
    stocking_dataset: EFRISDataset,
) -> None:
    """Report insufficient data when stock supply conditions are missing."""
    stocking_dataset.product_tax_records[0] = replace(
        stocking_dataset.product_tax_records[0],
        supply_condition=None,
    )

    results = RiskEngine([VATClassificationRule()]).run(stocking_dataset)
    stock_result = next(
        r for r in results if r.record_id == "TEST-STK-001"
    )

    assert stock_result.status == "Insufficient data"
    assert stock_result.related_fdns == ()