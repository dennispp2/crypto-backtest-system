# V2 task-local best_skill card

best_skill: quantitative backtest engineering + deterministic state-machine audit + reproducible artifact export

train_signal: V1 Full Strategy mixed dynamic DCA with a tactical overlay, allowed stage/exposure drift, and did not provide a cycle-reset audit.

selection_split: E20 on the frozen 2020-01-01 through last-complete-bar sample.

heldout_gate: Model A direct-reuse output, E30/E40 frozen floor sensitivities, prefix invariance, next-open signal execution, per-cycle one-shot buybacks, and exact A/E20 normal-DCA replay equality.

accepted_patterns: reuse V1 Model A without rewriting; replay its normal-DCA schedule in every challenger; point-in-time daily signals; next available 4H-open execution; explicit cycle, exposure, cash-ledger, and file-hash audits.

rejected_patterns: tuning thresholds after seeing performance; dynamic DCA; annual rebalancing; cash protection; V1 Strategy D; grid or Bayesian search; using tactical cash for normal DCA; resetting one-shot flags before a new sell cycle.

patch_scope: add V2-only configuration, engine, runner, tests, outputs, figures, and report while leaving all V1 implementation and artifacts unchanged.

reject_if: any DCA integrity mismatch; signal executed before availability; tactical cash below zero; tactical sell itself breaches the hard floor; repeated one-shot trigger within a cycle; prefix invariance failure; or a state transition crosses a confirmed NEW_BULL without reset.
