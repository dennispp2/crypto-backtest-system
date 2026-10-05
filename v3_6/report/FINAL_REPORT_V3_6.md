# BTC+ETH Macro Hedge V3.6

## Final verdict

**B. V3.1 REMAINS CHAMPION**

- `PROMOTION_GATE = FAIL`
- `V3_1_REPLAY_INTEGRITY = PASS`
- `FIXED_DCA_ROW_INTEGRITY = PASS`
- `NO_LOOK_AHEAD = PASS`
- `EXECUTION_INTEGRITY = PASS`
- `FSM_AUDIT = PASS`

## Performance

| model | final_portfolio_value | xirr | twr_cagr | maximum_drawdown | sharpe | sortino | calmar | tactical_turnover | tactical_event_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H0 | US$197,656.93 | 40.96% | 40.96% | -77.22% | 0.8638 | 0.8382 | 0.5304 | 0.0000x | 0 |
| A | US$279,201.22 | 38.39% | 42.50% | -76.87% | 0.8859 | 0.8593 | 0.5529 | 0.0000x | 0 |
| B | US$348,746.85 | 43.72% | 47.69% | -39.51% | 1.2494 | 1.2136 | 1.2070 | 9.3677x | 106 |
| H | US$188,752.57 | 29.30% | 32.18% | -39.51% | 1.0746 | 1.0331 | 0.8144 | 6.2600x | 61 |

## Direct answers

1. V3.1 Model B exact replay: **PASS**; final US$348,746.85, tactical events 106.
2. V3.6 Model H final value: **US$188,752.57** (US$-159,994.29 versus B).
3. H TWR CAGR: **32.18%**; delta versus B -15.51 percentage points.
4. H maximum drawdown: **-39.51%**; delta versus B 0.00 percentage points.
5. H Calmar: **0.8144**; delta -0.3926.
6. 2022 bottom events B/H: **12 / 4**; reduction 66.67%.
7. 2026 bottom events B/H: **22 / 12**; reduction 45.45%.
8. Full-period 7-day opposite-side whipsaw-pair reduction: **65.00%**.
9. Overall tactical turnover B/H: **9.3677x / 6.2600x**; reduction 33.17%.
10. 2021-11 through 2022-06 drawdown B/H: **-28.25% / -26.46%**.
11. 2025 through cutoff drawdown B/H: **-28.24% / -27.69%**.
12. COVID drawdown B/H: **-37.34% / -37.34%**; the patch does not block the original risk sells.
13. 2021 May drawdown B/H: **-33.20% / -29.08%**.
14. Fixed-DCA row identity: **PASS**.
15. Completed-candle/no-look-ahead audit: **PASS**.
16. Same-timestamp tactical buy and sell violations in H: **0**.
17. V3.2-V3.5 strategy inheritance found in H engine: **NO**.
18. The 30% drawdown threshold is **not** a V3.6 promotion gate; the frozen gates are reproduced below without alteration.
19. Final classification: **B. V3.1 REMAINS CHAMPION**.

## Frozen promotion gates

```json
{
  "G1_2022_BOTTOM_EVENTS_REDUCTION_GTE_50PCT": true,
  "G2_2026_BOTTOM_EVENTS_REDUCTION_GTE_50PCT": false,
  "G3_WHIPSAW_PAIRS_REDUCTION_GTE_50PCT": true,
  "G4_OVERALL_TURNOVER_REDUCTION_GTE_15PCT": true,
  "G5_2022_BEAR_DD_REGRESSION_LTE_2PP": true,
  "G6_2025_2026_DD_REGRESSION_LTE_2PP": true,
  "G7_OVERALL_MAX_DD_REGRESSION_LTE_2PP": true,
  "G8_TWR_CAGR_GTE_45PCT": false,
  "G9_FINAL_VALUE_GTE_95PCT_OF_B": false,
  "G10_ALL_INTEGRITY_PASS": true
}
```

## B versus H comparison

| comparison | delta_final_value | delta_cagr_percentage_points | delta_max_drawdown_percentage_points | delta_calmar | bottom_2022_event_reduction_fraction | bottom_2026_event_reduction_fraction | whipsaw_pair_reduction_fraction | overall_turnover_reduction_fraction | 2022_bear_dd_regression_percentage_points | 2025_2026_dd_regression_percentage_points | overall_max_dd_regression_percentage_points |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H V3.6 vs B V3.1 | -159994.2875967786 | -15.51377365688098 | 0.0 | -0.3926232118141807 | 0.6666666666666667 | 0.4545454545454546 | 0.65 | 0.33174655346536674 | -1.7847338664849555 | -0.5492453595743796 | 0.0 |

## Bottom-event summary

| period | model | start | end | bottom_tactical_event_count | bottom_tactical_trade_rows | bottom_tactical_notional_usd | bottom_turnover | whipsaw_pair_count | average_days_between_events | median_days_between_events |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FULL | B | 2020-01-01 00:00:00+00:00 | 2026-09-03 00:00:00+00:00 | 70 | 140 | 1538273.0331978032 | 7.185216212193274 | 60 | 33.31884057971015 | 7.0 |
| FULL | H | 2020-01-01 00:00:00+00:00 | 2026-09-03 00:00:00+00:00 | 35 | 70 | 475319.8507704765 | 4.176025145952262 | 21 | 67.73529411764706 | 7.0 |
| COVID_2020 | B | 2020-02-15 00:00:00+00:00 | 2020-04-30 00:00:00+00:00 | 5 | 10 | 9960.967044817504 | 0.41459155094715633 | 2 | 9.0 | 9.5 |
| COVID_2020 | H | 2020-02-15 00:00:00+00:00 | 2020-04-30 00:00:00+00:00 | 2 | 4 | 3796.8738591857195 | 0.16072673408902147 | 0 | 14.0 | 14.0 |
| MAY_2021 | B | 2021-05-01 00:00:00+00:00 | 2021-06-30 00:00:00+00:00 | 0 | 0 | 0.0 | 0.0 | 0 | nan | nan |
| MAY_2021 | H | 2021-05-01 00:00:00+00:00 | 2021-06-30 00:00:00+00:00 | 0 | 0 | 0.0 | 0.0 | 0 | nan | nan |
| BEAR_2021NOV_2022JUN | B | 2021-11-01 00:00:00+00:00 | 2022-06-30 00:00:00+00:00 | 5 | 10 | 104362.39459802245 | 0.597776728146329 | 4 | 3.0 | 2.0 |
| BEAR_2021NOV_2022JUN | H | 2021-11-01 00:00:00+00:00 | 2022-06-30 00:00:00+00:00 | 2 | 4 | 27567.26440477735 | 0.3118596993985961 | 1 | 7.0 | 7.0 |
| BOTTOM_2022 | B | 2022-06-01 00:00:00+00:00 | 2022-07-31 00:00:00+00:00 | 12 | 24 | 251957.03897094546 | 1.6059011515992843 | 10 | 4.0 | 3.0 |
| BOTTOM_2022 | H | 2022-06-01 00:00:00+00:00 | 2022-07-31 00:00:00+00:00 | 4 | 8 | 41675.421681947526 | 0.521077313659695 | 3 | 7.0 | 7.0 |
| FTX_2022 | B | 2022-11-01 00:00:00+00:00 | 2022-12-31 00:00:00+00:00 | 13 | 26 | 203828.16140422827 | 1.2807790867221258 | 12 | 4.0 | 4.0 |
| FTX_2022 | H | 2022-11-01 00:00:00+00:00 | 2022-12-31 00:00:00+00:00 | 7 | 14 | 71664.29423841604 | 0.9023950561139973 | 4 | 7.0 | 7.0 |
| BULL_2023_2025 | B | 2023-01-01 00:00:00+00:00 | 2025-12-31 00:00:00+00:00 | 2 | 4 | 31068.02822395361 | 0.1100711284310903 | 2 | 1.0 | 1.0 |
| BULL_2023_2025 | H | 2023-01-01 00:00:00+00:00 | 2025-12-31 00:00:00+00:00 | 1 | 2 | 8056.772265536124 | 0.05407553640858233 | 1 | nan | nan |
| BOTTOM_2026 | B | 2026-02-01 00:00:00+00:00 | 2026-06-30 00:00:00+00:00 | 22 | 44 | 783490.0829323701 | 2.4217524399963914 | 19 | 6.857142857142857 | 7.0 |
| BOTTOM_2026 | H | 2026-02-01 00:00:00+00:00 | 2026-06-30 00:00:00+00:00 | 12 | 24 | 271788.47154817294 | 1.5564391641154154 | 6 | 11.909090909090908 | 7.0 |
| CORRECTION_2025_2026 | B | 2025-01-01 00:00:00+00:00 | 2026-09-03 00:00:00+00:00 | 22 | 44 | 783490.0829323701 | 2.267009406001222 | 19 | 6.857142857142857 | 7.0 |
| CORRECTION_2025_2026 | H | 2025-01-01 00:00:00+00:00 | 2026-09-03 00:00:00+00:00 | 13 | 26 | 288765.7723859029 | 1.5491972534159133 | 6 | 12.166666666666666 | 7.0 |

## Event drawdown audit

| event | model | start | end | peak_to_trough_drawdown | average_crypto_exposure | minimum_crypto_exposure | tactical_event_count | tactical_notional_usd |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| COVID_2020 | B | 2020-02-15 00:00:00+00:00 | 2020-04-30 00:00:00+00:00 | -0.3733619544227105 | 0.5384205640736094 | 0.23854194653680644 | 8 | 18483.630831970095 |
| COVID_2020 | H | 2020-02-15 00:00:00+00:00 | 2020-04-30 00:00:00+00:00 | -0.3733619544227105 | 0.430253123967319 | 0.23854194653680644 | 6 | 13467.856443245291 |
| MAY_2021 | B | 2021-05-01 00:00:00+00:00 | 2021-06-30 00:00:00+00:00 | -0.33199475484147967 | 0.40780802488493134 | 0.18728375395373087 | 3 | 72534.05073035802 |
| MAY_2021 | H | 2021-05-01 00:00:00+00:00 | 2021-06-30 00:00:00+00:00 | -0.29081386984502566 | 0.3670537232974662 | 0.18955601110808834 | 1 | 22183.248639330308 |
| BEAR_2021NOV_2022JUN | B | 2021-11-01 00:00:00+00:00 | 2022-06-30 00:00:00+00:00 | -0.2824518654215672 | 0.24788935686998134 | 0.10343867939427827 | 6 | 119362.07314227082 |
| BEAR_2021NOV_2022JUN | H | 2021-11-01 00:00:00+00:00 | 2022-06-30 00:00:00+00:00 | -0.26460452675671764 | 0.24546263271779398 | 0.09334531376534971 | 3 | 36018.39212201199 |
| BOTTOM_2022 | B | 2022-06-01 00:00:00+00:00 | 2022-07-31 00:00:00+00:00 | -0.10019537943014678 | 0.3296186432938243 | 0.10343867939427827 | 12 | 251957.03897094546 |
| BOTTOM_2022 | H | 2022-06-01 00:00:00+00:00 | 2022-07-31 00:00:00+00:00 | -0.07779597970147034 | 0.2444176949386254 | 0.09334531376534971 | 4 | 41675.421681947526 |
| FTX_2022 | B | 2022-11-01 00:00:00+00:00 | 2022-12-31 00:00:00+00:00 | -0.1012713483189156 | 0.3264793406069617 | 0.2448121176543158 | 13 | 203828.16140422827 |
| FTX_2022 | H | 2022-11-01 00:00:00+00:00 | 2022-12-31 00:00:00+00:00 | -0.09103228761656224 | 0.31638342538911224 | 0.22285802616052486 | 7 | 71664.29423841604 |
| BULL_2023_2025 | B | 2023-01-01 00:00:00+00:00 | 2025-12-31 00:00:00+00:00 | -0.2333515820247538 | 0.5754174966243882 | 0.24589928162394076 | 18 | 353827.4150019476 |
| BULL_2023_2025 | H | 2023-01-01 00:00:00+00:00 | 2025-12-31 00:00:00+00:00 | -0.22745287208025422 | 0.5853745232161935 | 0.2459388063024065 | 18 | 182878.25062848837 |
| BOTTOM_2026 | B | 2026-02-01 00:00:00+00:00 | 2026-06-30 00:00:00+00:00 | -0.09203993009717393 | 0.3098144364365636 | 0.19168970151055392 | 22 | 783490.08293237 |
| BOTTOM_2026 | H | 2026-02-01 00:00:00+00:00 | 2026-06-30 00:00:00+00:00 | -0.08100458409577349 | 0.300293323182768 | 0.19521842543471388 | 12 | 271788.47154817294 |
| CORRECTION_2025_2026 | B | 2025-01-01 00:00:00+00:00 | 2026-09-03 00:00:00+00:00 | -0.2823700239088045 | 0.4398120305367679 | 0.19168970151055392 | 23 | 874608.3581044131 |
| CORRECTION_2025_2026 | H | 2025-01-01 00:00:00+00:00 | 2026-09-03 00:00:00+00:00 | -0.2768775703130607 | 0.44809575441180743 | 0.19521842543471388 | 14 | 342163.5355154099 |

## Interpretation and bias limits

- This is one realized crypto path, not an independent out-of-sample discovery. The patch was frozen before the formal run, but historical regime knowledge can still influence the research question.

- Model H differs from Model B in both the isolated buy-frequency guard and the explicitly requested DCA-first within-bar order. Because DCA trades are tiny, the row ledger is identical, but attribution should still acknowledge this execution-order difference.
- The requested 20-day-low field is used only to block/rearm buys. It never changes V3.1 macro classification, crash logic, risk sells or targets.
- Fees, slippage and minimum-notional assumptions are modeled constants. Liquidity, spread tails, taxes, custody risk and exchange failure are outside this backtest.
- Promotion means forward paper testing only, not permission to deploy live capital. No failed gate was repaired by changing a threshold after the run.
