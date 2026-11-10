from dataclasses import replace

from datetime import date

import pytest

from src.models import BusinessActivityEvidence

from src.dataset import EFRISDataset
from src.risk_engine import RiskEngine
from src.risk_rules import BusinessActivityRule


def test_matching_business_activity_is_not_flagged(
    sample_dataset: EFRISDataset,
) -> None:
    results = RiskEngine([BusinessActivityRule()]).run(sample_dataset)

    assert len(results) == 1
    assert results[0].status == "Not flagged"


def test_unexplained_business_activity_mismatch_is_flagged(
    sample_dataset: EFRISDataset,
) -> None:
    sample_dataset.product_references[0] = replace(
        sample_dataset.product_references[0],
        category="Electronics",
    )

    results = RiskEngine([BusinessActivityRule()]).run(sample_dataset)

    assert len(results) == 1

    result = results[0]

    assert result.status == "Flagged"
    assert result.taxpayer_id == "TEST001"
    assert result.fdn == "TEST-FDN-001"
    assert result.line_number == 1
    assert result.product_code == "TEST-PROD-001"
    assert result.estimated_vat_difference is None
    assert "Electronics" in result.reason
    assert "Hardware" in result.reason

@pytest.mark.parametrize(
    ("evidence_type", "fdn", "line_number"),
    [
        ("Diversification", None, None),
        ("Asset disposal", "TEST-FDN-001", 1),
    ],
)
def test_valid_activity_evidence_prevents_a_flag(
    sample_dataset: EFRISDataset,
    evidence_type: str,
    fdn: str | None,
    line_number: int | None,
) -> None:
    sample_dataset.product_references[0] = replace(
        sample_dataset.product_references[0],
        category="Electronics",
    )

    sample_dataset.business_activity_evidence = [
        BusinessActivityEvidence(
            record_id="TEST-EVIDENCE-001",
            taxpayer_id="TEST001",
            category="Electronics",
            evidence_type=evidence_type,
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 6, 30),
            evidence_reference="TEST-DOC-001",
            reason="Supporting evidence for a simulated sale",
            fdn=fdn,
            line_number=line_number,
        )
    ]

    results = RiskEngine([BusinessActivityRule()]).run(sample_dataset)

    assert len(results) == 1

    result = results[0]

    assert result.status == "Not flagged"
    assert "TEST-EVIDENCE-001" in result.reason
    assert "TEST-DOC-001" in result.reason

def test_asset_disposal_evidence_only_covers_its_invoice_line(
    sample_dataset: EFRISDataset,
) -> None:
    sample_dataset.product_references[0] = replace(
        sample_dataset.product_references[0],
        category="Electronics",
    )

    second_document = replace(
        sample_dataset.documents[0],
        fdn="TEST-FDN-002",
    )
    sample_dataset.documents.append(second_document)
    sample_dataset.documents_by_fdn[second_document.fdn] = second_document

    original_line = sample_dataset.lines[0]

    sample_dataset.lines.extend(
        [
            replace(original_line, line_number=2),
            replace(original_line, fdn=second_document.fdn),
        ]
    )

    sample_dataset.business_activity_evidence = [
        BusinessActivityEvidence(
            record_id="TEST-EVIDENCE-001",
            taxpayer_id="TEST001",
            category="Electronics",
            evidence_type="Asset disposal",
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 6, 30),
            evidence_reference="TEST-ASSET-DOC-001",
            reason="Evidence for this specific invoice line",
            fdn="TEST-FDN-001",
            line_number=1,
        )
    ]

    results = RiskEngine([BusinessActivityRule()]).run(sample_dataset)

    assert len(results) == 3

    statuses = {
        (result.fdn, result.line_number): result.status
        for result in results
    }

    assert statuses == {
        ("TEST-FDN-001", 1): "Not flagged",
        ("TEST-FDN-001", 2): "Flagged",
        ("TEST-FDN-002", 1): "Flagged",
    }

@pytest.mark.parametrize(
    ("valid_from", "valid_to", "expected_status"),
    [
        (date(2026, 1, 1), date(2026, 1, 9), "Flagged"),
        (date(2026, 1, 11), date(2026, 6, 30), "Flagged"),
        (date(2026, 1, 10), date(2026, 6, 30), "Not flagged"),
        (date(2026, 1, 1), date(2026, 1, 10), "Not flagged"),
    ],
    ids=[
        "expired",
        "not_yet_valid",
        "first_valid_day",
        "last_valid_day",
    ],
)
def test_activity_evidence_must_cover_invoice_date(
    sample_dataset: EFRISDataset,
    valid_from: date,
    valid_to: date,
    expected_status: str,
) -> None:
    sample_dataset.product_references[0] = replace(
        sample_dataset.product_references[0],
        category="Electronics",
    )

    sample_dataset.business_activity_evidence = [
        BusinessActivityEvidence(
            record_id="TEST-EVIDENCE-001",
            taxpayer_id="TEST001",
            category="Electronics",
            evidence_type="Diversification",
            valid_from=valid_from,
            valid_to=valid_to,
            evidence_reference="TEST-DATE-DOC-001",
            reason="Supporting evidence with a defined validity period",
        )
    ]

    results = RiskEngine([BusinessActivityRule()]).run(sample_dataset)

    assert len(results) == 1
    assert results[0].status == expected_status

def test_missing_category_reference_is_insufficient(
    sample_dataset: EFRISDataset,
) -> None:
    sample_dataset.product_references = []

    results = RiskEngine([BusinessActivityRule()]).run(sample_dataset)

    assert len(results) == 1
    assert results[0].status == "Insufficient data"
    assert results[0].estimated_vat_difference is None


def test_conflicting_category_references_are_insufficient(
    sample_dataset: EFRISDataset,
) -> None:
    sample_dataset.product_references.append(
        replace(
            sample_dataset.product_references[0],
            category="Electronics",
            supply_condition="Other simulated supply condition",
        )
    )

    results = RiskEngine([BusinessActivityRule()]).run(sample_dataset)

    assert len(results) == 1

    result = results[0]

    assert result.status == "Insufficient data"
    assert "hardware" in result.reason.casefold()
    assert "electronics" in result.reason.casefold()

