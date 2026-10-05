# V3 analysis log

## Accepted
- Strict eight-state deterministic FSM and frozen adjacency matrix.
- Crash Override is an exposure overlay and never creates or jumps macro state.
- Model A is the unchanged V1 Fixed DCA engine; every E model replays the same DCA ledger.
- Active exposure target prevents buyback/old-stage drift conflict.
- All tactical events pass the 5pp and max(US$100, 1% portfolio) guards.

## Rejected
- Audit-date conditions, parameter search, daily forced rebalance, Dynamic DCA, same-day signal execution, and using Universe Diagnostic results to alter V3.
- No redeployment rule was invented for Crash-only cash or an aborted Distribution because the frozen FSM did not authorize one.

## Implementation corrections before final acceptance
- Initialized two declared counters that stopped the first attempted execution before any performance output was produced.
- Removed the optional `tabulate` dependency from report rendering.
- Enforced the frozen rule that a previously confirmed cycle cannot later be labelled `ABORTED_DISTRIBUTION`; added a regression test and an explicit audit count.
- Added the required SMA10/SMA20 daily output columns and removed a case-only duplicate BTC close column.
- Made cycle Stage 1/2/3/4 audit fields preserve the first entry instead of being overwritten by later re-entry events.
- Removed dynamic PDF creation timestamps so complete-run file hashes are reproducible.

## Gates
- no-look-ahead/state audit: True
- illegal transitions: 0
- fixed-DCA mismatch rows: 0
- buy/sell conflicts: 0
- prefix invariant: True
- verdict: V3 NEEDS REDESIGN
