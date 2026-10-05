# V3.3 frozen assumptions and operational decisions

Frozen at `2026-09-03T10:51:49Z`, before the first V3.3 formal run.

## Parent and isolation

- V3.1 FSM-only Model B is the sole trading parent. Model B runs through the unchanged `v31_engine.py`; V3.3 runs in an isolated `v33_engine.py` that imports V3.1 accounting primitives only.
- No V3.2 trading module, feature module, Bull Recovery Gate, accelerated Stage 4, slower buyback, or five-day V3.2 redeploy is imported.
- Frozen V3.1 raw inputs and costs are reused so B can be compared bit-for-bit with the prior V3.1 output.

## Point-in-time and exposure observations

- A daily candle is usable only after it has closed. Its signal executes at the first common BTC/ETH four-hour open at or after availability.
- The accumulation exposure observation is the mark-to-market exposure at that execution open, before the day's FSM, crash, drift, or DCA orders. Strict `>` is used for the upper band.
- The consecutive count resets outside ACCUMULATION or whenever exposure is not strictly above `active_target + 10pp`. It may continue accumulating while a seven-day accumulation lock is active, but the ordinary drift sell is blocked until the lock expires. Crash Brake remains independent.
- An executed accumulation drift order sells toward `active_target + 5pp` and starts a 14-calendar-day cooldown. An order rejected by the unchanged V3.1 turnover/minimum-notional guard does not start cooldown and remains eligible on a later completed daily close.

## Hysteresis

- One trading day means one newly completed UTC daily signal. Ordinary DEEP_BEAR-to-BEAR exit is blocked until ten subsequent completed signal observations have elapsed since BEAR-to-DEEP_BEAR.
- The ordinary exit then requires: five consecutive completed closes above SMA50, SMA20 today above SMA20 five completed rows earlier, and today's close strictly above the minimum close of the prior 20 completed rows.
- The unchanged V3.1 AHR999 entry to ACCUMULATION is tested before the ordinary exit and bypasses minimum dwell. Hysteresis never participates in ACCUMULATION-to-NEW_BULL or NEW_BULL-to-BULL.

## Cycle reset and cash audit

- On V3.1 NEW_BULL confirmation, stage becomes zero, the active cycle is marked `CLOSING_NEW_BULL`, and the unchanged ten-signal V3.1 redeploy begins.
- On redeploy completion and NEW_BULL-to-BULL, that cycle is marked `COMPLETED_NEW_BULL`, `cycle_closed=true`, and ended on the signal date. The active cycle id becomes zero internally, the public audit renders this as `NONE`, and later distribution must allocate a strictly newer id.
- Temporary references that are already closed/reclassified stay closed. Any still-open zero-cash reference is marked closed on cycle completion. Non-zero temporary cash is not silently relabelled or spent.
- Cash reset passes when tactical-bear cash is at most 1% of portfolio. If it is above 1%, the only exemption is aggregate residual cash no greater than BTC+ETH modeled minimum notionals plus one cent. The unchanged V3.1 5pp turnover guard is not treated as a cash-reset exemption.

## Evaluation discipline

- Promotion gates and the two event regressions are evaluated only after the frozen run and never appear in trading decisions.
- `BEAR_PROTECTION_REGRESSION` and `BULL_REENTRY_REGRESSION` are auxiliary hard guardrails in the final promotion verdict because the request explicitly labels their breach as FAIL.
- Warnings at 730/1095 days are diagnostic only and never change trades.
- No parameter is changed after observing results. A different rule requires V3.4.
