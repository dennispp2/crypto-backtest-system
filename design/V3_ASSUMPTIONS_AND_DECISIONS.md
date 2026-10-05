# V3 frozen assumptions and operational definitions

These decisions resolve wording that was not numerically complete in the request. They are frozen before the first formal V3 run and are not selected from audit-case results.

## Point-in-time data

- All macro variables are calculated on the completed BTC daily candle labelled `signal_date`.
- That signal is available at 00:00 UTC on the following day and can first execute at that or the next common BTC/ETH/BNB 4-hour open.
- The 2019 period supplies rolling history only. Holdings, cash flows and performance restart at 2020-01-01 00:00 UTC.
- The existing V1 engine is called directly for Model A. Its code is not modified by V3.

## Previously qualitative terms

- The later supplied frozen FSM supersedes the earlier qualitative `near flat` branch: NEW_BULL requires `SMA200[t] >= SMA200[t-20]` exactly.
- `local-low rebound` means the close is at least 15% above the lowest BTC low observed in the trailing 30 completed days.
- `lower-high + lower-low` compares the latest completed 10-day high/low range with the immediately preceding non-overlapping 10-day range.
- `previous major low broken` means the close is below the lowest completed daily low from the prior 60 days, excluding the current day.
- A condition requiring confirmation uses consecutive completed daily closes. Distribution and Stage 2 require 2; Stage 3 requires 2; Deep Bear requires 3.
- Distribution invalidation uses the supplied three consecutive daily closes. EARLY_BEAR short-term repair uses the same three-close persistence because its exact persistence was not specified. DEEP_BEAR disappearance requires three consecutive completed days to satisfy the global anti-whipsaw requirement.
- `20 calendar days since the Bear/Deep-Bear low` uses the most recent new closing low observed within the current confirmed cycle while the state is BEAR, DEEP_BEAR, or ACCUMULATION.

## State separation

- Macro regime is a deterministic finite-state machine with the exact eight supplied states, including EARLY_BEAR. Every transition is checked against the frozen adjacency matrix.
- Crash Override is an exposure overlay only. It may lower the active target to 70%, but it does not change macro state, sell stage, or create a macro cycle.
- BULL and LATE_BULL never cause a normal tactical sale. LATE_BULL uses the already-frozen V1 2-of-3 overheat gate as context only.
- Stage targets are 85%, 70%, 55%, and floor+5 percentage points at Stage 4 (25/35/45% for E20/E30/E40). The floor is a sell-time constraint, not a daily rebalance target.
- `active_exposure_target` starts at the current stage target, rises with a completed buyback, and is lowered only by a new stage escalation, Crash Override, or formally re-armed bearish re-break.

## Turnover and conflicts

- All tactical orders require a gap of at least 5 percentage points and modeled notional of at least max(US$100, 1% of current portfolio). An order failing the gate remains deferred.
- Ordinary drift sales require exposure above the active target by more than 10 percentage points, seven calendar days since the prior drift sale, and seven calendar days since any tactical buy.
- Stage escalation, a newly armed Crash Override, or a newly armed bearish re-break is an explicit invalidation and may bypass the ordinary cooldown. It is labelled as such for the conflict audit.
- Asset sale priority is lexicographic: greater overweight versus BTC/ETH/BNB 50/30/20 first, then larger point-in-time technical weakness score. There is no permanently protected core coin or fixed BNB-first tie-break.

## Buyback and reset

- Only the highest eligible not-yet-used AHR/right-recovery layer is attempted on a signal day. A layer is marked used only after an executed trade.
- AHR/right-recovery buys may only use tactical cash and may not lower the active target.
- NEW_BULL uses all seven requested gates. Its SMA200 gate is the strict supplied `SMA200[t] >= SMA200[t-20]` rule.
- NEW_BULL can only follow ACCUMULATION. It resets sell stage and schedules remaining tactical cash across 10 daily signal executions as `remaining cash / remaining days`, subject to the turnover guard and a 95% ceiling.
- NEW_BULL remains the macro state for at least 20 completed daily signals. Only then may it become BULL if the frozen validation remains true. The preceding cycle closes at that transition.
- A failed NEW_BULL may only move to EARLY_BEAR under the supplied failure gate. Because the frozen FSM explicitly says this creates a new sell cycle, the prior cycle is closed as `FAILED_NEW_BULL` and a new already-confirmed cycle id is opened.

## Interpretation limits

- V3 is one frozen rule-tree evaluation, not an optimized estimate of future performance.
- E30/E40 change only the hard floor and corresponding Stage-4 target. They are sensitivities, not a basis for revising E20.
- Audit dates appear only in post-run reporting and never in the V3 indicator or execution engine.
- The frozen FSM supplies no bullish redeployment transition for a Crash-only overlay that never reaches a confirmed bear cycle, nor for an `ABORTED_DISTRIBUTION`. V3 therefore does not invent one: such tactical cash remains cash until a later permitted ACCUMULATION/NEW_BULL route. This is a design limitation, not an implementation failure.
