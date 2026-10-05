# BTC+ETH Macro Hedge V3.3

Run from the project root with `.venv\Scripts\python.exe run_backtest_v3_3.py` (or the available Python interpreter).

V3.1 Model B is replayed through the unchanged V3.1 engine. V3.3 Model E is isolated in `v33_engine.py`, imports no V3.2 module, and changes only the frozen V3.3 scope. Promotion gates are post-backtest diagnostics.
