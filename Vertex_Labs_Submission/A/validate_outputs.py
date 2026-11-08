"""Check the twelve saved responses without invoking a model."""

from collections import Counter
import json
import math
from pathlib import Path

from scoring import evaluate_output


ROOT = Path(__file__).resolve().parent


def validate_outputs():
    cases = json.loads((ROOT / 'evaluation_cases.json').read_text(encoding='utf-8'))
    inputs = json.loads((ROOT / 'inputs.json').read_text(encoding='utf-8'))
    manifest = json.loads((ROOT / 'raw_manifest.json').read_text(encoding='utf-8'))
    expected = json.loads((ROOT / 'summary.json').read_text(encoding='utf-8'))
    by_id = {case['id']: case for case in cases}
    if len(cases) != 4 or len(by_id) != 4 or len(manifest) != 12:
        raise ValueError('Expected four distinct inputs and twelve saved responses')
    if {item['id']: item['article'] for item in inputs} != {key: value['article'] for key, value in by_id.items()}:
        raise ValueError('Published inputs differ from the fixed evaluation cases')
    seen = Counter()
    results = []
    paths = set()
    for record in manifest:
        case_id = record['case_id']
        if case_id not in by_id or record['repeat'] not in {1, 2, 3}:
            raise ValueError('Unexpected case or repeat in response manifest')
        seen[(case_id, record['repeat'])] += 1
        path = Path(record['raw_file'])
        if len(path.parts) != 2 or path.parts[0] != 'raw_outputs' or path.suffix != '.txt':
            raise ValueError('Response paths must name files within raw_outputs')
        paths.add(path.as_posix())
        raw = (ROOT / path).read_text(encoding='utf-8')
        results.append(evaluate_output(raw, by_id[case_id]))
    wanted = {(case_id, repeat) for case_id in by_id for repeat in [1, 2, 3]}
    actual_paths = {path.relative_to(ROOT).as_posix() for path in (ROOT / 'raw_outputs').iterdir() if path.is_file()}
    if set(seen) != wanted or any(count != 1 for count in seen.values()) or paths != actual_paths:
        raise ValueError('Each input must have exactly three distinct raw response files')
    measured = {'outputs': len(results), 'schema_passes': sum(result['schema_valid'] for result in results),
                'exact_passes': sum(result['exact'] for result in results),
                'mean_score': sum(result['score'] for result in results) / len(results)}
    for key in ['outputs', 'schema_passes', 'exact_passes']:
        if measured[key] != expected[key]:
            raise ValueError(f'Saved summary does not match responses: {key}')
    if not math.isclose(measured['mean_score'], expected['mean_score'], rel_tol=0, abs_tol=1e-12):
        raise ValueError('Saved mean score does not match responses')
    if measured['schema_passes'] != 12:
        raise ValueError('At least one response violates the mechanical output rules')
    return measured


if __name__ == '__main__':
    print(json.dumps(validate_outputs(), indent=2))
