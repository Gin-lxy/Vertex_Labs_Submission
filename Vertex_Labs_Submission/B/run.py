"""Run the funding-analysis task using a saved configuration."""

import argparse
import json
from pathlib import Path

from funding import FundingTask
from harness import run_task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('config.json'))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = run_task(FundingTask(), args.input, args.config, args.output)
    print(json.dumps({'headline': result.metrics['headline'], 'counts': result.metrics['counts'],
                      'checks': result.checks}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
