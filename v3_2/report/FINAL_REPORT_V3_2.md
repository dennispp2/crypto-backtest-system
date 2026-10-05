# BTC+ETH Macro Hedge V3.2 — Final Report

## Formal result

**B. V3.1 REMAINS CHAMPION**

Formal cutoff: 2026-09-03 04:00:00+00:00. Rules were frozen before the V3.2 formal run; promotion thresholds were evaluated only afterward.

## Direct answers

1. H0 final value: **US$197,656.93**.
2. A Fixed DCA final value: **US$279,201.22**.
3. B V3.1 final value: **US$348,746.85**; frozen replay integrity **PASS**.
4. D V3.2 final value: **US$308,173.74**.
5. Max DD — H0: **-77.22%**, A: **-76.87%**, B: **-39.51%**, D: **-44.61%**.
6. V3.2 Max DD >= -30%: **FAIL** (-44.61%).
7. V3.2 CAGR >=45%: **FAIL** (44.65%).
8. V3.2 Calmar >=1.50: **FAIL** (1.001).
9. After 2021/11, Stage4 was not meaningfully earlier: **NO**—both governing cycles had already recorded Stage4 (B: **2021-05-24**, D: **2020-03-12**), but D had subsequently bought back above its 25% Stage4 target.
10. 2021-Nov→2022-Jun event DD change D vs B: **-12.05 pp**; this is a **deterioration**, not an improvement. D minimum exposure was 10.82%.
11. 2023–2025 V3.2 recovered exposure faster than V3.1: **NO**. B confirmed NEW_BULL in 2023, while D did not trigger Bull Recovery until 2025. D's eventual event: 60%: 1.0 days; 85%: 9.0 days; 95%: not reached.
12. V3.2 average exposure in BULL/NEW_BULL states: **81.21%**; fixed 2023–2025 window: **57.59%**.
13. Material Tactical Cash Time change: **+1.40 pp** (B 96.23% → D 97.63%).
14. BEAR↔DEEP_BEAR churn: B **223**, D **26**, reduction **88.34%**.
15. V3.2 tactical turnover: **9.8933x**.
16. Less bear loss plus stronger bull holding: **NO**.
17. Replace V3.1 in forward paper test: **NO**.
18. J Law Final Verdict: **B. V3.1 REMAINS CHAMPION**.

## Performance table

| model | initial_capital | external_contributions_after_inception | total_capital_supplied | final_portfolio_value | net_profit | xirr | twr_cagr | maximum_drawdown | peak_date | trough_date | recovery_date | sharpe | sortino | calmar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H0 | 20000 | 0 | 20000 | 197657 | 177657 | 0.409612 | 0.409612 | -0.772206 | 2021-11-10 12:00:00+00:00 | 2022-06-18 16:00:00+00:00 | 2024-12-05 00:00:00+00:00 | 0.863846 | 0.838158 | 0.530444 |
| A | 20000 | 29248 | 49248 | 279201 | 229953 | 0.383868 | 0.424998 | -0.76869 | 2021-11-10 12:00:00+00:00 | 2022-06-18 16:00:00+00:00 | 2024-11-21 20:00:00+00:00 | 0.88587 | 0.859291 | 0.552885 |
| B | 20000 | 29248 | 49248 | 348747 | 299499 | 0.437168 | 0.476915 | -0.395131 | 2020-02-14 20:00:00+00:00 | 2020-03-16 08:00:00+00:00 | 2020-07-27 00:00:00+00:00 | 1.24939 | 1.21365 | 1.20698 |
| D | 20000 | 29248 | 49248 | 308174 | 258926 | 0.407371 | 0.446532 | -0.446054 | 2021-05-12 00:00:00+00:00 | 2021-07-20 00:00:00+00:00 | 2024-02-27 00:00:00+00:00 | 1.12733 | 1.09209 | 1.00107 |

## D versus B

| comparison | delta_final_value | delta_cagr_percentage_points | delta_max_drawdown_percentage_points | delta_calmar | delta_material_tactical_cash_time_percentage_points | delta_tactical_turnover |
| --- | --- | --- | --- | --- | --- | --- |
| D V3.2 vs B V3.1 | -40573.1 | -3.03826 | -5.09225 | -0.205905 | 1.39506 | 0.525656 |

## B/D exposure, cash, turnover and costs

| model | average_crypto_exposure | median_crypto_exposure | average_tactical_cash | median_tactical_cash | average_tactical_cash_ratio | median_tactical_cash_ratio | material_tactical_cash_time | tactical_turnover | tactical_trade_count | tactical_event_count | fees | slippage | total_trading_costs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B | 0.515042 | 0.560806 | 103052 | 115289 | 0.432306 | 0.411909 | 0.96232 | 9.36769 | 212 | 106 | 2047.6 | 1023.84 | 3071.44 |
| D | 0.544899 | 0.557933 | 81957.7 | 84967.7 | 0.399365 | 0.396779 | 0.97627 | 9.89335 | 172 | 86 | 1928.27 | 964.168 | 2892.44 |

## Frozen promotion gates

| gate | pass |
| --- | --- |
| maximum_drawdown_gte_minus_0_30 | False |
| twr_cagr_gte_0_45 | False |
| calmar_gte_1_50 | False |
| new_bull_exposure_gte_0_85 | True |
| material_tactical_cash_time_below_v31 | False |
| tactical_turnover_lte_9_3677 | False |
| no_lookahead_pass | True |
| execution_integrity_pass | True |
| fsm_audit_pass | True |

## Material diagnostics

- V3.2's longest confirmed macro cycle lasted **1906 days**. The 2020 cycle did not close until the 2025 recovery, which fails the design intent that an old cycle must not remain open for years after a genuine bull market.
- Material tactical-cash time increased from **96.23%** to **97.63%**; the cash-drag problem was not solved.
- Stage number is historical cycle progress, not current target exposure. During ACCUMULATION, D may retain Stage 4 while its active target is 35%, 50%, or 60%; the zoom must be read together with the exposure line.

## Stability events

| event | model | start | end | event_drawdown | minimum_crypto_exposure | ending_crypto_exposure | d_dominant_state | d_dominant_stage | d_average_crypto_exposure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2020_COVID | H0 | 2020-02-15 00:00:00+00:00 | 2020-04-30 23:59:59+00:00 | -0.456458 | 0.629732 | 0.758366 | ACCUMULATION | 4 | 0.529836 |
| 2020_COVID | A | 2020-02-15 00:00:00+00:00 | 2020-04-30 23:59:59+00:00 | -0.459643 | 0.640489 | 0.773415 | ACCUMULATION | 4 | 0.529836 |
| 2020_COVID | B | 2020-02-15 00:00:00+00:00 | 2020-04-30 23:59:59+00:00 | -0.373362 | 0.238542 | 0.63503 | ACCUMULATION | 4 | 0.529836 |
| 2020_COVID | D | 2020-02-15 00:00:00+00:00 | 2020-04-30 23:59:59+00:00 | -0.373362 | 0.238542 | 0.581766 | ACCUMULATION | 4 | 0.529836 |
| 2021_MAY | H0 | 2021-05-10 00:00:00+00:00 | 2021-05-31 23:59:59+00:00 | -0.454681 | 0.954943 | 0.962749 | ACCUMULATION | 4 | 0.681573 |
| 2021_MAY | A | 2021-05-10 00:00:00+00:00 | 2021-05-31 23:59:59+00:00 | -0.449439 | 0.960418 | 0.966957 | ACCUMULATION | 4 | 0.681573 |
| 2021_MAY | B | 2021-05-10 00:00:00+00:00 | 2021-05-31 23:59:59+00:00 | -0.331995 | 0.223191 | 0.254487 | ACCUMULATION | 4 | 0.681573 |
| 2021_MAY | D | 2021-05-10 00:00:00+00:00 | 2021-05-31 23:59:59+00:00 | -0.380045 | 0.466454 | 0.522943 | ACCUMULATION | 4 | 0.681573 |
| 2021_NOV_TO_2022_JUN | H0 | 2021-11-01 00:00:00+00:00 | 2022-06-30 23:59:59+00:00 | -0.7548 | 0.913575 | 0.918571 | ACCUMULATION | 4 | 0.418442 |
| 2021_NOV_TO_2022_JUN | A | 2021-11-01 00:00:00+00:00 | 2022-06-30 23:59:59+00:00 | -0.751383 | 0.926356 | 0.930655 | ACCUMULATION | 4 | 0.418442 |
| 2021_NOV_TO_2022_JUN | B | 2021-11-01 00:00:00+00:00 | 2022-06-30 23:59:59+00:00 | -0.282452 | 0.103439 | 0.33114 | ACCUMULATION | 4 | 0.418442 |
| 2021_NOV_TO_2022_JUN | D | 2021-11-01 00:00:00+00:00 | 2022-06-30 23:59:59+00:00 | -0.402927 | 0.108175 | 0.330939 | ACCUMULATION | 4 | 0.418442 |
| 2022_FTX | H0 | 2022-11-01 00:00:00+00:00 | 2022-11-30 23:59:59+00:00 | -0.287957 | 0.914396 | 0.924413 | ACCUMULATION | 4 | 0.316106 |
| 2022_FTX | A | 2022-11-01 00:00:00+00:00 | 2022-11-30 23:59:59+00:00 | -0.284471 | 0.926735 | 0.935139 | ACCUMULATION | 4 | 0.316106 |
| 2022_FTX | B | 2022-11-01 00:00:00+00:00 | 2022-11-30 23:59:59+00:00 | -0.101271 | 0.244812 | 0.363131 | ACCUMULATION | 4 | 0.316106 |
| 2022_FTX | D | 2022-11-01 00:00:00+00:00 | 2022-11-30 23:59:59+00:00 | -0.101531 | 0.244974 | 0.363224 | ACCUMULATION | 4 | 0.316106 |
| 2023_BULL_RECOVERY | H0 | 2023-01-01 00:00:00+00:00 | 2023-12-31 23:59:59+00:00 | -0.227112 | 0.919887 | 0.959988 | ACCUMULATION | 4 | 0.465281 |
| 2023_BULL_RECOVERY | A | 2023-01-01 00:00:00+00:00 | 2023-12-31 23:59:59+00:00 | -0.219294 | 0.931747 | 0.968198 | ACCUMULATION | 4 | 0.465281 |
| 2023_BULL_RECOVERY | B | 2023-01-01 00:00:00+00:00 | 2023-12-31 23:59:59+00:00 | -0.148282 | 0.250125 | 0.598319 | ACCUMULATION | 4 | 0.465281 |
| 2023_BULL_RECOVERY | D | 2023-01-01 00:00:00+00:00 | 2023-12-31 23:59:59+00:00 | -0.110817 | 0.250133 | 0.552615 | ACCUMULATION | 4 | 0.465281 |
| 2024_CORRECTIONS | H0 | 2024-01-01 00:00:00+00:00 | 2024-12-31 23:59:59+00:00 | -0.373923 | 0.958498 | 0.976479 | ACCUMULATION | 4 | 0.641125 |
| 2024_CORRECTIONS | A | 2024-01-01 00:00:00+00:00 | 2024-12-31 23:59:59+00:00 | -0.351497 | 0.966945 | 0.9826 | ACCUMULATION | 4 | 0.641125 |
| 2024_CORRECTIONS | B | 2024-01-01 00:00:00+00:00 | 2024-12-31 23:59:59+00:00 | -0.217962 | 0.531414 | 0.54201 | ACCUMULATION | 4 | 0.641125 |
| 2024_CORRECTIONS | D | 2024-01-01 00:00:00+00:00 | 2024-12-31 23:59:59+00:00 | -0.237727 | 0.542585 | 0.703307 | ACCUMULATION | 4 | 0.641125 |
| 2025_2026_CORRECTION | H0 | 2025-01-01 00:00:00+00:00 | 2026-09-03 00:00:00+00:00 | -0.595424 | 0.957443 | 0.969644 | ACCUMULATION | 4 | 0.500775 |
| 2025_2026_CORRECTION | A | 2025-01-01 00:00:00+00:00 | 2026-09-03 00:00:00+00:00 | -0.580013 | 0.970153 | 0.978493 | ACCUMULATION | 4 | 0.500775 |
| 2025_2026_CORRECTION | B | 2025-01-01 00:00:00+00:00 | 2026-09-03 00:00:00+00:00 | -0.28237 | 0.19169 | 0.422338 | ACCUMULATION | 4 | 0.500775 |
| 2025_2026_CORRECTION | D | 2025-01-01 00:00:00+00:00 | 2026-09-03 00:00:00+00:00 | -0.292837 | 0.180716 | 0.424164 | ACCUMULATION | 4 | 0.500775 |

## FSM churn and dwell

| model | record_type | state | count | average_days | median_days |
| --- | --- | --- | --- | --- | --- |
| B | transition_count | BEAR->DEEP_BEAR | 113 |  |  |
| B | transition_count | DEEP_BEAR->BEAR | 110 |  |  |
| B | state_dwell | ACCUMULATION | 34 | 10.3529 | 7 |
| B | state_dwell | BEAR | 113 | 11.2124 | 1 |
| B | state_dwell | BULL | 3 | 37 | 30 |
| B | state_dwell | DEEP_BEAR | 144 | 2.34028 | 1 |
| B | state_dwell | DISTRIBUTION | 6 | 48.3333 | 9 |
| B | state_dwell | EARLY_BEAR | 6 | 10.5 | 10.5 |
| B | state_dwell | NEW_BULL | 2 | 9 | 9 |
| D | transition_count | BEAR->DEEP_BEAR | 14 |  |  |
| D | transition_count | DEEP_BEAR->BEAR | 12 |  |  |
| D | state_dwell | ACCUMULATION | 35 | 50.7429 | 7 |
| D | state_dwell | BEAR | 15 | 5.73333 | 1 |
| D | state_dwell | BULL | 3 | 28.6667 | 26 |
| D | state_dwell | DEEP_BEAR | 46 | 7.26087 | 1 |
| D | state_dwell | DISTRIBUTION | 7 | 14.8571 | 7 |
| D | state_dwell | EARLY_BEAR | 6 | 8 | 5.5 |
| D | state_dwell | NEW_BULL | 1 | 4 | 4 |

## Bull re-entry

| model | cycle_id | recovery_date | new_bull_date | first_60_date | days_recovery_to_60 | first_85_date | days_recovery_to_85 | first_95_date | days_recovery_to_95 | max_exposure_first_10d_after_new_bull |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B | 1 | 2020-03-29 00:00:00+00:00 | 2020-05-08 00:00:00+00:00 | 2020-04-23 12:00:00+00:00 | 25.5 |  |  |  |  | 0.78788 |
| B | 2 | 2023-01-03 00:00:00+00:00 | 2023-01-27 00:00:00+00:00 | 2023-01-31 00:00:00+00:00 | 28 | 2023-02-04 00:00:00+00:00 | 32 |  |  | 0.913183 |
| D | 1 | 2025-05-01 00:00:00+00:00 | 2025-05-06 00:00:00+00:00 | 2025-05-02 00:00:00+00:00 | 1 | 2025-05-10 00:00:00+00:00 | 9 |  |  | 0.91466 |

## Cycle audit

| model | cycle_id | start | end | status | confirmed | confirmed_date | cycle_peak_price | temporary_hedge_amount | new_bull_date | stage1_date | stage1_btc_price | stage1_eth_price | stage1_exposure | stage1_tactical_cash | stage1_bear_risk | stage2_date | stage2_btc_price | stage2_eth_price | stage2_exposure | stage2_tactical_cash | stage2_bear_risk | stage3_date | stage3_btc_price | stage3_eth_price | stage3_exposure | stage3_tactical_cash | stage3_bear_risk | stage4_date | stage4_btc_price | stage4_eth_price | stage4_exposure | stage4_tactical_cash | stage4_bear_risk | accumulation_date | accumulation_btc_price | accumulation_exposure | new_bull_btc_price | new_bull_exposure | bull_date | bull_btc_price | bull_exposure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B | 1 | 2020-02-20 00:00:00+00:00 | 2020-05-17 00:00:00+00:00 | COMPLETED_NEW_BULL | True | 2020-02-27 00:00:00+00:00 | 10344.4 | 0 | 2020-05-08 00:00:00+00:00 | 2020-02-20 00:00:00+00:00 | 9596.42 | 256.97 | 0.791702 | 0 |  | 2020-02-27 00:00:00+00:00 | 8823.21 | 227.73 | 0.775205 | 0 |  | 2020-02-29 00:00:00+00:00 | 8523.61 | 217.29 | 0.691751 | 2007.55 |  | 2020-03-12 00:00:00+00:00 | 4800 | 107.67 | 0.395905 | 5689.01 |  | 2020-03-13 00:00:00+00:00 | 5578.6 | 0.35 | 9800.01 | 0.668403 | 2020-05-17 00:00:00+00:00 | 9680.04 | 0.78345 |
| B | 2 | 2020-06-16 00:00:00+00:00 | 2023-02-05 00:00:00+00:00 | COMPLETED_NEW_BULL | True | 2020-06-20 00:00:00+00:00 | 67525.8 | 0 | 2023-01-27 00:00:00+00:00 | 2020-06-16 00:00:00+00:00 | 9525.59 | 235.31 | 0.79345 | 0 |  | 2020-06-20 00:00:00+00:00 | 9358.95 | 228.88 | 0.79017 | 0 |  | 2021-05-22 00:00:00+00:00 | 37449.7 | 2295.45 | 0.489315 | 72346.5 |  | 2021-05-24 00:00:00+00:00 | 38796.3 | 2647.92 | 0.519429 | 72346.5 |  | 2022-06-14 00:00:00+00:00 | 22136.4 | 0.35 | 23074.2 | 0.475573 | 2023-02-05 00:00:00+00:00 | 22932.9 | 0.911496 |
| B | 3 | 2023-03-07 00:00:00+00:00 | 2026-09-02 00:00:00+00:00 | OPEN_AT_END | True | 2023-03-08 00:00:00+00:00 | 124659 | 10041.4 |  | 2023-03-07 00:00:00+00:00 | 22198 | 1561.95 | 0.908656 | 9634.47 |  | 2023-03-08 00:00:00+00:00 | 21705.4 | 1532.38 | 0.847323 | 19675.8 |  | 2023-03-11 00:00:00+00:00 | 20455.7 | 1471.93 | 0.689469 | 44446.2 |  | 2025-11-20 00:00:00+00:00 | 86637.2 | 2834.21 | 0.521549 | 154478 |  | 2026-02-05 00:00:00+00:00 | 62909.9 | 0.35 |  |  |  |  |  |
| D | 1 | 2020-02-20 00:00:00+00:00 | 2025-05-10 00:00:00+00:00 | COMPLETED_NEW_BULL | True | 2020-02-27 00:00:00+00:00 | 106144 | 0 | 2025-05-06 00:00:00+00:00 | 2020-02-20 00:00:00+00:00 | 9596.42 | 256.97 | 0.791702 | 0 |  | 2020-02-27 00:00:00+00:00 | 8823.21 | 227.73 | 0.775205 | 0 |  | 2020-02-29 00:00:00+00:00 | 8523.61 | 217.29 | 0.691751 | 2007.55 |  | 2020-03-12 00:00:00+00:00 | 4800 | 107.67 | 0.395905 | 5689.01 |  | 2020-03-13 00:00:00+00:00 | 5578.6 | 0.35 | 96834 | 0.675502 | 2025-05-10 00:00:00+00:00 | 104810 | 0.913585 |
| D | 2 | 2025-06-05 00:00:00+00:00 | 2025-06-11 00:00:00+00:00 | ABORTED_DISTRIBUTION | False |  | 111696 | 17343.7 |  | 2025-06-05 00:00:00+00:00 | 101509 | 2414.02 | 0.910178 | 19888.2 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | 2025-06-11 00:00:00+00:00 | 108645 | 0.861225 |
| D | 3 | 2025-06-20 00:00:00+00:00 | 2026-09-02 00:00:00+00:00 | OPEN_AT_END | True | 2025-06-21 00:00:00+00:00 | 124659 | 0 |  | 2025-06-20 00:00:00+00:00 | 103298 | 2406.49 | 0.851486 | 37231.9 |  | 2025-06-21 00:00:00+00:00 | 102120 | 2295.72 | 0.848632 | 37231.9 |  | 2025-11-04 00:00:00+00:00 | 101497 | 3287.05 | 0.661662 | 100401 |  | 2025-11-17 00:00:00+00:00 | 92215.1 | 3031.44 | 0.527787 | 135495 |  | 2026-02-05 00:00:00+00:00 | 62909.9 | 0.35 |  |  |  |  |  |

## J Law

| Dimension | Finding |
| --- | --- |
| Champion | V3.1 B before evaluation |
| Challenger | V3.2 D |
| Return Edge | Delta final US$-40,573.12; delta CAGR -3.04 pp |
| Drawdown Edge | -5.09 pp |
| Calmar Edge | -0.206 |
| Bear Protection | -44.61% |
| Bull Participation | 81.21% |
| Cash Drag | material-time delta +1.40 pp |
| State Stability | churn reduction 88.34% |
| Turnover | 9.8933x |
| Execution Integrity | PASS |
| Overfit Risk | One frozen specification; single historical path remains a limitation |

## Independent interpretation

Promotion means eligibility for forward paper testing, not live-trading approval. H0 has no periodic contributions, so normalized TWR—not absolute ending wealth—is the fair strategy-performance comparison. The sample contains only one realized crypto history, and the 2025–2026 event window is right-censored at the data cutoff.

## Integrity

NO_LOOK_AHEAD=PASS; V3_1_ROW_INTEGRITY=PASS; promotion rules present in trading engine=False.