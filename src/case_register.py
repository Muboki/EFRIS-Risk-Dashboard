"""Run the dashboard review and group related findings into traceable cases."""
from calendar import monthrange
from collections import Counter, defaultdict
from copy import copy
from csv import DictWriter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.dataset import EFRISDataset
from src.risk_engine import RiskEngine
from src.risk_rules import (BusinessActivityRule, PriceDeviationRule, PurchaseSalesRule,
                            RiskResult, VATClassificationRule)

PREFIX = {'VAT misclassification': 'VAT', 'Purchases without sales': 'STOCK',
          'Business-profile mismatch': 'ACTIVITY', 'Possible price understatement': 'PRICE'}
RULES = tuple(PREFIX)
FIRST, LAST = date(2026, 1, 1), date(2026, 6, 30)
COLUMNS = ('case_id', 'risk_check', 'taxpayer_id', 'business_name', 'product', 'unit',
           'review_start', 'review_end', 'sale_fdn', 'sale_date', 'flagged_lines',
           'purchase_fdns', 'purchase_dates', 'stocking_records', 'units_purchased',
           'units_sold', 'closing_stock', 'estimated_vat_difference_ugx', 'reason')

@dataclass
class PeriodReview:
    start: date
    end: date
    findings: list[RiskResult]
    vat_evidence: list[RiskResult]   # includes dated evidence from before the selected start


def run_review(dataset: EFRISDataset, start: date, end: date) -> PeriodReview:
    """Retain earlier source evidence; never use transactions after the cut-off."""
    if (end < start or start.day != 1 or end.day != monthrange(end.year, end.month)[1]):
        raise ValueError('Select complete months, from the first month to the last.')
    docs = dataset.documents_by_fdn
    data = copy(dataset)
    data.documents = [d for d in dataset.documents if d.issue_date <= end]
    data.documents_by_fdn = {d.fdn: d for d in data.documents}
    data.lines = [line for line in dataset.lines if line.fdn in data.documents_by_fdn]
    data.price_contexts = [c for c in dataset.price_contexts if c.fdn in data.documents_by_fdn]
    data.product_tax_records = [r for r in dataset.product_tax_records if r.record_date <= end]
    data.stock_records = [r for r in dataset.stock_records if r.period_end <= end]
    dates = {r.record_id: r.record_date for r in data.product_tax_records}
    findings, support = [], []
    engine = RiskEngine([VATClassificationRule(), PurchaseSalesRule(start, end),
                         BusinessActivityRule(), PriceDeviationRule()])
    for r in engine.run(data):
        if r.record_type == 'Stock review':
            findings.append(r)  # its own rule used the exact requested period
            continue
        if r.record_type in ('Stocking-in', 'Registration') and r.status == 'Flagged':
            support.append(r)
        if r.record_id:
            day = dates[r.record_id]
        elif r.fdn:
            day = docs[r.fdn].issue_date
        else:
            raise ValueError(f"Missing date for a {r.rule_name} result for {r.taxpayer_id}.")
        if start <= day <= end:
            findings.append(r)
    return PeriodReview(start, end, findings, support)


def build_register(data: EFRISDataset, review: PeriodReview) -> list[dict[str, str]]:
    """One sale FDN per check, or one taxpayer/product/unit/period stock review."""
    groups: dict[tuple[str, str], list[RiskResult]] = defaultdict(list)
    for hit in review.findings:
        if hit.status != 'Flagged':
            continue
        ident = hit.fdn if hit.record_type == 'Invoice line' else (
            hit.record_id if hit.record_type == 'Stock review' else None)
        if ident:
            groups[(hit.rule_name, ident)].append(hit)

    products = {r.product_code: r.product_name for r in data.product_references}
    lines = {(l.fdn, l.line_number): l for l in data.lines}
    stock = defaultdict(list)
    for s in data.stock_records:
        if review.start <= s.period_start <= s.period_end <= review.end:
            stock[f'{s.taxpayer_id}/{s.product_code}/{s.unit}/{review.start}/{review.end}'].append(s)
    output = []
    for (rule, ident), hits in sorted(groups.items(), key=lambda pair: (RULES.index(pair[0][0]), pair[0][1])):
        first = hits[0]
        codes = sorted({r.product_code for r in hits if r.product_code})
        row = dict.fromkeys(COLUMNS, '')
        row.update(case_id=f'{PREFIX[rule]}/{ident}', risk_check=rule, taxpayer_id=first.taxpayer_id,
                   business_name=data.taxpayers_by_id[first.taxpayer_id].business_name,
                   product='; '.join(f'{code}: {products.get(code, code)}' for code in codes),
                   review_start=str(review.start), review_end=str(review.end),
                   reason=' | '.join(dict.fromkeys(r.reason for r in hits)))
        purchases = set()
        if first.record_type == 'Stock review':
            ledger = sorted(stock[ident], key=lambda s: s.period_end)
            purchases.update(first.related_fdns)
            if ledger:
                row.update(unit=ledger[0].unit, units_purchased=str(sum(s.purchases for s in ledger)),
                           units_sold=str(sum(s.sales for s in ledger)), closing_stock=str(ledger[-1].closing_stock))
        else:
            numbers = sorted({r.line_number for r in hits if r.line_number is not None})
            row.update(sale_fdn=ident, sale_date=str(data.documents_by_fdn[ident].issue_date),
                       flagged_lines='; '.join(map(str, numbers)),
                       unit='; '.join(sorted({lines[ident, n].unit for n in numbers})))
            if rule == 'VAT misclassification':
                evidence = [e for e in review.vat_evidence if e.taxpayer_id == first.taxpayer_id
                            and e.product_code in codes and ident in e.related_fdns]
                row['stocking_records'] = '; '.join(sorted(e.record_id for e in evidence if e.record_id))
                purchases.update(e.source_fdn for e in evidence if e.source_fdn)
                amounts = [r.estimated_vat_difference for r in hits if r.estimated_vat_difference is not None]
                if amounts:
                    row['estimated_vat_difference_ugx'] = f'{sum(amounts, Decimal(0)):.2f}'
        invoices = sorted(purchases, key=lambda fdn: (data.documents_by_fdn[fdn].issue_date, fdn))
        row['purchase_fdns'] = '; '.join(invoices)
        row['purchase_dates'] = '; '.join(str(data.documents_by_fdn[fdn].issue_date) for fdn in invoices)
        output.append(row)
    return output


def write_demo_register(folder: Path) -> list[dict[str, str]]:
    dataset = EFRISDataset(folder)
    review = run_review(dataset, FIRST, LAST)
    rows = build_register(dataset, review)
    counts = Counter(r['risk_check'] for r in rows)
    if any(counts[rule] < 5 for rule in RULES):
        raise ValueError(f'Six-month demo requires at least five independent cases per check: {counts}')
    path = folder / 'case_register.csv'
    tmp = path.with_suffix('.csv.tmp')
    with tmp.open('w', encoding='utf-8-sig', newline='') as f:
        writer = DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)
    statuses = Counter(r.status for r in review.findings)
    print(f'{len(rows)} distinct cases | ' + ' | '.join(f'{rule}: {counts[rule]}' for rule in RULES))
    print(f"Check results: {statuses['Flagged']} flagged | {statuses['Not flagged']} not flagged | "
          f"{statuses['Insufficient data']} insufficient data. Saved: {path.name}")
    return rows

if __name__ == '__main__':
    write_demo_register(Path(__file__).resolve().parents[1] / 'generated' / 'six_month')
