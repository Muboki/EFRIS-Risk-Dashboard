from csv import DictReader
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from src.models import PriceBenchmark
from src.models import InvoicePriceContext

from src.models import (
    FiscalDocument,
    InvoiceLine,
    ProductReference,
    ProductTaxRecord,
    StockLedger,
    Taxpayer,
    BusinessActivityEvidence,
)

class TaxpayerRepository:
    """Load and validate taxpayer records from a CSV file."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)

    def load(self) -> list[Taxpayer]:
        """Read the file and return validated taxpayer objects."""
        taxpayers: list[Taxpayer] = []
        seen_ids: set[str] = set()

        required_fields = {
            "taxpayer_id",
            "business_name",
            "business_type",
            "business_activity",
            "vat_registered",
        }

        with self.file_path.open(
            encoding="utf-8-sig", newline=""
        ) as file:
            reader = DictReader(file)
            headers = reader.fieldnames or []

            if len(headers) != len(set(headers)):
                raise ValueError("The CSV contains duplicate column names.")

            missing = required_fields - set(headers)
            if missing:
                raise ValueError(
                    f"Missing columns: {', '.join(sorted(missing))}"
                )

            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError(
                        f"Row {row_number} contains extra values."
                    )

                data = {
                    key: (row.get(key) or "").strip()
                    for key in required_fields
                }

                vat_status = data["vat_registered"].lower()
                if vat_status not in ("true", "false"):
                    raise ValueError(
                        f"Row {row_number}: VAT status must be True or False."
                    )

                try:
                    taxpayer = Taxpayer(
                        taxpayer_id=data["taxpayer_id"],
                        business_name=data["business_name"],
                        business_type=data["business_type"],
                        business_activity=data["business_activity"],
                        vat_registered=vat_status == "true",
                    )
                except ValueError as error:
                    raise ValueError(
                        f"Row {row_number}: {error}"
                    ) from error

                if taxpayer.taxpayer_id in seen_ids:
                    raise ValueError(
                        f"Row {row_number}: duplicate taxpayer ID "
                        f"{taxpayer.taxpayer_id}."
                    )

                seen_ids.add(taxpayer.taxpayer_id)
                taxpayers.append(taxpayer)

        return taxpayers

class FiscalDocumentRepository:
    """Load and validate invoice headers from a CSV file."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)

    def load(self) -> list[FiscalDocument]:
        """Return invoice headers with valid details and unique FDNs."""
        documents: list[FiscalDocument] = []
        seen_fdns: set[str] = set()

        required_fields = {
            "fdn",
            "seller_id",
            "issue_date",
            "buyer_id",
        }

        with self.file_path.open(
            encoding="utf-8-sig", newline=""
        ) as file:
            reader = DictReader(file)
            headers = reader.fieldnames or []

            if len(headers) != len(set(headers)):
                raise ValueError("The CSV contains duplicate column names.")

            missing = required_fields - set(headers)
            if missing:
                raise ValueError(
                    f"Missing columns: {', '.join(sorted(missing))}"
                )

            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError(
                        f"Row {row_number} contains extra values."
                    )

                data = {
                    key: (row.get(key) or "").strip()
                    for key in required_fields
                }

                try:
                     document = FiscalDocument(
                        fdn=data["fdn"],
                        seller_id=data["seller_id"],
                        issue_date=date.fromisoformat(data["issue_date"]),
                        buyer_id=data["buyer_id"] or None,
                        supply_condition=(
                            (row.get("supply_condition") or "").strip()
                            or None
                        ),
                        location=(
                            (row.get("location") or "").strip()
                            or None
                        ),
                    )
                except ValueError as error:
                    raise ValueError(
                        f"Row {row_number}: {error}"
                    ) from error

                if document.fdn in seen_fdns:
                    raise ValueError(
                        f"Row {row_number}: duplicate invoice FDN "
                        f"{document.fdn}."
                    )

                seen_fdns.add(document.fdn)
                documents.append(document)

        return documents

class InvoiceLineRepository:
    """Load and validate invoice product lines from a CSV file."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)

    def load(self) -> list[InvoiceLine]:
        """Return validated lines without duplicate FDN-line pairs."""
        lines: list[InvoiceLine] = []
        seen_keys: set[tuple[str, int]] = set()

        required_fields = {
            "fdn",
            "line_number",
            "product_code",
            "unit",
            "quantity",
            "unit_price",
            "vat_category",
            "vat_amount",
        }

        with self.file_path.open(
            encoding="utf-8-sig", newline=""
        ) as file:
            reader = DictReader(file)
            headers = reader.fieldnames or []

            if len(headers) != len(set(headers)):
                raise ValueError("The CSV contains duplicate column names.")

            missing = required_fields - set(headers)
            if missing:
                raise ValueError(
                    f"Missing columns: {', '.join(sorted(missing))}"
                )

            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError(
                        f"Row {row_number} contains extra values."
                    )

                data = {
                    key: (row.get(key) or "").strip()
                    for key in required_fields
                }

                try:
                    line = InvoiceLine(
                        fdn=data["fdn"],
                        line_number=int(data["line_number"]),
                        product_code=data["product_code"],
                        unit=data["unit"],
                        quantity=Decimal(data["quantity"]),
                        unit_price=Decimal(data["unit_price"]),
                        vat_category=data["vat_category"],
                        vat_amount=Decimal(data["vat_amount"]),
                    )
                except (ValueError, InvalidOperation) as error:
                    raise ValueError(
                        f"Row {row_number}: invalid invoice line: {error}"
                    ) from error

                key = (line.fdn, line.line_number)

                if key in seen_keys:
                    raise ValueError(
                        f"Row {row_number}: duplicate line "
                        f"{line.line_number} for invoice {line.fdn}."
                    )

                seen_keys.add(key)
                lines.append(line)

        return lines

class ProductReferenceRepository:
    """Load and validate dated product references from a CSV file."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)

    def load(self) -> list[ProductReference]:
        """Return references without overlapping validity periods."""
        references: list[ProductReference] = []

        groups: dict[
            tuple[str, str, str], list[ProductReference]
        ] = {}

        required_fields = {
            "product_code",
            "product_name",
            "category",
            "unit",
            "expected_vat_category",
            "vat_rate",
            "valid_from",
            "valid_to",
            "supply_condition",
            "reference_source",
        }

        with self.file_path.open(
            encoding="utf-8-sig", newline=""
        ) as file:
            reader = DictReader(file)
            headers = reader.fieldnames or []

            if len(headers) != len(set(headers)):
                raise ValueError("The CSV contains duplicate column names.")

            missing = required_fields - set(headers)
            if missing:
                raise ValueError(
                    f"Missing columns: {', '.join(sorted(missing))}"
                )

            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError(
                        f"Row {row_number} contains extra values."
                    )

                data = {
                    key: (row.get(key) or "").strip()
                    for key in required_fields
                }

                try:
                    reference = ProductReference(
                        product_code=data["product_code"],
                        product_name=data["product_name"],
                        category=data["category"],
                        unit=data["unit"],
                        expected_vat_category=data[
                            "expected_vat_category"
                        ],
                        vat_rate=Decimal(data["vat_rate"]),
                        valid_from=date.fromisoformat(data["valid_from"]),
                        valid_to=date.fromisoformat(data["valid_to"]),
                        supply_condition=data["supply_condition"],
                        reference_source=data["reference_source"],
                    )
                except (ValueError, InvalidOperation) as error:
                    raise ValueError(
                        f"Row {row_number}: invalid product reference: "
                        f"{error}"
                    ) from error

                key = (
                    reference.product_code,
                    reference.unit,
                    reference.supply_condition,
                )

                previous_references = groups.setdefault(key, [])

                for previous in previous_references:
                    if (
                        reference.valid_from <= previous.valid_to
                        and previous.valid_from <= reference.valid_to
                    ):
                        raise ValueError(
                            f"Row {row_number}: overlapping reference "
                            f"dates for {reference.product_code} "
                            f"({reference.unit}, "
                            f"{reference.supply_condition})."
                        )

                previous_references.append(reference)
                references.append(reference)

        return references

class ProductTaxRecordRepository:
    """Load product registration and stocking-in classifications."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)

    def load(self) -> list[ProductTaxRecord]:
        """Return validated records with unique record identifiers."""
        records: list[ProductTaxRecord] = []
        seen_ids: set[str] = set()

        required_fields = {
            "record_id",
            "taxpayer_id",
            "record_type",
            "record_date",
            "product_code",
            "unit",
            "vat_category",
            "supply_condition",
            "source_fdn",
            "source_line_number",
        }

        with self.file_path.open(
            encoding="utf-8-sig", newline=""
        ) as file:
            reader = DictReader(file)
            headers = reader.fieldnames or []

            if len(headers) != len(set(headers)):
                raise ValueError("The CSV contains duplicate column names.")

            missing = required_fields - set(headers)
            if missing:
                raise ValueError(
                    f"Missing columns: {', '.join(sorted(missing))}"
                )

            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError(
                        f"Row {row_number} contains extra values."
                    )

                data = {
                    key: (row.get(key) or "").strip()
                    for key in required_fields
                }

                try:
                    record = ProductTaxRecord(
                        record_id=data["record_id"],
                        taxpayer_id=data["taxpayer_id"],
                        record_type=data["record_type"],
                        record_date=date.fromisoformat(
                            data["record_date"]
                        ),
                        product_code=data["product_code"],
                        unit=data["unit"],
                        vat_category=data["vat_category"],
                        supply_condition=data["supply_condition"] or None,
                        source_fdn=data["source_fdn"] or None,
                        source_line_number=(
                            int(data["source_line_number"])
                            if data["source_line_number"]
                            else None
                        ),
                    )
                except ValueError as error:
                    raise ValueError(
                        f"Row {row_number}: invalid product tax record: "
                        f"{error}"
                    ) from error

                if record.record_id in seen_ids:
                    raise ValueError(
                        f"Row {row_number}: duplicate product tax record "
                        f"ID {record.record_id}."
                    )

                seen_ids.add(record.record_id)
                records.append(record)

        return records

class StockLedgerRepository:
    """Read and validate stock records from a CSV file."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)

    def load(self) -> list[StockLedger]:
        required_fields = {
            "taxpayer_id",
            "product_code",
            "unit",
            "period_start",
            "period_end",
            "opening_stock",
            "purchases",
            "sales",
            "closing_stock",
            "customer_returns",
            "supplier_returns",
            "own_use",
            "write_offs",
        }

        records: list[StockLedger] = []
        grouped_records: dict[
            tuple[str, str, str], list[StockLedger]
        ] = {}

        with self.file_path.open(
            encoding="utf-8-sig", newline=""
        ) as file:
            reader = DictReader(file)
            headers = reader.fieldnames or []

            if len(headers) != len(set(headers)):
                raise ValueError(
                    "The CSV contains duplicate column names."
                )

            missing = required_fields - set(headers)

            if missing:
                raise ValueError(
                    f"Missing columns: {', '.join(sorted(missing))}"
                )

            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError(
                        f"Row {row_number} contains extra values."
                    )

                data = {
                    field_name: (row.get(field_name) or "").strip()
                    for field_name in required_fields
                }

                try:
                    record = StockLedger(
                        taxpayer_id=data["taxpayer_id"],
                        product_code=data["product_code"],
                        unit=data["unit"],
                        period_start=date.fromisoformat(
                            data["period_start"]
                        ),
                        period_end=date.fromisoformat(
                            data["period_end"]
                        ),
                        opening_stock=Decimal(data["opening_stock"]),
                        purchases=Decimal(data["purchases"]),
                        sales=Decimal(data["sales"]),
                        closing_stock=Decimal(data["closing_stock"]),
                        customer_returns=Decimal(
                            data["customer_returns"]
                        ),
                        supplier_returns=Decimal(
                            data["supplier_returns"]
                        ),
                        own_use=Decimal(data["own_use"]),
                        write_offs=Decimal(data["write_offs"]),
                    )
                except (ValueError, InvalidOperation) as error:
                    raise ValueError(
                        f"Row {row_number}: {error}"
                    ) from error

                key = (
                    record.taxpayer_id,
                    record.product_code,
                    record.unit,
                )
                previous_records = grouped_records.setdefault(key, [])

                if any(
                    record.period_start <= previous.period_end
                    and previous.period_start <= record.period_end
                    for previous in previous_records
                ):
                    raise ValueError(
                        f"Row {row_number}: overlapping stock periods "
                        f"for {record.taxpayer_id}, "
                        f"{record.product_code} ({record.unit})."
                    )

                previous_records.append(record)
                records.append(record)

        return records

class BusinessActivityEvidenceRepository:
    """Read supporting evidence for business activity checks."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)

    def load(self) -> list[BusinessActivityEvidence]:
        required_fields = {
            "record_id",
            "taxpayer_id",
            "category",
            "evidence_type",
            "valid_from",
            "valid_to",
            "evidence_reference",
            "reason",
            "fdn",
            "line_number",
        }

        records: list[BusinessActivityEvidence] = []
        seen_ids: set[str] = set()

        with self.file_path.open(
            encoding="utf-8-sig", newline=""
        ) as file:
            reader = DictReader(file)
            headers = reader.fieldnames or []

            if len(headers) != len(set(headers)):
                raise ValueError(
                    "The CSV contains duplicate column names."
                )

            missing = required_fields - set(headers)

            if missing:
                raise ValueError(
                    f"Missing columns: {', '.join(sorted(missing))}"
                )

            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError(
                        f"Row {row_number} contains extra values."
                    )

                data = {
                    field_name: (row.get(field_name) or "").strip()
                    for field_name in required_fields
                }

                try:
                    record = BusinessActivityEvidence(
                        record_id=data["record_id"],
                        taxpayer_id=data["taxpayer_id"],
                        category=data["category"],
                        evidence_type=data["evidence_type"],
                        valid_from=date.fromisoformat(
                            data["valid_from"]
                        ),
                        valid_to=date.fromisoformat(
                            data["valid_to"]
                        ),
                        evidence_reference=data["evidence_reference"],
                        reason=data["reason"],
                        fdn=data["fdn"] or None,
                        line_number=(
                            int(data["line_number"])
                            if data["line_number"]
                            else None
                        ),
                    )
                except ValueError as error:
                    raise ValueError(
                        f"Row {row_number}: {error}"
                    ) from error

                if record.record_id in seen_ids:
                    raise ValueError(
                        f"Row {row_number}: duplicate evidence "
                        f"record ID {record.record_id}."
                    )

                seen_ids.add(record.record_id)
                records.append(record)

        return records

class PriceBenchmarkRepository:
    """Load and validate price benchmarks from a CSV file."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)

    def load(self) -> list[PriceBenchmark]:
        required_columns = {
            "benchmark_id",
            "product_code",
            "unit",
            "business_type",
            "location",
            "quality",
            "vat_basis",
            "minimum_unit_price",
            "maximum_unit_price",
            "valid_from",
            "valid_to",
            "reference_source",
        }

        benchmarks: list[PriceBenchmark] = []
        seen_ids: set[str] = set()
        groups: dict[tuple[str, ...], list[PriceBenchmark]] = {}

        with self.file_path.open(
            encoding="utf-8-sig", newline=""
        ) as file:
            reader = DictReader(file)
            headers = reader.fieldnames or []

            if len(headers) != len(set(headers)):
                raise ValueError("Duplicate column names are not allowed.")

            missing = required_columns - set(headers)

            if missing:
                raise ValueError(
                    f"Missing columns: {', '.join(sorted(missing))}"
                )

            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError(
                        f"Row {row_number}: too many values."
                    )

                values = {
                    name: (row.get(name) or "").strip()
                    for name in required_columns
                }

                try:
                    benchmark = PriceBenchmark(
                        benchmark_id=values["benchmark_id"],
                        product_code=values["product_code"],
                        unit=values["unit"],
                        business_type=values["business_type"],
                        location=values["location"],
                        quality=values["quality"],
                        vat_basis=values["vat_basis"],
                        minimum_unit_price=Decimal(
                            values["minimum_unit_price"]
                        ),
                        maximum_unit_price=Decimal(
                            values["maximum_unit_price"]
                        ),
                        valid_from=date.fromisoformat(
                            values["valid_from"]
                        ),
                        valid_to=date.fromisoformat(
                            values["valid_to"]
                        ),
                        reference_source=values["reference_source"],
                    )
                except (ValueError, InvalidOperation) as error:
                    raise ValueError(
                        f"Row {row_number}: {error}"
                    ) from error

                if benchmark.benchmark_id in seen_ids:
                    raise ValueError(
                        f"Row {row_number}: duplicate benchmark ID "
                        f"{benchmark.benchmark_id}."
                    )

                key = (
                    benchmark.product_code,
                    benchmark.unit,
                    benchmark.business_type,
                    benchmark.location.casefold(),
                    benchmark.quality.casefold(),
                    benchmark.vat_basis,
                )

                for existing in groups.get(key, []):
                    if (
                        benchmark.valid_from <= existing.valid_to
                        and existing.valid_from <= benchmark.valid_to
                    ):
                        raise ValueError(
                            f"Row {row_number}: benchmark "
                            f"{benchmark.benchmark_id} overlaps "
                            f"{existing.benchmark_id} for the "
                            "same comparison context."
                        )

                seen_ids.add(benchmark.benchmark_id)
                groups.setdefault(key, []).append(benchmark)
                benchmarks.append(benchmark)

        return benchmarks

class InvoicePriceContextRepository:
    """Load quality and discount details for invoice lines."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)

    def load(self) -> list[InvoicePriceContext]:
        required_columns = {
            "fdn",
            "line_number",
            "quality",
            "discount_rate",
            "discount_reference",
            "discount_reason",
        }

        contexts: list[InvoicePriceContext] = []
        seen_keys: set[tuple[str, int]] = set()

        with self.file_path.open(
            encoding="utf-8-sig", newline=""
        ) as file:
            reader = DictReader(file)
            headers = reader.fieldnames or []

            if len(headers) != len(set(headers)):
                raise ValueError("Duplicate column names are not allowed.")

            missing = required_columns - set(headers)

            if missing:
                raise ValueError(
                    f"Missing columns: {', '.join(sorted(missing))}"
                )

            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError(
                        f"Row {row_number}: too many values."
                    )

                values = {
                    name: (row.get(name) or "").strip()
                    for name in required_columns
                }

                try:
                    context = InvoicePriceContext(
                        fdn=values["fdn"],
                        line_number=int(values["line_number"]),
                        quality=values["quality"] or None,
                        discount_rate=(
                            Decimal(values["discount_rate"])
                            if values["discount_rate"]
                            else None
                        ),
                        discount_reference=(
                            values["discount_reference"] or None
                        ),
                        discount_reason=(
                            values["discount_reason"] or None
                        ),
                    )
                except (ValueError, InvalidOperation) as error:
                    raise ValueError(
                        f"Row {row_number}: {error}"
                    ) from error

                key = (context.fdn, context.line_number)

                if key in seen_keys:
                    raise ValueError(
                        f"Row {row_number}: duplicate price context "
                        f"for {context.fdn}, line {context.line_number}."
                    )

                seen_keys.add(key)
                contexts.append(context)

        return contexts

