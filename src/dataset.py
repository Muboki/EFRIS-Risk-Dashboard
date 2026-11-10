from pathlib import Path

from src.repositories import (
    FiscalDocumentRepository,
    InvoiceLineRepository,
    ProductReferenceRepository,
    ProductTaxRecordRepository,
    StockLedgerRepository,
    TaxpayerRepository,
    BusinessActivityEvidenceRepository,
    InvoicePriceContextRepository,
    PriceBenchmarkRepository,
)

class EFRISDataset:
    """Load taxpayer and invoice records and validate their links."""

    def __init__(self, data_folder: str | Path) -> None:
        folder = Path(data_folder)

        self.taxpayers = TaxpayerRepository(
            folder / "taxpayers.csv"
        ).load()

        self.documents = FiscalDocumentRepository(
            folder / "fiscal_documents.csv"
        ).load()

        self.lines = InvoiceLineRepository(
            folder / "invoice_lines.csv"
        ).load()

        self.product_references = ProductReferenceRepository(
            folder / "product_catalogue.csv"
        ).load()

        self.product_tax_records = ProductTaxRecordRepository(
            folder / "product_tax_records.csv"
        ).load()

        self.stock_records = StockLedgerRepository(
            folder / "stock_ledger.csv"
        ).load()

        self.business_activity_evidence = BusinessActivityEvidenceRepository(
            folder / "business_activity_evidence.csv"
        ).load()

        self.price_benchmarks = PriceBenchmarkRepository(
            folder / "price_benchmarks.csv"
        ).load()

        self.price_contexts = InvoicePriceContextRepository(
            folder / "invoice_price_contexts.csv"
        ).load()

        self.taxpayers_by_id = {
            taxpayer.taxpayer_id: taxpayer
            for taxpayer in self.taxpayers
        }

        self.documents_by_fdn = {
            document.fdn: document
            for document in self.documents
        }

        self._validate_links()
        self._validate_product_tax_records()
        self._validate_stock_records()
        self._validate_business_activity_evidence()
        self._validate_price_contexts()

    def _validate_links(self) -> None:
        """Check references between the three datasets."""
        for document in self.documents:
            if document.seller_id not in self.taxpayers_by_id:
                raise ValueError(
                    f"Invoice {document.fdn}: unknown seller "
                    f"{document.seller_id}."
                )

            if (
                document.buyer_id is not None
                and document.buyer_id not in self.taxpayers_by_id
            ):
                raise ValueError(
                    f"Invoice {document.fdn}: unknown buyer "
                    f"{document.buyer_id}."
                )

        for line in self.lines:
            if line.fdn not in self.documents_by_fdn:
                raise ValueError(
                    f"Product line {line.line_number} refers to "
                    f"unknown invoice {line.fdn}."
                )

        fdns_with_lines = {line.fdn for line in self.lines}
        missing_lines = set(self.documents_by_fdn) - fdns_with_lines

        if missing_lines:
            raise ValueError(
                "Invoice headers without product lines: "
                + ", ".join(sorted(missing_lines))
            )

    def _validate_product_tax_records(self) -> None:
        """Validate taxpayer and purchase links where supplied."""
        lines_by_key = {
            (line.fdn, line.line_number): line
            for line in self.lines
        }

        for record in self.product_tax_records:
            label = f"Product tax record {record.record_id}"

            if record.taxpayer_id not in self.taxpayers_by_id:
                raise ValueError(
                    f"{label}: unknown taxpayer {record.taxpayer_id}."
                )

            if (
                record.source_fdn is None
                or record.source_line_number is None
            ):
                continue

            source_line = lines_by_key.get(
                (record.source_fdn, record.source_line_number)
            )

            if source_line is None:
                raise ValueError(
                    f"{label}: unknown source invoice "
                    f"{record.source_fdn}, "
                    f"line {record.source_line_number}."
                )

            source_document = self.documents_by_fdn[record.source_fdn]

            if (
                source_line.product_code != record.product_code
                or source_line.unit != record.unit
            ):
                raise ValueError(
                    f"{label}: source product or unit does not match."
                )

            if (
                source_document.buyer_id is not None
                and source_document.buyer_id != record.taxpayer_id
            ):
                raise ValueError(
                    f"{label}: source invoice names a different buyer."
                )

            if (
                record.record_type == "Stocking-in"
                and source_document.issue_date > record.record_date
            ):
                raise ValueError(
                    f"{label}: source invoice is dated after stocking-in."
                )

    def _validate_stock_records(self) -> None:
        """Check that stock records belong to known taxpayers."""

        for record in self.stock_records:
            if record.taxpayer_id not in self.taxpayers_by_id:
                raise ValueError(
                    f"Stock record for {record.product_code} "
                    f"({record.unit}), "
                    f"{record.period_start} to {record.period_end}: "
                    f"unknown taxpayer {record.taxpayer_id}."
                )

    def _validate_business_activity_evidence(self) -> None:
        """Validate taxpayer and asset disposal invoice links."""

        line_keys = {
            (line.fdn, line.line_number)
            for line in self.lines
        }

        for record in self.business_activity_evidence:
            label = f"Business activity evidence {record.record_id}"

            if record.taxpayer_id not in self.taxpayers_by_id:
                raise ValueError(
                    f"{label}: unknown taxpayer "
                    f"{record.taxpayer_id}."
                )

            if record.fdn is None or record.line_number is None:
                continue

            if (record.fdn, record.line_number) not in line_keys:
                raise ValueError(
                    f"{label}: unknown invoice {record.fdn}, "
                    f"line {record.line_number}."
                )

            document = self.documents_by_fdn[record.fdn]

            if document.seller_id != record.taxpayer_id:
                raise ValueError(
                    f"{label}: invoice seller does not match "
                    "the evidence taxpayer."
                )

    def _validate_price_contexts(self) -> None:
        """Check that price context refers to an existing invoice line."""

        line_keys = {
            (line.fdn, line.line_number)
            for line in self.lines
        }

        for context in self.price_contexts:
            key = (context.fdn, context.line_number)

            if key not in line_keys:
                raise ValueError(
                    f"Price context: unknown invoice {context.fdn}, "
                    f"line {context.line_number}."
                )