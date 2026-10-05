# V3.10 pre-run interpretation freeze

Frozen before any V3.10 Challenger result was calculated.

1. Model Q starts from the unchanged V3.1 Model B engine. Its only direct rule difference is to hold an otherwise executable V3.1 `EARLY_BEAR -> BEAR` Stage3 transition until the frozen confirmation resolves.
2. Stage3 eligibility is a historical latch set only after the unchanged V3.1 FSM has emitted `NEW_BULL_CONFIRMED`. V3.1 closes that cycle when redeployment completes, so interpreting eligibility as a non-null `new_bull_date` on the later active cycle would make the requested rule unreachable. The request's later wording, "after an original V3.1 NEW_BULL has existed", is therefore controlling. This latch neither creates a bull state nor changes exposure.
3. The candidate row counts as completed close 1. The next two completed daily closes must each have `BTC close < SMA50` and `SMA20 < SMA50`. The implementation directly imports the frozen V3.9 `_new_candidate` and `_resolve_candidate` helpers and reproduces its completed-close counting and calendar-day delay semantics.
4. A failed confirmation sequence rejects the candidate and leaves Q on the last legally executed V3.1 target. A later original Stage3 signal may start a new candidate.
5. Three consecutive completed closes below SMA200 cancel the candidate before the same row is handed back to the unchanged V3.1 FSM. Hard failure creates no independent trade, state, or target.
6. The separately replayed V3.1 shadow is authoritative for same-day Stage4. If Q is still in `EARLY_BEAR`, that Stage4 cancels the candidate and executes the original V3.1 Stage4 transition/target/fill immediately.
7. Crash L1/L2 use Q's unchanged V3.1 crash engine and cancel an open candidate after executing. No crash action is delayed or suppressed.
8. `_process_drift`, temporary-lot unwind, AHR999, right-side buybacks, NEW_BULL redeployment, DCA commitment, costs, minimum notional, floor, and all non-Stage3 FSM rules are unchanged V3.1 helpers.
9. A B/Q trade difference on the candidate row is `DIRECT_STAGE3_DELAY`. A later difference is allowed only as `INDIRECT_PATH_DIFFERENCE` and must name the most recent causal Stage3 candidate. Anything else is `UNEXPECTED_DIFFERENCE` and invalidates the scope gate.
10. Forward 30/60-day candidate values and local drawdowns are appended only after execution. Portfolio values use the first available daily observation on or after candidate date plus 30/60 calendar days. Local drawdown resets cash-flow-adjusted `unit_nav` at the candidate date and runs through +60 calendar days. Incremental exposure-days is the inclusive daily sum of `Q exposure - B exposure` through confirmation or rejection. These are diagnostics and never enter Q decisions.
11. Event drawdown uses cash-flow-adjusted `unit_nav` reset at each requested window's first observation. The 2025-2026 window is 2025-01-01 through the frozen common data end, matching the V3.1/V3.9 reference convention.
12. Promotion thresholds are post-backtest evaluation gates only. They never alter orders, targets, state transitions, or candidate resolution.
