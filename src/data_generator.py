from calendar import monthrange
from collections import Counter
from csv import DictWriter
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from random import Random
from src.models import ProductTaxRecord
from src.repositories import ProductTaxRecordRepository
from src.repositories import StockLedgerRepository

from src.dataset import EFRISDataset
from decimal import Decimal, ROUND_HALF_UP

from src.models import FiscalDocument, InvoiceLine, StockLedger
from src.repositories import FiscalDocumentRepository, InvoiceLineRepository
from src.models import InvoicePriceContext
from src.repositories import InvoicePriceContextRepository
from shutil import copy2
from src.case_register import write_demo_register
from src.demo_scenarios import VAT_STOCKING, add_case_transactions, save_reference_rows


MONTHLY_LINE_TARGETS = (252, 248, 252, 248, 252, 248)


@dataclass(frozen=True)
class PlannedTrade:
    """Plan a wholesale invoice and a subsequent retail invoice."""

    template_fdn: str
    wholesale_fdn: str
    retail_fdn: str
    wholesale_date: date
    retail_date: date


def build_trade_plan(
    dataset: EFRISDataset,
    seed: int = 2026,
) -> list[PlannedTrade]:
    """Plan additional trades using the verified January demo."""

    if any(
        (doc.issue_date.year, doc.issue_date.month) != (2026, 1)
        for doc in dataset.documents
    ):
        raise ValueError("Use the January demonstration dataset as the source.")

    rng = Random(seed)
    line_counts = Counter(line.fdn for line in dataset.lines)

    templates = [
        doc
        for doc in sorted(dataset.documents, key=lambda item: item.fdn)
        if doc.buyer_id is not None
        and line_counts[doc.fdn] == 2
        and dataset.taxpayers_by_id[doc.seller_id].business_type == "Wholesale"
        and dataset.taxpayers_by_id[doc.buyer_id].business_type == "Retail"
    ]

    if len(templates) != 6 or len({doc.buyer_id for doc in templates}) != 6:
        raise ValueError("Expected six wholesale invoices to six retailers.")

    plan: list[PlannedTrade] = []

    for month, target in enumerate(MONTHLY_LINE_TARGETS, start=1):
        existing = len(dataset.lines) if month == 1 else 0
        additional = target - existing

        if additional < 0 or additional % 4 != 0:
            raise ValueError(f"Month {month}: cannot reach the target in four-line trades.")

        # Preserve DEMO002's verified January purchase and sales quantities.
        eligible = [
            doc for doc in templates
            if month != 1 or doc.buyer_id != "DEMO002"
        ]
        rng.shuffle(eligible)

        last_day = monthrange(2026, month)[1]

        for index in range(additional // 4):
            template = eligible[index % len(eligible)]
            buy_day = rng.randint(1, last_day - 1)
            sell_day = rng.randint(buy_day + 1, min(buy_day + 3, last_day))
            number = len(plan) + 1

            plan.append(
                PlannedTrade(
                    template_fdn=template.fdn,
                    wholesale_fdn=f"SIM-W-{number:04d}",
                    retail_fdn=f"SIM-R-{number:04d}",
                    wholesale_date=date(2026, month, buy_day),
                    retail_date=date(2026, month, sell_day),
                )
            )

    return plan

def write_fiscal_documents(
    dataset: EFRISDataset,
    trades: list[PlannedTrade],
    output_file: Path,
) -> None:
    """Write the original and generated invoice headers."""

    documents = list(dataset.documents)
    used_fdns = set(dataset.documents_by_fdn)

    for trade in trades:
        template = dataset.documents_by_fdn[trade.template_fdn]
        retailer_id = template.buyer_id

        if retailer_id is None:
            raise ValueError(f"Template {template.fdn} has no retailer.")

        if trade.retail_date < trade.wholesale_date:
            raise ValueError("A retail sale cannot precede its planned purchase.")

        wholesale = replace(
            template,
            fdn=trade.wholesale_fdn,
            issue_date=trade.wholesale_date,
        )

        retail = replace(
            template,
            fdn=trade.retail_fdn,
            seller_id=retailer_id,
            buyer_id=None,
            issue_date=trade.retail_date,
        )

        for document in (wholesale, retail):
            if document.fdn in used_fdns:
                raise ValueError(f"Duplicate FDN: {document.fdn}.")

            used_fdns.add(document.fdn)
            documents.append(document)

    columns: list[str] = [
        "fdn",
        "seller_id",
        "issue_date",
        "buyer_id",
        "supply_condition",
        "location",
    ]

    output_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = output_file.with_suffix(".csv.tmp")

    with temporary_file.open("w", encoding="utf-8", newline="") as file:
        writer = DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(asdict(document) for document in documents)

    temporary_file.replace(output_file)

def make_generated_line(
    dataset: EFRISDataset,
    document: FiscalDocument,
    source: InvoiceLine,
    units: int,
    rng: Random,
) -> InvoiceLine:
    """Generate one ordinary sale line for standard-quality goods."""

    product = (source.product_code, source.unit)
    seller = dataset.taxpayers_by_id[document.seller_id]
    location = (document.location or "").casefold()

    tax_refs = [
        ref for ref in dataset.product_references
        if (ref.product_code, ref.unit) == product
        and ref.supply_condition == document.supply_condition
        and ref.is_valid_on(document.issue_date)
    ]

    price_refs = [
        ref for ref in dataset.price_benchmarks
        if (ref.product_code, ref.unit) == product
        and ref.business_type == seller.business_type
        and ref.location.casefold() == location
        and ref.quality.casefold() == "standard"
        and ref.vat_basis == "VAT-exclusive"
        and ref.is_valid_on(document.issue_date)
    ]

    if len(tax_refs) != 1 or len(price_refs) != 1:
        raise ValueError(
            f"{document.fdn}, {source.product_code}: expected one VAT "
            f"and one price reference; found {len(tax_refs)} "
            f"and {len(price_refs)}."
        )

    tax = tax_refs[0]
    benchmark = price_refs[0]
    money = Decimal("0.01")

    # Choose a reproducible price inside the fictional reference range.
    fraction = Decimal(rng.randint(20, 80)) / Decimal("100")
    unit_price = (
        benchmark.minimum_unit_price
        + (benchmark.maximum_unit_price - benchmark.minimum_unit_price)
        * fraction
    ).quantize(money, rounding=ROUND_HALF_UP)

    quantity = Decimal(units)
    net = (quantity * unit_price).quantize(money, rounding=ROUND_HALF_UP)
    vat = (net * tax.vat_rate).quantize(money, rounding=ROUND_HALF_UP)

    return InvoiceLine(
        fdn=document.fdn,
        line_number=source.line_number,
        product_code=source.product_code,
        unit=source.unit,
        quantity=quantity,
        unit_price=unit_price,
        vat_category=tax.expected_vat_category,
        vat_amount=vat,
    )

@dataclass
class MonthlyStockMovement:
    """Store purchased and sold quantities for one stock group."""

    purchases: Decimal = Decimal("0")
    sales: Decimal = Decimal("0")


def collect_monthly_stock_movements(
    lines: list[InvoiceLine],
    documents: dict[str, FiscalDocument],
) -> dict[tuple[str, str, str, date], MonthlyStockMovement]:
    totals: dict[tuple[str, str, str, date], MonthlyStockMovement] = {}

    for line in lines:
        document = documents[line.fdn]
        month_start = document.issue_date.replace(day=1)

        seller_key = (
            document.seller_id, line.product_code, line.unit, month_start
        )
        seller_totals = totals.setdefault(seller_key, MonthlyStockMovement())
        seller_totals.sales += line.quantity

        if document.buyer_id is not None:
            buyer_key = (
                document.buyer_id, line.product_code, line.unit, month_start
            )
            buyer_totals = totals.setdefault(buyer_key, MonthlyStockMovement())
            buyer_totals.purchases += line.quantity

    return totals

def build_monthly_stock_rows(
    dataset: EFRISDataset,
    trades: list[PlannedTrade],
    movements: dict[tuple[str, str, str, date], MonthlyStockMovement],
) -> list[StockLedger]:
    # Reserve one maximum-sized lot per planned wholesale delivery.
    deliveries = Counter(trade.template_fdn for trade in trades)
    reserve: Counter[tuple[str, str, str]] = Counter()

    for line in dataset.lines:
        if line.fdn in deliveries:
            seller = dataset.documents_by_fdn[line.fdn].seller_id
            maximum_lot = max(1, int(line.quantity) // 4)
            reserve[(seller, line.product_code, line.unit)] += (
                deliveries[line.fdn] * maximum_lot
            )

    rows: list[StockLedger] = []
    zero = Decimal("0")

    for seed in dataset.stock_records:
        key = (seed.taxpayer_id, seed.product_code, seed.unit)
        opening = seed.opening_stock + Decimal(reserve[key])

        for month in range(1, 7):
            start = date(2026, month, 1)
            end = date(2026, month, monthrange(2026, month)[1])
            movement = movements.get((*key, start), MonthlyStockMovement())

            # The original returns, own use and write-offs apply only to January.
            customer_returns = seed.customer_returns if month == 1 else zero
            supplier_returns = seed.supplier_returns if month == 1 else zero
            own_use = seed.own_use if month == 1 else zero
            write_offs = seed.write_offs if month == 1 else zero

            closing = (
                opening + movement.purchases + customer_returns
                - movement.sales - supplier_returns - own_use - write_offs
            )
            if closing < 0:
                raise ValueError(f"Negative closing stock for {key} in {start:%Y-%m}.")

            rows.append(replace(
                seed,
                period_start=start, period_end=end,
                opening_stock=opening, purchases=movement.purchases,
                sales=movement.sales, closing_stock=closing,
                customer_returns=customer_returns, supplier_returns=supplier_returns,
                own_use=own_use, write_offs=write_offs,
            ))
            opening = closing  # Next month starts with this month's closing stock.

    return rows

if __name__ == "__main__":
    folder = Path(__file__).resolve().parents[1] / "data"
    dataset = EFRISDataset(folder)
    trades = build_trade_plan(dataset)

    print("Existing invoice lines:", len(dataset.lines))
    print("New invoice pairs planned:", len(trades))
    print("New invoices planned:", 2 * len(trades))
    print("New invoice lines planned:", 4 * len(trades))
    print("Planned six-month total:", len(dataset.lines) + 4 * len(trades))
    output = folder.parent / "generated" / "six_month" / "fiscal_documents.csv"
    write_fiscal_documents(dataset, trades, output)

    saved = FiscalDocumentRepository(output).load()
    by_fdn = {document.fdn: document for document in saved}

    linked_pairs = sum(
        by_fdn[trade.wholesale_fdn].buyer_id
        == by_fdn[trade.retail_fdn].seller_id
        and by_fdn[trade.retail_fdn].buyer_id is None
        for trade in trades
    )

    print("Saved fiscal documents:", len(saved))
    print("Unique FDNs:", len(by_fdn))
    print("Linked wholesale-retail pairs:", linked_pairs)

    rng = Random(2027)
    product_lines = list(dataset.lines)

    for trade in trades:
        sources = sorted(
            (line for line in dataset.lines if line.fdn == trade.template_fdn),
            key=lambda line: line.line_number,
        )

        for source in sources:
            maximum_lot = max(1, int(source.quantity) // 4)
            purchased = rng.randint(1, maximum_lot)
            sold = rng.randint(1, purchased)

            for fdn, units in (
                (trade.wholesale_fdn, purchased),
                (trade.retail_fdn, sold),
            ):
                product_lines.append(
                    make_generated_line(dataset, by_fdn[fdn], source, units, rng)
                )

    product_lines = add_case_transactions(dataset, by_fdn, product_lines)
    product_lines.sort(
        key=lambda line: (by_fdn[line.fdn].issue_date, line.fdn, line.line_number)
    )

    line_file = output.with_name("invoice_lines.csv")
    temporary = line_file.with_suffix(".csv.tmp")
    columns: list[str] = [
        "fdn", "line_number", "product_code", "unit",
        "quantity", "unit_price", "vat_category", "vat_amount",
    ]

    with temporary.open("w", encoding="utf-8", newline="") as file:
        writer = DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(asdict(line) for line in product_lines)

    verified = InvoiceLineRepository(temporary).load()
    fdns = {line.fdn for line in verified}

    if fdns != set(by_fdn):
        raise ValueError("Product lines do not match the saved invoice FDNs.")

    counts = Counter(by_fdn[line.fdn].issue_date.month for line in verified)
    monthly = [counts[month] for month in range(1, 7)]

    if tuple(monthly) != MONTHLY_LINE_TARGETS:
        raise ValueError(f"Unexpected monthly totals: {monthly}")

    temporary.replace(line_file)
    print(f"Saved invoice lines: {len(verified)} | FDNs: {len(fdns)} | Monthly lines: {monthly}")
    original_keys = {
        (line.fdn, line.line_number)
        for line in dataset.lines
    }

    new_contexts = [
        InvoicePriceContext(
            fdn=line.fdn,
            line_number=line.line_number,
            quality="Standard",
            discount_rate=Decimal("0"),
        )
        for line in verified
        if (line.fdn, line.line_number) not in original_keys
    ]

    all_contexts = dataset.price_contexts + new_contexts
    context_file = line_file.with_name("invoice_price_contexts.csv")
    context_tmp = context_file.with_suffix(".csv.tmp")

    context_columns: list[str] = [
        "fdn", "line_number", "quality", "discount_rate",
        "discount_reference", "discount_reason",
    ]

    with context_tmp.open("w", encoding="utf-8", newline="") as file:
        writer = DictWriter(file, fieldnames=context_columns)
        writer.writeheader()
        writer.writerows(asdict(context) for context in all_contexts)

    saved_contexts = InvoicePriceContextRepository(context_tmp).load()

    expected_keys = {(line.fdn, line.line_number) for line in verified}
    saved_keys = {
        (context.fdn, context.line_number)
        for context in saved_contexts
    }

    if saved_keys != expected_keys:
        raise ValueError("The price contexts do not match the invoice lines.")

    if saved_contexts != all_contexts:
        raise ValueError("The saved quality or discount details changed.")

    context_tmp.replace(context_file)
    print(
        f"Saved price contexts: {len(saved_contexts)} | "
        f"Original: {len(dataset.price_contexts)} | New: {len(new_contexts)}"
    )
    wholesale_fdns = {trade.wholesale_fdn for trade in trades}
    purchase_lines = [
        line for line in verified if line.fdn in wholesale_fdns
    ]

    purchase_counts = Counter(line.fdn for line in purchase_lines)
    if any(purchase_counts[fdn] != 2 for fdn in wholesale_fdns):
        raise ValueError("Expected two products on each generated wholesale invoice.")

    new_stocking_records: list[ProductTaxRecord] = []

    for line in purchase_lines:
        purchase = by_fdn[line.fdn]
        retailer_id = purchase.buyer_id

        if retailer_id is None:
            raise ValueError(f"Wholesale invoice {line.fdn} has no identified buyer.")

        # For ordinary simulated purchases, the retailer records
        # the VAT category shown on the supplier's invoice line.
        new_stocking_records.append(
            ProductTaxRecord(
                record_id=f"STK-{line.fdn}-{line.line_number}",
                taxpayer_id=retailer_id,
                record_type="Stocking-in",
                record_date=purchase.issue_date,
                product_code=line.product_code,
                unit=line.unit,
                vat_category=VAT_STOCKING.get((line.fdn, line.line_number), line.vat_category),
                supply_condition=purchase.supply_condition,
                source_fdn=line.fdn,
                source_line_number=line.line_number,
            )
        )

    all_tax_records = dataset.product_tax_records + new_stocking_records
    tax_file = line_file.with_name("product_tax_records.csv")
    tax_tmp = tax_file.with_suffix(".csv.tmp")
    tax_columns: list[str] = [
        "record_id", "taxpayer_id", "record_type", "record_date",
        "product_code", "unit", "vat_category", "supply_condition",
        "source_fdn", "source_line_number",
    ]

    with tax_tmp.open("w", encoding="utf-8", newline="") as file:
        writer = DictWriter(file, fieldnames=tax_columns)
        writer.writeheader()
        writer.writerows(asdict(record) for record in all_tax_records)

    saved_tax_records = ProductTaxRecordRepository(tax_tmp).load()

    expected_sources = {(line.fdn, line.line_number) for line in purchase_lines}
    saved_sources = [
        (record.source_fdn, record.source_line_number)
        for record in saved_tax_records
        if record.record_type == "Stocking-in"
        and record.source_fdn in wholesale_fdns
    ]

    if len(saved_sources) != len(expected_sources) or set(saved_sources) != expected_sources:
        raise ValueError("Each generated purchase line needs exactly one stocking-in record.")

    if saved_tax_records != all_tax_records:
        raise ValueError("Saving changed one or more product tax records.")

    tax_tmp.replace(tax_file)
    print(
        f"Saved product tax records: {len(saved_tax_records)} | "
        f"Original: {len(dataset.product_tax_records)} | "
        f"New stocking-in: {len(saved_sources)}"
    )
    movements = collect_monthly_stock_movements(verified, by_fdn)

    stock_keys = {
        (taxpayer_id, product_code, unit)
        for taxpayer_id, product_code, unit, month_start in movements
    }
    known_stock_keys = {
        (record.taxpayer_id, record.product_code, record.unit)
        for record in dataset.stock_records
    }

    missing = stock_keys - known_stock_keys
    if missing:
        raise ValueError(f"No starting stock record for: {sorted(missing)}")

    cement = movements[("DEMO002", "PROD001", "bag", date(2026, 1, 1))]
    print(
        f"Stock groups: {len(stock_keys)} | "
        f"Active monthly groups: {len(movements)} | "
        f"DEMO002 January cement: {cement.purchases} bags purchased, "
        f"{cement.sales} bags sold"
    )
    stock_rows = build_monthly_stock_rows(dataset, trades, movements)
    balances = {
        (r.taxpayer_id, r.product_code, r.unit, r.period_start): r.closing_stock
        for r in stock_rows
    }
    jan_cement = balances[("DEMO002", "PROD001", "bag", date(2026, 1, 1))]
    jun_pipes = balances[("DEMO002", "PROD013", "piece", date(2026, 6, 1))]
    print(
        f"Monthly stock rows: {len(stock_rows)} | "
        f"DEMO002 January closing cement: {jan_cement} bags | "
        f"June closing pipes: {jun_pipes} pieces"
    )
    stock_file = line_file.with_name("stock_ledger.csv")
    stock_tmp = stock_file.with_name("stock_ledger.tmp.csv")
    stock_columns: list[str] = [
        "taxpayer_id", "product_code", "unit", "period_start", "period_end",
        "opening_stock", "purchases", "sales", "closing_stock",
        "customer_returns", "supplier_returns", "own_use", "write_offs",
    ]

    with stock_tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = DictWriter(handle, fieldnames=stock_columns)
        writer.writeheader()
        writer.writerows(asdict(row) for row in stock_rows)

    saved_stock = StockLedgerRepository(stock_tmp).load()
    if saved_stock != stock_rows:
        raise ValueError("The stock rows changed when saved and reloaded.")

    stock_index = {
        (r.taxpayer_id, r.product_code, r.unit, r.period_start): r
        for r in saved_stock
    }
    carry_checks = 0

    for seed in dataset.stock_records:
        group = (seed.taxpayer_id, seed.product_code, seed.unit)
        previous_closing: Decimal | None = None

        for month in range(1, 7):
            start = date(2026, month, 1)
            key = (*group, start)
            row = stock_index.get(key)
            if row is None:
                raise ValueError(f"Missing monthly stock row: {key}")

            flow = movements.get(key, MonthlyStockMovement())
            if (row.purchases, row.sales) != (flow.purchases, flow.sales):
                raise ValueError(f"Stock quantities do not match invoices: {key}")

            if previous_closing is not None:
                if row.opening_stock != previous_closing:
                    raise ValueError(f"Opening stock does not match last month: {key}")
                carry_checks += 1

            previous_closing = row.closing_stock

    stock_tmp.replace(stock_file)
    print(
        f"Saved stock ledger: {len(saved_stock)} rows | "
        f"Carry-forward checks passed: {carry_checks}"
    )
    dashboard_folder = stock_file.parent

    for filename in (
        "taxpayers.csv",
        "business_activity_evidence.csv",
        "demo_case_labels.csv",
    ):
        copy2(folder / filename, dashboard_folder / filename)

    save_reference_rows(dashboard_folder / "product_catalogue.csv", dataset.product_references)
    save_reference_rows(dashboard_folder / "price_benchmarks.csv", dataset.price_benchmarks)

    ready = EFRISDataset(dashboard_folder)
    print(
        f"Dashboard data ready: {len(ready.taxpayers)} taxpayers | "
        f"{len(ready.documents)} invoices | {len(ready.lines)} invoice lines | "
        f"{len(ready.stock_records)} stock rows"
    )
    write_demo_register(dashboard_folder)
