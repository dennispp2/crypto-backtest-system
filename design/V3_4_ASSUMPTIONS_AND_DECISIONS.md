# BTC+ETH Macro Hedge V3.4 FINAL — frozen assumptions and decisions

Frozen before formal execution at 2026-09-03T11:30:03Z. The sole strategy base is V3.1 FSM-only Model B. V3.4 retains only V3.3's BEAR/DEEP_BEAR hysteresis and adds exactly Patch A/B/C. V3.3's accumulation exposure drift cap is deliberately excluded.

## Scope and timing

- Universe, allocation, capital, costs, 20% floor, $2/4H DCA, Stage 1-4, AHR999, ordinary buybacks, Crash L1/L2, and original NEW_BULL redeploy are inherited unchanged from V3.1.
- Every new V3.4 feature is calculated from completed UTC daily candles. A signal becomes available only after that candle closes and executes at the next common BTC/ETH 4-hour open.
- Rolling N-calendar-day price windows mean the current completed daily close and the previous N-1 completed daily closes. No portfolio drawdown or promotion result is an engine input.

## Patch A decisions

- L3 eligibility is checked after unchanged V3.1 L1/L2 logic on the same daily signal, so an L2 activation can make L3 eligible at that next 4-hour execution bar.
- A crash episode begins on an actual L1 trigger. It ends only after the unchanged V3.1 five-clear-close rearm rule and no L1 active days remain, or when a confirmed macro bear reclassifies all crash cash.
- L3 cash is an independently tagged temporary lot (`source=CRASH_LEVEL3`). The unchanged legacy temporary unwind skips this lot; only the specified L3 recovery may unwind it unless a macro bear reclassifies it.
- A false-positive flag requires both no further 10% BTC decline within 30 calendar days and an L3 recovery confirmation within that horizon. It is audit-only.

## Patch B decisions

- Crash-free gates count actual L2/L3 executions over prior completed signal observations. Candidate day is day zero; confirmation requires five subsequent completed closes. Bear invalidation is also day zero for a further five-close NEW_BULL confirmation.
- Bear invalidation changes only the active target to 70%; it does not spend cash immediately because no deployment schedule was specified. After confirmation, the unchanged V3.1 ten-day NEW_BULL redeploy performs buying.
- During the five-close invalidated hold, the existing state label is retained and ordinary bear-state transitions are suspended; Crash L1/L2/L3 remains active. This is the minimum implementation that makes “bear thesis invalidated” operational without adding a state.
- Patch-authorized direct transitions from BEAR/DEEP_BEAR/ACCUMULATION to NEW_BULL are logged distinctly and accepted by the V3.4 FSM audit. All other transition legality remains V3.1.
- A false-bull flag requires a sub-SMA200 close and a 20% decline from confirmation within 60 calendar days. It is audit-only.

## Patch C decisions

- On the final unchanged NEW_BULL redeploy observation, open temporary lots belonging to the active cycle are first reclassified into tactical bear cash. The sweep then buys BTC/ETH at 62.5/37.5, may bypass only the 5 percentage-point gap rule, and continues to respect 95%, fees, slippage, and per-asset minimum notionals.
- Cycle close occurs only after the sweep and cash audit. Residual tactical bear cash above 1% fails unless it is no more than the aggregate modeled minimum notionals plus USD 0.01 rounding tolerance.

## Evaluation discipline

- All performance, drawdown, normal-bear, participation, cash-reset, churn, turnover, and integrity gates are evaluated after the complete simulation.
- The 2020, 2021, 2022, 2023-2025, and 2025-cutoff dates are audit windows only and never enter transaction logic.
- One formal frozen-parameter run is permitted. A failed gate is reported as a failure; it does not authorize threshold search or V3.5.
