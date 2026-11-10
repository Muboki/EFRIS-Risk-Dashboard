from collections.abc import Sequence

from src.dataset import EFRISDataset
from src.risk_rules import RiskResult, RiskRule
from dataclasses import dataclass

REVIEW_WEIGHTS = {
    "VAT misclassification": 40,
    "Purchases without sales": 25,
    "Possible price understatement": 20,
    "Business-profile mismatch": 15,
}

@dataclass(frozen=True)
class TaxpayerPriority:
    """Explain the review points assigned to one taxpayer."""

    taxpayer_id: str
    flagged_findings: int
    rule_points: tuple[tuple[str, int], ...]

    @property
    def total_points(self) -> int:
        return sum(points for _, points in self.rule_points)
    
class RiskEngine:
    """Run compliance risk checks through a shared interface."""

    def __init__(self, rules: Sequence[RiskRule]) -> None:
        if not rules:
            raise ValueError("At least one risk rule is required.")

        if any(not isinstance(rule, RiskRule) for rule in rules):
            raise TypeError("Every rule must inherit from RiskRule.")

        self._rules = tuple(rules)

    def run(self, dataset: EFRISDataset) -> list[RiskResult]:
        """Collect explained results from all supplied risk rules."""
        results: list[RiskResult] = []

        for rule in self._rules:
            results.extend(rule.evaluate(dataset))

        return results

    @staticmethod
    def rank_for_review(
        results: Sequence[RiskResult],
    ) -> list[TaxpayerPriority]:
        """Rank taxpayers with flagged findings by distinct risk checks."""

        grouped: dict[str, list[RiskResult]] = {}

        for result in results:
            if result.status == "Flagged":
                grouped.setdefault(result.taxpayer_id, []).append(result)

        priorities: list[TaxpayerPriority] = []

        for taxpayer_id, findings in grouped.items():
            triggered_rules = {finding.rule_name for finding in findings}
            missing = triggered_rules.difference(REVIEW_WEIGHTS)

            if missing:
                raise ValueError(
                    "No review weight configured for: "
                    + ", ".join(sorted(missing))
                )

            rule_points = tuple(
                (name, points)
                for name, points in REVIEW_WEIGHTS.items()
                if name in triggered_rules
            )

            priorities.append(
                TaxpayerPriority(
                    taxpayer_id=taxpayer_id,
                    flagged_findings=len(findings),
                    rule_points=rule_points,
                )
            )

        return sorted(
            priorities,
            key=lambda item: (-item.total_points, item.taxpayer_id),
        )