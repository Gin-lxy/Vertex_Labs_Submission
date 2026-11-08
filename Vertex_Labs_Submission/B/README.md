# Section B

Slide answer: **Fintech: US$277.67 million.** The amount includes LedgerLeaf's recorded US$250 million Seed round. It contributes 90.03% of the sector total and needs confirmation before external presentation. Excluding that single record changes the leading sector to Logistics, with US$44.55 million.

`answer.txt`, `partner_note.txt` and `ai_log.txt` are the short submission documents. Detailed calculations and decisions are in `results/`. The original CSV is in `data/rounds.csv`.

The generic runner is `harness.py`; the task adapter is `funding.py`; the CLI is `run.py`. All runtime dependencies are in the Python standard library. The configuration fixes dates, supplied currency rates, aliases, cross-date duplicate handling and the LedgerLeaf exclusion scenario. Run metadata uses paths relative to its saved snapshots.

Rules: use 2026-07-01 through 2026-09-30 as the reporting period; parse both explicit date formats; merge the two PayLoom reports and the two Kirana Fleet reports; normalize Fintech labels; use SGD=0.77 USD and INR=0.012 USD. Keep the supplied LedgerLeaf amount in the primary result. This yields 18 unique Q3 events and US$399.09 million across all sectors.

From this directory, choose a new output directory:

```powershell
python -B run.py --input data/rounds.csv --config config.json --output results_copy
```

Input/configuration snapshots, exact decimal amounts, source-row decisions, all sources, reconciliation checks and scenario results are saved for each run. A separate task adapter in the tests demonstrates reuse of the runner. The top-level verification command reruns this analysis in a temporary directory and compares all business artifacts.
