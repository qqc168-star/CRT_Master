"""Read supported issuer tables by cell coordinates and dated column headers.

No swing in document order or adjacent financial column can select a value.
Ambiguous tables remain missing; narrative fallbacks must not override them.
"""
from datetime import datetime, timezone
from html.parser import HTMLParser
import re

_MONTHS = 'January February March April May June July August September October November December'.split()
_DATE = r'(' + '|'.join(_MONTHS) + r')\s+(\d{1,2}),\s+(20\d{2})'


def _date(text):
    match = re.search(_DATE, text, re.I)
    if not match:
        return None
    try:
        month = [m.lower() for m in _MONTHS].index(match[1].lower()) + 1
        return datetime(int(match[3]), month, int(match[2]), tzinfo=timezone.utc).date().isoformat()
    except ValueError:
        return None


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            if self.stack:
                self.stack[-1]['invalid'] = True
            self.stack.append({'rows': [], 'row': None, 'cell': None, 'invalid': False})
        if not self.stack:
            return
        state = self.stack[-1]
        if tag == 'tr':
            state['row'] = []
        elif tag in ('td', 'th') and state['row'] is not None:
            attrs = dict(attrs)
            try:
                span = int(attrs.get('colspan', '1'))
                if not 1 <= span <= 100 or int(attrs.get('rowspan', '1')) != 1:
                    state['invalid'] = True
            except ValueError:
                span = 1
                state['invalid'] = True
            state['cell'] = [span, []]

    def handle_data(self, data):
        if self.stack and self.stack[-1]['cell'] is not None:
            self.stack[-1]['cell'][1].append(data)

    def handle_endtag(self, tag):
        if not self.stack:
            return
        state = self.stack[-1]
        if tag in ('td', 'th') and state['cell'] is not None:
            span, parts = state['cell']
            start = state['row'][-1][1] if state['row'] else 0
            text = re.sub(r'\s+', ' ', ' '.join(parts)).strip()
            state['row'].append((start, start + span, text))
            state['cell'] = None
        elif tag == 'tr' and state['row'] is not None:
            state['rows'].append(state['row'])
            state['row'] = None
        elif tag == 'table':
            self.tables.append(self.stack.pop())


def _number(row, start, end):
    text = ' '.join(t for a, b, t in row if a >= start and b <= end).strip()
    text = re.sub(r'\s*\(\d+\)\s*$', '', text).strip()
    if re.fullmatch(r'\$?\s*(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?', text):
        return float(text.replace('$', '').replace(',', '').strip())
    # A dash or missing cell is not assumed to be zero.
    return None


def dated_table_facts(raw, issuer, *, disclosed_at_ms=None):
    parser = _Tables()
    parser.feed(raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw)
    candidates = {}
    labels = {
        'Bitcoin held': ('BTC_HOLDINGS', 1),
        'Assumed Fully Diluted Shares': ('DILUTED_SHARES', 1),
        'Shares Underlying Traditional Warrants': ('WARRANTS_OUTSTANDING', 1),
        'Shares of STRC held': ('STRIVE_STRC_HOLDINGS', 1),
        'Fair value of STRC Stock (in thousands)': ('STRIVE_STRC_FAIR_VALUE', 1000),
    }

    def add(kind, value, date, table, label, period=None):
        context = {'reported_as_of_date': date, 'date_precision': 'DAY',
                   'table_label': label, 'time_semantics': 'REPORTED_DATE_NOT_EXECUTION_TIME'}
        if period:
            context['reported_period'] = period
            context['time_semantics'] = 'PERIOD_AGGREGATE_NOT_SINGLE_EXECUTION'
        if kind == 'DILUTED_SHARES':
            context['share_basis'] = ('AFDS_EXCLUDES_TRADITIONAL_WARRANTS' if
                'Shares underlying Traditional Warrants are excluded' in table else
                'ASSUMED_FULLY_DILUTED_SHARES_AS_REPORTED')
        candidates.setdefault(kind, []).append({'value': value, 'reported_context': context})

    for table in parser.tables:
        rows = table['rows']
        text = ' '.join(t for row in rows for _, _, t in row)
        if issuer == 'STRATEGY':
            dates = {_date(t) for row in rows for _, _, t in row if t.lower().startswith('as of ')}
            date = next(iter(dates)) if len(dates) == 1 else None
            periods = list(re.finditer(r'During Period\s+(' + _DATE + r')\s+to\s+(' + _DATE + r')', text, re.I))
            period_text = periods[0][0] if len(periods) == 1 else None
            period_dates = [_date(m[0]) for m in re.finditer(_DATE, period_text or '', re.I)]
            period_valid = (len(period_dates) == 2 and all(period_dates) and date is not None
                            and period_dates[0] <= period_dates[1] == date)
            for i, row in enumerate(rows):
                for start, end, label in row:
                    if label == 'Aggregate BTC Holdings':
                        cells = [cell for cell in row if cell[2]]
                        if len(cells) == 2 and cells[0][2] == label:
                            # Unambiguous vertical label/value pair only.
                            value = _number([cells[1]], cells[1][0], cells[1][1])
                        elif (all(_number([cell], cell[0], cell[1]) is None for cell in cells)
                              and i + 1 < len(rows)):
                            # Horizontal header: use its exact column, never a nearby number.
                            value = _number(rows[i + 1], start, end)
                        else:
                            value = None
                        add('BTC_HOLDINGS', None if table['invalid'] else value, date, text, label)
                    if re.fullmatch(r'Shares Sold(?:\s*\(\d+\))?', label):
                        for data in rows[i + 1:]:
                            if any(t == 'MSTR Stock' for _, _, t in data):
                                security_columns = [(a,b) for a,b,t in row if t == 'Security']
                                identity_valid = len(security_columns) == 1 and any(
                                    (a,b) == security_columns[0] and t == 'MSTR Stock' for a,b,t in data)
                                valid = not table['invalid'] and period_valid and identity_valid
                                add('ATM_SHARES_ISSUED', _number(data, start, end) if valid else None,
                                    date, text, 'MSTR Stock / ' + label, period_text)
        elif issuer == 'STRIVE':
            headers = [row for row in rows if sum(t.lower().startswith('as of ') for _, _, t in row) >= 2]
            for row in rows:
                for label_start, label_end, label in row:
                    clean = re.sub(r'\s*\(\d+\)$', '', label).strip()
                    if clean not in labels:
                        continue
                    # Single-period balance sheet is not a comparison-table fallback.
                    kind, scale = labels[clean]
                    if not headers:
                        numeric_cells = [cell for cell in row if _number([cell], cell[0], cell[1]) is not None]
                        if len(numeric_cells) >= 2:
                            add(kind, None, None, text, clean)
                        continue
                    dated = [(a, b, _date(t)) for a, b, t in headers[0] if t.lower().startswith('as of ')]
                    valid = (len(headers) == 1 and all(d for _, _, d in dated) and not table['invalid']
                             and all(label_end <= a for a,_,_ in dated))
                    date = max(d for _, _, d in dated) if valid else None
                    cols = [(a, b) for a, b, d in dated if d == date] if valid else []
                    value = _number(row, *cols[0]) if len(cols) == 1 else None
                    add(kind, value * scale if value is not None else None, date, text, clean)
    result = {}
    for kind, items in candidates.items():
        if any(not item['reported_context']['reported_as_of_date'] for item in items):
            result[kind] = {'value': None, 'reason': 'TABLE_DATE_OR_LAYOUT_UNRESOLVED'}
            continue
        latest = max(item['reported_context']['reported_as_of_date'] for item in items)
        selected = [item for item in items if item['reported_context']['reported_as_of_date'] == latest]
        if len({(item['value'], item['reported_context'].get('reported_period'),
                 item['reported_context'].get('share_basis')) for item in selected}) != 1 or selected[0]['value'] is None:
            result[kind] = {'value': None, 'reason': 'TABLE_VALUE_MISSING_OR_CONFLICT'}
        else:
            result[kind] = selected[0]
    if disclosed_at_ms is not None:
        disclosed_date = datetime.fromtimestamp(disclosed_at_ms / 1000, timezone.utc).date().isoformat()
        for kind, item in list(result.items()):
            if item.get('reported_context', {}).get('reported_as_of_date', '') > disclosed_date:
                result[kind] = {'value': None, 'reason': 'TABLE_DATE_AFTER_DISCLOSURE'}
    return result


def bind_table_context(facts, table_facts):
    for fact in facts:
        item = table_facts.get(fact['fact_type'])
        if item and item.get('value') is not None:
            context = dict(item['reported_context'])
            fact['reported_context'] = context
            # Existing integer field is a date anchor only, never a claimed intraday execution.
            fact['effective_at_ms'] = int(datetime.fromisoformat(
                context['reported_as_of_date']).replace(tzinfo=timezone.utc).timestamp() * 1000)
