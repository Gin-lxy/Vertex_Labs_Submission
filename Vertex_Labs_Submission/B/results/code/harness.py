"""Reusable runner for deterministic tabular analysis tasks."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import csv
import inspect
import json
from pathlib import Path
import platform
import shutil
import time


@dataclass
class TaskResult:
    tables: dict
    metrics: dict
    checks: dict
    texts: dict = field(default_factory=dict)
    table_columns: dict = field(default_factory=dict)
    json_artifacts: dict = field(default_factory=dict)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def artifact_path(directory, name):
    if not isinstance(name, str) or not name or Path(name).name != name or name in {'.', '..'} or '\\' in name:
        raise ValueError('Artifact names must be single file names')
    path = directory / name
    if path.exists():
        raise FileExistsError(f'Artifact already exists: {name}')
    return path


def read_config(path):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate configuration key: {key}')
            result[key] = value
        return result
    config = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
    if not isinstance(config, dict):
        raise ValueError('Configuration must be an object')
    return config


def run_task(adapter, input_path, config_path, output_dir):
    input_path, config_path, output_dir = map(lambda path: Path(path).resolve(),
                                              [input_path, config_path, output_dir])
    if not input_path.is_file() or not config_path.is_file():
        raise FileNotFoundError('Input and configuration must be existing files')
    output_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    record = {'task_id': adapter.task_id, 'adapter_version': adapter.version,
              'python_version': platform.python_version(), 'status': 'running',
              'started_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
              'time_zone': 'Asia/Shanghai',
              'input_path': 'input.csv', 'config_path': 'config.json'}
    try:
        write_json(output_dir / 'run.json', record)
        shutil.copyfile(input_path, output_dir / 'input.csv')
        shutil.copyfile(config_path, output_dir / 'config.json')
        code_dir = output_dir / 'code'
        code_dir.mkdir()
        source_paths = [Path(__file__).resolve(), Path(inspect.getfile(type(adapter))).resolve()]
        for source in source_paths:
            target = code_dir / source.name
            if target.exists():
                raise ValueError('Adapter source filename conflicts with runner filename')
            shutil.copyfile(source, target)
        result = adapter.execute(output_dir / 'input.csv', read_config(output_dir / 'config.json'))
        if not isinstance(result, TaskResult):
            raise TypeError('Task adapter must return TaskResult')
        write_json(output_dir / 'checks.json', result.checks)
        if not result.checks or not all(value is True for value in result.checks.values()):
            raise ValueError('One or more result checks failed')
        for name, rows in result.tables.items():
            target = artifact_path(output_dir, name + '.csv')
            columns = result.table_columns.get(name) or (list(rows[0]) if rows else [])
            with target.open('x', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
        for name, text in result.texts.items():
            artifact_path(output_dir, name).write_text(text, encoding='utf-8')
        for name, value in result.json_artifacts.items():
            write_json(artifact_path(output_dir, name), value)
        write_json(artifact_path(output_dir, 'report.json'), result.metrics)
        record['status'] = 'complete'
        record['elapsed_seconds'] = round(time.monotonic() - started, 4)
        write_json(output_dir / 'run.json', record)
        return result
    except Exception as exc:
        for name in ['answer.txt', 'partner_note.txt']:
            target = output_dir / name
            if target.is_file():
                target.unlink()
        record.update(status='failed', error_type=type(exc).__name__,
                      elapsed_seconds=round(time.monotonic() - started, 4))
        write_json(output_dir / 'run.json', record)
        raise
