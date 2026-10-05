# V3.8 frozen assumptions and decisions

## Research boundary

V3.8 changes no market-state logic. A separately executed, unmodified V3.1 Model B engine remains the only source of State, Stage, Cycle, Target, Crash, NEW_BULL and desired tactical actions. Model K can differ only because execution of `TACTICAL_BUYBACK_AHR999_TO_35` is delayed or cancelled.

## Executable interpretations

1. The cooldown counter is based on newly available completed daily signals, not elapsed wall-clock days. A sell-triggering signal is close zero. The next three signal updates are all blocked. AHR becomes eligible only at the first tradable bar after the third subsequent close, when the fourth subsequent daily signal is available.
2. A new risk-sell signal resets the completed-close counter even if actual K exposure is already below the unchanged target. The audit action is `NO_TRADE_ALREADY_BELOW_TARGET`, decision `EXECUTE`; it is not suppression.
3. Pending AHR validity is tested when the cooldown reaches zero. Before then it remains pending unless Right-side or NEW_BULL cancels it. Validity requires frozen AHR999 <= 0.35 and Shadow state in BEAR, DEEP_BEAR or ACCUMULATION; ACCUMULATION is necessary because the independent Shadow already executed its original AHR order.
4. V3.8 has no duplicate suppression, rearm rule, post-buy sell lock, sticky base or episode-controlled behavior. Any later V3.1 risk sell executes immediately.
5. Tactical events follow their original V3.1 event order and occur before DCA, matching V3.1. If a risk sell and AHR request ever coexist, the risk sell is stably moved first and AHR cannot fill at that timestamp.
6. Right-side and NEW_BULL cancel pending AHR before their unchanged order is applied. NEW_BULL also clears the AHR cooldown.
7. An execution target is applied to K actual holdings. A non-AHR shadow instruction can therefore be a zero-notional execute if K already satisfies the target; this never modifies Shadow state.
8. Every delayed Shadow request receives an opportunity-cost record. If several requests belong to the same outstanding pending order, they share the eventual execution or cancellation outcome without creating duplicate actual orders.
9. The 30-day and 60-day forward BTC returns use future prices only in the post-backtest opportunity-cost report. These fields never enter the execution frame or engine.
10. Audit windows and promotion thresholds exist only in configuration, analysis and reporting—not in the execution engine.
