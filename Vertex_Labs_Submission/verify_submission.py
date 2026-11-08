"""Verify the saved submission offline and rerun its deterministic work."""

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent


def execute(arguments, cwd, expected_exit=0):
    result = subprocess.run([sys.executable, '-B', *arguments], cwd=cwd,
                            capture_output=True, text=True, timeout=120)
    if result.returncode != expected_exit:
        raise RuntimeError(f'Command failed in {cwd.name}: {result.stdout}\n{result.stderr}')
    return result.stdout


def word_count(relative):
    return len((ROOT / relative).read_text(encoding='utf-8').split())


def inspect_files():
    patterns = {
        'credential': re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
        'bearer_value': re.compile(r'\bBearer[ \t]+[A-Za-z0-9._~+/-]{20,}', re.I),
        'private_key': re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
        'personal_path': re.compile(r'/(?:Users|home)/[^\s<>"\']+'),
        'windows_personal_path': re.compile(r'\b[A-Za-z]:\\(?:Users|Documents)\\'),
        'provider_connection': re.compile(r'https?://api\.deepseek\.com'),
    }
    forbidden = {'.bin', '.pkl', '.pickle', '.pyc', '.pem', '.key', '.jsonl', '.zip', '.tar', '.gz'}
    findings = []
    files = []
    for path in sorted(ROOT.rglob('*')):
        if path.is_symlink():
            findings.append({'file': path.relative_to(ROOT).as_posix(), 'category': 'symbolic_link'})
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        files.append(relative)
        if path.suffix.lower() in forbidden or path.name.startswith('.env'):
            findings.append({'file': relative, 'category': 'unexpected_runtime_file'})
            continue
        content = path.read_text(encoding='utf-8')
        for category, pattern in patterns.items():
            if pattern.search(content):
                findings.append({'file': relative, 'category': category})
    if findings:
        raise ValueError('Submission inspection failed: ' + json.dumps(findings))
    return files


def main():
    limits = {'A/failure_notes.txt': 150, 'A/ai_log.txt': 80,
              'B/partner_note.txt': 150, 'B/ai_log.txt': 80,
              'C/review.md': 200, 'C/revision/ai_log.txt': 80}
    counts = {path: word_count(path) for path in limits}
    if any(counts[path] > limit for path, limit in limits.items()):
        raise ValueError('A submission word limit was exceeded')
    a_result = json.loads(execute(['A/validate_outputs.py'], ROOT))
    test_output = execute(['-m', 'pytest', '-p', 'no:cacheprovider', '-q'], ROOT)
    match = re.search(r'(\d+) passed', test_output)
    if match is None:
        raise ValueError('Missing passing-test summary')

    with tempfile.TemporaryDirectory(prefix='vertex-submission-') as temporary:
        temporary_path = Path(temporary).resolve()
        if temporary_path.parent != Path(tempfile.gettempdir()).resolve():
            raise ValueError('Unexpected temporary verification directory')
        output = temporary_path / 'results'
        execute(['run.py', '--input', 'data/rounds.csv', '--config', 'config.json',
                 '--output', str(output)], ROOT / 'B')
        compared = ['input.csv', 'config.json', 'normalized_rows.csv', 'funding_events.csv',
                    'decisions.csv', 'sector_totals.csv', 'report.json', 'scenarios.json',
                    'checks.json', 'answer.txt', 'partner_note.txt']
        for filename in compared:
            if (output / filename).read_bytes() != (ROOT / 'B' / 'results' / filename).read_bytes():
                raise ValueError(f'B reproduction differs: {filename}')
        for filename in ['answer.txt', 'partner_note.txt']:
            if (ROOT / 'B' / filename).read_bytes() != (output / filename).read_bytes():
                raise ValueError(f'B headline material differs: {filename}')
        run_record = json.loads((output / 'run.json').read_text(encoding='utf-8'))
        if run_record['input_path'] != 'input.csv' or run_record['config_path'] != 'config.json':
            raise ValueError('B run metadata must use snapshot-relative paths')

    original_output = execute(['-m', 'pytest', '-p', 'no:cacheprovider', 'revision/test_revised.py',
                               '--implementation=fix', '-q', '--tb=no'], ROOT / 'C', expected_exit=1)
    failed = re.search(r'(\d+) failed', original_output)
    passed = re.search(r'(\d+) passed', original_output)
    if failed is None or passed is None or (int(failed.group(1)), int(passed.group(1))) != (32, 9):
        raise ValueError('Original PR comparison does not match the recorded result')
    files = inspect_files()
    report = {'status': 'passed', 'offline': True, 'tests_passed': int(match.group(1)),
              'A_saved_outputs': a_result, 'B_reproduction': 'matched all eleven business artifacts',
              'C_revised_tests_passed': 41, 'C_original_comparison': {'passed': 9, 'failed': 32},
              'word_counts': counts, 'privacy_findings': [], 'inspected_file_count': len(files)}
    (ROOT / 'verification_report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
