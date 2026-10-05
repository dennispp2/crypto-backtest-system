# V3.9 pre-run interpretation freeze

Frozen before any V3.9 Challenger result was calculated.

1. `BULL_PERSISTENCE_ACTIVE` is a latch set only when the Challenger's unchanged V3.1 FSM confirms `NEW_BULL`. It is not a new way to create a bull state.
2. `BULL_PERSISTENCE_GUARD` is the conjunction of that latch and the five market/crash conditions in the request. The crash item is represented by the two original V3.1 raw crash signals, so a current-day crash cannot be called healthy.
3. Stage 1 and Stage 2 retain the exact V3.1 state transitions, targets, costs, and fills, while the persistence latch stays set.
4. Stage 3 is intercepted whenever persistence remains latched, not only while the instantaneous healthy-structure conjunction is true. This is logically necessary: a Stage 3 confirmation needs closes below SMA50, whereas healthy structure requires the close above SMA50. Restricting the candidate clock to instantaneous `Guard=ON` would make the requested three-close rule impossible.
5. The candidate close counts as confirmation close 1. The next two completed daily candles must also satisfy both `close < SMA50` and `SMA20 < SMA50`. A break rejects the candidate; a later original V3.1 Stage 3 can start a new candidate.
6. Three consecutive completed closes below SMA200 release persistence before the day's unchanged V3.1 FSM runs. This hard failure creates no new sell, state, or target by itself.
7. A same-day Stage 4 action emitted by the separately replayed V3.1 Model B shadow is authoritative. If P has diverged and is not in BEAR, P is handed directly to DEEP_BEAR and the unchanged V3.1 Stage 4 target/fill is executed. This is required to make “original V3.1 Stage4 is 100% priority” operational rather than state-dependent.
8. Crash L1/L2 use P's unchanged V3.1 crash engine. Any L1/L2 action, including a guarded no-fill outcome, releases persistence; no crash action is suppressed.
9. Drift is suppressed only when instantaneous Guard is ON. The baseline shadow event is logged, and no substitute sell or exposure target is created.
10. The 2025–2026 drawdown window is the original V3.1 `CASE_8_2025_2026_CORRECTION`: 2025-01-01 through the common data end. This is the convention that reproduces the stated approximately -28.24% reference.
11. Period drawdown and period CAGR use cash-flow-adjusted `unit_nav`. Forward 30/60-day BTC returns are appended only after the run.
12. All requested thresholds and promotion gates are evaluation-only. They never enter order sizing or state decisions.

