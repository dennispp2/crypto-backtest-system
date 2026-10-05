# V2.0 Fixed DCA + Corrected Cycle Hedge

## Reproduce

From the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe run_backtest_v2.py
```

The V2 runner reads the frozen V1 processed market/signal input, verifies its SHA-256 hash and point-in-time signal availability, reinitializes the portfolio at 2020-01-01 UTC, and writes only under `v2/`. It does not overwrite V1 results.

## Models

- `A - Fixed DCA Champion`: direct call to the existing V1 `run_backtest` with Test-2 initial conditions and fixed US$2 per calendar 4H interval.
- `E20`: exact Model-A normal-DCA replay plus corrected cycle hedge, 20% tactical-sell floor.
- `E30`, `E40`: frozen floor sensitivities; no other rule changes.

## Required outputs

- `results/summary_v2.csv`
- `results/daily_portfolio_v2.csv`
- `results/trade_log_v2.csv`
- `results/signal_log_v2.csv`
- `results/cycle_audit.csv`
- `results/exposure_audit.csv`
- `results/fixed_dca_integrity_audit.csv`
- `results/segment_analysis_v2.csv`
- `artifacts/no_lookahead_audit.json`
- `artifacts/run_manifest_v2.json`
- `report/FINAL_REPORT_V2.md`
- `figures/*.png` and `figures/*.pdf`

## Important floor definition

The hard floor prevents a tactical sell from taking combined crypto exposure below the floor. It is not an always-on daily rebalance guarantee: later market-price declines can push marked-to-market exposure below the floor. Those rows are retained in `exposure_audit.csv` with an explicit reason.
