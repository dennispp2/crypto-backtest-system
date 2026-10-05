# V3 task-local best_skill card

- best_skill: time-series event-driven backtest; frozen macro-state machine; reproducible CSV/JSON/PNG/PDF package
- train_signal: V2 false NEW_BULL, delayed crash response, buyback/drift conflict, and excessive tactical turnover
- selection_split: full frozen 2020-to-data-end run; no rule may reference an audit-case date
- heldout_gate: prefix invariance, exact A/E20 DCA ledger equality, next-bar execution, E30/E40 rule identity except floor/Stage-4 target, zero ordinary buy/drift conflict, and unchanged Model A source hash
- accepted_patterns: completed-daily signals, next-4H-open execution, separate normal/tactical ledgers, sell-time floor, explicit active exposure target, event and cycle audit tables
- rejected_patterns: date hard-coding, parameter search, same-day signal execution, daily forced rebalance, dynamic DCA, tactical buys from normal cash, and post-result threshold changes
- patch_scope: add V3 indicators/state machine/audits/reporting without changing V1/V2 strategy logic or outputs
- reject_if: any integrity/no-look-ahead audit fails, Model A differs, sensitivity variants change a rule other than floor/Stage-4 target, or outputs cannot be reproduced

The economics regression/table defaults in the general skill are not applicable to this path-dependent portfolio simulation. The relevant skill controls are the pre-run freeze, data contract, bounded patch, held-out checks, audit artifacts, and reproducibility stamp.
