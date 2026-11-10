from csv import DictReader
from datetime import date
from pathlib import Path

import pytest

from src.dataset import EFRISDataset
from src.risk_engine import RiskEngine
from src.risk_rules import (
    BusinessActivityRule,
    PriceDeviationRule,
    PurchaseSalesRule,
    RiskResult,
    VATClassificationRule,
)


DATA_FOLDER = Path(__file__).resolve().parents[1] / "data"

with (DATA_FOLDER / "demo_case_labels.csv").open(
    encoding="utf-8-sig", newline=""
) as file:
    CASES = list(DictReader(file))

CASE_IDS = [case["case_id"] for case in CASES]


@pytest.fixture(scope="module")
def demo_results() -> list[RiskResult]:
    """Run the four checks once against the demonstration data."""

    dataset = EFRISDataset(DATA_FOLDER)
    engine = RiskEngine(
        [
            VATClassificationRule(),
            PurchaseSalesRule(date(2026, 1, 1), date(2026, 1, 31)),
            BusinessActivityRule(),
            PriceDeviationRule(),
        ]
    )
    return engine.run(dataset)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_demo_case_matches_expected_result(
    case: dict[str, str],
    demo_results: list[RiskResult],
) -> None:
    line_number = int(case["line_number"]) if case["line_number"] else None

    matches = [
        result
        for result in demo_results
        if result.rule_name == case["rule_name"]
        and result.taxpayer_id == case["taxpayer_id"]
        and result.product_code == case["product_code"]
        and result.record_type == case["record_type"]
        and result.record_id == (case["record_id"] or None)
        and result.fdn == (case["fdn"] or None)
        and result.line_number == line_number
    ]

    assert len(matches) == 1, (
        f"{case['case_id']}: expected one matching result, "
        f"found {len(matches)}."
    )

    result = matches[0]
    assert result.status == case["expected_status"], (
        f"{case['case_id']}: expected {case['expected_status']}, "
        f"got {result.status}. Explanation: {result.reason}"
    )