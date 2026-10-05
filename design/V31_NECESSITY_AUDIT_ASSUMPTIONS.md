# V3.1 Tactical Necessity Audit - frozen executable interpretations

1. This is a diagnostic study, not a strategy. It neither changes V3.1 nor creates V3.9.
2. Every counterfactual uses the original V3.1 Model B daily state, stage, cycle, crash, NEW_BULL, target, signal date and portfolio-level tactical-event schedule. Actual counterfactual holdings never feed the shadow history.
3. A portfolio event is the pair of BTC and ETH legs sharing one original `tactical_event_id`. Both legs are deleted together.
4. All Fixed DCA commitments and executions are copied from Model A. Initial allocation is unchanged.
5. If an undeleted shadow order cannot trade because the counterfactual already satisfies its target, it remains an observed shadow instruction with a zero-notional no-fill. This is an indirect removal, not a deleted signal.
6. Return and risk contributions are Baseline minus Counterfactual. Positive final contribution means the original event helped ending wealth. Positive drawdown-protection contribution means deletion made drawdown more negative and the original event protected risk.
7. Resynchronization is confirmed on the third consecutive completed daily close with absolute exposure difference at most 0.50 percentage points. The reported first-resync date is that confirmation close.
8. Local portfolio values use the first available 4H close at or after 7/30/60/90/180 calendar days. Local drawdown is reported at 7/30/60/90 days and through the next major frozen-shadow transition.
9. A major transition is the first later completed daily signal with a state change, cycle change, Right-side action or NEW_BULL action.
10. Cluster identification follows the ordered boundaries frozen in the audit config. Dates are never hard-coded into cluster formation; 2022 and 2026 are reporting windows only.
11. Loose and Strict values were not supplied. They are frozen symmetrically around the user-specified Base thresholds before the counterfactual run and affect diagnostic labels only.
12. Exclusive classification precedence is conflict Mixed, Risk Essential, Return Essential, Harmful, Redundant, then Mixed/Uncertain. Raw effects and individual rule flags remain available so this precedence cannot hide evidence.
13. Forward BTC/ETH returns are appended only after all simulations and are tagged `EX_POST_DIAGNOSTIC_ONLY`.
14. LOEO effects are non-additive because holdings, order notional, fees and compounding interact. Pairwise deletion explicitly measures part of this path dependence.
15. Robust Redundant/Harmful baskets are hindsight-biased upper bounds and cannot be promoted, paper-traded, or treated as implementable strategies.
