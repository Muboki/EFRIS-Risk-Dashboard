from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from datetime import date
from src.models import (
    BusinessActivityEvidence,
    FiscalDocument,
    InvoiceLine,
    StockLedger,
)

from src.dataset import EFRISDataset


RiskStatus = Literal[
    "Flagged",
    "Not flagged",
    "Insufficient data",
]


@dataclass(frozen=True)
class RiskResult:
    """Store an explained outcome from a compliance risk check."""

    rule_name: str
    taxpayer_id: str
    status: RiskStatus
    reason: str
    fdn: str | None = None
    line_number: int | None = None
    product_code: str | None = None
    estimated_vat_difference: Decimal | None = None
    related_fdns: tuple[str, ...] = ()
    record_type: str = "Invoice line"
    record_id: str | None = None
    source_fdn: str | None = None
    source_line_number: int | None = None

    def __post_init__(self) -> None:
        """Validate the status and required identifying details."""
        if self.status not in (
            "Flagged",
            "Not flagged",
            "Insufficient data",
        ):
            raise ValueError("Invalid risk result status.")

        for field_name in (
            "rule_name",
            "taxpayer_id",
            "reason",
            "record_type",
        ):
            value = getattr(self, field_name)

            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must contain text.")


class RiskRule(ABC):
    """Define the interface shared by all compliance risk checks."""

    @abstractmethod
    def evaluate(self, dataset: EFRISDataset) -> list[RiskResult]:
        """Evaluate relevant records and return explained results."""
        raise NotImplementedError

class VATClassificationRule(RiskRule):
    """Compare invoice VAT details with applicable dated references."""

    def evaluate(self, dataset: EFRISDataset) -> list[RiskResult]:
        """Check VAT categories and amounts for VAT-registered sellers."""
        results: list[RiskResult] = []

        for line in dataset.lines:
            document = dataset.documents_by_fdn[line.fdn]
            seller = dataset.taxpayers_by_id[document.seller_id]

            if not seller.vat_registered:
                continue

            matches = [
                reference
                for reference in dataset.product_references
                if reference.product_code == line.product_code
                and reference.unit == line.unit
                and reference.supply_condition == document.supply_condition
                and reference.is_valid_on(document.issue_date)
            ]

            status: RiskStatus = "Insufficient data"
            estimated_difference: Decimal | None = None

            if document.supply_condition is None:
                reason = "Supply conditions are missing from the invoice."

            elif not matches:
                reason = (
                    "No reference matches this product, unit, invoice "
                    "date and supply conditions."
                )

            elif len(matches) > 1:
                reason = "More than one applicable reference was found."

            else:
                reference = matches[0]

                expected_vat = (
                    line.net_amount * reference.vat_rate
                ).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                )

                recorded_vat = line.vat_amount.quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                )

                issues: list[str] = []

                if line.vat_category != reference.expected_vat_category:
                    issues.append(
                        f"Recorded category '{line.vat_category}' differs "
                        f"from reference '{reference.expected_vat_category}'"
                    )

                if recorded_vat != expected_vat:
                    issues.append(
                        f"Recorded VAT is UGX {recorded_vat:,.2f}; "
                        f"reference VAT is UGX {expected_vat:,.2f}"
                    )

                status = "Flagged" if issues else "Not flagged"

                estimated_difference = max(
                    expected_vat - recorded_vat,
                    Decimal("0.00"),
                )

                if issues:
                    reason = (
                        "; ".join(issues)
                        + f". Reference: {reference.reference_source}."
                    )
                else:
                    reason = (
                        "VAT category and recorded amount match the "
                        f"dated reference ({reference.reference_source})."
                    )

            results.append(
                RiskResult(
                    rule_name="VAT misclassification",
                    taxpayer_id=document.seller_id,
                    status=status,
                    reason=reason,
                    fdn=document.fdn,
                    line_number=line.line_number,
                    product_code=line.product_code,
                    estimated_vat_difference=estimated_difference,
                    related_fdns=(document.fdn,),
                )
            )

        results.extend(self._evaluate_product_tax_records(dataset))
        return results

    def _evaluate_product_tax_records(
        self,
        dataset: EFRISDataset,
    ) -> list[RiskResult]:
        """Check recorded product classifications and find related sales."""
        results: list[RiskResult] = []

        for record in dataset.product_tax_records:
            taxpayer = dataset.taxpayers_by_id[record.taxpayer_id]

            if not taxpayer.vat_registered:
                continue

            matches = [
                reference
                for reference in dataset.product_references
                if reference.product_code == record.product_code
                and reference.unit == record.unit
                and reference.supply_condition == record.supply_condition
                and reference.is_valid_on(record.record_date)
            ]

            status: RiskStatus = "Insufficient data"
            related_fdns: set[str] = set()

            if record.supply_condition is None:
                reason = "Supply conditions are missing from this record."

            elif not matches:
                reason = (
                    "No reference matches this product, unit, record "
                    "date and supply conditions."
                )

            elif len(matches) > 1:
                reason = "More than one applicable reference was found."

            else:
                reference = matches[0]

                if record.vat_category == reference.expected_vat_category:
                    status = "Not flagged"
                    reason = (
                        f"{record.record_type} classification matches "
                        f"the reference on {record.record_date} "
                        f"({reference.reference_source})."
                    )

                else:
                    status = "Flagged"
                    reason = (
                        f"{record.record_type} record on "
                        f"{record.record_date} uses "
                        f"'{record.vat_category}'; the reference category "
                        f"is '{reference.expected_vat_category}'. "
                        f"Reference: {reference.reference_source}."
                    )

                    for line in dataset.lines:
                        document = dataset.documents_by_fdn[line.fdn]

                        if (
                            document.seller_id == record.taxpayer_id
                            and line.product_code == record.product_code
                            and line.unit == record.unit
                            and line.vat_category == record.vat_category
                            and document.supply_condition
                            == record.supply_condition
                            and record.record_date
                            <= document.issue_date
                            <= reference.valid_to
                        ):
                            related_fdns.add(document.fdn)

                    if related_fdns:
                        reason += (
                            " Matching sales using this VAT category: "
                            + ", ".join(sorted(related_fdns))
                            + "."
                        )
                    else:
                        reason += (
                            " No matching sales using this VAT category "
                            "were found in the reference period."
                        )

            results.append(
                RiskResult(
                    rule_name="VAT misclassification",
                    taxpayer_id=record.taxpayer_id,
                    status=status,
                    reason=reason,
                    product_code=record.product_code,
                    related_fdns=tuple(sorted(related_fdns)),
                    record_type=record.record_type,
                    record_id=record.record_id,
                    source_fdn=record.source_fdn,
                    source_line_number=record.source_line_number,
                )
            )

        return results

class PurchaseSalesRule(RiskRule):
    """Review repeated purchases without sales over a chosen period."""

    def __init__(
        self,
        period_start: date,
        period_end: date,
        minimum_purchase_days: int = 2,
    ) -> None:
        if (
            type(period_start) is not date
            or type(period_end) is not date
        ):
            raise ValueError(
                "Review period dates must be date objects."
            )

        if period_end < period_start:
            raise ValueError(
                "The review period cannot end before it starts."
            )

        if (
            type(minimum_purchase_days) is not int
            or minimum_purchase_days < 2
        ):
            raise ValueError(
                "Minimum purchase days must be an integer of at least 2."
            )

        self.period_start = period_start
        self.period_end = period_end
        self.minimum_purchase_days = minimum_purchase_days

    def _stock_coverage_issue(
        self,
        stock_records: list[StockLedger],
    ) -> str | None:
        """Check stock coverage for one taxpayer, product and unit."""

        if not stock_records:
            return (
                "No stock records were supplied for this product "
                "within the review period."
            )

        ordered = sorted(
            stock_records,
            key=lambda record: record.period_start,
        )

        if (
            ordered[0].period_start != self.period_start
            or ordered[-1].period_end != self.period_end
        ):
            return (
                f"Stock records must cover {self.period_start} "
                f"to {self.period_end} using complete stock periods."
            )

        for previous, current in zip(ordered, ordered[1:]):
            if (
                current.period_start.toordinal()
                != previous.period_end.toordinal() + 1
            ):
                return (
                    "Stock coverage contains a gap or overlap "
                    f"before {current.period_start}."
                )

            if current.opening_stock != previous.closing_stock:
                return (
                    f"Opening stock of {current.opening_stock} "
                    f"on {current.period_start} does not match "
                    f"the previous closing stock of "
                    f"{previous.closing_stock}."
                )

        return None

    def _invoice_quantity_issue(
        self,
        dataset: EFRISDataset,
        stock_records: list[StockLedger],
    ) -> str | None:
        """Compare stock movements with invoice quantities."""

        for record in stock_records:
            invoice_purchases = Decimal("0")
            invoice_sales = Decimal("0")

            for line in dataset.lines:
                if (
                    line.product_code != record.product_code
                    or line.unit != record.unit
                ):
                    continue

                document = dataset.documents_by_fdn[line.fdn]

                if not (
                    record.period_start
                    <= document.issue_date
                    <= record.period_end
                ):
                    continue

                if document.buyer_id == record.taxpayer_id:
                    invoice_purchases += line.quantity

                if document.seller_id == record.taxpayer_id:
                    invoice_sales += line.quantity

            for movement, ledger_quantity, invoice_quantity in (
                ("purchases", record.purchases, invoice_purchases),
                ("sales", record.sales, invoice_sales),
            ):
                if ledger_quantity != invoice_quantity:
                    return (
                        f"For {record.period_start} to "
                        f"{record.period_end}, the stock ledger "
                        f"records {movement} of {ledger_quantity} "
                        f"{record.unit}, but linked invoices total "
                        f"{invoice_quantity} {record.unit}."
                    )

        return None

    def _classify_pattern(
        self,
        stock_records: list[StockLedger],
        purchase_days: int,
    ) -> tuple[RiskStatus, str]:
        """Classify a pattern after stock and invoice checks pass."""

        total_sales = sum(
            (record.sales for record in stock_records),
            Decimal("0"),
        )

        if total_sales > 0:
            return (
                "Not flagged",
                f"Recorded sales total {total_sales} "
                f"{stock_records[0].unit} within the review period.",
            )

        if purchase_days < self.minimum_purchase_days:
            return (
                "Not flagged",
                f"Purchases occurred on {purchase_days} different "
                f"dates, below the threshold of "
                f"{self.minimum_purchase_days}.",
            )

        pattern = (
            f"Purchases occurred on {purchase_days} different dates "
            "with no recorded sales during the review period."
        )

        unbalanced_records = [
            record
            for record in stock_records
            if record.stock_difference != 0
        ]

        if unbalanced_records:
            details = "; ".join(
                f"{record.period_start} to {record.period_end}: "
                f"reported closing stock {record.closing_stock}, "
                f"expected {record.expected_closing_stock} "
                f"{record.unit}"
                for record in unbalanced_records
            )

            return (
                "Flagged",
                f"{pattern} Stock differences were also found: "
                f"{details}. Review the purchase invoices, "
                "stock counts and adjustments.",
            )

        final_record = max(
            stock_records,
            key=lambda record: record.period_end,
        )

        if final_record.closing_stock == 0:
            return (
                "Not flagged",
                f"{pattern} Recorded returns, own use or write-offs "
                "account for the available goods, leaving "
                "no closing stock.",
            )

        unit_label = final_record.unit

        if final_record.closing_stock != Decimal("1"):
            unit_label = {
                "piece": "pieces",
                "bag": "bags",
                "bottle": "bottles",
                "packet": "packets",
                "pair": "pairs",
            }.get(unit_label, unit_label)

        return (
            "Flagged",
            f"{pattern} Recorded stock movements balance, with "
            f"{final_record.closing_stock} {unit_label} "
            "remaining at period end. Stock accumulation may "
            "explain this pattern; further review is required.",
        )

    def evaluate(self, dataset: EFRISDataset) -> list[RiskResult]:
        """Review purchase patterns using invoices and stock records."""

        stock_by_key: dict[tuple[str, str, str], list[StockLedger]] = {}
        purchase_dates: dict[tuple[str, str, str], set[date]] = {}
        purchase_fdns: dict[tuple[str, str, str], set[str]] = {}

        for record in dataset.stock_records:
            if (
                record.period_start <= self.period_end
                and record.period_end >= self.period_start
            ):
                key = (
                    record.taxpayer_id,
                    record.product_code,
                    record.unit,
                )
                stock_by_key.setdefault(key, []).append(record)

        keys = set(stock_by_key)

        for line in dataset.lines:
            document = dataset.documents_by_fdn[line.fdn]

            if not (
                self.period_start
                <= document.issue_date
                <= self.period_end
            ):
                continue

            keys.add(
                (
                    document.seller_id,
                    line.product_code,
                    line.unit,
                )
            )

            buyer_id = document.buyer_id

            if buyer_id is not None:
                key = (buyer_id, line.product_code, line.unit)
                keys.add(key)

                purchase_dates.setdefault(key, set()).add(
                    document.issue_date
                )
                purchase_fdns.setdefault(key, set()).add(
                    document.fdn
                )

        results: list[RiskResult] = []

        for key in sorted(keys):
            taxpayer_id, product_code, unit = key
            taxpayer = dataset.taxpayers_by_id[taxpayer_id]

            if not taxpayer.vat_registered:
                continue

            stock_records = stock_by_key.get(key, [])

            issue = self._stock_coverage_issue(stock_records)

            if issue is None:
                issue = self._invoice_quantity_issue(
                    dataset, stock_records
                )

            status: RiskStatus

            if issue is not None:
                status = "Insufficient data"
                reason = issue
            else:
                status, reason = self._classify_pattern(
                    stock_records,
                    len(purchase_dates.get(key, set())),
                )

            results.append(
                RiskResult(
                    rule_name="Purchases without sales",
                    taxpayer_id=taxpayer_id,
                    status=status,
                    reason=(
                        f"Review period: {self.period_start} "
                        f"to {self.period_end}. {reason}"
                    ),
                    product_code=product_code,
                    record_type="Stock review",
                    record_id=(
                        f"{taxpayer_id}/{product_code}/{unit}/"
                        f"{self.period_start}/{self.period_end}"
                    ),
                    related_fdns=tuple(
                        sorted(purchase_fdns.get(key, set()))
                    ),
                )
            )

        return results

class BusinessActivityRule(RiskRule):
    """Compare sold categories with declared business activities."""

    def _matching_evidence(
        self,
        dataset: EFRISDataset,
        document: FiscalDocument,
        line: InvoiceLine,
        category: str,
    ) -> list[BusinessActivityEvidence]:
        """Find supporting evidence applicable to this sale."""

        matches: list[BusinessActivityEvidence] = []
        normalized_category = category.strip().casefold()

        for evidence in dataset.business_activity_evidence:
            if (
                evidence.taxpayer_id != document.seller_id
                or evidence.category.strip().casefold() != normalized_category
                or not evidence.is_valid_on(document.issue_date)
            ):
                continue

            if evidence.evidence_type == "Diversification":
                matches.append(evidence)

            elif (
                evidence.evidence_type == "Asset disposal"
                and evidence.fdn == line.fdn
                and evidence.line_number == line.line_number
            ):
                matches.append(evidence)

        return matches

    def evaluate(self, dataset: EFRISDataset) -> list[RiskResult]:
        """Review sales against declared activities and valid evidence."""

        results: list[RiskResult] = []

        for line in dataset.lines:
            document = dataset.documents_by_fdn[line.fdn]
            taxpayer = dataset.taxpayers_by_id[document.seller_id]

            if not taxpayer.vat_registered:
                continue

            references = [
                reference
                for reference in dataset.product_references
                if reference.product_code == line.product_code
                and reference.unit == line.unit
                and reference.is_valid_on(document.issue_date)
            ]

            categories = {
                reference.category.strip().casefold()
                for reference in references
            }

            status: RiskStatus

            if not references:
                status = "Insufficient data"
                reason = (
                    "No product category reference matches the "
                    "product, unit and invoice date."
                )

            elif len(categories) > 1:
                status = "Insufficient data"
                reason = (
                    "The dated product references give conflicting "
                    f"categories: {', '.join(sorted(categories))}."
                )

            else:
                category = references[0].category.strip()
                activity = taxpayer.business_activity.strip()

                if category.casefold() == activity.casefold():
                    status = "Not flagged"
                    reason = (
                        f"Sold category '{category}' matches declared "
                        f"business activity '{activity}'."
                    )

                else:
                    evidence = self._matching_evidence(
                        dataset, document, line, category
                    )

                    if evidence:
                        status = "Not flagged"

                        details = "; ".join(
                            f"{entry.evidence_type} {entry.record_id} "
                            f"(reference {entry.evidence_reference}; "
                            f"{entry.reason})"
                            for entry in evidence
                        )

                        reason = (
                            f"Declared activity: '{activity}'. "
                            f"Sale of category '{category}' is supported "
                            f"by the supplied evidence: {details}."
                        )

                    else:
                        status = "Flagged"
                        reason = (
                            f"Sold category '{category}' differs from "
                            f"declared business activity '{activity}'. "
                            "No applicable diversification or asset "
                            "disposal evidence was supplied. "
                            "Further review is required."
                        )

                sources = ", ".join(
                    sorted(
                        {
                            reference.reference_source
                            for reference in references
                        }
                    )
                )
                reason += f" Catalogue source: {sources}."

            results.append(
                RiskResult(
                    rule_name="Business-profile mismatch",
                    taxpayer_id=document.seller_id,
                    status=status,
                    reason=reason,
                    fdn=document.fdn,
                    line_number=line.line_number,
                    product_code=line.product_code,
                    related_fdns=(document.fdn,),
                )
            )

        return results

class PriceDeviationRule(RiskRule):
    """Identify unusually low prices using comparable price benchmarks."""

    def evaluate(self, dataset: EFRISDataset) -> list[RiskResult]:
        results: list[RiskResult] = []

        contexts = {
            (context.fdn, context.line_number): context
            for context in dataset.price_contexts
        }

        for line in dataset.lines:
            document = dataset.documents_by_fdn[line.fdn]
            taxpayer = dataset.taxpayers_by_id[document.seller_id]

            if not taxpayer.vat_registered:
                continue

            context = contexts.get((line.fdn, line.line_number))
            status: RiskStatus = "Insufficient data"

            if document.location is None:
                reason = "The sale location was not supplied."

            elif context is None:
                reason = "No price context was supplied for this invoice line."

            elif context.quality is None:
                reason = "Product quality was not supplied."

            elif context.discount_rate is None:
                reason = "Discount information was not supplied."

            elif context.discount_rate > 0 and (
                context.discount_reference is None
                or context.discount_reason is None
            ):
                reason = (
                    "A discount was recorded, but its supporting "
                    "reference or reason was not supplied."
                )

            elif context.discount_rate == Decimal("1") and (
                line.unit_price != Decimal("0")
            ):
                reason = (
                    "A 100% discount was recorded, but the final "
                    "unit price is not zero. The details require review."
                )

            else:
                matches = [
                    benchmark
                    for benchmark in dataset.price_benchmarks
                    if benchmark.product_code == line.product_code
                    and benchmark.unit == line.unit
                    and benchmark.business_type == taxpayer.business_type
                    and benchmark.location.casefold()
                    == document.location.casefold()
                    and benchmark.quality.casefold()
                    == context.quality.casefold()
                    and benchmark.vat_basis == "VAT-exclusive"
                    and benchmark.is_valid_on(document.issue_date)
                ]

                if not matches:
                    reason = (
                        "No price benchmark matches the product, unit, "
                        "business type, location, quality, invoice date "
                        "and VAT-exclusive basis."
                    )

                elif len(matches) > 1:
                    reason = (
                        "Multiple price benchmarks match this sale. "
                        "A single applicable reference is required."
                    )

                else:
                    benchmark = matches[0]
                    discount_factor = Decimal("1") - context.discount_rate

                    minimum_price = (
                        benchmark.minimum_unit_price * discount_factor
                    ).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )

                    maximum_price = (
                        benchmark.maximum_unit_price * discount_factor
                    ).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )

                    recorded_price = line.unit_price.quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )

                    if recorded_price < minimum_price:
                        status = "Flagged"
                        explanation = (
                            "The recorded price is below the comparable "
                            "minimum; further review is required."
                        )
                    else:
                        status = "Not flagged"
                        explanation = (
                            "The recorded price is not below the "
                            "comparable minimum."
                        )

                    reason = (
                        f"Recorded unit price: UGX {recorded_price:,.2f}. "
                        f"Comparable range: UGX {minimum_price:,.2f} "
                        f"to {maximum_price:,.2f}. "
                        f"Comparison: {taxpayer.business_type}; "
                        f"{document.location}; quality {context.quality}; "
                        f"unit {line.unit}; VAT-exclusive. "
                        f"{explanation} "
                        f"Benchmark: {benchmark.benchmark_id}, valid "
                        f"{benchmark.valid_from} to {benchmark.valid_to}. "
                        f"Source: {benchmark.reference_source}."
                    )

                    if context.discount_rate > 0:
                        reason += (
                            " Reference range adjusted for the supplied "
                            f"{context.discount_rate * Decimal('100'):.2f}% "
                            f"discount (reference "
                            f"{context.discount_reference}; "
                            f"{context.discount_reason})."
                        )
                    else:
                        reason += " No discount was recorded."

            results.append(
                RiskResult(
                    rule_name="Possible price understatement",
                    taxpayer_id=document.seller_id,
                    status=status,
                    reason=reason,
                    fdn=document.fdn,
                    line_number=line.line_number,
                    product_code=line.product_code,
                    related_fdns=(document.fdn,),
                )
            )

        return results