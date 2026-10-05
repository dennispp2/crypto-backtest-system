# BTC+ETH Macro Hedge V3.4 FINAL — Formal Backtest Report

**Final Verdict: B. V3.1 REMAINS CHAMPION**

This was one frozen-parameter run. No result-aware threshold search was performed, and promotion gates were evaluated only after simulation.

## Headline performance

| model | strategy                                               | start                     | end                       | initial_capital | external_contributions_after_inception | total_invested_capital | final_portfolio_value | xirr                | twr_cagr            | maximum_drawdown    | peak_date                 | trough_date               | recovery_date             | dd_duration_days   | sharpe             | sortino            | calmar             | average_crypto_exposure | median_crypto_exposure | average_tactical_cash | average_tactical_cash_ratio | median_tactical_cash_ratio | ending_tactical_cash | ending_tactical_bear_cash | ending_temporary_hedge_cash | material_tactical_cash_time | tactical_turnover | tactical_trade_count | tactical_event_count | total_trade_count | fees               | slippage           | total_trading_costs | tactical_fees      | tactical_slippage  | tactical_costs     | total_capital_supplied | net_profit         | median_tactical_cash | confirmed_cycle_count | longest_cycle_duration_days | crash_level3_count | macro_bull_requalification_count | final_cash_sweep_count |
| ----- | ------------------------------------------------------ | ------------------------- | ------------------------- | --------------- | -------------------------------------- | ---------------------- | --------------------- | ------------------- | ------------------- | ------------------- | ------------------------- | ------------------------- | ------------------------- | ------------------ | ------------------ | ------------------ | ------------------ | ----------------------- | ---------------------- | --------------------- | --------------------------- | -------------------------- | -------------------- | ------------------------- | --------------------------- | --------------------------- | ----------------- | -------------------- | -------------------- | ----------------- | ------------------ | ------------------ | ------------------- | ------------------ | ------------------ | ------------------ | ---------------------- | ------------------ | -------------------- | --------------------- | --------------------------- | ------------------ | -------------------------------- | ---------------------- |
| H0    | H0 Initial Only - No DCA / No Trading                  | 2020-01-01 00:00:00+00:00 | 2026-09-03 04:00:00+00:00 | 20000.0         | 0.0                                    | 20000.0                | 197656.92532693208    | 0.4096121579054236  | 0.40961215790538374 | -0.772206462898925  | 2021-11-10 12:00:00+00:00 | 2022-06-18 16:00:00+00:00 | 2024-12-05 00:00:00+00:00 | 1120.5             | 0.8638461204256458 | 0.8381583518035132 | 0.5304438354059701 | 0.9354813306534269      | 0.9621005410951023     | 0.0                   | 0.0                         | 0.0                        | 0.0                  | 0.0                       | 0.0                         | 0.0                         | 0.0               | 0                    | 0                    | 2                 | 13.986013986013988 | 6.98951223688827   | 20.97552622290226   | 0.0                | 0.0                | 0.0                | 20000.0                | 177656.92532693208 | 0.0                  | 0                     | 0.0                         | 0                  | 0                                | 0                      |
| A     | MODEL A - BTC+ETH Fixed DCA                            | 2020-01-01 00:00:00+00:00 | 2026-09-03 04:00:00+00:00 | 20000.0         | 29248.0                                | 49248.0                | 279201.223366351      | 0.3838680921371841  | 0.4249976470925976  | -0.7686904739305493 | 2021-11-10 12:00:00+00:00 | 2022-06-18 16:00:00+00:00 | 2024-11-21 20:00:00+00:00 | 1107.3333333333333 | 0.8858696964901264 | 0.8592908785521536 | 0.5528852789334759 | 0.9439856743715443      | 0.9690425216890647     | 0.0                   | 0.0                         | 0.0                        | 0.0                  | 0.0                       | 0.0                         | 0.0                         | 0.0               | 0                    | 0                    | 4975              | 43.200049950049944 | 21.589230359843167 | 64.78928030989314   | 0.0                | 0.0                | 0.0                | 49248.0                | 229953.22336635098 | 0.0                  | 0                     | 0.0                         | 0                  | 0                                | 0                      |
| B     | MODEL B - BTC+ETH Fixed DCA + V3.1 FSM Frozen Champion | 2020-01-01 00:00:00+00:00 | 2026-09-03 04:00:00+00:00 | 20000.0         | 29248.0                                | 49248.0                | 348746.8528777533     | 0.4371684768710826  | 0.4769146261923145  | -0.3951313419600695 | 2020-02-14 20:00:00+00:00 | 2020-03-16 08:00:00+00:00 | 2020-07-27 00:00:00+00:00 | 163.16666666666666 | 1.249388659779247  | 1.2136451248176452 | 1.2069774668507813 | 0.515041507854678       | 0.5608060399316342     | 103052.38995137413    | 0.4323055873252319          | 0.4119091819955568         | 195453.08651958118   | 195453.08651958118        | 0.0                         | 0.9623196334541476          | 9.367689873226654 | 212                  | 106                  | 5187              | 2047.5985458111043 | 1023.8380932237421 | 3071.4366390348464  | 2004.3984958610545 | 1002.2488628638989 | 3006.6473587249534 | 49248.0                | 299498.8528777533  | 115289.30549376445   | 3                     | 1275.0                      | 0                  | 0                                | 0                      |
| F     | MODEL F - BTC+ETH Fixed DCA + V3.4 FINAL Challenger    | 2020-01-01 00:00:00+00:00 | 2026-09-03 04:00:00+00:00 | 20000.0         | 29248.0                                | 49248.0                | 211481.0895336187     | 0.31900645813467887 | 0.3628172128463587  | -0.5836885615856346 | 2025-10-06 16:00:00+00:00 | 2026-06-30 12:00:00+00:00 | NaT                       | 331.5              | 0.9113528868452136 | 0.876329734897652  | 0.6215938374066095 | 0.7020385048240317      | 0.7359757088457782     | 34618.98784510592     | 0.23785874788692096         | 0.13399652290710987        | 1758.2290673859725   | 1758.2290673859725        | 0.0                         | 0.9095944744580455          | 8.498845322868728 | 270                  | 135                  | 5245              | 1412.0457415322464 | 706.0130290254947  | 2118.0587705577414  | 1368.8456915821967 | 684.4237986656516  | 2053.269490247848  | 49248.0                | 162233.0895336187  | 6935.149516795969    | 6                     | 919.0                       | 1                  | 4                                | 9                      |

## Direct answers

1. H0 final: US$197,656.93.
2. A Fixed DCA final: US$279,201.22.
3. B V3.1 final: US$348,746.85.
4. F V3.4 final: US$211,481.09.
5. Max DD — H0: -77.22%, A: -76.87%, B: -39.51%, F: -58.37%.
6. V3.4 within 30%: NO.
7. V3.4 maximum drawdown: 2025-10-06 to 2026-06-30, -58.37%.
8. COVID DD — B: -37.34%; F: -37.34%.
9. 2021 May DD — B: -33.20%; F: -33.20%.
10. 2021-Nov to 2022-Jun F DD: -50.67%; normal-bear gate FAIL.
11. Crash L3 triggers: 1.
12. Crash false positives: 0.
13. Macro Bull Requalifications: 4.
14. 2023-2025 F average exposure: 78.08%.
15. Exposure improvement vs B: 19.24 percentage points.
16. First F NEW_BULL: days to 85/90/95 = 236 / 271 / 564.0.
17. Longest F cycle: 919 days.
18. Missed multi-year macro bull remains: YES.
19. Final Cash Sweep cash reset <=1%: YES.
20. F material tactical cash time: 90.96%.
21. State churn: B 223, F 18, reduction 91.93%.
22. F tactical turnover: 8.4988x.
23. CAGR >=45%: NO (36.28%).
24. Calmar >=1.5: NO (0.622).
25. Crash protection + normal-bear preservation + bull participation + cash reset all achieved: NO.
26. Replace V3.1 for forward paper test: NO.

## F vs B deltas

| comparison       | delta_final_value  | delta_cagr_percentage_points | delta_max_drawdown_percentage_points | delta_calmar        | delta_material_tactical_cash_time_percentage_points | delta_tactical_turnover | delta_covid_dd_percentage_points | delta_may_dd_percentage_points | delta_2022_bear_dd_percentage_points | delta_2023_2025_average_exposure_percentage_points | delta_2025_2026_correction_dd_percentage_points | delta_state_churn_count | state_churn_reduction_fraction | delta_longest_cycle_duration_days |
| ---------------- | ------------------ | ---------------------------- | ------------------------------------ | ------------------- | --------------------------------------------------- | ----------------------- | -------------------------------- | ------------------------------ | ------------------------------------ | -------------------------------------------------- | ----------------------------------------------- | ----------------------- | ------------------------------ | --------------------------------- |
| F V3.4 vs B V3.1 | -137265.7633441346 | -11.40974133459558           | -18.855721962556515                  | -0.5853836294441719 | -5.272515899610209                                  | -0.8688445503579256     | 0.0                              | 0.0                            | -22.424421701920238                  | 19.243786302569678                                 | -29.68398496676503                              | -205                    | 0.9192825112107623             | -356.0                            |

## Promotion gates

| gate                               | pass  |
| ---------------------------------- | ----- |
| maximum_drawdown_gte_minus_0_30    | False |
| twr_cagr_gte_0_45                  | False |
| calmar_gte_1_50                    | False |
| final_value_gte_95pct_of_v31_b     | False |
| normal_bear_regression_lte_2pp     | False |
| bull_participation_pass            | False |
| cash_reset_pass                    | True  |
| state_churn_reduced_at_least_50pct | True  |
| tactical_turnover_lte_9_8361       | True  |
| no_lookahead_pass                  | True  |
| execution_integrity_pass           | True  |
| fsm_audit_pass                     | True  |
| cash_reset_audit_pass              | True  |

## Crash L3 audit

| model | lot_id | crash_episode_id | level3_trigger_date       | btc_close_at_trigger | pre_crash_macro_target | exposure_before_level3 | exposure_after_level3 | level3_action_outcome           | crash_cash_original | crash_cash_remaining | recovery_confirmed_date | unwind_completed_date | status                                  | closure_reason         |
| ----- | ------ | ---------------- | ------------------------- | -------------------- | ---------------------- | ---------------------- | --------------------- | ------------------------------- | ------------------- | -------------------- | ----------------------- | --------------------- | --------------------------------------- | ---------------------- |
| F     | nan    | 1                | 2020-03-12 00:00:00+00:00 | 4800.0               | 0.25                   | 0.3959048111316347     | 0.25000000000000006   | EXPOSURE_ALREADY_AT_OR_BELOW_35 | 0.0                 | 0.0                  | NaT                     | NaT                   | NO_SELL_EXPOSURE_ALREADY_AT_OR_BELOW_35 | NO_LEVEL3_CASH_CREATED |

## Macro Bull Requalification audit

| model | candidate_date            | macro_bear_invalidated_date | new_bull_confirmed_date   | candidate_to_invalidated_days | invalidated_to_new_bull_days | within_60d_below_sma200 | within_60d_drawdown_gte_20pct | potential_false_bull_requalification |
| ----- | ------------------------- | --------------------------- | ------------------------- | ----------------------------- | ---------------------------- | ----------------------- | ----------------------------- | ------------------------------------ |
| F     | 2021-11-02 00:00:00+00:00 | 2021-11-07 00:00:00+00:00   | 2021-11-12 00:00:00+00:00 | 5                             | 5                            | True                    | True                          | True                                 |
| F     | 2023-03-14 00:00:00+00:00 | 2023-03-19 00:00:00+00:00   | 2023-03-24 00:00:00+00:00 | 5                             | 5                            | False                   | False                         | False                                |
| F     | 2023-11-09 00:00:00+00:00 | 2023-11-14 00:00:00+00:00   | 2023-11-19 00:00:00+00:00 | 5                             | 5                            | False                   | False                         | False                                |
| F     | 2024-11-07 00:00:00+00:00 | 2024-11-12 00:00:00+00:00   | 2024-11-17 00:00:00+00:00 | 5                             | 5                            | False                   | False                         | False                                |

## Bull participation

| model | cycle_id | new_bull_date             | new_bull_path                       | exposure_5d        | crash_l2_l3_within_5d | exposure_10d       | crash_l2_l3_within_10d | exposure_20d       | crash_l2_l3_within_20d | exposure_30d       | crash_l2_l3_within_30d | first_85_date             | days_to_85 | first_90_date             | days_to_90 | first_95_date             | days_to_95 | gate_10d_85_pass | gate_20d_90_pass |
| ----- | -------- | ------------------------- | ----------------------------------- | ------------------ | --------------------- | ------------------ | ---------------------- | ------------------ | ---------------------- | ------------------ | ---------------------- | ------------------------- | ---------- | ------------------------- | ---------- | ------------------------- | ---------- | ---------------- | ---------------- |
| B     | 1        | 2020-05-08 00:00:00+00:00 | NEW_BULL_ALL_SEVEN_GATES            | 0.7107279642773889 | False                 | 0.7867074875043605 | False                  | 0.7877156814927744 | False                  | 0.7975596607255669 | False                  | 2020-12-30 00:00:00+00:00 | 236        | 2021-02-03 00:00:00+00:00 | 271        | NaT                       | nan        | False            | False            |
| B     | 2        | 2023-01-27 00:00:00+00:00 | NEW_BULL_ALL_SEVEN_GATES            | 0.6993332221875157 | False                 | 0.9108476020068933 | False                  | 0.9128607961798814 | False                  | 0.9130636517003787 | False                  | 2023-02-04 00:00:00+00:00 | 8          | 2023-02-05 00:00:00+00:00 | 9          | NaT                       | nan        | True             | True             |
| F     | 1        | 2020-05-08 00:00:00+00:00 | NEW_BULL_ALL_SEVEN_GATES            | 0.7107279642773889 | False                 | 0.7867074875043605 | False                  | 0.7877156814927744 | False                  | 0.7975596607255669 | False                  | 2020-12-30 00:00:00+00:00 | 236        | 2021-02-03 00:00:00+00:00 | 271        | 2021-11-23 00:00:00+00:00 | 564.0      | False            | False            |
| F     | 2        | 2021-11-12 00:00:00+00:00 | MACRO_BULL_REQUALIFICATION_NEW_BULL | 0.6591297510846509 | False                 | 0.9480057255551197 | False                  | 0.9510219400542801 | False                  | 0.9461655755442704 | False                  | 2021-11-21 00:00:00+00:00 | 9          | 2021-11-21 00:00:00+00:00 | 9          | 2021-11-23 00:00:00+00:00 | 11.0       | True             | True             |
| F     | 3        | 2023-01-27 00:00:00+00:00 | NEW_BULL_ALL_SEVEN_GATES            | 0.6921707621957941 | False                 | 0.9496280525563096 | False                  | 0.9508150926085932 | False                  | 0.9509470090107889 | False                  | 2023-02-05 00:00:00+00:00 | 9          | 2023-02-06 00:00:00+00:00 | 10         | 2023-02-07 00:00:00+00:00 | 11.0       | True             | True             |
| F     | 4        | 2023-03-24 00:00:00+00:00 | MACRO_BULL_REQUALIFICATION_NEW_BULL | 0.7850306236029745 | False                 | 0.9498794234493847 | False                  | 0.9543218490812329 | False                  | 0.950406702199626  | False                  | 2023-03-31 00:00:00+00:00 | 7          | 2023-04-02 00:00:00+00:00 | 9          | 2023-04-04 00:00:00+00:00 | 11.0       | True             | True             |
| F     | 5        | 2023-11-19 00:00:00+00:00 | MACRO_BULL_REQUALIFICATION_NEW_BULL | 0.7939210592139421 | False                 | 0.9498446084276733 | False                  | 0.9562866933402716 | False                  | 0.9541798879891907 | False                  | 2023-11-26 00:00:00+00:00 | 7          | 2023-11-28 00:00:00+00:00 | 9          | 2023-12-01 00:00:00+00:00 | 12.0       | True             | True             |
| F     | 6        | 2024-11-17 00:00:00+00:00 | MACRO_BULL_REQUALIFICATION_NEW_BULL | 0.8114398593649221 | False                 | 0.9528781999660756 | False                  | 0.9555348657377842 | False                  | 0.956662475714701  | False                  | 2024-11-24 00:00:00+00:00 | 7          | 2024-11-25 00:00:00+00:00 | 8          | 2024-11-27 00:00:00+00:00 | 10.0       | True             | True             |

## Cash reset

| model | cycle_id | start                     | end                       | status             | new_bull_date             | bull_date                 | final_cash_sweep_date     | final_cash_sweep_spent | cash_reset_audit | cash_reset_reason                        | tactical_bear_cash_ratio_at_close | cycle_closed |
| ----- | -------- | ------------------------- | ------------------------- | ------------------ | ------------------------- | ------------------------- | ------------------------- | ---------------------- | ---------------- | ---------------------------------------- | --------------------------------- | ------------ |
| F     | 1        | 2020-02-20 00:00:00+00:00 | 2020-05-17 00:00:00+00:00 | COMPLETED_NEW_BULL | 2020-05-08 00:00:00+00:00 | 2020-05-17 00:00:00+00:00 | NaT                       | 0.0                    | PASS             | TACTICAL_BEAR_CASH_AT_OR_BELOW_1_PERCENT | 0.0                               | True         |
| F     | 2        | 2020-06-16 00:00:00+00:00 | 2022-01-21 00:00:00+00:00 | COMPLETED_NEW_BULL | 2021-11-12 00:00:00+00:00 | 2022-01-21 00:00:00+00:00 | 2022-01-21 00:00:00+00:00 | 11622.522390634895     | PASS             | TACTICAL_BEAR_CASH_AT_OR_BELOW_1_PERCENT | 0.0                               | True         |
| F     | 3        | 2022-02-20 00:00:00+00:00 | 2023-02-05 00:00:00+00:00 | COMPLETED_NEW_BULL | 2023-01-27 00:00:00+00:00 | 2023-02-05 00:00:00+00:00 | NaT                       | 0.0                    | PASS             | TACTICAL_BEAR_CASH_AT_OR_BELOW_1_PERCENT | 0.0014696204619737674             | True         |
| F     | 4        | 2023-03-07 00:00:00+00:00 | 2023-04-02 00:00:00+00:00 | COMPLETED_NEW_BULL | 2023-03-24 00:00:00+00:00 | 2023-04-02 00:00:00+00:00 | 2023-04-02 00:00:00+00:00 | 3893.174095816635      | PASS             | TACTICAL_BEAR_CASH_AT_OR_BELOW_1_PERCENT | 0.004705454739789999              | True         |
| F     | 5        | 2023-05-09 00:00:00+00:00 | 2023-12-04 00:00:00+00:00 | COMPLETED_NEW_BULL | 2023-11-19 00:00:00+00:00 | 2023-12-04 00:00:00+00:00 | 2023-11-28 00:00:00+00:00 | 3490.980159878652      | PASS             | TACTICAL_BEAR_CASH_AT_OR_BELOW_1_PERCENT | 0.009689397842785588              | True         |
| F     | 6        | 2024-01-14 00:00:00+00:00 | 2026-07-21 00:00:00+00:00 | COMPLETED_NEW_BULL | 2024-11-17 00:00:00+00:00 | 2026-07-21 00:00:00+00:00 | 2026-06-28 00:00:00+00:00 | 57445.67806365103      | PASS             | TACTICAL_BEAR_CASH_AT_OR_BELOW_1_PERCENT | 0.009873590540853565              | True         |

## Integrity

- NO_LOOK_AHEAD: PASS
- EXECUTION_INTEGRITY: PASS
- CASH_RESET_AUDIT: PASS

## J Law decision matrix

- Champion: V3.1 B before evaluation; challenger: V3.4 F.
- Return Edge: delta final US$-137,265.76; delta CAGR -11.41 pp.
- Drawdown Edge: delta Max DD -18.86 pp.
- COVID Protection: 0.00 pp.
- May Crash Protection: 0.00 pp.
- Normal Bear Protection: FAIL.
- Bull Requalification Quality: 4 candidate episode(s), 4 confirmed.
- Bull Participation: FAIL.
- Cash Reset Quality: PASS.
- Cycle Duration Quality: longest 919 days; missed macro bull YES.
- State Stability: PASS.
- Turnover: PASS.
- Execution Integrity: PASS.
- Overfit Risk: rules were frozen before the single formal run; nevertheless all thresholds remain historical hypotheses requiring forward validation.
- Final Verdict: B. V3.1 REMAINS CHAMPION
