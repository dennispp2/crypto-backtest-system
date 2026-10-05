# V3.7 frozen assumptions and decisions

## Research boundary

V3.7 is not a macro strategy. A separately executed, unmodified V3.1 FSM-only engine is the sole source of market state and desired tactical actions. Model J can differ from Model B only because its execution overlay delays, cancels, or suppresses an AHR value buy.

## Executable interpretations

1. A V3.1 shadow tactical signal means an executed tactical-event group in the independent shadow trade ledger. Non-executed V3.1 guard outcomes do not become artificial orders.
2. The only restrictable action is V3.1 `TACTICAL_BUYBACK_AHR999_TO_35`, labeled `AHR_VALUE_BUY` in overlay audits. V3.1 has no separate executed `AHR_DEEP_VALUE_BUY` action.
3. Pending validity is checked once per newly available completed daily signal. It requires AHR999 at or below the frozen V3.1 threshold and shadow state in BEAR, DEEP_BEAR, or ACCUMULATION. ACCUMULATION must be included because the independent shadow already executed the delayed order and consequently left the original trigger state.
4. Seven calendar days means `[sell, sell+7d)` is blocked and exactly `sell+7d` is eligible. Three calendar days means duplicates with elapsed time `<3d` are suppressed and exactly three days is eligible.
5. Every executed tactical sell resets the AHR cooldown. If actual exposure already satisfies a non-AHR shadow target, the unchanged target order is classified as `EXECUTE_NO_FILL_AT_TARGET`, not suppression.
6. Right-side and NEW_BULL actions cancel pending AHR before their unchanged order is applied. NEW_BULL also clears cooldown.
7. Temporary hedge lots remain operational execution ledgers only. Their balances never enter the shadow state transition logic.
8. Model B retains the untouched V3.1 within-bar sequence for exact replay. Model J follows the requested DCA-first order. This difference is disclosed and audited; DCA rows must remain numerically and key-wise identical.
9. Audit dates and promotion thresholds exist only in configuration/reporting modules, never in the execution overlay.
