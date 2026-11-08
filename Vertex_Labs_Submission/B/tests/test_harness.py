import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data' / 'rounds.csv'


def test_complete_run_writes_reusable_artifacts_and_preserves_inputs(tmp_path):
    from harness import run_task
    from funding import FundingTask
    original = SOURCE.read_bytes()
    result = run_task(FundingTask(), SOURCE, ROOT / 'config.json', tmp_path / 'result')
    output = tmp_path / 'result'
    assert result.metrics['headline']['amount_usd'] == '277670000'
    assert SOURCE.read_bytes() == original
    assert (output / 'input.csv').read_bytes() == original
    assert json.loads((output / 'run.json').read_text())['status'] == 'complete'
    assert (output / 'sector_totals.csv').exists()
    scenarios = json.loads((output / 'scenarios.json').read_text())
    assert scenarios[0]['headline']['amount_usd'] == '44550000'
    assert '277.67' in (output / 'answer.txt').read_text()
    assert len((output / 'partner_note.txt').read_text().split()) <= 150


def test_existing_run_is_not_overwritten(tmp_path):
    from harness import run_task
    from funding import FundingTask
    output = tmp_path / 'existing'
    output.mkdir()
    marker = output / 'keep.txt'
    marker.write_text('unchanged')
    with pytest.raises(FileExistsError):
        run_task(FundingTask(), SOURCE, ROOT / 'config.json', output)
    assert marker.read_text() == 'unchanged'


def test_invalid_data_records_failure_without_a_headline(tmp_path):
    from harness import run_task
    from funding import FundingTask
    source = tmp_path / 'invalid.csv'
    source.write_text('bad\nvalue\n')
    output = tmp_path / 'failed'
    with pytest.raises(ValueError):
        run_task(FundingTask(), source, ROOT / 'config.json', output)
    assert json.loads((output / 'run.json').read_text())['status'] == 'failed'
    assert not (output / 'answer.txt').exists()


def test_run_metadata_uses_snapshot_relative_paths(tmp_path):
    from harness import run_task
    from funding import FundingTask
    output = tmp_path / 'portable'
    run_task(FundingTask(), SOURCE, ROOT / 'config.json', output)
    record_text = (output / 'run.json').read_text()
    record = json.loads(record_text)
    assert record['input_path'] == 'input.csv'
    assert record['config_path'] == 'config.json'
    assert str(SOURCE.resolve()) not in record_text
    assert str(tmp_path.resolve()) not in record_text


def test_failed_run_metadata_does_not_serialize_private_diagnostics(tmp_path):
    from harness import run_task

    class FailingTask:
        task_id = 'test_failure'
        version = '1'

        def execute(self, input_path, config):
            raise RuntimeError('private diagnostic value')

    output = tmp_path / 'private_failure'
    with pytest.raises(RuntimeError):
        run_task(FailingTask(), SOURCE, ROOT / 'config.json', output)
    record_text = (output / 'run.json').read_text()
    record = json.loads(record_text)
    assert record['status'] == 'failed'
    assert record['error_type'] == 'RuntimeError'
    assert 'private diagnostic value' not in record_text
