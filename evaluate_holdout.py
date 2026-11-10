"""Evaluate frozen EFRIS rules on new, pre-labelled fictional transactions.

Run from the project: python evaluate_holdout.py
The four taxpayer profiles reuse the project's business-activity vocabulary.
Only the reference catalogue, price benchmarks and CSV schemas are shared.
No demonstration transactions, case labels or six-month outputs are read.
The unit of evaluation is a specified rule applied to a specified record.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.risk_rules import RiskResult


START, END = date(2026, 3, 1), date(2026, 3, 31)
FLAG, CLEAR, UNKNOWN = "Flagged", "Not flagged", "Insufficient data"
VAT = "VAT misclassification"
STOCK = "Purchases without sales"
ACTIVITY = "Business-profile mismatch"
PRICE = "Possible price understatement"
WHOLESALER, FURNITURE, CLOTHING, HOUSEHOLD = "HOLD001", "HOLD002", "HOLD003", "HOLD004"
CHAIR, TABLE, FRIDGE, SHOES, BUCKET = "PROD009", "PROD010", "PROD004", "PROD008", "PROD011"


def fdn(number: int) -> str:
    return f"HOLD-FDN-{number:03d}"


@dataclass(frozen=True)
class Case:
    case_id: str
    rule: str
    taxpayer: str
    product: str
    expected: str
    scenario: str
    invoice: str = ""
    line: int | None = None
    stock_entry: str = ""

    def matches(self, finding: RiskResult) -> bool:
        if (finding.rule_name, finding.taxpayer_id, finding.product_code) != (
            self.rule, self.taxpayer, self.product
        ):
            return False
        if self.invoice:
            return finding.fdn == self.invoice and finding.line_number == self.line
        if self.stock_entry:
            return finding.record_id == self.stock_entry
        # There is one review window and one unit per product in this fixture.
        return finding.record_type == "Stock review"


# Set before calling the engine. These labels are never passed to any rule.
CASES = (
    Case("H01", VAT, FURNITURE, TABLE, FLAG, "Standard-rated tables stocked as exempt; an exempt sale follows.", stock_entry="HOLD-STK-02"),
    Case("H02", VAT, FURNITURE, CHAIR, CLEAR, "Chairs stocked under the category in the dated catalogue.", stock_entry="HOLD-STK-01"),
    Case("H03", STOCK, FURNITURE, CHAIR, FLAG, "Chairs bought on 4 and 13 March, none sold; all 11 remain."),
    Case("H04", STOCK, FURNITURE, TABLE, CLEAR, "Five tables bought, two sold and three left at month end."),
    Case("H05", ACTIVITY, CLOTHING, FRIDGE, FLAG, "Clothing retailer sells a fridge without a documented exception.", fdn(4), 1),
    Case("H06", ACTIVITY, CLOTHING, SHOES, CLEAR, "The same clothing retailer sells a pair of shoes on the same invoice.", fdn(4), 2),
    Case("H07", PRICE, HOUSEHOLD, BUCKET, FLAG, "Bucket at 65% of the benchmark minimum with no discount.", fdn(5), 1),
    Case("H08", PRICE, HOUSEHOLD, BUCKET, CLEAR, "Bucket at 85% of the minimum; a documented 20% discount explains it.", fdn(6), 1),
    Case("H09", PRICE, HOUSEHOLD, BUCKET, UNKNOWN, "No price-context row: quality and discount evidence are missing.", fdn(7), 1),
)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_rows(path: Path, header: list[str], rows) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def build_fixture(seed: Path, target: Path) -> None:
    """Write only to the temporary directory. Use project headers and reference values."""
    def table(name: str, rows) -> None:
        with (seed / name).open(encoding="utf-8-sig", newline="") as stream:
            header = next(csv.reader(stream))
        write_rows(target / name, header, rows)

    profiles = {r["taxpayer_id"]: r for r in read_rows(seed / "taxpayers.csv")}
    owners = {
        WHOLESALER: ("DEMO009", "Holdout Furniture Wholesale"),
        FURNITURE: ("DEMO010", "Holdout Furniture Retail"),
        CLOTHING: ("DEMO008", "Holdout Clothing Retail"),
        HOUSEHOLD: ("DEMO012", "Holdout Household Retail"),
    }
    table("taxpayers.csv", [
        {**profiles[template], "taxpayer_id": uid, "business_name": name}
        for uid, (template, name) in owners.items()
    ])
    for filename in ("product_catalogue.csv", "price_benchmarks.csv"):
        copyfile(seed / filename, target / filename)
    table("business_activity_evidence.csv", [])

    # The verified demo catalogue has one domestic reference per product and
    # one standard-quality price range per product and trading level in March.
    def covers_march(row: dict[str, str]) -> bool:
        return (row["valid_from"] <= START.isoformat()
                and (not row["valid_to"] or row["valid_to"] >= END.isoformat()))

    references = {r["product_code"]: r for r in read_rows(target / "product_catalogue.csv")
                  if covers_march(r) and r["supply_condition"].casefold() == "ordinary domestic sale"}
    benchmarks = {(r["product_code"], r["business_type"]): r
                  for r in read_rows(target / "price_benchmarks.csv")
                  if covers_march(r) and r["quality"].casefold() == "standard"
                  and r["location"].casefold() == "demo town"
                  and "".join(c for c in r["vat_basis"].casefold() if c.isalnum()) in {"vatexclusive", "exclusive"}}
    if references[TABLE]["expected_vat_category"].casefold() == "exempt" or Decimal(references[TABLE]["vat_rate"]) <= 0:
        raise ValueError("H01 requires a positive-rated reference for the tables.")

    # Each tuple gives document number, day in March, seller and optional buyer.
    docs = ((1, 4, WHOLESALER, FURNITURE), (2, 13, WHOLESALER, FURNITURE), (3, 19, FURNITURE, ""), (4, 20, CLOTHING, ""),
            (5, 22, HOUSEHOLD, ""), (6, 23, HOUSEHOLD, ""), (7, 24, HOUSEHOLD, ""))
    sellers = {n: seller for n, _, seller, _ in docs}
    location = benchmarks[(BUCKET, "Retail")]["location"]
    table("fiscal_documents.csv", [
        dict(fdn=fdn(n), seller_id=seller, buyer_id=buyer, issue_date=date(2026, 3, day),
             supply_condition=references[TABLE]["supply_condition"], location=location)
        for n, day, seller, buyer in docs
    ])

    lines, contexts = [], []

    def line(doc: int, number: int, code: str, quantity: int, *, exempt: bool = False,
             floor_fraction: str = "", discount: str = "0", context: bool = True) -> None:
        ref = references[code]
        level = profiles[owners[sellers[doc]][0]]["business_type"]
        benchmark = benchmarks[(code, level)]
        low, high = (Decimal(benchmark[k]) for k in ("minimum_unit_price", "maximum_unit_price"))
        price = low * Decimal(floor_fraction) if floor_fraction else (low + high) / 2
        unit_price = price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rate = Decimal("0") if exempt else Decimal(ref["vat_rate"])
        vat = (unit_price * quantity * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        lines.append(dict(fdn=fdn(doc), line_number=number, product_code=code, unit=ref["unit"],
                          quantity=quantity, unit_price=unit_price,
                          vat_category="Exempt" if exempt else ref["expected_vat_category"], vat_amount=vat))
        if context:
            contexts.append(dict(fdn=fdn(doc), line_number=number, quality=benchmark["quality"],
                                 discount_rate=discount, discount_reference="HOLD-PROMO-01" if discount != "0" else "",
                                 discount_reason="Documented promotion on this sale" if discount != "0" else ""))

    line(1, 1, CHAIR, 4)
    line(1, 2, TABLE, 3)
    line(2, 1, CHAIR, 7)
    line(2, 2, TABLE, 2)
    line(3, 1, TABLE, 2, exempt=True)
    line(4, 1, FRIDGE, 1)
    line(4, 2, SHOES, 1)
    line(5, 1, BUCKET, 1, floor_fraction="0.65")
    line(6, 1, BUCKET, 1, floor_fraction="0.85", discount="0.20")
    line(7, 1, BUCKET, 1, floor_fraction="0.85", context=False)
    table("invoice_lines.csv", lines)
    table("invoice_price_contexts.csv", contexts)
    table("product_tax_records.csv", [
        dict(record_id=f"HOLD-STK-{n:02d}", taxpayer_id=FURNITURE, record_type="Stocking-in",
             record_date=date(2026, 3, 4), product_code=code, unit=references[code]["unit"],
             vat_category=category, supply_condition=references[code]["supply_condition"],
             source_fdn=fdn(1), source_line_number=n)
        for n, code, category in ((1, CHAIR, references[CHAIR]["expected_vat_category"]),
                                  (2, TABLE, "Exempt"))
    ])
    # Opening, purchases, sales and closing stock are specified independently.
    ledger = ((WHOLESALER, CHAIR, 11, 0, 11, 0), (WHOLESALER, TABLE, 5, 0, 5, 0),
              (FURNITURE, CHAIR, 0, 11, 0, 11), (FURNITURE, TABLE, 0, 5, 2, 3),
              (CLOTHING, FRIDGE, 1, 0, 1, 0), (CLOTHING, SHOES, 1, 0, 1, 0), (HOUSEHOLD, BUCKET, 3, 0, 3, 0))
    table("stock_ledger.csv", [
        dict(taxpayer_id=uid, product_code=code, unit=references[code]["unit"],
             period_start=START, period_end=END, opening_stock=opening, purchases=bought,
             sales=sold, closing_stock=closing, customer_returns=0, supplier_returns=0, own_use=0, write_offs=0)
        for uid, code, opening, bought, sold, closing in ledger
    ])


def compare(findings: list[RiskResult]) -> list[dict]:
    rows = []
    for case in CASES:
        hits = [r for r in findings if case.matches(r)]
        if len(hits) != 1:
            raise ValueError(f"{case.case_id}: expected exactly one matching finding; got {len(hits)}. No metrics produced.")
        hit = hits[0]
        if hit.status not in (FLAG, CLEAR, UNKNOWN):
            raise ValueError(f"{case.case_id}: unexpected status {hit.status!r}.")
        rows.append({**asdict(case), "actual": hit.status, "matches_label": hit.status == case.expected,
                     "result_record_id": hit.record_id or "", "related_fdns": "; ".join(hit.related_fdns),
                     "explanation": hit.reason})
    return rows


def summarise(rows: list[dict]) -> str:
    """Count abstentions explicitly; an abstention on a known risk is a missed risk."""
    binary = [r for r in rows if r["expected"] in (FLAG, CLEAR)]
    tp = sum(r["expected"] == FLAG and r["actual"] == FLAG for r in binary)
    fp = sum(r["expected"] == CLEAR and r["actual"] == FLAG for r in binary)
    fn = sum(r["expected"] == FLAG and r["actual"] != FLAG for r in binary)
    tn = sum(r["expected"] == CLEAR and r["actual"] == CLEAR for r in binary)
    abstained = sum(r["actual"] == UNKNOWN for r in binary)
    evidence = [r for r in rows if r["expected"] == UNKNOWN]

    def ratio(top: int, bottom: int) -> str:
        return f"{top / bottom:.1%} ({top}/{bottom})" if bottom else "undefined (zero denominator)"

    return "\n".join((
        f"Labelled risk/legitimate cases: {len(binary)} | TP: {tp} | FP: {fp} | FN: {fn} | TN: {tn}",
        f"Precision: {ratio(tp, tp + fp)} | Recall: {ratio(tp, tp + fn)} | False positives: {fp}",
        f"Insufficient-data outcomes on binary cases: {abstained}",
        f"Missing-evidence check: {sum(r['actual'] == UNKNOWN for r in evidence)}/{len(evidence)} returned Insufficient data",
    ))


def main() -> None:
    root = Path(__file__).resolve().parent
    if not (root / "src" / "dataset.py").is_file() or not (root / "data" / "taxpayers.csv").is_file():
        raise SystemExit("Save evaluate_holdout.py in EFRIS-Risk-Dashboard, next to app.py, then run it again.")
    from src.dataset import EFRISDataset
    from src.risk_engine import RiskEngine
    from src.risk_rules import BusinessActivityRule, PriceDeviationRule, PurchaseSalesRule, VATClassificationRule

    with TemporaryDirectory(prefix="efris_holdout_") as folder:
        fixture = Path(folder)
        build_fixture(root / "data", fixture)
        engine = RiskEngine([VATClassificationRule(), PurchaseSalesRule(START, END),
                             BusinessActivityRule(), PriceDeviationRule()])
        rows = compare(engine.run(EFRISDataset(fixture)))

    output = root / "evaluation"
    output.mkdir(exist_ok=True)
    report = summarise(rows)
    write_rows(output / "holdout_results.csv", list(rows[0]), rows)
    (output / "holdout_summary.txt").write_text(report + "\n", encoding="utf-8")
    print(report)
    print("Saved: evaluation/holdout_results.csv and evaluation/holdout_summary.txt")


if __name__ == "__main__":
    main()
