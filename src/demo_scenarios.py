"""Deliberate fictional transactions in the six-month demo, never in the holdout.

FDNs refer to the fixed-seed trade plan. Change the records reviewed by the
engine here; risk decisions are always made by the ordinary rule classes.
"""
from collections.abc import Sequence
from csv import DictWriter
from dataclasses import asdict, dataclass, fields, replace
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from src.dataset import EFRISDataset
from src.models import FiscalDocument, InvoiceLine, PriceBenchmark, ProductReference, StockLedger

D = Decimal
CENT = D('0.01')

# Retail invoice, line -> incorrect category recorded at stocking-in and sale.
VAT_SALES = {
    ('SIM-R-0059', 1): 'Exempt',       # radio
    ('SIM-R-0175', 1): 'Zero-rated',   # biscuits
    ('SIM-R-0188', 2): 'Exempt',       # shoes
    ('SIM-R-0272', 1): 'Zero-rated',   # chair
}
VAT_STOCKING = {(fdn.replace('SIM-R-', 'SIM-W-'), n): category
                for (fdn, n), category in VAT_SALES.items()}

# Non-core merchandise present in opening stock; no diversification/disposal
# evidence was submitted for these particular retailers, products and sales.
OUTSIDE_ACTIVITY = {
    ('SIM-R-0093', 1): ('PROD003', 1),  # hardware shop sells a radio
    ('SIM-R-0162', 1): ('PROD007', 3),  # household shop sells shirts
    ('SIM-R-0184', 2): ('PROD009', 2),  # electronics shop sells chairs
    ('SIM-R-0354', 2): ('PROD012', 4),  # furniture shop sells basins
}

# Recorded UGX per unit, exclusive of VAT; standard quality and no discount.
LOW_PRICES = {('SIM-R-0110', 1): 49000, ('SIM-R-0129', 2): 37500,
              ('SIM-R-0217', 1): 5200, ('SIM-R-0357', 2): 950}

@dataclass(frozen=True)
class UnsoldProduct:
    code: str
    name: str
    like_product: str       # same category, unit and simulated VAT conditions
    wholesaler: str
    retailer: str
    wholesale_range: tuple[int, int]
    retail_range: tuple[int, int]
    deliveries: tuple[tuple[str, int, int], ...]  # FDN, line, quantity

UNSOLD = (
    UnsoldProduct('PROD014', 'Electric kettle', 'PROD003', 'DEMO003', 'DEMO004',
                  (45000, 55000), (55000, 72000), (('SIM-W-0125', 1, 3), ('SIM-W-0311', 1, 5))),
    UnsoldProduct('PROD015', 'Mango cordial 1 litre', 'PROD006', 'DEMO005', 'DEMO006',
                  (5500, 6500), (7000, 8500), (('SIM-W-0221', 2, 12), ('SIM-W-0314', 2, 8))),
    UnsoldProduct('PROD016', 'Cotton scarf', 'PROD007', 'DEMO007', 'DEMO008',
                  (10000, 14000), (15000, 20000), (('SIM-W-0218', 1, 5), ('SIM-W-0343', 1, 7))),
    UnsoldProduct('PROD017', 'Wooden stool', 'PROD009', 'DEMO009', 'DEMO010',
                  (32000, 43000), (45000, 58000), (('SIM-W-0158', 1, 4), ('SIM-W-0348', 1, 3))),
)

def opening_group(owner: str, code: str, unit: str, quantity: Decimal) -> StockLedger:
    return StockLedger(owner, code, unit, date(2026, 1, 1), date(2026, 1, 31),
                       quantity, D(0), D(0), quantity)


def add_case_transactions(seed: EFRISDataset, documents: dict[str, FiscalDocument],
                          lines: list[InvoiceLine]) -> list[InvoiceLine]:
    """Enrich only the in-memory simulation; leave the January input CSVs intact."""
    indexed = {(line.fdn, line.line_number): line for line in lines}
    refs = {r.product_code: r for r in seed.product_references}
    prices = {(p.product_code, p.business_type): p for p in seed.price_benchmarks}

    def record_sale(key: tuple[str, int], code: str, quantity: int, price: Decimal) -> None:
        ref = refs[code]
        net = (D(quantity) * price).quantize(CENT, rounding=ROUND_HALF_UP)
        vat = (net * ref.vat_rate).quantize(CENT, rounding=ROUND_HALF_UP)
        indexed[key] = replace(indexed[key], product_code=code, unit=ref.unit,
                               quantity=D(quantity), unit_price=price, vat_category=ref.expected_vat_category,
                               vat_amount=vat)

    for item in UNSOLD:
        ref = replace(refs[item.like_product], product_code=item.code, product_name=item.name)
        refs[item.code] = ref
        seed.product_references.append(ref)
        for level, limits in [('Wholesale', item.wholesale_range), ('Retail', item.retail_range)]:
            seed.price_benchmarks.append(replace(prices[item.like_product, level],
                benchmark_id=f'SIM-PRICE-{item.code}-{level[0]}', product_code=item.code,
                minimum_unit_price=D(limits[0]), maximum_unit_price=D(limits[1])))
        opening = D(sum(qty for _, _, qty in item.deliveries))
        seed.stock_records.extend((opening_group(item.wholesaler, item.code, ref.unit, opening),
                                   opening_group(item.retailer, item.code, ref.unit, D(0))))
        for fdn, number, quantity in item.deliveries:
            doc = documents[fdn]
            if (doc.seller_id, doc.buyer_id, indexed[fdn, number].product_code) != (
                    item.wholesaler, item.retailer, item.like_product):
                raise ValueError(f'{fdn}/{number}: expected the planned buyer, seller and product.')
            record_sale((fdn, number), item.code, quantity, D(sum(item.wholesale_range)) / 2)

    for (fdn, number), (code, quantity) in OUTSIDE_ACTIVITY.items():
        seller = documents[fdn].seller_id
        seed.stock_records.append(opening_group(seller, code, refs[code].unit, D(quantity)))
        price: PriceBenchmark = prices[code, 'Retail']
        record_sale((fdn, number), code, quantity, (price.minimum_unit_price + price.maximum_unit_price) / 2)

    for key, price_amount in LOW_PRICES.items():
        line = indexed[key]
        record_sale(key, line.product_code, int(line.quantity), D(price_amount))

    for key, category in VAT_SALES.items():
        indexed[key] = replace(indexed[key], vat_category=category, vat_amount=D('0.00'))

    return list(indexed.values())


def save_reference_rows(path: Path, records: Sequence[ProductReference | PriceBenchmark]) -> None:
    """Write the dated catalogue or price references, including the extra SKUs."""
    tmp = path.with_suffix('.csv.tmp')
    with tmp.open('w', encoding='utf-8', newline='') as output:
        writer = DictWriter(output, fieldnames=[f.name for f in fields(records[0])])
        writer.writeheader()
        writer.writerows(asdict(record) for record in records)
    tmp.replace(path)
