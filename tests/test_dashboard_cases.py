"""A reviewer sees one heading per risk and the right invoices beneath it."""
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

from streamlit.testing.v1 import AppTest


class CaseSummaryReader(HTMLParser):
    """Read accessible issue/row summaries from the HTML actually sent to Streamlit."""
    def __init__(self):
        super().__init__()
        self.groups = {}
        self.details = []
        self.current_summary = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'details':
            if 'data-risk' in a:
                risk = a['data-risk']
                assert risk not in self.groups, f'Repeated issue heading: {risk}'
                self.groups[risk] = {'title': [], 'cases': {}}
                self.details.append(('group', risk))
            elif 'data-case' in a:
                _, risk = self.details[-1]
                key = a['data-case']
                assert key not in self.groups[risk]['cases'], f'Duplicate case: {key}'
                self.groups[risk]['cases'][key] = []
                self.details.append(('case', (risk, key)))
            else:
                self.details.append(('other', None))
        elif tag == 'summary' and self.details:
            self.current_summary = self.details[-1]

    def handle_data(self, text):
        if self.current_summary:
            kind, item = self.current_summary
            if kind == 'group':
                self.groups[item]['title'].append(text)
            elif kind == 'case':
                risk, key = item
                self.groups[risk]['cases'][key].append(text)

    def handle_endtag(self, tag):
        if tag == 'summary':
            self.current_summary = None
        elif tag == 'details':
            self.details.pop()


def screen(ui):
    assert not ui.exception
    pieces = [x.proto.body for x in ui.get('html')]
    register = next(s for s in pieces if 'aria-label="Cases grouped by issue"' in s)
    reader = CaseSummaryReader()
    reader.feed(register)
    return reader.groups


def test_dashboard_shows_case_counts_and_respects_selected_months():
    ui = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=15).run()
    groups = screen(ui)
    assert {k:len(g['cases']) for k,g in groups.items()} == {
        'VAT misclassification': 5, 'Purchases without sales': 5,
        'Business-profile mismatch': 5, 'Possible price understatement': 5,
    }
    vat = groups['VAT misclassification']
    assert '5 flagged invoices' in ''.join(vat['title'])
    assert set(vat['cases']) == {f'VAT/{fdn}' for fdn in ('DEMO-FDN-007', 'SIM-R-0059', 'SIM-R-0175', 'SIM-R-0188', 'SIM-R-0272')}
    assert all('VAT misclassification' not in ''.join(text) for text in vat['cases'].values())
    pipe = next(''.join(t) for key,t in groups['Purchases without sales']['cases'].items() if '/DEMO002/PROD013/' in key)
    assert all(s in pipe for s in ('DEMO-FDN-013', 'DEMO-FDN-014', '20 pieces'))
    assert len(ui.get('download_button')) == 2
    ui.selectbox(key='review_from').set_value(date(2026,2,1)).run()
    ui.selectbox(key='review_through').set_value(date(2026,2,1)).run()
    groups = screen(ui)
    assert {k:len(v['cases']) for k,v in groups.items()} == {
        'VAT misclassification': 1, 'Purchases without sales': 0,
        'Business-profile mismatch': 1, 'Possible price understatement': 1,
    }
    assert set(groups['VAT misclassification']['cases']) == {'VAT/SIM-R-0059'}
