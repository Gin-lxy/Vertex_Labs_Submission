"""Funding-event normalization, aggregation and sensitivity analysis."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
import csv
import json
from pathlib import Path
import re

from harness import TaskResult


COLUMNS = ['date', 'company', 'sector', 'round', 'amount', 'currency', 'source']
SELECTOR_FIELDS = {'company', 'date', 'round', 'amount', 'currency', 'sector'}


def norm(text):
    return ' '.join(text.split()).casefold()


def number(text, *, positive=False):
    if not isinstance(text, str) or not re.fullmatch(r'\d+(?:\.\d+)?', text.strip()):
        raise ValueError(f'Invalid decimal amount or rate: {text!r}')
    if len(text.replace('.', '').strip()) > 24:
        raise ValueError('Decimal values must have at most 24 digits')
    value = Decimal(text.strip())
    if positive and value <= 0:
        raise ValueError('Exchange rates must be positive')
    return value


def decimal_text(value):
    return format(value, 'f').rstrip('0').rstrip('.') if '.' in format(value, 'f') else format(value, 'f')


def parse_date(text, formats):
    for pattern in formats:
        try:
            return datetime.strptime(text.strip(), pattern).date()
        except ValueError:
            continue
    raise ValueError(f'Date does not match configured formats: {text!r}')


def usd_amount(amount, currency, rates):
    currency = currency.strip().upper()
    if currency not in rates:
        raise ValueError(f'Unsupported currency: {currency}')
    with localcontext() as context:
        context.prec = 80
        return number(amount) * number(rates[currency], positive=True)


def aliases(mapping):
    result = {}
    for key, value in mapping.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip():
            raise ValueError('Aliases must map nonempty strings to nonempty strings')
        if norm(key) in result and result[norm(key)] != value.strip():
            raise ValueError('Conflicting normalized aliases')
        result[norm(key)] = value.strip()
    return result


def validate_config(config):
    expected = {'task_id', 'period', 'date_formats', 'usd_rates', 'company_aliases',
                'sector_aliases', 'event_merges', 'review_items', 'scenarios'}
    if set(config) != expected or config['task_id'] != FundingTask.task_id:
        raise ValueError('Unexpected or missing funding configuration fields')
    period = config['period']
    start, end = date.fromisoformat(period['start']), date.fromisoformat(period['end_exclusive'])
    if start >= end:
        raise ValueError('Period start must precede its exclusive end')
    if not config['date_formats'] or not all(isinstance(value, str) for value in config['date_formats']):
        raise ValueError('At least one explicit date format is required')
    if config['usd_rates'].get('USD') != '1':
        raise ValueError('The USD exchange rate must be the string 1')
    for currency, rate in config['usd_rates'].items():
        if not isinstance(currency, str) or not re.fullmatch('[A-Z]{3}', currency):
            raise ValueError('Currency keys must be uppercase three-letter codes')
        number(rate, positive=True)
    for group in ['event_merges', 'review_items', 'scenarios']:
        ids = [rule['id'] for rule in config[group]]
        if len(set(ids)) != len(ids) or not all(isinstance(value, str) and value for value in ids):
            raise ValueError(f'{group} identifiers must be nonempty and unique')
    review_ids = {rule['id'] for rule in config['review_items']}
    for scenario in config['scenarios']:
        if not set(scenario['exclude_review_ids']) <= review_ids:
            raise ValueError('Scenario references an unknown review identifier')
    return start, end


def load_rows(path, config):
    company_aliases, sector_aliases = aliases(config['company_aliases']), aliases(config['sector_aliases'])
    result = []
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or len(reader.fieldnames) != len(COLUMNS) or set(reader.fieldnames) != set(COLUMNS):
            raise ValueError('CSV columns must be exactly: ' + ', '.join(COLUMNS))
        for raw in reader:
            if None in raw or any(not isinstance(raw[key], str) or not raw[key].strip() for key in COLUMNS):
                raise ValueError(f'Missing or extra fields on source row {reader.line_num}')
            values = {key: value.strip() for key, value in raw.items()}
            company = company_aliases.get(norm(values['company']), values['company'])
            sector = sector_aliases.get(norm(values['sector']), values['sector'])
            parsed = parse_date(values['date'], config['date_formats'])
            result.append({'row_id': reader.line_num, 'raw': raw,
                           'date': parsed, 'company': company, 'company_key': norm(company),
                           'sector': sector, 'sector_key': norm(sector), 'round': values['round'],
                           'round_key': norm(values['round']), 'amount': number(values['amount']),
                           'currency': values['currency'].upper(), 'source': values['source'],
                           'amount_usd': usd_amount(values['amount'], values['currency'], config['usd_rates'])})
    return result


def event_from_rows(rows, rules=None):
    signatures = {(row['company_key'], row['sector_key'], row['round_key'], row['currency'], row['amount']) for row in rows}
    if len(signatures) != 1:
        raise ValueError('Configured event merge has a field conflict')
    first = min(rows, key=lambda row: (row['date'], row['row_id']))
    event = {key: first[key] for key in ['company_key', 'sector_key', 'round_key', 'amount', 'currency', 'amount_usd']}
    event.update(company=min(row['company'] for row in rows), sector=min(row['sector'] for row in rows),
                 round=min(row['round'] for row in rows), date=min(row['date'] for row in rows),
                 rows=rows, representative_row=first['row_id'], merge_rules=list(rules or []))
    return event


def matches(event, selector):
    if not selector or not set(selector) <= SELECTOR_FIELDS:
        raise ValueError('Invalid event selector fields')
    for key, wanted in selector.items():
        if key == 'date':
            if date.fromisoformat(wanted) not in {row['date'] for row in event['rows']}:
                return False
        elif key == 'amount':
            if event[key] != number(wanted):
                return False
        elif norm(event[key]) != norm(wanted):
            return False
    return True


def deduplicate(rows, config):
    grouped = defaultdict(list)
    signatures = defaultdict(set)
    for row in rows:
        identity = (row['company_key'], row['date'], row['round_key'])
        signatures[identity].add((row['currency'], row['amount']))
        grouped[(*identity, row['currency'], row['amount'])].append(row)
    if any(len(values) > 1 for values in signatures.values()):
        raise ValueError('Amount or currency conflict for the same company, date and round')
    events = [event_from_rows(group) for group in grouped.values()]
    for rule in config['event_merges']:
        selected = set()
        for selector in rule['members']:
            found = [index for index, event in enumerate(events) if matches(event, selector)]
            if len(found) > 1:
                raise ValueError('An event merge selector matched multiple events')
            selected.update(found)
        if len(selected) < 2:
            continue
        picked = [events[index] for index in sorted(selected)]
        if any(event['merge_rules'] for event in picked):
            raise ValueError('Overlapping configured event merges are ambiguous')
        combined = event_from_rows([row for event in picked for row in event['rows']], [rule['id']])
        events = [event for index, event in enumerate(events) if index not in selected] + [combined]
    events.sort(key=lambda event: (event['date'], event['company_key'], event['round_key'], event['currency'], event['amount']))
    for index, event in enumerate(events, 1):
        event['event_id'] = f'event_{index:04d}'
        event['review_ids'] = [rule['id'] for rule in config['review_items'] if matches(event, rule['match'])]
    return events


def aggregate(events):
    grouped = defaultdict(list)
    for event in events:
        grouped[event['sector_key']].append(event)
    totals = [{'sector': min(event['sector'] for event in group),
               'amount_usd': decimal_text(sum((event['amount_usd'] for event in group), Decimal(0))),
               'event_count': len(group)} for group in grouped.values()]
    return sorted(totals, key=lambda item: (-Decimal(item['amount_usd']), item['sector']))


def headline(totals):
    if not totals:
        return None
    sectors = sorted(item['sector'] for item in totals if Decimal(item['amount_usd']) == Decimal(totals[0]['amount_usd']))
    return {'sector': sectors[0] if len(sectors) == 1 else None, 'sectors': sectors,
            'tied': len(sectors) > 1, 'amount_usd': totals[0]['amount_usd']}


def format_usd(value):
    amount = Decimal(value)
    if amount >= 1000000:
        return 'US$' + decimal_text(amount / Decimal(1000000)) + ' million'
    return 'US$' + decimal_text(amount)


def partner_note(metrics, config, rows):
    period = metrics['period']
    last = date.fromisoformat(period['end_exclusive']) - timedelta(days=1)
    text = (f"Filtered the export to {period['start']} through {last.isoformat()} using supplied reporting dates. "
            f"Merged {metrics['counts']['duplicate_reports']} duplicate reports and standardized sector labels. ")
    foreign = sorted({row['currency'] for row in rows} - {'USD'})
    if foreign:
        text += 'Converted currencies using the supplied USD rates: ' + ', '.join(
            f"{currency}={config['usd_rates'][currency]}" for currency in foreign) + '. '
    else:
        text += 'All amounts are already in USD. '
    mixed_dates = sorted({row['raw']['date'] for row in rows if row['raw']['date'].strip() != row['date'].isoformat()})
    if mixed_dates:
        parsed = next(row['date'].isoformat() for row in rows if row['raw']['date'] == mixed_dates[0])
        text += f"Read {mixed_dates[0]} as {parsed}. "
    if metrics['review_items']:
        flag = metrics['review_items'][0]
        text += (f"The total includes {flag['company']}'s recorded {format_usd(flag['amount_usd'])} "
                 f"{flag['round']} round ({Decimal(flag['share_of_sector_pct']):.2f}% of its sector total). "
                 f"Review note: {flag['reason']} ")
        applicable = [scenario for scenario in metrics['scenarios'] if scenario['applicable'] and scenario['headline']]
        if applicable:
            scenario = applicable[0]
            text += f"In the exclusion scenario, {' / '.join(scenario['headline']['sectors'])} leads with {format_usd(scenario['headline']['amount_usd'])}. "
        if len(metrics['review_items']) > 1:
            text += 'Additional flagged records are listed in the report. '
    return text.strip() + '\n'


class FundingTask:
    task_id = 'funding_by_sector'
    version = '1.0.0'

    def execute(self, input_path, config):
        with localcontext() as context:
            context.prec = 80
            return self._execute(input_path, config)

    def _execute(self, input_path, config):
        start, end = validate_config(config)
        rows = load_rows(input_path, config)
        events = deduplicate(rows, config)
        for event in events:
            event['included'] = start <= event['date'] < end
        included = [event for event in events if event['included']]
        totals = aggregate(included)
        grand = sum((event['amount_usd'] for event in included), Decimal(0))
        review_items = []
        for event in included:
            for review_id in event['review_ids']:
                sector_total = next(Decimal(item['amount_usd']) for item in totals if norm(item['sector']) == event['sector_key'])
                rule = next(item for item in config['review_items'] if item['id'] == review_id)
                review_items.append({'review_id': review_id, 'event_id': event['event_id'], 'company': event['company'],
                                     'round': event['round'], 'amount_usd': decimal_text(event['amount_usd']),
                                     'share_of_sector_pct': decimal_text((event['amount_usd'] / sector_total * 100).quantize(Decimal('0.0001'))) if sector_total else '0',
                                     'reason': rule['reason']})
        scenarios, scenario_checks = [], []
        for rule in config['scenarios']:
            excluded = [event for event in included if set(event['review_ids']) & set(rule['exclude_review_ids'])]
            excluded_ids = {event['event_id'] for event in excluded}
            kept = [event for event in included if event['event_id'] not in excluded_ids]
            scenario_totals = aggregate(kept)
            scenario_total = sum((event['amount_usd'] for event in kept), Decimal(0))
            scenarios.append({'id': rule['id'], 'applicable': bool(excluded), 'excluded_event_count': len(excluded),
                              'excluded_event_ids': sorted(excluded_ids), 'headline': headline(scenario_totals),
                              'sector_totals': scenario_totals, 'grand_total_usd': decimal_text(scenario_total)})
            scenario_checks.append(scenario_total == grand - sum((event['amount_usd'] for event in excluded), Decimal(0)))
        counts = {'raw_rows': len(rows), 'duplicate_reports': len(rows) - len(events),
                  'out_of_period_events': len(events) - len(included), 'included_events': len(included)}
        metrics = {'period': config['period'], 'usd_rates': config['usd_rates'], 'counts': counts,
                   'sector_totals': totals, 'grand_total_usd': decimal_text(grand), 'headline': headline(totals),
                   'review_items': review_items, 'scenarios': scenarios}
        decisions, event_table = [], []
        for event in events:
            reason = ('Configured merge: ' + ', '.join(event['merge_rules'])) if event['merge_rules'] else 'Same normalized company, date, round, amount and currency'
            for row in sorted(event['rows'], key=lambda item: item['row_id']):
                duplicate = row['row_id'] != event['representative_row']
                status = 'duplicate_report' if duplicate else ('included' if event['included'] else 'out_of_period')
                decisions.append({'source_row': row['row_id'], 'company': row['raw']['company'], 'event_id': event['event_id'],
                                  'decision': status, 'reason': reason if duplicate else ('Event reporting date is within period' if event['included'] else 'Event reporting date is outside period')})
            event_table.append({'event_id': event['event_id'], 'date': event['date'].isoformat(), 'company': event['company'],
                                'sector': event['sector'], 'round': event['round'], 'amount': decimal_text(event['amount']),
                                'currency': event['currency'], 'usd_rate': config['usd_rates'][event['currency']],
                                'amount_usd': decimal_text(event['amount_usd']), 'included': event['included'],
                                'source_rows': json.dumps(sorted(row['row_id'] for row in event['rows'])),
                                'sources': json.dumps(sorted({row['source'] for row in event['rows']})),
                                'merge_rules': json.dumps(event['merge_rules']), 'review_ids': json.dumps(event['review_ids'])})
        normalized = [{'source_row': row['row_id'], **{'raw_' + key: value for key, value in row['raw'].items()},
                       'date': row['date'].isoformat(), 'company': row['company'], 'sector': row['sector'],
                       'round': row['round'], 'amount': decimal_text(row['amount']), 'currency': row['currency'],
                       'amount_usd': decimal_text(row['amount_usd'])} for row in rows]
        note = partner_note(metrics, config, rows)
        winner = metrics['headline']
        answer = (' / '.join(winner['sectors']) + ': ' + format_usd(winner['amount_usd']) +
                  (' (tie)' if winner['tied'] else '') + '\n') if winner else 'No funding events in the configured period.\n'
        checks = {'row_partition': counts['raw_rows'] == sum(counts[key] for key in ['duplicate_reports', 'out_of_period_events', 'included_events']),
                  'every_source_row_assigned_once': sorted(item['source_row'] for item in decisions) == sorted(row['row_id'] for row in rows),
                  'event_ids_unique': len({event['event_id'] for event in events}) == len(events),
                  'sector_amounts_reconcile': sum((Decimal(item['amount_usd']) for item in totals), Decimal(0)) == grand,
                  'sector_counts_reconcile': sum(item['event_count'] for item in totals) == len(included),
                  'scenario_amounts_reconcile': all(scenario_checks), 'partner_note_within_150_words': len(note.split()) <= 150}
        return TaskResult(tables={'normalized_rows': normalized, 'funding_events': event_table,
                                  'decisions': sorted(decisions, key=lambda item: item['source_row']), 'sector_totals': totals},
                          metrics=metrics, checks=checks, texts={'answer.txt': answer, 'partner_note.txt': note},
                          json_artifacts={'scenarios.json': scenarios},
                          table_columns={'sector_totals': ['sector', 'amount_usd', 'event_count'],
                                         'funding_events': ['event_id', 'date', 'company', 'sector', 'round', 'amount', 'currency',
                                                            'usd_rate', 'amount_usd', 'included', 'source_rows', 'sources', 'merge_rules', 'review_ids']})
