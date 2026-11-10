from dataclasses import replace
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import pytest

from src.dataset import EFRISDataset
from src.models import InvoicePriceContext, PriceBenchmark
from src.risk_engine import RiskEngine
from src.risk_rules import PriceDeviationRule


@pytest.fixture
def price_dataset(sample_dataset: EFRISDataset) -> EFRISDataset:
    """Provide a sale with a comparable fictional price benchmark."""

    sample_dataset.price_benchmarks = [
        PriceBenchmark(
            benchmark_id="TEST-PRICE-001",
            product_code="TEST-PROD-001",
            unit="piece",
            business_type="Retail",
            location="Demo town",
            quality="Standard",
            vat_basis="VAT-exclusive",
            minimum_unit_price=Decimal("900.00"),
            maximum_unit_price=Decimal("1100.00"),
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 6, 30),
            reference_source="Simulation assumption",
        )
    ]

    sample_dataset.price_contexts = [
        InvoicePriceContext(
            fdn="TEST-FDN-001",
            line_number=1,
            quality="Standard",
            discount_rate=Decimal("0"),
        )
    ]

    return sample_dataset


@pytest.mark.parametrize(
    ("unit_price", "expected_status"),
    [
        ("899.99", "Flagged"),
        ("900.00", "Not flagged"),
        ("1000.00", "Not flagged"),
        ("1200.00", "Not flagged"),
    ],
)
def test_price_thresholds(
    price_dataset: EFRISDataset,
    unit_price: str,
    expected_status: str,
) -> None:
    original = price_dataset.lines[0]
    price = Decimal(unit_price)

    price_dataset.lines[0] = replace(
        original,
        unit_price=price,
        vat_amount=(
            original.quantity * price * Decimal("0.18")
        ).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ),
    )

    results = RiskEngine([PriceDeviationRule()]).run(price_dataset)

    assert len(results) == 1

    result = results[0]
    assert result.status == expected_status
    assert result.fdn == "TEST-FDN-001"
    assert result.line_number == 1
    assert result.product_code == "TEST-PROD-001"
    assert "TEST-PRICE-001" in result.reason
    assert result.estimated_vat_difference is None

@pytest.mark.parametrize(
    ("unit_price", "reference", "reason", "expected_status"),
    [
        ("720.00", "TEST-PROMO-001", "Clearance sale", "Not flagged"),
        ("719.99", "TEST-PROMO-001", "Clearance sale", "Flagged"),
        ("720.00", None, "Clearance sale", "Insufficient data"),
        ("720.00", "TEST-PROMO-001", None, "Insufficient data"),
    ],
)
def test_discount_evidence(
    price_dataset: EFRISDataset,
    unit_price: str,
    reference: str | None,
    reason: str | None,
    expected_status: str,
) -> None:
    line = price_dataset.lines[0]
    price = Decimal(unit_price)

    price_dataset.lines[0] = replace(
        line,
        unit_price=price,
        vat_amount=(line.quantity * price * Decimal("0.18")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ),
    )

    price_dataset.price_contexts[0] = replace(
        price_dataset.price_contexts[0],
        discount_rate=Decimal("0.20"),
        discount_reference=reference,
        discount_reason=reason,
    )

    results = RiskEngine([PriceDeviationRule()]).run(price_dataset)

    assert len(results) == 1
    result = results[0]
    assert result.status == expected_status

    if reference is not None and reason is not None:
        assert reference in result.reason
        assert reason in result.reason

@pytest.mark.parametrize(
    ("include_match", "expected_status"),
    [
        (False, "Insufficient data"),
        (True, "Not flagged"),
    ],
)
def test_damaged_goods_require_comparable_benchmark(
    price_dataset: EFRISDataset,
    include_match: bool,
    expected_status: str,
) -> None:
    price_dataset.price_contexts[0] = replace(
        price_dataset.price_contexts[0],
        quality="Damaged packaging",
    )

    base = price_dataset.price_benchmarks[0]
    damaged = replace(
        base,
        benchmark_id="TEST-DAMAGED-RETAIL",
        quality="Damaged packaging",
    )

    # Each of these ranges differs from the sale in at least one detail.
    price_dataset.price_benchmarks = [
        replace(
            base,
            minimum_unit_price=Decimal("1400.00"),
            maximum_unit_price=Decimal("1600.00"),
        ),
        replace(damaged, benchmark_id="OTHER-PRODUCT", product_code="OTHER"),
        replace(damaged, benchmark_id="OTHER-UNIT", unit="box"),
        replace(damaged, benchmark_id="WHOLESALE", business_type="Wholesale"),
        replace(damaged, benchmark_id="OTHER-TOWN", location="Another town"),
        replace(damaged, benchmark_id="VAT-INCLUSIVE", vat_basis="VAT-inclusive"),
        replace(
            damaged,
            benchmark_id="EXPIRED",
            valid_from=date(2025, 12, 1),
            valid_to=date(2025, 12, 31),
        ),
    ]

    if include_match:
        price_dataset.price_benchmarks.append(damaged)

    results = RiskEngine([PriceDeviationRule()]).run(price_dataset)

    assert len(results) == 1
    result = results[0]
    assert result.status == expected_status

    if include_match:
        assert "TEST-DAMAGED-RETAIL" in result.reason
    else:
        assert "No price benchmark" in result.reason