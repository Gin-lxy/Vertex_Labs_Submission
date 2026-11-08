# Section C

The review submission is [review.md](review.md). Business assumptions are recorded in [assumptions.md](assumptions.md).

`fix.py` and `test_fix.py` are unchanged copies of the supplied PR. The proposed implementation is `revision/fix_revised.py`. Regression tests and their implementation-selection fixture are in `revision/`.

From this directory:

```powershell
python -B -m pytest -p no:cacheprovider revision/test_revised.py -q
python -B -m pytest -p no:cacheprovider revision/test_revised.py --implementation=fix -q
```

The first command validates the proposal. The second demonstrates the original PR's behaviour with the same cases and is expected to report failures. All reference times are fixed; the default-clock test substitutes a fixed clock in memory.

The AI-use log is [revision/ai_log.txt](revision/ai_log.txt).
