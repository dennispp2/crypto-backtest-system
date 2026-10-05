# BTC+ETH V3.1 Tactical Event / Round-Trip Necessity Audit

## Research-only verdict

**C. V3.1 CONTAINS MATERIAL HARMFUL TRADING**

- `BASELINE_INTEGRITY = PASS`
- `V31_BASELINE_REPLAY = PASS`
- `FIXED_DCA_ROW_INTEGRITY = PASS`
- `FROZEN_SHADOW_HISTORY = PASS`
- `NO_LOOK_AHEAD = PASS`
- This is diagnostic attribution only. It is not V3.9 and no trading rule was changed.

## Baseline replay

| model | strategy | start | end | initial_capital | external_contributions_after_inception | total_invested_capital | final_portfolio_value | xirr | twr_cagr | maximum_drawdown | peak_date | trough_date | recovery_date | dd_duration_days | sharpe | sortino | calmar | average_crypto_exposure | median_crypto_exposure | average_tactical_cash | average_tactical_cash_ratio | median_tactical_cash_ratio | ending_tactical_cash | ending_tactical_bear_cash | ending_temporary_hedge_cash | material_tactical_cash_time | tactical_turnover | tactical_trade_count | tactical_event_count | total_trade_count | fees | slippage | total_trading_costs | tactical_fees | tactical_slippage | tactical_costs | V31_BASELINE_REPLAY | independent_zero_deletion_replay | zero_replay_max_metric_delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B | MODEL B - BTC+ETH Fixed DCA + V3.1 FSM | 2020-01-01 00:00:00+00:00 | 2026-09-03 04:00:00+00:00 | 20000.0 | 29248.0 | 49248.0 | 348746.8528777533 | 0.4371684768710826 | 0.4769146261923145 | -0.3951313419600695 | 2020-02-14 20:00:00+00:00 | 2020-03-16 08:00:00+00:00 | 2020-07-27 00:00:00+00:00 | 163.16666666666666 | 1.249388659779247 | 1.2136451248176452 | 1.2069774668507811 | 0.515041507854678 | 0.5608060399316342 | 103052.38995137412 | 0.4323055873252319 | 0.4119091819955568 | 195453.0865195812 | 195453.0865195812 | 0.0 | 0.9623196334541476 | 9.367689873226654 | 212 | 106 | 5187 | 2047.5985458111045 | 1023.838093223742 | 3071.4366390348464 | 2004.3984958610545 | 1002.2488628638988 | 3006.6473587249534 | PASS | PASS | 0.0 |

## Event classification counts

| classification | events |
| --- | --- |
| REDUNDANT | 49 |
| MIXED_UNCERTAIN | 25 |
| HARMFUL | 14 |
| RISK_ESSENTIAL | 11 |
| RETURN_ESSENTIAL | 7 |

The formal verdict uses the pre-frozen **Base** labels. Sensitivity disagreement is material and must not be hidden:

| sensitivity | classification | events |
| --- | --- | --- |
| LOOSE | REDUNDANT | 46 |
| LOOSE | HARMFUL | 24 |
| LOOSE | RISK_ESSENTIAL | 15 |
| LOOSE | RETURN_ESSENTIAL | 11 |
| LOOSE | MIXED_UNCERTAIN | 10 |
| BASE | REDUNDANT | 49 |
| BASE | MIXED_UNCERTAIN | 25 |
| BASE | HARMFUL | 14 |
| BASE | RISK_ESSENTIAL | 11 |
| BASE | RETURN_ESSENTIAL | 7 |
| STRICT | MIXED_UNCERTAIN | 62 |
| STRICT | REDUNDANT | 27 |
| STRICT | RISK_ESSENTIAL | 7 |
| STRICT | RETURN_ESSENTIAL | 5 |
| STRICT | HARMFUL | 5 |

Robust classifications (same label under Loose/Base/Strict):

| classification | robust_events |
| --- | --- |
| REDUNDANT | 27 |
| MIXED_UNCERTAIN | 10 |
| RISK_ESSENTIAL | 7 |
| HARMFUL | 5 |
| RETURN_ESSENTIAL | 4 |

## 2022 and 2026 audit windows

| window | events | RETURN_ESSENTIAL | RISK_ESSENTIAL | REDUNDANT | HARMFUL | MIXED_UNCERTAIN | positive_raw_contribution |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BOTTOM_2022 | 41 | 2 | 3 | 21 | 9 | 6 | 20 |
| BOTTOM_2026 | 22 | 2 | 2 | 8 | 4 | 6 | 13 |

## AHR999 overall attribution

| events | positive_raw | negative_raw | median_final_contribution | mean_final_contribution | median_btc_forward_30d | median_btc_forward_60d | median_overall_dd_protection_pp | forward_data_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 34 | 17 | 17 | -16.859777637117084 | 684.7033262369788 | 0.0377349958651849 | 0.1124133264497352 | 0.0 | EX_POST_DIAGNOSTIC_ONLY |

Environment slices (hypothesis generation only):

| ahr_environment | events | positive_fraction | median_final_contribution | mean_final_contribution | median_btc_forward_3d | median_btc_forward_30d |
| --- | --- | --- | --- | --- | --- | --- |
| ABOVE_SMA20_NOT_NEAR_LOW | 3 | 0.0 | -761.6513818572857 | -606.2321352233024 | -0.005163194990911 | 0.0045675110597056 |
| BELOW_SMA20_FALLING | 27 | 0.5555555555555556 | 84.34097250871127 | 1083.6868566325716 | 0.0016907833040338 | 0.0457733131159969 |
| BELOW_SMA20_NOT_FALLING | 4 | 0.5 | -693.3416874249815 | -1040.233907838061 | -0.0023342892887489998 | 0.013076241401431703 |

## Cross-period structural reading

- AHR attribution is heavy-tailed: its median and mean point in different directions. Therefore neither "AHR always has alpha" nor "AHR is useless" is supported.
- The short-whipsaw groups retain slightly more than half positive raw contributions. Short spacing alone is not a sufficient historical discriminator.
- Risk-sell effects are dispersed: some events protect local/overall drawdown while several improve ending wealth when deleted. Signal name alone is not enough.
- The largest pair interaction is reported as a fraction of baseline wealth. This path dependence is why isolated rankings must not become a deletion rule.
- Environment cell sizes are shown explicitly. Small cells are weak hypothesis evidence, not a basis for a new threshold.

## Direct answers

1. V3.1 Baseline完整重現：是，PASS。
2. 以Base的±0.25% materiality band計，正貢獻 30、負貢獻 23、接近0為 53（raw符號與數值均保留於CSV）。
3. RETURN_ESSENTIAL：7。
4. RISK_ESSENTIAL：11。
5. REDUNDANT：49。
6. HARMFUL：14。
7. MIXED / UNCERTAIN：25。
8. 2022底部窗口中的robust redundant clusters：0。
9. 2026底部窗口中的robust redundant clusters：0。
10. 2022窗口 41 個Events中有 20 個正raw貢獻；2026窗口 22 個中有 13 個。
11. AHR999 Value Buy為混合結果：17/34 筆正raw貢獻；中位數 US$-16.86，平均 US$684.70。平均為正但由尾部大贏家拉高，不能概括成每筆都有alpha。
12. AHR Buy歷史平均貢獻最佳環境：BELOW_SMA20_FALLING。這是事後假說，不是規則。
13. AHR Buy三日負報酬比例最高環境：ABOVE_SMA20_NOT_NEAR_LOW。這是事後假說，不是規則。
14. 真正達Base Risk Essential的Risk Sell event IDs：2, 22, 25, 27, 37, 53, 79, 83, 84, 93, 97。
15. DD影響≤0.25pp但刪除後Final提高的Risk Sell IDs：19, 20, 23, 31, 39, 45, 51, 57, 59, 61, 63, 65, 80, 81, 82, 86, 88, 101。
16. Right-side Buy中位Final貢獻：US$1,186.65。
17. NEW_BULL Redeploy中位Final貢獻：US$112.41。
18. 3_COMPLETED_CLOSES短期反向交易多數沒價值？否；count=59, positive fraction=52.5%, median contribution=US$84.34。
19. 7_CALENDAR_DAYS短期反向交易多數沒價值？否；count=68, positive fraction=54.4%, median contribution=US$131.33。
20. 14_CALENDAR_DAYS短期反向交易多數沒價值？否；count=68, positive fraction=54.4%, median contribution=US$131.33。
21. 最有價值Top 10 Event IDs：84, 2, 25, 37, 68, 106, 22, 7, 34, 28。
22. 最低貢獻Top 10 Event IDs：24, 80, 20, 82, 81, 26, 21, 3, 19, 54。
23. 高turnover/低絕對貢獻Cluster IDs：12, 19, 11, 21, 20, 14, 15, 1, 13, 10。
24. Robust Redundant basket理論刪除 9 個Event，來自 5 個clusters。
25. 理論可減少tactical turnover 0.0473x。
26. 該basket DD contribution為 +0.000pp；是否近似不變依Base 0.25pp門檻為 是。
27. 該basket Final contribution為 US$1,177.79（+0.34%）；是否近似不變依Base 0.25%門檻為 否。
28. 對106次操作的整體判斷：C. V3.1 CONTAINS MATERIAL HARMFUL TRADING。
29. 是否繼續研究降低頻率：是，但只能另立前瞻、預先凍結的結構假說。
30. 是否接受部分高頻熊底AHR有經濟價值：是；但並非每筆都有效。

## Signal-type contribution

| signal_type | count | median_final_contribution | mean_final_contribution | median_local_30d_contribution | median_turnover_saved | median_cost_saved | positive_contribution_fraction | negative_contribution_fraction | median_dd_protection_pp | robust_classification_fraction |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AHR_VALUE_BUY | 34 | -16.859777637117077 | 684.7033262369788 | 41.5794169951696 | 0.1494703372047867 | 50.638048724981445 | 0.5 | 0.5 | 0.0 | 0.4411764705882353 |
| BEARISH_REBREAK_SELL | 31 | 184.7177663606126 | 1292.3610186309295 | 72.182858302549 | 0.1546004000484977 | 57.802936135307846 | 0.6129032258064516 | 0.3870967741935484 | 0.0 | 0.3225806451612903 |
| CRASH_SELL | 1 | -1937.9777432577685 | -1937.9777432577685 | -981.8179994130332 | -0.0035572020412555 | -17.550140095528604 | 0.0 | 1.0 | 0.0 | 1.0 |
| NEW_BULL_REDEPLOY | 19 | 112.40826459461825 | 12.468875754857436 | 11.09356897186808 | 0.0035280696250268 | 2.649556671043229 | 0.5789473684210527 | 0.4210526315789473 | 0.0 | 0.6842105263157895 |
| OTHER_RISK_SELL | 3 | -13300.761497743952 | -8059.796661591022 | -2334.182926937996 | 0.035339446679167 | -59.66246767929124 | 0.3333333333333333 | 0.6666666666666666 | 0.0 | 1.0 |
| RIGHT_SIDE_BUY | 5 | 1186.6533262348385 | 2163.3757821805425 | 265.4461345706077 | 0.003544585180812 | 58.811283022827865 | 0.8 | 0.2 | 0.0 | 0.4 |
| STAGE_RISK_SELL | 13 | 461.4209945434122 | -233.30827021990152 | 61.04358276500716 | 0.0005481335875803 | 2.073020680664285 | 0.5384615384615384 | 0.4615384615384615 | 0.0 | 0.6923076923076923 |

## Whipsaw contribution

| whipsaw_window | count | median_final_contribution | positive_contribution_fraction | median_dd_protection_pp | median_turnover_saved | median_cost_saved |
| --- | --- | --- | --- | --- | --- | --- |
| 3_COMPLETED_CLOSES | 59 | 84.34097250871127 | 0.5254237288135594 | 0.0 | 0.1507484008186672 | 50.48508104617213 |
| 7_CALENDAR_DAYS | 68 | 131.3267803653143 | 0.5441176470588235 | 0.0 | 0.1536915163878491 | 51.529191919314144 |
| 14_CALENDAR_DAYS | 68 | 131.3267803653143 | 0.5441176470588235 | 0.0 | 0.1536915163878491 | 51.529191919314144 |

## Top 10 return contributors

| tactical_event_id | timestamp | action | signal_type | final_wealth_contribution | dd_protection_contribution_pp | classification | robust_classification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 84 | 2025-11-21 00:00:00+00:00 | TACTICAL_SELL_STAGE4 | STAGE_RISK_SELL | 29387.123822290043 | 0.0 | RISK_ESSENTIAL | True |
| 2 | 2020-03-01 00:00:00+00:00 | TACTICAL_SELL_STAGE3 | STAGE_RISK_SELL | 26000.910442533088 | 5.3237013080518425 | RISK_ESSENTIAL | True |
| 25 | 2022-01-04 00:00:00+00:00 | TACTICAL_SELL_STAGE4 | STAGE_RISK_SELL | 24664.925320308364 | 2.856003704696952 | RISK_ESSENTIAL | True |
| 37 | 2022-07-29 00:00:00+00:00 | TACTICAL_SELL_STAGE4 | BEARISH_REBREAK_SELL | 22330.480701567256 | 0.0 | RISK_ESSENTIAL | True |
| 68 | 2023-01-04 00:00:00+00:00 | TACTICAL_BUYBACK_AHR999_TO_35 | AHR_VALUE_BUY | 12228.315566533827 | 0.0 | RETURN_ESSENTIAL | True |
| 106 | 2026-06-30 00:00:00+00:00 | TACTICAL_BUYBACK_AHR999_TO_35 | AHR_VALUE_BUY | 10876.560370457126 | 0.0 | RETURN_ESSENTIAL | True |
| 22 | 2021-05-15 00:00:00+00:00 | TACTICAL_SELL_STAGE2 | STAGE_RISK_SELL | 8406.695474576496 | 0.5501238354021831 | RISK_ESSENTIAL | False |
| 7 | 2020-04-04 00:00:00+00:00 | TACTICAL_BUYBACK_RIGHT_TO_50 | RIGHT_SIDE_BUY | 7547.691872485273 | 0.0 | RETURN_ESSENTIAL | True |
| 34 | 2022-07-13 00:00:00+00:00 | TACTICAL_BUYBACK_AHR999_TO_35 | AHR_VALUE_BUY | 7125.761854261393 | 0.0 | RETURN_ESSENTIAL | True |
| 28 | 2022-06-19 00:00:00+00:00 | TACTICAL_BUYBACK_AHR999_TO_35 | AHR_VALUE_BUY | 5498.814709049184 | 0.0 | RETURN_ESSENTIAL | False |

## Top 10 historically harmful events

| tactical_event_id | timestamp | action | signal_type | final_wealth_contribution | dd_protection_contribution_pp | classification | robust_classification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 24 | 2021-05-25 00:00:00+00:00 | TACTICAL_SELL_STAGE4 | STAGE_RISK_SELL | -25065.57487435988 | 0.4928783826921079 | MIXED_UNCERTAIN | True |
| 80 | 2023-03-12 00:00:00+00:00 | TACTICAL_SELL_STAGE3 | STAGE_RISK_SELL | -23106.742981350515 | 0.0 | MIXED_UNCERTAIN | True |
| 20 | 2020-09-05 00:00:00+00:00 | TACTICAL_SELL_STAGE2 | STAGE_RISK_SELL | -19732.75488984026 | 0.0 | MIXED_UNCERTAIN | True |
| 82 | 2024-02-19 00:00:00+00:00 | TACTICAL_SELL_DRIFT | OTHER_RISK_SELL | -16218.71193166799 | 0.0 | MIXED_UNCERTAIN | True |
| 81 | 2023-11-02 00:00:00+00:00 | TACTICAL_SELL_DRIFT | OTHER_RISK_SELL | -13300.761497743952 | 0.0 | MIXED_UNCERTAIN | True |
| 26 | 2022-06-15 00:00:00+00:00 | TACTICAL_BUYBACK_AHR999_TO_35 | AHR_VALUE_BUY | -10814.958777446009 | 0.0 | HARMFUL | True |
| 21 | 2021-04-21 00:00:00+00:00 | TACTICAL_SELL_STAGE2 | STAGE_RISK_SELL | -10417.023925045389 | 0.2724149241369433 | MIXED_UNCERTAIN | True |
| 3 | 2020-03-13 00:00:00+00:00 | TACTICAL_SELL_STAGE4 | STAGE_RISK_SELL | -8930.079920156102 | -0.4453364144022975 | MIXED_UNCERTAIN | True |
| 19 | 2020-06-21 00:00:00+00:00 | TACTICAL_SELL_STAGE2 | STAGE_RISK_SELL | -8580.430664562038 | 0.0 | MIXED_UNCERTAIN | True |
| 54 | 2022-11-09 00:00:00+00:00 | TACTICAL_BUYBACK_AHR999_TO_35 | AHR_VALUE_BUY | -3482.7662881856086 | 0.0 | HARMFUL | True |

## Robust Redundant basket (hindsight upper bound)

| baseline_final_value | counterfactual_final_value | final_wealth_contribution | final_wealth_contribution_fraction | delta_twr_cagr_pp | delta_xirr_pp | delta_sharpe | delta_sortino | delta_calmar | baseline_max_dd | counterfactual_max_dd | dd_protection_contribution_pp | baseline_tactical_events | counterfactual_tactical_events | tactical_events_removed_direct | tactical_events_removed_indirect | tactical_trade_rows_removed | gross_notional_saved | turnover_saved | fees_saved | slippage_saved | total_trading_cost_saved | next_major_transition_date | observed_date_7d | baseline_value_7d | counterfactual_value_7d | portfolio_value_contribution_7d | observed_date_30d | baseline_value_30d | counterfactual_value_30d | portfolio_value_contribution_30d | observed_date_60d | baseline_value_60d | counterfactual_value_60d | portfolio_value_contribution_60d | observed_date_90d | baseline_value_90d | counterfactual_value_90d | portfolio_value_contribution_90d | observed_date_180d | baseline_value_180d | counterfactual_value_180d | portfolio_value_contribution_180d | baseline_value_next_transition | counterfactual_value_next_transition | portfolio_value_contribution_next_transition | baseline_local_dd_7d | counterfactual_local_dd_7d | local_dd_protection_7d_pp | baseline_local_dd_30d | counterfactual_local_dd_30d | local_dd_protection_30d_pp | baseline_local_dd_60d | counterfactual_local_dd_60d | local_dd_protection_60d_pp | baseline_local_dd_90d | counterfactual_local_dd_90d | local_dd_protection_90d_pp | baseline_local_dd_next_transition | counterfactual_local_dd_next_transition | local_dd_protection_next_transition_pp | max_local_dd_protection_pp | first_resync_date | days_to_resync | resync_status | net_crypto_exposure_day_difference | absolute_crypto_exposure_day_difference | basket | scope | deleted_event_ids | deleted_event_count | diagnostic_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 348746.8528777533 | 347569.0659440155 | 1177.786933737807 | 0.0033771973109407 | 0.0873558307299182 | 0.0820427212373853 | -0.0007981517413124 | -0.0011316625395798 | 0.0022108049008864 | -0.3951313419600695 | -0.3951313419600695 | 0.0 | 106 | 95 | 9 | 2 | 22 | 17054.94776604511 | 0.04729028812792 | 17.054600028947107 | 8.527473883021798 | 25.58207391196902 | 2020-05-11 00:00:00+00:00 | 2020-05-17 00:00:00+00:00 | 27308.42716863529 | 27289.15979386565 | 19.26737476964263 | 2020-06-09 00:00:00+00:00 | 29503.715435773986 | 29295.29292393391 | 208.42251184007543 | 2020-07-09 00:00:00+00:00 | 29453.81065114392 | 29358.072243791292 | 95.73840735262638 | 2020-08-08 00:00:00+00:00 | 37573.22343138649 | 37523.08695446537 | 50.13647692112136 | 2020-11-06 00:00:00+00:00 | 44997.4708698546 | 44937.76420949424 | 59.706660360352544 | 25678.03932025529 | 25712.408554255187 | -34.36923399989246 | -0.0336713075435908 | -0.0316156083674221 | -0.2055699176168657 | -0.0764316182213965 | -0.0680625706839657 | -0.836904753743084 | -0.0870856118208248 | -0.081089248736707 | -0.5996363084117773 | -0.0870856118208248 | -0.081089248736707 | -0.5996363084117773 | -0.0212241297318497 | -0.0207882435281381 | -0.0435886203711599 | -0.0435886203711599 | 2020-09-07 00:00:00+00:00 | 120.0 | RESYNCED | -2.414618904302797 | 3.6796072099441024 | ROBUST_REDUNDANT_BASKET_CF | ALL | 10|11|14|15|16|17|18|70|71 | 9 | EX_POST_UPPER_BOUND_DIAGNOSTIC_NOT_A_STRATEGY |
| 348746.8528777533 | 348746.8528777533 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | -0.3951313419600695 | -0.3951313419600695 | 0.0 | 106 | 106 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 2020-02-21 00:00:00+00:00 | 2020-01-08 00:00:00+00:00 | 22037.17901910048 | 22037.17901910048 | 0.0 | 2020-01-31 00:00:00+00:00 | 25332.108835558567 | 25332.108835558567 | 0.0 | 2020-03-01 00:00:00+00:00 | 26267.910996909 | 26267.910996909 | 0.0 | 2020-03-31 00:00:00+00:00 | 21241.447449769417 | 21241.447449769417 | 0.0 | 2020-06-29 00:00:00+00:00 | 28219.280960628057 | 28219.280960628057 | 0.0 | 29172.250570736884 | 29172.250570736884 | 0.0 | -0.0265850594169808 | -0.0265850594169808 | 0.0 | -0.0691853705114706 | -0.0691853705114706 | 0.0 | -0.1580101868572728 | -0.1580101868572728 | 0.0 | -0.3866281956168792 | -0.3866281956168792 | 0.0 | -0.0787552831141166 | -0.0787552831141166 | 0.0 | 0.0 | 2020-01-03 00:00:00+00:00 | 2.0 | RESYNCED | 0.0 | 0.0 | ROBUST_REDUNDANT_BASKET_CF | BOTTOM_2022 | nan | 0 | EX_POST_UPPER_BOUND_DIAGNOSTIC_NOT_A_STRATEGY |
| 348746.8528777533 | 348746.8528777533 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | -0.3951313419600695 | -0.3951313419600695 | 0.0 | 106 | 106 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 2020-02-21 00:00:00+00:00 | 2020-01-08 00:00:00+00:00 | 22037.17901910048 | 22037.17901910048 | 0.0 | 2020-01-31 00:00:00+00:00 | 25332.108835558567 | 25332.108835558567 | 0.0 | 2020-03-01 00:00:00+00:00 | 26267.910996909 | 26267.910996909 | 0.0 | 2020-03-31 00:00:00+00:00 | 21241.447449769417 | 21241.447449769417 | 0.0 | 2020-06-29 00:00:00+00:00 | 28219.280960628057 | 28219.280960628057 | 0.0 | 29172.250570736884 | 29172.250570736884 | 0.0 | -0.0265850594169808 | -0.0265850594169808 | 0.0 | -0.0691853705114706 | -0.0691853705114706 | 0.0 | -0.1580101868572728 | -0.1580101868572728 | 0.0 | -0.3866281956168792 | -0.3866281956168792 | 0.0 | -0.0787552831141166 | -0.0787552831141166 | 0.0 | 0.0 | 2020-01-03 00:00:00+00:00 | 2.0 | RESYNCED | 0.0 | 0.0 | ROBUST_REDUNDANT_BASKET_CF | BOTTOM_2026 | nan | 0 | EX_POST_UPPER_BOUND_DIAGNOSTIC_NOT_A_STRATEGY |

## Robust Harmful basket (severe hindsight upper bound)

| baseline_final_value | counterfactual_final_value | final_wealth_contribution | final_wealth_contribution_fraction | delta_twr_cagr_pp | delta_xirr_pp | delta_sharpe | delta_sortino | delta_calmar | baseline_max_dd | counterfactual_max_dd | dd_protection_contribution_pp | baseline_tactical_events | counterfactual_tactical_events | tactical_events_removed_direct | tactical_events_removed_indirect | tactical_trade_rows_removed | gross_notional_saved | turnover_saved | fees_saved | slippage_saved | total_trading_cost_saved | next_major_transition_date | observed_date_7d | baseline_value_7d | counterfactual_value_7d | portfolio_value_contribution_7d | observed_date_30d | baseline_value_30d | counterfactual_value_30d | portfolio_value_contribution_30d | observed_date_60d | baseline_value_60d | counterfactual_value_60d | portfolio_value_contribution_60d | observed_date_90d | baseline_value_90d | counterfactual_value_90d | portfolio_value_contribution_90d | observed_date_180d | baseline_value_180d | counterfactual_value_180d | portfolio_value_contribution_180d | baseline_value_next_transition | counterfactual_value_next_transition | portfolio_value_contribution_next_transition | baseline_local_dd_7d | counterfactual_local_dd_7d | local_dd_protection_7d_pp | baseline_local_dd_30d | counterfactual_local_dd_30d | local_dd_protection_30d_pp | baseline_local_dd_60d | counterfactual_local_dd_60d | local_dd_protection_60d_pp | baseline_local_dd_90d | counterfactual_local_dd_90d | local_dd_protection_90d_pp | baseline_local_dd_next_transition | counterfactual_local_dd_next_transition | local_dd_protection_next_transition_pp | max_local_dd_protection_pp | first_resync_date | days_to_resync | resync_status | net_crypto_exposure_day_difference | absolute_crypto_exposure_day_difference | basket | scope | deleted_event_ids | deleted_event_count | diagnostic_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 348746.8528777533 | 351350.4563961487 | -2603.6035183953936 | -0.0074655971714475 | -0.1739530150627555 | -0.1804924502915694 | -0.0049230226981409 | -0.0053450146456832 | -0.0044024099480404 | -0.3951313419600695 | -0.3951313419600695 | 0.0 | 106 | 103 | 2 | 1 | 6 | 30747.61931923125 | 0.1941916988383614 | 30.748354224465857 | 15.373809659613244 | 46.12216388407933 | 2023-02-05 00:00:00+00:00 | 2023-02-11 00:00:00+00:00 | 167077.72149293835 | 168608.0386620044 | -1530.3171690660529 | 2023-03-06 00:00:00+00:00 | 171950.3135262341 | 172933.2399499638 | -982.9264237297176 | 2023-04-05 00:00:00+00:00 | 193611.1716354424 | 195088.36153325223 | -1477.189897809876 | 2023-05-05 00:00:00+00:00 | 194857.0027442737 | 196343.0963722958 | -1486.0936280221213 | 2023-08-03 00:00:00+00:00 | 194173.48662061425 | 195647.871451581 | -1474.3848309667665 | 179716.5049642539 | 179781.87886773463 | -65.37390348076588 | -0.0790988961869351 | -0.0702141921469854 | -0.8884704039949676 | -0.0951835284846229 | -0.0842350082382104 | -1.0948520246412574 | -0.1692477915986618 | -0.1580275475660735 | -1.122024403258837 | -0.1692477915986618 | -0.1580275475660735 | -1.122024403258837 | -0.0062328780511627 | -0.0057693614171701 | -0.0463516633992688 | -0.0463516633992688 | 2023-03-11 00:00:00+00:00 | 35.0 | RESYNCED | -3.472554693570865 | 3.472554693570865 | ROBUST_HARMFUL_BASKET_CF | ALL | 76|77 | 2 | EX_POST_UPPER_BOUND_DIAGNOSTIC_NOT_A_STRATEGY |
| 348746.8528777533 | 348746.8528777533 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | -0.3951313419600695 | -0.3951313419600695 | 0.0 | 106 | 106 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 2020-02-21 00:00:00+00:00 | 2020-01-08 00:00:00+00:00 | 22037.17901910048 | 22037.17901910048 | 0.0 | 2020-01-31 00:00:00+00:00 | 25332.108835558567 | 25332.108835558567 | 0.0 | 2020-03-01 00:00:00+00:00 | 26267.910996909 | 26267.910996909 | 0.0 | 2020-03-31 00:00:00+00:00 | 21241.447449769417 | 21241.447449769417 | 0.0 | 2020-06-29 00:00:00+00:00 | 28219.280960628057 | 28219.280960628057 | 0.0 | 29172.250570736884 | 29172.250570736884 | 0.0 | -0.0265850594169808 | -0.0265850594169808 | 0.0 | -0.0691853705114706 | -0.0691853705114706 | 0.0 | -0.1580101868572728 | -0.1580101868572728 | 0.0 | -0.3866281956168792 | -0.3866281956168792 | 0.0 | -0.0787552831141166 | -0.0787552831141166 | 0.0 | 0.0 | 2020-01-03 00:00:00+00:00 | 2.0 | RESYNCED | 0.0 | 0.0 | ROBUST_HARMFUL_BASKET_CF | BOTTOM_2022 | nan | 0 | EX_POST_UPPER_BOUND_DIAGNOSTIC_NOT_A_STRATEGY |
| 348746.8528777533 | 348746.8528777533 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | -0.3951313419600695 | -0.3951313419600695 | 0.0 | 106 | 106 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 2020-02-21 00:00:00+00:00 | 2020-01-08 00:00:00+00:00 | 22037.17901910048 | 22037.17901910048 | 0.0 | 2020-01-31 00:00:00+00:00 | 25332.108835558567 | 25332.108835558567 | 0.0 | 2020-03-01 00:00:00+00:00 | 26267.910996909 | 26267.910996909 | 0.0 | 2020-03-31 00:00:00+00:00 | 21241.447449769417 | 21241.447449769417 | 0.0 | 2020-06-29 00:00:00+00:00 | 28219.280960628057 | 28219.280960628057 | 0.0 | 29172.250570736884 | 29172.250570736884 | 0.0 | -0.0265850594169808 | -0.0265850594169808 | 0.0 | -0.0691853705114706 | -0.0691853705114706 | 0.0 | -0.1580101868572728 | -0.1580101868572728 | 0.0 | -0.3866281956168792 | -0.3866281956168792 | 0.0 | -0.0787552831141166 | -0.0787552831141166 | 0.0 | 0.0 | 2020-01-03 00:00:00+00:00 | 2.0 | RESYNCED | 0.0 | 0.0 | ROBUST_HARMFUL_BASKET_CF | BOTTOM_2026 | nan | 0 | EX_POST_UPPER_BOUND_DIAGNOSTIC_NOT_A_STRATEGY |

## J Law Diagnostic Verdict

```json
{
  "Baseline Integrity": "PASS",
  "AHR Economic Edge": "count=34; median_usd=-16.86; mean_usd=684.70; positive_raw_fraction=0.5000; median_direction=NEGATIVE",
  "Risk-Sell Economic Edge": "count=48; median_usd=183.47; mean_usd=227.35; positive_raw_fraction=0.5625; median_direction=POSITIVE",
  "Right-Side Economic Edge": "count=5; median_usd=1186.65; mean_usd=2163.38; positive_raw_fraction=0.8000; median_direction=POSITIVE",
  "NEW_BULL Economic Edge": "count=19; median_usd=112.41; mean_usd=12.47; positive_raw_fraction=0.5789; median_direction=POSITIVE",
  "Whipsaw Necessity": "count=68; median_usd=131.33; positive_raw_fraction=0.5441",
  "2022 Bottom Efficiency": "events=41; positive_raw=20; redundant=21; harmful=9",
  "2026 Bottom Efficiency": "events=22; positive_raw=13; redundant=8; harmful=4",
  "Redundant Trade Fraction": 0.46226415094339623,
  "Harmful Trade Fraction": 0.1320754716981132,
  "Return-Essential Fraction": 0.0660377358490566,
  "Risk-Essential Fraction": 0.10377358490566038,
  "Robust Redundant Trade Fraction": 0.25471698113207547,
  "Robust Harmful Trade Fraction": 0.04716981132075472,
  "Robust Return-Essential Fraction": 0.03773584905660377,
  "Robust Risk-Essential Fraction": 0.0660377358490566,
  "Classification Sensitivity Warning": "53_OF_106_EVENTS_CHANGE_LABEL_ACROSS_LOOSE_BASE_STRICT",
  "Turnover Efficiency": 0.9949517662552987,
  "Path Dependency Risk": "HIGH",
  "Maximum Pair Interaction Fraction": 0.0560497252979733,
  "Hindsight Bias Risk": "HIGH",
  "Overfit Risk": "HIGH_IF_CONVERTED_TO_RULE; THIS RUN DOES_NOT_CONVERT",
  "Verdict Trigger": "BASE_HARMFUL_EVENT_FRACTION_GATE",
  "Final Verdict": "C. V3.1 CONTAINS MATERIAL HARMFUL TRADING"
}
```

- The letter verdict is a reporting-gate result, not proof of a causal trading rule. Read its `Verdict Trigger` together with the robust fractions.

## Interaction and non-additivity

- LOEO contributions are non-additive. They cannot be summed to obtain strategy return.
- Pairwise audit: {"candidate_clusters": 10, "pair_count": 45, "maximum_absolute_interaction_usd": 19547.165302330803, "maximum_absolute_interaction_fraction": 0.0560497252979733}
- Cluster deletion and pair deletion alter later order notionals, costs and compounding even though the Shadow FSM remains frozen.

## Interpretation limits

- Classification is a historical diagnostic label. Loose/Base/Strict thresholds were frozen before counterfactual execution and are never used by V3.1.
- Robust Redundant and Robust Harmful baskets are `EX_POST UPPER-BOUND DIAGNOSTIC`; their apparent improvement is hindsight-biased and is not implementable evidence.
- Forward 3/7/14/30/60/90-day BTC/ETH outcomes were attached only after simulations completed and never entered the execution engine.
- Only one realized 2020–2026 market path is observed. Path dependence, sequential research after V3.7/V3.8, selection bias and multiple comparisons limit external validity.
- Fees and frozen slippage are modeled; taxes, capacity, exchange failure and time-varying spread are not.
- No V3.1 rule, threshold, cooldown or live decision was modified. No V3.9 was created.
