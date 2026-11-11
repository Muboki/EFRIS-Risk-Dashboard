"""Presentation only: render actual case-register rows, without evaluating any risks."""
from __future__ import annotations

from base64 import b64encode
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from html import escape
from pathlib import Path

from src.case_register import RULES, PeriodReview
from src.dataset import EFRISDataset
from src.risk_engine import REVIEW_WEIGHTS, TaxpayerPriority
from src.risk_rules import RiskResult

ROOT = Path(__file__).resolve().parents[1]
STYLES = ROOT / "assets" / "dashboard.css"
VAT, STOCK, ACTIVITY, PRICE = RULES
Case = dict[str, str]

# Colour identifies the check; labels and icons give the same information without colour.
LOOK = {
    VAT: ("vat", "#ffbd82", "Estimated VAT difference",
          "Compare each sale with its dated VAT classification. Open an invoice to see the stocking evidence.",
          '<path d="M5 3h14v18l-2-1.5L15 21l-3-1.5L9 21l-2-1.5L5 21zM8 8h8M8 12h5M8 16h3"/>'),
    STOCK: ("stock", "#80dfc8", "Closing stock",
            "Each row is one buyer and product. Both purchase invoices support the same stock review.",
            '<path d="m3 7 9-4 9 4-9 4zM3 7v10l9 4 9-4V7M12 11v10M8 5l9 4"/>'),
    ACTIVITY: ("activity", "#cebaff", "Declared activity",
               "Compare the goods on the invoice with the seller’s declared business activity.",
               '<path d="M3 10h18l-2-6H5zM5 10v10h14V10M9 20v-6h6v6M3 10c0 3 4 3 4 0 0 3 5 3 5 0 0 3 5 3 5 0 0 3 4 3 4 0"/>'),
    PRICE: ("price", "#a6d3ff", "Recorded unit price",
            "Open a sale to compare its recorded price with the applicable range and discount evidence.",
            '<path d="M3 4h8l10 10-7 7L3 10z"/><circle cx="7.5" cy="7.5" r="1.1"/>'),
}


def e(value: object) -> str:
    return escape(str(value), quote=True)


def _svg_uri(svg: str) -> str:
    return 'data:image/svg+xml;base64,' + b64encode(svg.encode()).decode('ascii')


def _icon(path: str, colour: str) -> str:
    return _svg_uri(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                    f'stroke="{colour}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">{path}</svg>')


MARK = _icon('<path d="M4 4h16v16H4zM8 8h8M8 12h5M8 16h7"/>', '#edc77c')
ART = _svg_uri("""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 340 207" fill="none">
 <defs><pattern id="grid" width="16" height="16" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".9" fill="#739f99" opacity=".4"/></pattern></defs>
 <rect x="11" y="4" width="324" height="200" fill="url(#grid)"/>
 <path d="M5 168c69 0 63-105 142-105h171M15 179c80 0 72-105 147-105h152" stroke="#8ac0b3" stroke-opacity=".26"/>
 <g transform="rotate(12 215 100)"><rect x="165" y="28" width="105" height="143" rx="9" fill="#1d4145" stroke="#538a83"/><path d="M178 48h60M178 59h42m-42 72h74m-74 10h52" stroke="#89b6ac" opacity=".7"/></g>
 <g transform="rotate(-7 168 105)"><path d="M119 26h98q6 0 6 6v140l-9-4-8 5-9-5-9 5-9-5-9 5-9-5-9 5-9-5-9 5-9-5-8 4V32q0-6 6-6Z" fill="#213943" stroke="#91bcb0" stroke-width="1.5"/>
 <rect x="128" y="42" width="18" height="18" rx="3" fill="#305552"/><path d="m132 51 3 3 7-8" stroke="#a5f0d7" stroke-width="2"/>
 <text x="152" y="49" font-family="Arial,sans-serif" font-size="7" font-weight="bold" letter-spacing="1" fill="#f5f8f6">FISCAL</text>
 <text x="152" y="58" font-family="Arial,sans-serif" font-size="7" font-weight="bold" letter-spacing="1" fill="#f5f8f6">DOCUMENT</text>
 <path d="M128 70h79" stroke="#71968f"/><path d="M128 82h39m19 0h21m-79 12h45m13 0h21m-79 12h35m21 0h23" stroke="#a2c3bc" stroke-width="2.6"/>
 <path d="M128 117h79" stroke="#71968f" stroke-dasharray="3 3"/><text x="128" y="133" font-family="monospace" font-size="9" fill="#f6cf8d">FDN</text>
 <path d="M152 129h53M128 145h72" stroke="#91b6b0" stroke-width="3"/></g>
 <circle cx="234" cy="150" r="24" fill="#493d29" stroke="#e9bf75" stroke-width="2.8"/><path d="m222 150 8 8 15-18" stroke="#f7e4ad" stroke-width="3.3" stroke-linecap="round" stroke-linejoin="round"/>
 </svg>""")


def period_label(start: date, end: date) -> str:
    if (start.year, start.month) == (end.year, end.month):
        return start.strftime('%B %Y')
    if start.year == end.year:
        return f"{start:%B} – {end:%B %Y}"
    return f"{start:%B %Y} – {end:%B %Y}"


def header(data: EFRISDataset) -> str:
    return f'''<header class="ef-surface ef-hero"><div class="ef-hero-text">
      <div class="ef-brand"><img class="ef-brand-mark" src="{MARK}" alt="">Uganda <span class="ef-brand-rule"></span> Tax compliance review</div>
      <h1>EFRIS Risk Dashboard</h1><p>Review VAT compliance risks across wholesale and retail invoices.</p>
      <div class="ef-chipline"><span class="ef-chip">Fictional data</span><span>Full dataset: {len(data.taxpayers):,} taxpayers · {len(data.documents):,} invoices · {len(data.lines):,} product lines</span></div>
      </div><img class="ef-hero-art" src="{ART}" alt=""></header>'''


def metric_band(cases: Sequence[Case], review: PeriodReview) -> str:
    counts = Counter(r.status for r in review.findings)
    metrics = [('Distinct flagged cases', len(cases), 'Invoices and stock reviews', '#86ddbb'),
               ('Flagged findings', counts['Flagged'], 'Individual check results', '#ffbd82'),
               ('Not flagged', counts['Not flagged'], 'Individual check results', '#83d6e3'),
               ('Insufficient data', counts['Insufficient data'], 'Evidence needed', '#c9b9ee')]
    cells = ''.join(f'<div class="ef-stat{" ef-stat-focus" if i == 0 else ""}"><span class="ef-stat-label">'
                    f'<i class="ef-dot" style="--point:{color}" aria-hidden="true"></i>{label}</span>'
                    f'<strong>{n:,}</strong><small>{note}</small></div>'
                    for i, (label, n, note, color) in enumerate(metrics))
    return f'<section class="ef-surface ef-metrics" aria-label="Review totals">{cells}</section>'


def lead(kicker: str, title: str, text: str) -> str:
    return (f'<div class="ef-surface ef-lead"><span class="ef-kicker">{e(kicker)}</span>'
            f'<h2>{e(title)}</h2><p>{e(text)}</p></div>')


def _split(val: str) -> list[str]:
    return [x.strip() for x in val.split(';') if x.strip()]


def _date(value: str) -> str:
    return date.fromisoformat(value).strftime('%d %b %Y') if value else 'Date not supplied'


def _ugx(value: object) -> str:
    if value is None or value == '':
        return 'Not estimated'
    amount = Decimal(str(value))
    return 'UGX ' + (f'{amount:,.0f}' if amount == amount.to_integral_value() else f'{amount:,.2f}')


def _stock_amount(c: Case) -> str:
    if not c['closing_stock']:
        return 'Not supplied'
    n = Decimal(c['closing_stock']); unit = c['unit']
    if n != 1:
        unit = {'piece':'pieces', 'bag':'bags', 'packet':'packets', 'bottle':'bottles', 'pair':'pairs'}.get(unit, unit)
    return f'{n:,} {unit}'


def _pairs(items: Iterable[tuple[str, str]]) -> str:
    values = ''.join(f'<dt>{e(k)}</dt><dd>{e(v)}</dd>' for k, v in items if v)
    return f'<dl>{values}</dl>' if values else ''


def _case_row(rule: str, c: Case, data: EFRISDataset, prices: dict[tuple[str, int], Decimal],
              support: dict[str, RiskResult]) -> str:
    is_stock = rule == STOCK
    docs = _split(c['purchase_fdns']) if is_stock else [c['sale_fdn']]
    if is_stock:
        dates = [_date(s) for s in _split(c['purchase_dates'])]
        subtitle = f'{len(set(dates))} purchase dates'; owner = 'Buyer'
    else:
        subtitle = _date(c['sale_date']); owner = 'Seller'
    product_parts = [v.partition(': ') for v in _split(c['product'])]
    product = '; '.join(name or code for code, _, name in product_parts)
    short_product = '; '.join(code for code, _, _ in product_parts) if is_stock else 'Line ' + c['flagged_lines'].replace('; ', ', ')
    if is_stock:
        outcome = _stock_amount(c)
    elif rule == VAT:
        outcome = _ugx(c['estimated_vat_difference_ugx'])
    elif rule == ACTIVITY:
        outcome = data.taxpayers_by_id[c['taxpayer_id']].business_activity
    else:
        numbers = [int(n) for n in _split(c['flagged_lines'])]
        outcome = ' · '.join((f'L{n}: ' if len(numbers) > 1 else '') + _ugx(prices.get((c['sale_fdn'], n))) for n in numbers)
    cols = ('Purchase FDNs' if is_stock else 'Sale FDN', owner, 'Product', LOOK[rule][2])
    fnums = ''.join(f'<span class="ef-fdn ef-line">{e(f)}</span>' for f in docs) or 'Not supplied'
    def cell(label: str, content: str, css: str='') -> str:
        return f'<span class="{css}"><span class="ef-row-label">{e(label)}: </span>{content}</span>'
    units = [s for s in (c['units_purchased'], c['units_sold']) if s]
    evidence = [('Taxpayer', f"{c['business_name']} ({c['taxpayer_id']})"), ('Product and unit', f"{c['product']} · {c['unit']}"),
                ('Sale invoice', c['sale_fdn']), ('Flagged line(s)', c['flagged_lines']), ('Purchase FDNs', c['purchase_fdns']),
                ('Purchase dates', c['purchase_dates']), ('Stocking record(s)', c['stocking_records'])]
    if is_stock and len(units)==2:
        evidence.append(('Stock movements', f"{units[0]} purchased · {units[1]} sold · {_stock_amount(c)} at period end"))
    if rule == VAT and c['estimated_vat_difference_ugx']:
        evidence.append(('Estimated VAT difference', _ugx(c['estimated_vat_difference_ugx'])))
    for sid in _split(c['stocking_records']):
        hit = support.get(sid)
        if hit:
            source = (f" Source: {hit.source_fdn}, line {hit.source_line_number}." if hit.source_fdn and hit.source_line_number is not None else '')
            evidence.append((sid, hit.reason + source))
    summary = (cell(cols[0], f'{fnums}<span class="ef-sub">{e(subtitle)}</span>')+
               cell(cols[1], f'<span class="ef-key">{e(c["business_name"])}</span><span class="ef-sub">{e(c["taxpayer_id"])}</span>')+
               cell(cols[2], f'<span class="ef-key">{e(product)}</span><span class="ef-sub">{e(short_product)}</span>')+
               cell(cols[3], e(outcome), 'ef-outcome')+'<i class="ef-chevron" aria-hidden="true"></i>')
    return (f'<div class="ef-item" role="listitem"><details class="ef-case" data-case="{e(c["case_id"])}">'
            f'<summary class="ef-row">{summary}</summary><div class="ef-detail"><strong>Why this was flagged</strong>'
            f'<p>{e(c["reason"])}</p>{_pairs(evidence)}</div></details></div>')


def _extra_records(items: Sequence[RiskResult]) -> str:
    if not items:
        return ''
    parts = []
    for item in items:
        ident = item.record_id or item.fdn or item.taxpayer_id
        line = f' · line {item.line_number}' if item.line_number else ''
        parts.append(f'<article><strong>{e(ident + line)}</strong> · {e(item.status)} · {e(item.record_type)}'
                     f'<p>{e(item.reason)}</p>{_pairs([("Taxpayer",item.taxpayer_id),("Source FDN",item.source_fdn or ""),("Related FDNs", "; ".join(item.related_fdns))])}</article>')
    return (f'<details class="ef-extra"><summary>Other records to review ({len(parts)})'
            f'<i class="ef-chevron" aria-hidden="true"></i></summary>{"".join(parts)}</details>')


def grouped_cases(data: EFRISDataset, review: PeriodReview, cases: Sequence[Case]) -> str:
    """Render one issue heading per rule; a single sale FDN or stock pattern per row."""
    by_rule: dict[str, list[Case]] = defaultdict(list)
    for c in cases:
        by_rule[c['risk_check']].append(c)
    attached = {sid for c in cases for sid in _split(c['stocking_records'])}
    support = {r.record_id:r for r in review.vat_evidence if r.record_id}
    extras: dict[str, list[RiskResult]] = defaultdict(list)
    for r in review.findings:
        if r.status == 'Insufficient data' or (r.status == 'Flagged' and r.record_type in ('Stocking-in', 'Registration') and r.record_id not in attached):
            extras[r.rule_name].append(r)
    prices = {(line.fdn,line.line_number):line.unit_price for line in data.lines}
    first = next((rule for rule in RULES if by_rule[rule] or extras[rule]), None)
    sections = []
    for rule in RULES:
        css, color, last_col, tip, icon = LOOK[rule]
        stock = rule == STOCK
        rows = by_rule[rule]; n = len(rows)
        label = ('stock case' if stock else 'flagged invoice') + ('' if n == 1 else 's')
        badges = f'<span class="ef-pill">{n} {label}</span>'
        cols = ['Purchase FDNs' if stock else 'Sale FDN', 'Buyer' if stock else 'Seller', 'Product', last_col]
        if rows:
            entries = ''.join(_case_row(rule,c,data,prices,support) for c in rows)
            body = ('<div class="ef-cols" aria-hidden="true">' + ''.join(f'<span>{e(col)}</span>' for col in cols) + '<span></span></div>'
                    f'<div role="list" aria-label="{e(rule)} cases">{entries}</div>')
        else:
            body = '<p class="ef-empty">No flagged cases for this issue in the selected period.</p>'
        sections.append(f'''<details class="ef-issue ef-{css}" data-risk="{e(rule)}"{' open' if rule==first else ''}><summary class="ef-issue-header">
          <span class="ef-symbol"><img alt="" src="{_icon(icon,color)}"></span><span class="ef-issue-name">{e(rule)}</span>
          {badges}<i class="ef-chevron" aria-hidden="true"></i></summary><div class="ef-issue-body">
          <p class="ef-intro">{e(tip)}</p>{body}{_extra_records(extras[rule])}</div></details>''')
    return '<section class="ef-surface ef-issues" aria-label="Cases grouped by issue">' + ''.join(sections) + '</section>'


def ranking(data: EFRISDataset, ranks: Sequence[TaxpayerPriority]) -> str:
    rows = []
    max_points = sum(REVIEW_WEIGHTS.values())
    for item in ranks:
        width = min(100, int(100 * item.total_points / max_points))
        name = data.taxpayers_by_id[item.taxpayer_id].business_name
        rows.append(f'<div class="ef-rank"><span><span class="ef-key">{e(name)}</span><small class="ef-sub">{e(item.taxpayer_id)}</small></span>'
                    f'<span class="ef-track" aria-hidden="true"><i style="--bar:{width}%"></i></span><span class="ef-score">{item.total_points} pts</span></div>')
    return '<div class="ef-surface ef-ranking">' + ''.join(rows) + '</div>'


def saved_view(data: EFRISDataset, review: PeriodReview, cases: Sequence[Case]) -> str:
    """A portable copy of the same case-review components; no web service or script required."""
    period = period_label(review.start, review.end)
    return ('<!doctype html><html lang="en" class="ef-document"><head><meta charset="utf-8"><meta name="color-scheme" content="dark"><meta name="theme-color" content="#101923">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>EFRIS Risk Dashboard · Saved case review</title><style>' + STYLES.read_text(encoding='utf-8') + '</style></head>'
            '<body class="ef-preview"><main class="ef-surface">' + header(data)
            + f'<p class="ef-preview-note">Saved view · {e(period)}. Open an issue, then an invoice, to inspect the evidence.</p>'
            + metric_band(cases, review) + lead(period, 'Flagged cases by issue', 'Each sale counts once under its issue. A stock case can include several purchase invoices.')
            + grouped_cases(data,review,cases)
            + '<p class="ef-foot">Fictional demonstration data. A flag requires review and does not prove wrongdoing. Use the Streamlit app to change months and download findings.</p></main></body></html>')


if __name__ == '__main__':
    from src.case_register import FIRST, LAST, build_register, run_review
    dataset = EFRISDataset(ROOT / 'generated' / 'six_month')
    reviewed = run_review(dataset, FIRST, LAST)
    output = ROOT / 'preview' / 'EFRIS_Dashboard_Preview.html'
    output.parent.mkdir(exist_ok=True)
    output.write_text(saved_view(dataset, reviewed, build_register(dataset, reviewed)), encoding='utf-8')
    print(f'Saved {output.name}')
