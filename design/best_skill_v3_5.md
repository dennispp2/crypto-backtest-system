# V3.5 task-local best_skill card

best_skill: deterministic frozen challenger with bottom-whipsaw path audit
train_signal: user-specified Patch D to prevent repeated 25/35/50 accumulation reversals
selection_split: full 2020-to-cutoff V3.5 Model G compared with unchanged V3.1 B and frozen V3.4 F
heldout_gate: 2022 and 2026 audit windows, exact Fixed-DCA rows, V3.1 replay, V3.4 F replay, prefix invariance, one-rung actions, 14-day cooldown, and required CSV/PNG/PDF artifacts
accepted_patterns: persistent episode ids, independently logged action cooldown, explicit rung transitions, post-backtest whipsaw pairing
rejected_patterns: overwriting frozen V3.4, date-coded trades, portfolio-DD signals, performance-aware tuning, same-episode rearming without all gates
patch_scope: Patch D only on top of the unchanged frozen V3.4 A/B/C engine behavior
reject_if: any base replay changes, any non-crash normal action skips a rung/cooldown, any future field reaches execution, or a post-backtest gate affects a trade
