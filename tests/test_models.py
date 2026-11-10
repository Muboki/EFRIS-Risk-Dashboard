from datetime import date

import pytest

from decimal import Decimal

from src.models import StockLedger

from src.models import FiscalDocument, InvoiceLine, Taxpayer


def test_valid_taxpayer():
    """Accept a taxpayer with valid details."""
    taxpayer = Taxpayer(
        taxpayer_id="DEMO001",
        business_name="Demo Hardware",
        business_type="Retail",
        business_activity="Hardware",
        vat_registered=True,
    )

    assert taxpayer.taxpayer_id == "DEMO001"
    assert taxpayer.vat_registered is True


def test_missing_taxpayer_id():
    """Reject a record without a taxpayer identifier."""
    with pytest.raises(ValueError):
        Taxpayer("", "Demo Hardware", "Retail", "Hardware")


def test_invalid_business_type():
    """Reject a business type outside our project scope."""
    with pytest.raises(ValueError):
        Taxpayer("DEMO001", "Demo Hardware", "Factory", "Hardware")


def test_invalid_vat_status():
    """Reject text where a True or False value is required."""
    with pytest.raises(ValueError):
        Taxpayer(
            "DEMO001",
            "Demo Hardware",
            "Retail",
            "Hardware",
            vat_registered="False",  # pyright: ignore[reportArgumentType]
        )

def test_valid_invoice():
    """Accept an invoice with an identified buyer."""
    invoice = FiscalDocument(
        fdn="DEMO-FDN-001",
        seller_id="DEMO001",
        issue_date=date(2026, 1, 10),
        buyer_id="DEMO002",
    )

    assert invoice.fdn == "DEMO-FDN-001"
    assert invoice.buyer_id == "DEMO002"


def test_retail_invoice_without_buyer_id():
    """Accept a retail invoice with an unidentified buyer."""
    invoice = FiscalDocument(
        fdn="DEMO-FDN-002",
        seller_id="DEMO001",
        issue_date=date(2026, 1, 10),
    )

    assert invoice.buyer_id is None


def test_invoice_requires_fdn():
    """Reject an invoice without its document identifier."""
    with pytest.raises(ValueError):
        FiscalDocument(
            fdn="",
            seller_id="DEMO001",
            issue_date=date(2026, 1, 10),
        )
def test_invoice_line_amounts():
    """Calculate the amount before VAT and the total."""
    line = InvoiceLine(
        fdn="DEMO-FDN-001",
        line_number=1,
        product_code="PROD001",
        unit="piece",
        quantity=Decimal("2"),
        unit_price=Decimal("1000.00"),
        vat_category="Standard-rated",
        vat_amount=Decimal("360.00"),
    )

    assert line.net_amount == Decimal("2000.00")
    assert line.total_amount == Decimal("2360.00")


def test_invoice_line_rounding():
    """Round the calculated amount to two decimal places."""
    line = InvoiceLine(
        fdn="DEMO-FDN-002",
        line_number=1,
        product_code="PROD002",
        unit="piece",
        quantity=Decimal("3"),
        unit_price=Decimal("0.335"),
        vat_category="Zero-rated",
        vat_amount=Decimal("0.00"),
    )

    assert line.net_amount == Decimal("1.01")
    assert line.total_amount == Decimal("1.01")


def test_invoice_line_rejects_negative_quantity():
    """Reject a negative quantity on a sales invoice."""
    with pytest.raises(ValueError):
        InvoiceLine(
            fdn="DEMO-FDN-003",
            line_number=1,
            product_code="PROD001",
            unit="piece",
            quantity=Decimal("-2"),
            unit_price=Decimal("1000.00"),
            vat_category="Standard-rated",
            vat_amount=Decimal("0.00"),
        )

def test_balanced_stock():
    """Account for purchases, sales, returns, own use and write-offs."""
    stock = StockLedger(
        taxpayer_id="DEMO001",
        product_code="PROD001",
        unit="piece",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_stock=Decimal("100"),
        purchases=Decimal("50"),
        sales=Decimal("80"),
        closing_stock=Decimal("60"),
        customer_returns=Decimal("5"),
        supplier_returns=Decimal("10"),
        own_use=Decimal("2"),
        write_offs=Decimal("3"),
    )

    assert stock.expected_closing_stock == Decimal("60")
    assert stock.stock_difference == Decimal("0")


def test_stock_shortage():
    """Identify when reported stock is below the expected quantity."""
    stock = StockLedger(
        taxpayer_id="DEMO001",
        product_code="PROD001",
        unit="piece",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_stock=Decimal("10"),
        purchases=Decimal("5"),
        sales=Decimal("3"),
        closing_stock=Decimal("10"),
    )

    assert stock.expected_closing_stock == Decimal("12")
    assert stock.stock_difference == Decimal("-2")