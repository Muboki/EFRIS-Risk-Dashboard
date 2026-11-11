"""Acceptance tests for the lecturer's independent invoice-case requirement."""
import csv
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.case_register import FIRST, LAST, RULES, build_register, run_review
from src.dataset import EFRISDataset

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'generated' / 'six_month'

class CaseCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = EFRISDataset(FOLDER)
        cls.review = run_review(cls.data, FIRST, LAST)
        cls.cases = build_register(cls.data, cls.review)

    def test_five_independent_cases_per_issue(self):
        counts = Counter(c['risk_check'] for c in self.cases)
        self.assertEqual(set(counts), set(RULES))
        self.assertTrue(all(n >= 5 for n in counts.values()))
        self.assertEqual(len({c['case_id'] for c in self.cases}), len(self.cases))
        # These three demonstrations deliberately use separate sales invoices.
        sales = [c for c in self.cases if c['sale_fdn']]
        self.assertEqual(len({c['sale_fdn'] for c in sales}), len(sales))
        expected = {'VAT misclassification': 'DEMO-FDN-007', 'Business-profile mismatch': 'DEMO-FDN-015',
                    'Possible price understatement': 'DEMO-FDN-008'}
        self.assertTrue(all(any(c['risk_check'] == rule and c['sale_fdn'] == fdn for c in sales)
                            for rule, fdn in expected.items()))
        self.assertEqual(sum(r.status == 'Insufficient data' for r in self.review.findings), 0)

    def test_stock_cases_trace_to_two_dates_and_reconciled_goods(self):
        groups, used = set(), set()
        for c in self.cases:
            if c['risk_check'] != 'Purchases without sales':
                continue
            product = c['product'].split(':')[0]
            key = c['taxpayer_id'], product, c['unit']
            self.assertNotIn(key, groups)
            groups.add(key)
            docs = c['purchase_fdns'].split('; ')
            self.assertFalse(used.intersection(docs)); used.update(docs)
            self.assertGreaterEqual(len({self.data.documents_by_fdn[f].issue_date for f in docs}), 2)
            for fdn in docs:
                self.assertEqual(self.data.documents_by_fdn[fdn].buyer_id, key[0])
            matching = [l for l in self.data.lines if (l.product_code, l.unit) == key[1:]]
            purchase = [l for l in matching if self.data.documents_by_fdn[l.fdn].buyer_id == key[0]]
            self.assertEqual(set(docs), {l.fdn for l in purchase})
            self.assertFalse([l for l in matching if self.data.documents_by_fdn[l.fdn].seller_id == key[0]])
            qty = sum(l.quantity for l in purchase)
            self.assertGreater(qty, 0)
            self.assertEqual((Decimal(c['units_purchased']), Decimal(c['units_sold']), Decimal(c['closing_stock'])),
                             (qty, Decimal(0), qty))
        self.assertGreaterEqual(len(groups), 5)
        self.assertGreaterEqual(len(used), 10)

    def test_vat_evidence_links_stocking_and_sale_without_double_counting(self):
        records = {r.record_id: r for r in self.data.product_tax_records}
        source = {(l.fdn, l.line_number): l for l in self.data.lines}
        for c in self.cases:
            if c['risk_check'] != 'VAT misclassification':
                continue
            stocking = records[c['stocking_records']]
            sale = source[c['sale_fdn'], int(c['flagged_lines'])]
            self.assertEqual(stocking.taxpayer_id, c['taxpayer_id'])
            self.assertEqual(c['purchase_fdns'], stocking.source_fdn)
            self.assertEqual(source[stocking.source_fdn, stocking.source_line_number].product_code, sale.product_code)
            self.assertLessEqual(stocking.record_date, self.data.documents_by_fdn[sale.fdn].issue_date)
            self.assertIn(stocking.vat_category, ('Exempt', 'Zero-rated'))
            self.assertEqual(stocking.vat_category, sale.vat_category)
            self.assertEqual(sale.vat_amount, 0)
            self.assertGreater(Decimal(c['estimated_vat_difference_ugx']), 0)

    def test_multiple_flagged_lines_still_give_one_invoice_case(self):
        hit = next(r for r in self.review.findings if r.fdn == 'DEMO-FDN-007' and r.status == 'Flagged')
        second = next(l for l in self.data.lines if l.fdn == hit.fdn and l.line_number != hit.line_number)
        extra = replace(hit, line_number=second.line_number, product_code=second.product_code,
                        estimated_vat_difference=Decimal('100'))
        new = build_register(self.data, replace(self.review, findings=self.review.findings + [extra]))
        self.assertEqual(len(new), len(self.cases))
        merged = next(c for c in new if c['risk_check'] == hit.rule_name and c['sale_fdn'] == hit.fdn)
        self.assertEqual(merged['flagged_lines'], '1; 2')
        self.assertEqual(Decimal(merged['estimated_vat_difference_ugx']), Decimal('72100'))

    def test_one_month_does_not_borrow_later_purchases(self):
        feb = run_review(self.data, date(2026, 2, 1), date(2026, 2, 28))
        only = build_register(self.data, feb)
        self.assertEqual(len(only), 3)
        self.assertTrue(all(row['sale_date'].startswith('2026-02') for row in only))
        self.assertFalse(any(r.rule_name == 'Purchases without sales' and r.status == 'Flagged' for r in feb.findings))

    def test_invoice_totals_and_stock_balance_each_day_and_month(self):
        d = self.data
        self.assertEqual((len(d.taxpayers), len(d.documents_by_fdn), len(d.lines)), (12, 752, 1500))
        self.assertEqual(Counter(d.documents_by_fdn[l.fdn].issue_date.month for l in d.lines),
                         dict(enumerate((252, 248, 252, 248, 252, 248), 1)))
        ledger = defaultdict(list); changes = defaultdict(Decimal)
        for r in d.stock_records:
            key = r.taxpayer_id, r.product_code, r.unit
            ledger[key].append(r)
            changes[r.period_end, key] += r.customer_returns - r.supplier_returns - r.own_use - r.write_offs
        for l in d.lines:
            doc = d.documents_by_fdn[l.fdn]
            changes[doc.issue_date, (doc.seller_id, l.product_code, l.unit)] -= l.quantity
            if doc.buyer_id:
                changes[doc.issue_date, (doc.buyer_id, l.product_code, l.unit)] += l.quantity
        stock = {}
        for key, rows in ledger.items():
            rows.sort(key=lambda r: r.period_start)
            self.assertEqual([r.period_start.month for r in rows], list(range(1, 7)))
            self.assertTrue(all(r.stock_difference == 0 for r in rows))
            self.assertTrue(all(a.closing_stock == b.opening_stock for a, b in zip(rows, rows[1:])))
            stock[key] = rows[0].opening_stock
        for (day, key), delta in sorted(changes.items()):
            stock[key] += delta
            self.assertGreaterEqual(stock[key], 0, (day, key))
            row = ledger[key][day.month - 1]
            if day == row.period_end:
                self.assertEqual(stock[key], row.closing_stock, (day, key))

    def test_generator_recreates_shipped_inputs_and_register(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / 'src', root / 'src', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(ROOT / 'data', root / 'data')
            p = subprocess.run([sys.executable, '-m', 'src.data_generator'], cwd=root,
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            output = root / 'generated' / 'six_month'
            self.assertEqual({f.name for f in output.glob('*.csv')}, {f.name for f in FOLDER.glob('*.csv')})
            for f in FOLDER.glob('*.csv'):
                # A Git checkout may convert file newlines on Windows.
                self.assertEqual(f.read_text(encoding='utf-8-sig'), (output / f.name).read_text(encoding='utf-8-sig'), f.name)
            with (output / 'case_register.csv').open(encoding='utf-8-sig', newline='') as f:
                self.assertEqual(list(csv.DictReader(f)), self.cases)
