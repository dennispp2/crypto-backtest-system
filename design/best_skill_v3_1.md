# V3.1 task-local best-skill card

- best_skill: point-in-time, event-driven portfolio backtest with a frozen finite-state machine and annual expanding-window classifier
- train_signal: completed BTC daily candle; execution is no earlier than the next common BTC/ETH 4-hour open
- selection_split: no parameter selection; the 2020-to-end path is a single frozen evaluation, while the AI is retrained only on matured labels available at each prior year-end
- heldout_gate: prefix invariance, exact Model A/B/C Fixed DCA ledger equality, annual training-cutoff audit, feature/label separation, legal FSM transitions, hard-floor compliance, and deterministic rerun hashes
- accepted_patterns: immutable raw inputs with hashes, seven declared AI features, annual out-of-sample prediction, separate normal/bear/temporary cash ledgers, explicit state-transition table, deferred tactical minimum-order guard
- rejected_patterns: audit-date logic, parameter search, same-candle execution, incomplete daily candles, dynamic DCA, BNB, hidden features, AI-created trades or states outside its two permissions, and post-result threshold changes
- patch_scope: add an isolated `v3_1` implementation and outputs; do not modify the V1/V2/V3 engines or historical result packages
- reject_if: any point-in-time, DCA-row, transition, cash-ledger, sell-floor, model-year cutoff, or deterministic-prefix audit fails

The general empirical-analysis skill's regression and causal-inference templates do not apply to this path-dependent strategy simulation. Its applicable controls are the pre-run freeze, data contract, bounded implementation, held-out/prefix checks, reproducibility manifest, and honest reporting of failed gates.
