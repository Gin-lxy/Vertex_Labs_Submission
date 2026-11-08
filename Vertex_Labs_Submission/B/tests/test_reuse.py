import csv
import json
from pathlib import Path

import pytest

from harness import TaskResult


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data' / 'rounds.csv'
CONFIG_PATH = ROOT / 'config.json'
FIELDS = ['date', 'company', 'sector', 'round', 'amount', 'currency', 'source']


def read_fixture():
    with SOURCE.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def write_rows(path, rows, fields=FIELDS):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))


def analyze(path, config=None):
    from funding import FundingTask
    return FundingTask().execute(path, config if config is not None else load_config())


def totals_by_sector(result):
    return {item['sector']: (item['amount_usd'], item['event_count'])
            for item in result.metrics['sector_totals']}


def test_run_task_accepts_a_generic_adapter_and_writes_table_and_text(tmp_path):
    from harness import run_task

    class ToyTask:
        task_id = 'toy_row_counter'
        version = '0.2.0'

        def execute(self, input_path, config):
            with Path(input_path).open(newline='', encoding='utf-8') as stream:
                count = sum(1 for _ in csv.DictReader(stream))
            return TaskResult(
                tables={'computed': [{'label': config['label'], 'value': str(count)}]},
                metrics={'row_count': count, 'label': config['label']},
                checks={'count_is_positive': count > 0},
                texts={'summary.txt': f"{config['label']}: {count} rows\n"},
                table_columns={'computed': ['label', 'value']},
            )

    config_path = tmp_path / 'toy_config.json'
    config_path.write_text('{"label":"toy"}', encoding='utf-8')
    output = tmp_path / 'toy_run'
    result = run_task(ToyTask(), SOURCE, config_path, output)

    assert result.metrics == {'row_count': 22, 'label': 'toy'}
    assert (output / 'computed.csv').read_text(encoding='utf-8').splitlines() == [
        'label,value', 'toy,22'
    ]
    assert (output / 'summary.txt').read_text(encoding='utf-8') == 'toy: 22 rows\n'
    assert json.loads((output / 'report.json').read_text(encoding='utf-8')) == result.metrics
    run = json.loads((output / 'run.json').read_text(encoding='utf-8'))
    assert (run['task_id'], run['adapter_version'], run['status']) == (
        'toy_row_counter', '0.2.0', 'complete'
    )


def test_duplicate_report_does_not_increase_funding_total(tmp_path):
    rows = read_fixture()
    duplicate = next(row.copy() for row in rows if row['company'] == 'PayLoom')
    duplicate['source'] = 'Additional publication'
    source = write_rows(tmp_path / 'duplicate.csv', rows + [duplicate])

    result = analyze(source)

    assert result.metrics['grand_total_usd'] == '399090000'
    assert result.metrics['counts'] == {
        'raw_rows': 23, 'duplicate_reports': 3,
        'out_of_period_events': 2, 'included_events': 18,
    }
    assert totals_by_sector(result)['Fintech'] == ('277670000', 4)


def test_moving_one_real_event_out_of_quarter_only_removes_its_amount(tmp_path):
    rows = read_fixture()
    target = next(row for row in rows if row['company'] == 'ClearCap')
    target['date'] = '2026-10-01'
    source = write_rows(tmp_path / 'clearcap_outside.csv', rows)

    result = analyze(source)

    assert result.metrics['grand_total_usd'] == '397890000'
    assert result.metrics['counts'] == {
        'raw_rows': 22, 'duplicate_reports': 2,
        'out_of_period_events': 3, 'included_events': 17,
    }
    assert totals_by_sector(result) == {
        'Logistics': ('44550000', 5),
        'Healthtech': ('37390000', 3),
        'Agritech': ('25800000', 3),
        'Fintech': ('276470000', 3),
        'Climate': ('13680000', 3),
    }


def test_changing_source_names_does_not_change_amounts(tmp_path):
    rows = read_fixture()
    for row in rows:
        row['source'] = 'Renamed publication'
    source = write_rows(tmp_path / 'renamed_sources.csv', rows)

    result = analyze(source)

    assert result.metrics['grand_total_usd'] == '399090000'
    assert totals_by_sector(result) == {
        'Fintech': ('277670000', 4),
        'Logistics': ('44550000', 5),
        'Healthtech': ('37390000', 3),
        'Agritech': ('25800000', 3),
        'Climate': ('13680000', 3),
    }
    assert all(item['sources'] == '["Renamed publication"]'
               for item in result.tables['funding_events'])


def test_new_independent_round_adds_its_amount_to_sector_and_total(tmp_path):
    rows = read_fixture()
    rows.append({
        'date': '2026-09-27', 'company': 'NewClimateCo', 'sector': 'Climate',
        'round': 'Series A', 'amount': '1234567', 'currency': 'USD',
        'source': 'New source',
    })
    source = write_rows(tmp_path / 'new_round.csv', rows)

    result = analyze(source)

    assert result.metrics['grand_total_usd'] == '400324567'
    assert totals_by_sector(result)['Climate'] == ('14914567', 4)
    assert result.metrics['counts']['included_events'] == 19


@pytest.mark.parametrize('invalid_row', [
    {'amount': '', 'currency': 'USD'},
    {'amount': '1000000', 'currency': 'EUR'},
])
def test_empty_amount_and_unsupported_currency_are_rejected(tmp_path, invalid_row):
    rows = read_fixture()
    bad = {
        'date': '2026-09-27', 'company': 'InvalidRecord', 'sector': 'Climate',
        'round': 'Seed', 'amount': invalid_row['amount'],
        'currency': invalid_row['currency'], 'source': 'Invalid source',
    }
    source = write_rows(tmp_path / 'invalid_value.csv', rows + [bad])

    with pytest.raises(ValueError):
        analyze(source)


def test_missing_amount_column_is_rejected(tmp_path):
    source = tmp_path / 'missing_amount_column.csv'
    source.write_text(
        'date,company,sector,round,currency,source\n'
        '2026-08-01,MissingAmount,Climate,Seed,USD,Report\n',
        encoding='utf-8',
    )

    with pytest.raises(ValueError, match='columns'):
        analyze(source)


def test_cross_boundary_merge_uses_earliest_date_before_quarter_filtering(tmp_path):
    base = next(row.copy() for row in read_fixture() if row['company'] == 'MediNest')
    earlier = base.copy()
    earlier['date'] = '2026-06-30'
    later = base.copy()
    later['date'] = '2026-07-09'
    source = write_rows(tmp_path / 'cross_boundary.csv', [earlier, later])
    config = load_config()
    config['event_merges'] = [{
        'id': 'medinest_cross_boundary',
        'members': [
            {'company': 'MediNest', 'date': '2026-06-30', 'round': 'Seed',
             'amount': '2000000', 'currency': 'USD'},
            {'company': 'MediNest', 'date': '2026-07-09', 'round': 'Seed',
             'amount': '2000000', 'currency': 'USD'},
        ],
        'reason': 'The two reports describe one round.',
    }]

    result = analyze(source, config)

    assert result.metrics['counts'] == {
        'raw_rows': 2, 'duplicate_reports': 1,
        'out_of_period_events': 1, 'included_events': 0,
    }
    assert result.metrics['grand_total_usd'] == '0'
    assert result.metrics['headline'] is None
    event = result.tables['funding_events'][0]
    assert event['date'] == '2026-06-30'
    assert event['included'] is False
    assert event['source_rows'] == '[2, 3]'


def test_scenario_is_not_applicable_when_its_flagged_event_is_absent(tmp_path):
    clearcap = next(row.copy() for row in read_fixture() if row['company'] == 'ClearCap')
    source = write_rows(tmp_path / 'no_flagged_event.csv', [clearcap])

    result = analyze(source)

    scenario = result.metrics['scenarios'][0]
    assert scenario['id'] == 'without_ledgerleaf'
    assert scenario['applicable'] is False
    assert scenario['excluded_event_count'] == 0
    assert scenario['grand_total_usd'] == '1200000'


def test_run_task_rejects_output_path_traversal_without_creating_outside_file(tmp_path):
    from harness import run_task

    class TraversalTask:
        task_id = 'traversal_task'
        version = '1.0'

        def execute(self, input_path, config):
            return TaskResult(
                tables={'../outside': [{'value': 'blocked'}]},
                metrics={'value': 'blocked'},
                checks={'result_valid': True},
            )

    output = tmp_path / 'run'
    outside_file = tmp_path / 'outside.csv'
    with pytest.raises(ValueError, match='single file names'):
        run_task(TraversalTask(), SOURCE, CONFIG_PATH, output)

    assert not outside_file.exists()
    assert json.loads((output / 'run.json').read_text(encoding='utf-8'))['status'] == 'failed'


def test_read_config_rejects_duplicate_json_keys(tmp_path):
    from harness import read_config

    config = tmp_path / 'duplicate_key.json'
    config.write_text('{"task_id":"first","task_id":"second"}', encoding='utf-8')

    with pytest.raises(ValueError, match='Duplicate configuration key'):
        read_config(config)
