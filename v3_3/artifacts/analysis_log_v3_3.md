# V3.3 analysis log

## Accepted
- Frozen V3.1 A/B exact replay and a V3.3 E engine importing V3.1 accounting primitives only.
- Two bounded trading patches: accumulation exposure drift cap and BEAR/DEEP_BEAR hysteresis.
- Cycle lifecycle accounting, completed-daily signals, next-common-4H execution, exact fixed-DCA replay, and prefix invariance.
- Promotion gates evaluated only after the full historical simulation.

## Rejected before formal execution
- V3.2 Bull Recovery Gate, V3.2 Stage-4 acceleration, V3.2 buyback/redeploy, AI, BNB, dynamic DCA, parameter search, and performance-aware trading.

## Non-applicable skill artifacts
- Regression tables, causal estimators, standard errors, and treatment-effect inference are not applicable because this is a deterministic historical backtest rather than an identified causal design. Strategy comparison tables, event-window audits, prefix tests, and six PNG/PDF figures are the task-appropriate evidence bundle.
