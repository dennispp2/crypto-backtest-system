# Reproducible no-look-ahead crypto backtest

GitHub 保存範圍、排除項目與 Windows 還原方式見 [GITHUB_README.md](GITHUB_README.md)。

This package implements the supplied frozen BTC/ETH/BNB strategy and benchmark horse-race. It downloads public Binance Spot 4H/1D candles plus Bitstamp BTCUSD daily history, freezes raw files with SHA-256 hashes, enforces completed-daily-candle availability, executes at the next 4H open, and keeps normal/pending/tactical cash ledgers separate.

## V2.0

The independent 2020-to-data-end Fixed DCA + Corrected Cycle Hedge implementation is run with:

```powershell
.\.venv\Scripts\python.exe run_backtest_v2.py
```

V2 outputs are isolated under `v2/`; see `v2/README_V2.md`. The V1 engine and V1 result files remain unchanged.

## V3.0 Macro Cycle Hedge

The frozen eight-state FSM, E20 primary, and E30/E40 floor sensitivities run with:

```powershell
.\.venv\Scripts\python.exe run_backtest_v3.py
.\.venv\Scripts\python.exe -m pytest -q tests
```

V3 outputs are isolated under `v3/`. The main report is
`v3/report/FINAL_REPORT_V3.md`; the machine audit is
`v3/artifacts/no_lookahead_audit_v3.json`.

## Independent Fixed DCA Universe Diagnostic

The U1 BTC-only, U2 BTC+ETH, and U3 BTC+ETH+BNB diagnostic is deliberately
separate from the V3 FSM and runs with:

```powershell
.\.venv\Scripts\python.exe universe_diagnostic\run_universe_diagnostic.py
.\.venv\Scripts\python.exe -m pytest -q universe_diagnostic\tests
```

Its report, frozen rules, tests, audit and results are isolated under
`universe_diagnostic/`; it reuses only the frozen V1 execution engine and price
data from the project root. It does not import `v3_engine.py` or
`v3_indicators.py` and cannot update V3 regime, Stage, floor, buyback, or hedge
parameters.

## Run

PowerShell:

```powershell
.\.venv\Scripts\python.exe run_backtest.py --refresh-data
.\.venv\Scripts\python.exe -m pytest -q
```

For an exact rerun of the delivered frozen raw files, omit `--refresh-data`. Refreshing later data intentionally changes hashes and the backtest end date.

## Important interpretation

- All strategies receive exactly US$2 of external capital every 4H bar. Dynamic DCA changes spending speed from the accumulated normal-cash ledger; it does not change contributions.
- If a common three-asset 4H candle is missing, the elapsed US$2 contributions and DCA intent accumulate and execute no earlier than the next genuine common 4H open; no price is fabricated.
- The primary three-asset run begins at the first common Binance 4H bar, not 2017-08-01, because BNBUSDT did not yet exist.
- The US$5 minimum notional is a current Binance rule snapshot used as a historical modeling proxy. Historical point-in-time exchange filters were not available.
- Sensitivity output is a frozen grid and must not be used to replace the primary parameters.

## Main deliverables

- `report/FINAL_REPORT.md`
- `results/backtest_summary.csv`
- `results/trade_log.csv`
- `results/daily_portfolio.csv`
- `results/signal_log.csv`
- `results/cycle_analysis.csv`
- `results/cash_analysis.csv`
- `results/parameter_sensitivity.csv`
- `results/btc_extended_validation.csv`
- `figures/01_...` through `11_...`, each in PNG and PDF
- `artifacts/no_lookahead_audit.json`
- `data/source_manifest.csv`
