# V3.3 task-local best-skill card

- best_skill: deterministic point-in-time BTC+ETH historical backtest with frozen V3.1 replay, two bounded V3.3 patches, audit CSVs, and publication-grade figures
- train_signal: test whether accumulation exposure drift and BEAR/DEEP_BEAR churn can be corrected without contaminating V3.1 bear protection or bull re-entry
- selection_split: the frozen 2020-01-01 through latest-complete common 4-hour history, with explicit 2021-May and 2021-November-to-2022-June event audits
- heldout_gate: exact V3.1 Model B replay, exact fixed-DCA rows, prefix invariance, legal FSM transitions, cycle close/reset, and 2023 bull re-entry delay no greater than 60 calendar days
- accepted_patterns: completed-daily signals; next-common-4H execution; ledger-separated cash; post-backtest-only promotion evaluation; PNG plus PDF figures
- rejected_patterns: parameter search; performance-aware trading; V3.2 Bull Recovery Gate; V3.2 Stage3-to-Stage4 acceleration; V3.2 buyback/redeploy logic; AI; BNB; Dynamic DCA
- patch_scope: only accumulation drift cap, BEAR/DEEP_BEAR hysteresis, and stronger cycle lifecycle accounting
- reject_if: V3.1 replay or fixed-DCA rows differ, any prefix changes when future rows are appended, any illegal transition occurs, or a completed NEW_BULL-to-BULL cycle remains open

This is a deterministic historical simulation, not a causal empirical design. Regression estimators and M1-to-M6 inference tables are therefore non-applicable; the equivalent evidence bundle is the frozen comparator table, event-window diagnostics, integrity audits, and six dual-format figures.
