import copy
import csv
from datetime import date
from decimal import Decimal
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data' / 'rounds.csv'


@pytest.fixture
def config():
    return json.loads((ROOT / 'config.json').read_text())


def write_rows(path, rows):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['date', 'company', 'sector', 'round', 'amount', 'currency', 'source'])
        writer.writeheader()
        writer.writerows(rows)
    return path


def row(**changes):
    return dict({'date': '2026-08-01', 'company': 'Example', 'sector': 'Fintech',
                 'round': 'Seed', 'amount': '1000000', 'currency': 'USD', 'source': 'Report'}, **changes)


def analyze(path, config):
    from funding import FundingTask
    return FundingTask().execute(path, config)


@pytest.mark.parametrize('text,want', [('2026-09-18', date(2026, 9, 18)), ('18/09/2026', date(2026, 9, 18))])
def test_explicit_date_formats(text, want):
    from funding import parse_date
    assert parse_date(text, ['%Y-%m-%d', '%d/%m/%Y']) == want


@pytest.mark.parametrize('text', ['2026-02-30', '09/31/2026', '', 'next Tuesday'])
def test_invalid_dates_are_not_guessed(text):
    from funding import parse_date
    with pytest.raises(ValueError):
        parse_date(text, ['%Y-%m-%d', '%d/%m/%Y'])


@pytest.mark.parametrize('amount,currency,want', [('25000000', 'SGD', '19250000'), ('400000000', 'INR', '4800000'), ('0.1', 'USD', '0.1')])
def test_given_rates_use_exact_decimal_arithmetic(amount, currency, want):
    from funding import usd_amount
    assert usd_amount(amount, currency, {'USD': '1', 'SGD': '0.77', 'INR': '0.012'}) == Decimal(want)


@pytest.mark.parametrize('amount,currency', [('NaN', 'USD'), ('Infinity', 'USD'), ('-1', 'USD'), ('', 'USD'), ('1M', 'USD'), ('1', 'EUR')])
def test_invalid_amount_or_unknown_currency_is_rejected(amount, currency):
    from funding import usd_amount
    with pytest.raises(ValueError):
        usd_amount(amount, currency, {'USD': '1'})


def test_actual_csv_totals_and_count_reconciliation(config):
    result = analyze(SOURCE, config)
    totals = {item['sector']: (item['amount_usd'], item['event_count']) for item in result.metrics['sector_totals']}
    assert totals == {'Fintech': ('277670000', 4), 'Logistics': ('44550000', 5),
                      'Healthtech': ('37390000', 3), 'Agritech': ('25800000', 3), 'Climate': ('13680000', 3)}
    assert result.metrics['counts'] == {'raw_rows': 22, 'duplicate_reports': 2, 'out_of_period_events': 2, 'included_events': 18}
    assert result.metrics['grand_total_usd'] == '399090000'
    assert result.metrics['headline']['sector'] == 'Fintech'
    assert all(result.checks.values())


def test_flagged_amount_is_retained_and_only_excluded_in_scenario(config):
    result = analyze(SOURCE, config)
    assert result.metrics['headline']['amount_usd'] == '277670000'
    scenario = result.metrics['scenarios'][0]
    assert scenario['applicable'] is True
    assert scenario['excluded_event_count'] == 1
    assert scenario['headline']['sector'] == 'Logistics'
    assert scenario['headline']['amount_usd'] == '44550000'
    assert result.metrics['review_items'][0]['amount_usd'] == '250000000'


def test_boundary_dates_and_different_quarter(tmp_path, config):
    rows = [row(date=value, company=str(index)) for index, value in enumerate(['2026-06-30', '2026-07-01', '2026-09-30', '2026-10-01'])]
    source = write_rows(tmp_path / 'dates.csv', rows)
    assert analyze(source, config).metrics['headline']['amount_usd'] == '2000000'
    config['period'] = {'start': '2026-10-01', 'end_exclusive': '2027-01-01'}
    assert analyze(source, config).metrics['headline']['amount_usd'] == '1000000'


def test_case_aliases_and_extra_report_do_not_add_money(tmp_path, config):
    source = write_rows(tmp_path / 'duplicates.csv', [row(company='PayLoom'), row(company='PayLoom', sector='FinTech', source='Second')])
    result = analyze(source, config)
    assert result.metrics['headline']['amount_usd'] == '1000000'
    assert result.metrics['counts']['duplicate_reports'] == 1
    assert json.loads(result.tables['funding_events'][0]['sources']) == ['Report', 'Second']


def test_same_company_different_rounds_are_preserved(tmp_path, config):
    source = write_rows(tmp_path / 'rounds.csv', [row(), row(date='2026-09-01', round='Series A', amount='3000000')])
    assert analyze(source, config).metrics['headline']['amount_usd'] == '4000000'


def test_conflicting_same_date_round_is_not_silently_summed(tmp_path, config):
    source = write_rows(tmp_path / 'conflict.csv', [row(), row(amount='2000000', source='Second')])
    with pytest.raises(ValueError, match='conflict'):
        analyze(source, config)


def test_input_order_does_not_change_metrics(tmp_path, config):
    with SOURCE.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    reverse = write_rows(tmp_path / 'reverse.csv', list(reversed(rows)))
    assert analyze(reverse, config).metrics == analyze(SOURCE, config).metrics


def test_changing_rate_affects_only_matching_currency(tmp_path, config):
    source = write_rows(tmp_path / 'fx.csv', [row(company='SG', amount='100', currency='SGD'), row(company='US', amount='100')])
    assert analyze(source, config).metrics['headline']['amount_usd'] == '177'
    config['usd_rates']['SGD'] = '0.5'
    assert analyze(source, config).metrics['headline']['amount_usd'] == '150'


def test_empty_quarter_has_no_invented_winner(tmp_path, config):
    source = write_rows(tmp_path / 'empty.csv', [row(date='2026-06-01')])
    result = analyze(source, config)
    assert result.metrics['headline'] is None
    assert result.metrics['sector_totals'] == []


def test_tied_sectors_are_explicit(tmp_path, config):
    source = write_rows(tmp_path / 'tie.csv', [row(company='A'), row(company='B', sector='Logistics')])
    result = analyze(source, config)
    assert result.metrics['headline']['tied'] is True
    assert result.metrics['headline']['sectors'] == ['Fintech', 'Logistics']


def test_missing_required_field_fails(tmp_path, config):
    source = tmp_path / 'bad.csv'
    source.write_text('date,company\n2026-08-01,Example\n')
    with pytest.raises(ValueError, match='columns'):
        analyze(source, config)


def test_partner_note_describes_the_date_actually_parsed(tmp_path, config):
    config['date_formats'] = ['%m/%d/%Y']
    source = write_rows(tmp_path / 'month_first.csv', [row(date='08/09/2026')])
    note = analyze(source, config).texts['partner_note.txt']
    assert '08/09/2026 as 2026-08-09' in note


def test_small_amount_is_not_displayed_as_zero_millions(tmp_path, config):
    source = write_rows(tmp_path / 'small.csv', [row(amount='1.23')])
    result = analyze(source, config)
    assert result.texts['answer.txt'] == 'Fintech: US$1.23\n'


def test_note_uses_the_configured_review_reason(tmp_path, config):
    config['review_items'] = [{'id': 'date_review', 'match': {'company': 'Example'},
                               'reason': 'Reporting date needs confirmation.'}]
    config['scenarios'] = [{'id': 'without_review', 'exclude_review_ids': ['date_review']}]
    source = write_rows(tmp_path / 'date_review.csv', [row()])
    note = analyze(source, config).texts['partner_note.txt']
    assert 'Reporting date needs confirmation.' in note
    assert 'unusually large' not in note


def test_note_does_not_claim_foreign_currency_conversion_when_all_usd(tmp_path, config):
    source = write_rows(tmp_path / 'usd_only.csv', [row()])
    note = analyze(source, config).texts['partner_note.txt']
    assert 'All amounts are already in USD.' in note
