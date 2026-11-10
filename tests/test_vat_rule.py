from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.dataset import EFRISDataset
from src.risk_rules import VATClassificationRule


def test_correct_vat_is_not_flagged(
    sample_dataset: EFRISDataset,
) -> None:
    """Accept a line with the correct category and VAT amount."""
    results = VATClassificationRule().evaluate(sample_dataset)

    assert len(results) == 1
    assert results[0].status == "Not flagged"
    assert results[0].estimated_vat_difference == Decimal("0.00")


@pytest.mark.parametrize(
    "category,recorded_vat,expected_difference",
    [
        ("Exempt", "0.00", "360.00"),
        ("Zero-rated", "0.00", "360.00"),
        ("Exempt", "360.00", "0.00"),
    ],
)
def test_vat_misclassification(
    sample_dataset: EFRISDataset,
    category: str,
    recorded_vat: str,
    expected_difference: str,
) -> None:
    """Flag incorrect categories and calculate the VAT shortfall."""
    sample_dataset.lines[0] = replace(
        sample_dataset.lines[0],
        vat_category=category,
        vat_amount=Decimal(recorded_vat),
    )

    results = VATClassificationRule().evaluate(sample_dataset)

    assert len(results) == 1
    assert results[0].status == "Flagged"
    assert results[0].fdn == "TEST-FDN-001"
    assert results[0].line_number == 1
    assert results[0].estimated_vat_difference == Decimal(
        expected_difference
    )


def test_incorrect_vat_amount_is_flagged(
    sample_dataset: EFRISDataset,
) -> None:
    """Detect missing VAT even when the category is correct."""
    sample_dataset.lines[0] = replace(
        sample_dataset.lines[0],
        vat_amount=Decimal("0.00"),
    )

    result = VATClassificationRule().evaluate(sample_dataset)[0]

    assert result.status == "Flagged"
    assert result.estimated_vat_difference == Decimal("360.00")


def test_missing_reference_is_insufficient_data(
    sample_dataset: EFRISDataset,
) -> None:
    """Report insufficient evidence when no reference is available."""
    sample_dataset.product_references = []

    result = VATClassificationRule().evaluate(sample_dataset)[0]

    assert result.status == "Insufficient data"
    assert result.estimated_vat_difference is None


def test_expired_reference_is_insufficient_data(
    sample_dataset: EFRISDataset,
) -> None:
    """Reject a reference that expired before the invoice date."""
    sample_dataset.product_references[0] = replace(
        sample_dataset.product_references[0],
        valid_to=date(2026, 1, 9),
    )

    result = VATClassificationRule().evaluate(sample_dataset)[0]

    assert result.status == "Insufficient data"
    assert result.estimated_vat_difference is None


def test_missing_supply_conditions_is_insufficient_data(
    sample_dataset: EFRISDataset,
) -> None:
    """Avoid choosing a reference without supply conditions."""
    document = replace(
        sample_dataset.documents[0],
        supply_condition=None,
    )

    sample_dataset.documents[0] = document
    sample_dataset.documents_by_fdn[document.fdn] = document

    result = VATClassificationRule().evaluate(sample_dataset)[0]

    assert result.status == "Insufficient data"
    assert result.estimated_vat_difference is None