# V3.1 reproducibility note

This directory is the isolated BTC+ETH V3.1 result package. It does not modify the V1/V2/V3 strategy engines or outputs.

## Exact rerun from the frozen raw snapshot

From the `crypto_backtest_system` directory:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe .\run_backtest_v3_1.py
```

The no-argument run uses the raw files under `v3_1/data/raw`. Their hashes are recorded in `artifacts/source_manifest_v3_1.csv` and the run manifest.

## Refresh to a different data cutoff

```powershell
.\.venv\Scripts\python.exe .\run_backtest_v3_1.py --refresh
```

`--refresh` deliberately creates a new point-in-time snapshot and therefore is not expected to reproduce the existing cutoff byte for byte.

## Frozen outcome

- Hard execution/no-look-ahead audit: PASS
- Fixed DCA row identity across A/B/C: PASS
- FSM edge: PASS under the pre-run gate
- AI edge: FAIL because Max-DD improvement versus Model B was below 3 percentage points
- Formal verdict: `B. V3.1 FSM PROMOTED TO FORWARD PAPER TEST`

The promotion is for paper testing only. Model B still held material tactical cash for most of the historical observations; see the final report and cash audit.
