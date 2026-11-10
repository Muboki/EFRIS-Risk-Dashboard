from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

@dataclass(frozen=True)
class Taxpayer:
    """Represent a taxpayer whose transactions will be reviewed."""

    taxpayer_id: str
    business_name: str
    business_type: str
    business_activity: str
    vat_registered: bool = True

    def __post_init__(self) -> None:
        """Validate the taxpayer's details."""

        for field_name in (
            "taxpayer_id",
            "business_name",
            "business_activity",
        ):
            value = getattr(self, field_name)

            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must contain text.")

        if self.business_type not in ("Wholesale", "Retail"):
            raise ValueError(
                "Business type must be Wholesale or Retail."
            )

        if not isinstance(self.vat_registered, bool):
            raise ValueError("VAT registration must be True or False.")


@dataclass(frozen=True)
class FiscalDocument:
    """Represent an invoice header and its analysis context."""

    fdn: str
    seller_id: str
    issue_date: date
    buyer_id: str | None = None
    supply_condition: str | None = None
    location: str | None = None

    def __post_init__(self) -> None:
        """Validate the invoice identifiers, date and context."""
        for field_name in ("fdn", "seller_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must contain text.")

        if type(self.issue_date) is not date:
            raise ValueError("Issue date must be a date object.")

        for field_name in (
            "buyer_id",
            "supply_condition",
            "location",
        ):
            value = getattr(self, field_name)

            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"{field_name} must contain text or be None."
                    ) 

@dataclass(frozen=True)
class InvoiceLine:
    """Represent one product on an invoice, with a VAT-exclusive price."""

    fdn: str
    line_number: int
    product_code: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    vat_category: str
    vat_amount: Decimal

    def __post_init__(self) -> None:
        """Validate the product details and recorded amounts."""

        for field_name in ("fdn", "product_code", "unit"):
            value = getattr(self, field_name)

            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must contain text.")

        if type(self.line_number) is not int or self.line_number < 1:
            raise ValueError("Line number must be a positive integer.")

        for field_name in ("quantity", "unit_price", "vat_amount"):
            value = getattr(self, field_name)

            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(
                    f"{field_name} must be a finite Decimal."
                )

            if value < 0:
                raise ValueError(f"{field_name} cannot be negative.")

        if self.quantity == 0:
            raise ValueError("Quantity must be greater than zero.")

        if self.vat_category not in (
            "Standard-rated",
            "Zero-rated",
            "Exempt",
        ):
            raise ValueError("Invalid VAT category.")

    @property
    def net_amount(self) -> Decimal:
        """Calculate the amount before VAT, rounded to two decimals."""
        return (self.quantity * self.unit_price).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    @property
    def total_amount(self) -> Decimal:
        """Calculate the amount including the recorded VAT."""
        return self.net_amount + self.vat_amount

@dataclass(frozen=True)
class StockLedger:
    """Summarise stock for one taxpayer and product over a period."""

    taxpayer_id: str
    product_code: str
    unit: str
    period_start: date
    period_end: date
    opening_stock: Decimal
    purchases: Decimal
    sales: Decimal
    closing_stock: Decimal
    customer_returns: Decimal = Decimal("0")
    supplier_returns: Decimal = Decimal("0")
    own_use: Decimal = Decimal("0")
    write_offs: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        """Validate identifiers, dates and stock quantities."""

        for field_name in ("taxpayer_id", "product_code", "unit"):
            value = getattr(self, field_name)

            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must contain text.")

        if (
            type(self.period_start) is not date
            or type(self.period_end) is not date
        ):
            raise ValueError("Stock period dates must be date objects.")

        if self.period_end < self.period_start:
            raise ValueError("The stock period cannot end before it starts.")

        for field_name in (
            "opening_stock",
            "purchases",
            "sales",
            "closing_stock",
            "customer_returns",
            "supplier_returns",
            "own_use",
            "write_offs",
        ):
            value = getattr(self, field_name)

            if (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or value < 0
            ):
                raise ValueError(
                    f"{field_name} must be a non-negative finite Decimal."
                )

    @property
    def expected_closing_stock(self) -> Decimal:
        """Calculate the quantity expected to remain in stock."""
        return (
            self.opening_stock
            + self.purchases
            + self.customer_returns
            - self.sales
            - self.supplier_returns
            - self.own_use
            - self.write_offs
        )

    @property
    def stock_difference(self) -> Decimal:
        """Compare reported closing stock with expected closing stock."""
        return self.closing_stock - self.expected_closing_stock

        
@dataclass(frozen=True)
class ProductReference:
    """Represent a dated reference classification for a product."""

    product_code: str
    product_name: str
    category: str
    unit: str
    expected_vat_category: str
    vat_rate: Decimal
    valid_from: date
    valid_to: date
    supply_condition: str
    reference_source: str

    def __post_init__(self) -> None:
        """Validate the reference details, VAT rate and dates."""
        for field_name in (
            "product_code",
            "product_name",
            "category",
            "unit",
            "supply_condition",
            "reference_source",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must contain text.")

        if self.expected_vat_category not in (
            "Standard-rated",
            "Zero-rated",
            "Exempt",
        ):
            raise ValueError("Invalid reference VAT category.")

        if (
            not isinstance(self.vat_rate, Decimal)
            or not self.vat_rate.is_finite()
            or not Decimal("0") <= self.vat_rate <= Decimal("1")
        ):
            raise ValueError(
                "VAT rate must be a finite Decimal between 0 and 1."
            )

        if self.expected_vat_category == "Standard-rated":
            if self.vat_rate == 0:
                raise ValueError(
                    "A standard-rated reference must have a positive VAT rate."
                )
        elif self.vat_rate != 0:
            raise ValueError(
                "Exempt and zero-rated references must have a VAT rate of 0."
            )

        if (
            type(self.valid_from) is not date
            or type(self.valid_to) is not date
        ):
            raise ValueError("Reference dates must be date objects.")

        if self.valid_to < self.valid_from:
            raise ValueError(
                "The reference end date cannot precede its start date."
            )

    def is_valid_on(self, transaction_date: date) -> bool:
        """Check whether a date falls within the reference period."""
        return self.valid_from <= transaction_date <= self.valid_to

@dataclass(frozen=True)
class ProductTaxRecord:
    """Record a product's VAT category during registration or stocking-in."""

    record_id: str
    taxpayer_id: str
    record_type: str
    record_date: date
    product_code: str
    unit: str
    vat_category: str
    supply_condition: str | None = None
    source_fdn: str | None = None
    source_line_number: int | None = None

    def __post_init__(self) -> None:
        """Validate the classification record and its optional source."""
        for field_name in (
            "record_id",
            "taxpayer_id",
            "product_code",
            "unit",
        ):
            value = getattr(self, field_name)

            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must contain text.")

        if self.record_type not in ("Registration", "Stocking-in"):
            raise ValueError(
                "Record type must be Registration or Stocking-in."
            )

        if type(self.record_date) is not date:
            raise ValueError("Record date must be a date object.")

        if self.vat_category not in (
            "Standard-rated",
            "Zero-rated",
            "Exempt",
        ):
            raise ValueError("Invalid recorded VAT category.")

        for field_name in ("supply_condition", "source_fdn"):
            value = getattr(self, field_name)

            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"{field_name} must contain text or be None."
                    )

        if (self.source_fdn is None) != (
            self.source_line_number is None
        ):
            raise ValueError(
                "Source FDN and source line number must be provided together."
            )

        if self.source_line_number is not None:
            if (
                type(self.source_line_number) is not int
                or self.source_line_number < 1
            ):
                raise ValueError(
                    "Source line number must be a positive integer."
                )

@dataclass(frozen=True)
class BusinessActivityEvidence:
    """Record documented diversification or a specific asset disposal."""

    record_id: str
    taxpayer_id: str
    category: str
    evidence_type: str
    valid_from: date
    valid_to: date
    evidence_reference: str
    reason: str
    fdn: str | None = None
    line_number: int | None = None

    def __post_init__(self) -> None:
        """Validate the evidence details and its scope."""

        for field_name in (
            "record_id",
            "taxpayer_id",
            "category",
            "evidence_reference",
            "reason",
        ):
            value = getattr(self, field_name)

            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{field_name} must contain text."
                )

        if self.evidence_type not in (
            "Diversification",
            "Asset disposal",
        ):
            raise ValueError(
                "Evidence type must be Diversification or Asset disposal."
            )

        if (
            type(self.valid_from) is not date
            or type(self.valid_to) is not date
        ):
            raise ValueError(
                "Evidence validity dates must be date objects."
            )

        if self.valid_to < self.valid_from:
            raise ValueError(
                "Evidence cannot expire before its start date."
            )

        if self.evidence_type == "Diversification":
            if self.fdn is not None or self.line_number is not None:
                raise ValueError(
                    "Diversification evidence must not specify an invoice."
                )
        else:
            if not isinstance(self.fdn, str) or not self.fdn.strip():
                raise ValueError(
                    "Asset disposal evidence requires an invoice FDN."
                )

            if (
                self.line_number is None
                or type(self.line_number) is not int
                or self.line_number < 1
            ):
                raise ValueError(
                    "Asset disposal evidence requires a positive "
                    "invoice line number."
                )

    def is_valid_on(self, transaction_date: date) -> bool:
        return self.valid_from <= transaction_date <= self.valid_to

@dataclass(frozen=True)
class PriceBenchmark:
    """Represent a dated reference range for unit prices in UGX."""

    benchmark_id: str
    product_code: str
    unit: str
    business_type: str
    location: str
    quality: str
    vat_basis: str
    minimum_unit_price: Decimal
    maximum_unit_price: Decimal
    valid_from: date
    valid_to: date
    reference_source: str

    def __post_init__(self) -> None:
        """Validate the price range and its comparison context."""

        for field_name in (
            "benchmark_id",
            "product_code",
            "unit",
            "location",
            "quality",
            "reference_source",
        ):
            value = getattr(self, field_name)

            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must contain text.")

        if self.business_type not in ("Wholesale", "Retail"):
            raise ValueError(
                "Business type must be Wholesale or Retail."
            )

        if self.vat_basis not in ("VAT-exclusive", "VAT-inclusive"):
            raise ValueError(
                "VAT basis must be VAT-exclusive or VAT-inclusive."
            )

        for field_name in (
            "minimum_unit_price",
            "maximum_unit_price",
        ):
            value = getattr(self, field_name)

            if (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or value <= 0
            ):
                raise ValueError(
                    f"{field_name} must be a finite positive Decimal."
                )

        if self.maximum_unit_price < self.minimum_unit_price:
            raise ValueError(
                "Maximum price cannot be below minimum price."
            )

        if (
            type(self.valid_from) is not date
            or type(self.valid_to) is not date
        ):
            raise ValueError(
                "Benchmark validity dates must be date objects."
            )

        if self.valid_to < self.valid_from:
            raise ValueError(
                "Benchmark cannot expire before its start date."
            )

    def is_valid_on(self, transaction_date: date) -> bool:
        return self.valid_from <= transaction_date <= self.valid_to

@dataclass(frozen=True)
class InvoicePriceContext:
    """Record supplied quality and discount details for an invoice line."""

    fdn: str
    line_number: int
    quality: str | None = None
    discount_rate: Decimal | None = None
    discount_reference: str | None = None
    discount_reason: str | None = None

    def __post_init__(self) -> None:
        """Validate identifiers and any supplied price context."""

        if not isinstance(self.fdn, str) or not self.fdn.strip():
            raise ValueError("FDN must contain text.")

        if type(self.line_number) is not int or self.line_number < 1:
            raise ValueError("Line number must be a positive integer.")

        for field_name in (
            "quality",
            "discount_reference",
            "discount_reason",
        ):
            value = getattr(self, field_name)

            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"{field_name} must contain text or be None."
                    )

        value = self.discount_rate

        if value is not None:
            if (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or not Decimal("0") <= value <= Decimal("1")
            ):
                raise ValueError(
                    "Discount rate must be a finite Decimal "
                    "between 0 and 1, or None."
                )