# Fixed DCA Universe Diagnostic

Independent, frozen-universe diagnostic for U1 BTC-only, U2 BTC+ETH, and U3
BTC+ETH+BNB across fresh 2020/2021/2022/2023 starts.

Run from the project root:

```powershell
.\.venv\Scripts\python.exe universe_diagnostic\run_universe_diagnostic.py
.\.venv\Scripts\python.exe -m pytest -q universe_diagnostic\tests
```

The mandatory U3 reproduction gate runs first and aborts the experiment if the
2020 U3 rows or ending value do not reproduce the V2 Fixed DCA Champion.

