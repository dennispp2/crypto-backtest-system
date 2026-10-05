# V2.0 assumptions and decisions

## Frozen scope

- Formal performance begins with a fresh US$20,000 portfolio at the first common 4H bar on or after 2020-01-01 00:00 UTC.
- 2019 is indicator warm-up only. No 2019 holdings, cash flows, returns, stages, regimes, or one-shot flags enter formal performance.
- Model A calls the existing V1 `crypto_backtest.engine.run_backtest` implementation directly. V1 source and V1 outputs are not overwritten.
- Model E replays Model A's actual normal-DCA schedule. This makes normal contribution, intended notional, executed notional, execution asset, price, cost, and quantity independently auditable and identical.
- Only E20, E30, and E40 are run. The floor is the only sensitivity dimension.

## State machine

- `BULL -> LATE_BULL` when the frozen V1 BTC overheat gate arms.
- `LATE_BULL -> DISTRIBUTION` and Stage 1 only when the frozen V1 Stage-1 condition subsequently confirms.
- Stage 2 maps to `BEAR`; Stage 3 remains `BEAR`; Stage 4 maps to `DEEP_BEAR`.
- Frozen V1 `right_confirmation` moves a live sell cycle to `ACCUMULATION` and permits one right-side tactical tranche even when AHR999 never became deeply undervalued.
- Two consecutive frozen V1 `strong_confirmation` signals establish `NEW_BULL`.
- In `NEW_BULL`, 25% of remaining tactical cash is redeployed per confirmed daily signal, capped at the 95% bull-completion exposure. Completion resets stage, trigger flags, and active cycle.
- The 25% daily redeployment fraction is an implementation completion rule, not a fitted parameter. It is frozen before the V2 result is read and is not searched.

## Exposure semantics

- Stage targets are combined crypto value divided by total portfolio value.
- A stage entry sells toward its target. Later daily signals sell again only when exposure exceeds the stage upper drift band.
- A tactical sell may never cause post-trade exposure below the scenario hard floor.
- For E30/E40, an effective target is `max(base target, hard floor)` and the original target-to-upper slack is retained. This is a deterministic feasibility adjustment, not parameter fitting.
- The hard floor is a transaction constraint. A later market decline can push daily mark-to-market exposure below the floor without a tactical sell. Treating the floor as an always-on daily allocation guarantee would require a new forced-buy rule and would contradict the frozen buyback-only design. Both daily mark-to-market breaches and sell-time floor compliance are therefore reported separately.

## Accounting

- Normal cash, pending normal-DCA cash, and tactical cash are separate ledgers.
- Tactical cash originates only from tactical sells and funds only tactical buys.
- Fees, slippage, modeled minimum notional, target weights, and prices match V1 Primary Cost.
- `cash_drag` is a path attribution based on cash share times the contemporaneous target-basket return. It is descriptive, not a causal decomposition.

## Reporting exclusions from the generic empirical skill

Regression tables, treatment-effect estimates, event studies, and paper-style balance tables are inapplicable because this is a deterministic strategy simulation, not a causal econometric design. The user-specified backtest tables, state audits, sensitivity comparison, and figures replace those artifacts.
