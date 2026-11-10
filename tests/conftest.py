from pathlib import Path

import pytest

from src.dataset import EFRISDataset


@pytest.fixture
def sample_dataset(tmp_path: Path) -> EFRISDataset:
    """Create a small, repeatable dataset for testing risk rules."""
    files = {
        "business_activity_evidence.csv": (
            "record_id,taxpayer_id,category,evidence_type,"
            "valid_from,valid_to,evidence_reference,reason,"
            "fdn,line_number\n"
        ),
        "stock_ledger.csv": (
            "taxpayer_id,product_code,unit,period_start,period_end,"
            "opening_stock,purchases,sales,closing_stock,"
            "customer_returns,supplier_returns,own_use,write_offs\n"
        ),       
        "product_tax_records.csv": (
            "record_id,taxpayer_id,record_type,record_date,"
            "product_code,unit,vat_category,supply_condition,"
            "source_fdn,source_line_number\n"
        ),
        "taxpayers.csv": (
            "taxpayer_id,business_name,business_type,"
            "business_activity,vat_registered\n"
            "TEST001,Test Hardware,Retail,Hardware,True\n"
        ),
        "fiscal_documents.csv": (
            "fdn,seller_id,issue_date,buyer_id,"
            "supply_condition,location\n"
            "TEST-FDN-001,TEST001,2026-01-10,,"
            "Ordinary domestic sale,Demo town\n"
        ),
        "invoice_lines.csv": (
            "fdn,line_number,product_code,unit,quantity,"
            "unit_price,vat_category,vat_amount\n"
            "TEST-FDN-001,1,TEST-PROD-001,piece,2,"
            "1000.00,Standard-rated,360.00\n"
        ),
        "product_catalogue.csv": (
            "product_code,product_name,category,unit,"
            "expected_vat_category,vat_rate,valid_from,valid_to,"
            "supply_condition,reference_source\n"
            "TEST-PROD-001,Test item,Hardware,piece,"
            "Standard-rated,0.18,2026-01-01,2026-06-30,"
            "Ordinary domestic sale,Simulation assumption\n"
        ),
        "price_benchmarks.csv": (
            "benchmark_id,product_code,unit,business_type,"
            "location,quality,vat_basis,minimum_unit_price,"
            "maximum_unit_price,valid_from,valid_to,reference_source\n"
        ),
        "invoice_price_contexts.csv": (
            "fdn,line_number,quality,discount_rate,"
            "discount_reference,discount_reason\n"
        ),
    }

    for filename, content in files.items():
        (tmp_path / filename).write_text(
            content,
            encoding="utf-8",
        )

    return EFRISDataset(tmp_path)

@pytest.fixture
def stocking_dataset(
    sample_dataset: EFRISDataset,
    tmp_path: Path,
) -> EFRISDataset:
    """Add a supplier purchase and stocking-in record to the test data."""
    buyer_id = sample_dataset.taxpayers[0].taxpayer_id

    additions = {
        "taxpayers.csv": (
            "SUPPLIER001,Test Supplier,Wholesale,Hardware,True\n"
        ),
        "fiscal_documents.csv": (
            f"TEST-PURCHASE-001,SUPPLIER001,2026-01-05,{buyer_id},"
            "Ordinary domestic sale,Demo town\n"
        ),
        "invoice_lines.csv": (
            "TEST-PURCHASE-001,1,TEST-PROD-001,piece,2,"
            "800.00,Standard-rated,288.00\n"
        ),
        "product_tax_records.csv": (
            f"TEST-STK-001,{buyer_id},Stocking-in,2026-01-05,"
            "TEST-PROD-001,piece,Standard-rated,"
            "Ordinary domestic sale,TEST-PURCHASE-001,1\n"
        ),
    }

    for filename, content in additions.items():
        with (tmp_path / filename).open(
            "a",
            encoding="utf-8",
        ) as file:
            file.write(content)

    return EFRISDataset(tmp_path)

@pytest.fixture
def purchase_dataset(
    sample_dataset: EFRISDataset,
    tmp_path: Path,
) -> EFRISDataset:
    """Create repeated purchases without sales and balanced stock."""

    buyer_id = sample_dataset.taxpayers[0].taxpayer_id

    with (tmp_path / "taxpayers.csv").open(
        "a", encoding="utf-8"
    ) as file:
        file.write(
            "SUPPLIER001,Test Supplier,Wholesale,Hardware,True\n"
        )

    files = {
        "fiscal_documents.csv": (
            "fdn,seller_id,issue_date,buyer_id,"
            "supply_condition,location\n"
            f"TEST-PURCHASE-001,SUPPLIER001,2026-01-05,{buyer_id},"
            "Ordinary domestic sale,Demo town\n"
            f"TEST-PURCHASE-002,SUPPLIER001,2026-01-20,{buyer_id},"
            "Ordinary domestic sale,Demo town\n"
        ),
        "invoice_lines.csv": (
            "fdn,line_number,product_code,unit,quantity,"
            "unit_price,vat_category,vat_amount\n"
            "TEST-PURCHASE-001,1,TEST-PROD-001,piece,2,"
            "800.00,Standard-rated,288.00\n"
            "TEST-PURCHASE-002,1,TEST-PROD-001,piece,2,"
            "800.00,Standard-rated,288.00\n"
        ),
        "stock_ledger.csv": (
            "taxpayer_id,product_code,unit,period_start,period_end,"
            "opening_stock,purchases,sales,closing_stock,"
            "customer_returns,supplier_returns,own_use,write_offs\n"
            f"{buyer_id},TEST-PROD-001,piece,2026-01-01,"
            "2026-01-31,0,4,0,4,0,0,0,0\n"
            "SUPPLIER001,TEST-PROD-001,piece,2026-01-01,"
            "2026-01-31,4,0,4,0,0,0,0,0\n"
        ),
    }

    for filename, content in files.items():
        (tmp_path / filename).write_text(
            content, encoding="utf-8"
        )

    return EFRISDataset(tmp_path)
