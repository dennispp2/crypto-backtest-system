# Reproducing the V3.1 Necessity Audit

From the `crypto_backtest_system` project root on Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe run_v31_necessity_audit.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_v31_necessity_audit.py
```

The formal run verifies the frozen V3.1 config, engine, source manifest and user-specification SHA-256 values before execution. It then runs the independent zero-deletion replay, 106 LOEO simulations, all automatically identified LOCO simulations, the frozen top-10 cluster pair audit, diagnostic baskets, integrity checks, figures, report and archive.

`qa_finalize_v31_necessity_audit.py` is only a report/figure QA rebuilder for an already completed run. It does not replace the formal simulations.

The source manifest intentionally points to the immutable V3.1 raw-data snapshot in `v3_1/data/raw`. No network refresh is performed by this audit.
