# V3.8 task-local best_skill card

best_skill: deterministic historical execution-overlay experiment with an independent frozen V3.1 shadow, completed-close cooldown accounting, opportunity-cost attribution, and replay gates
train_signal: V3.7 reduced turnover and whipsaw but its seven-calendar-day delay reduced ending wealth below the frozen 95 percent gate
selection_split: frozen 2022-06-01 through 2022-07-31 and 2026-02-01 through 2026-06-30 reporting windows
heldout_gate: full-period V3.1 and V3.7 replay, all-date shadow parity, fixed-DCA row identity, COVID/May-2021/2021-2022/2025-2026 drawdown guards, prefix invariance, opportunity-audit completeness, and required artifacts
accepted_patterns: separate original V3.1 shadow; original V3.1 within-bar tactical-before-DCA order; restrict only AHR value-buy execution; count actual newly available completed daily closes
rejected_patterns: calendar-time cooldown approximation; duplicate suppression; actual holdings changing the shadow FSM; performance gates in execution; date-conditioned logic; post-result threshold changes
patch_scope: replace only the V3.7 seven-calendar-day AHR cooldown with three completed daily closes and restore original V3.1 bar order
reject_if: either replay fails, any shadow mismatch, any non-AHR restriction, DCA mismatch, look-ahead violation, incomplete opportunity-cost lifecycle, or a frozen promotion gate fails

The Full Empirical Analysis Python workflow is used for freeze, data-contract, held-out-validation, reproducibility, and artifact discipline. Regression-specific outputs are inapplicable to this deterministic backtest and are replaced by the user-specified ledgers, audits, figures, and replay tests.
