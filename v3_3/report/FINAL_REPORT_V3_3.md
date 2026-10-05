# BTC+ETH Macro Hedge V3.3 — Final Report

## Formal verdict

**C. V3.3 NEEDS REDESIGN**

Formal cutoff: 2026-09-03 04:00:00+00:00. Rules were frozen before the first formal V3.3 run; all promotion gates were evaluated afterward only.

## Direct answers

1. H0 final: **US$197,656.93**.
2. A Fixed DCA final: **US$279,201.22**.
3. B V3.1 final: **US$348,746.85**; exact replay **PASS**.
4. E V3.3 final: **US$348,746.85**.
5. Max DD — H0: **-77.22%**, A: **-76.87%**, B: **-39.51%**, E: **-39.51%**.
6. Max DD <=30%: **FAIL** (-39.51%).
7. CAGR >=45%: **PASS** (47.69%).
8. Calmar >=1.50: **FAIL** (1.207).
9. 2021-May exposure control: **PASS**; maximum May–July actual exposure while active target <=60% was 51.95%; longest >80% while target <=60% over the full sample was 0 completed days. The May–July window itself contained 0 ACCUMULATION signal days.
10. 2021-Nov→2022-Jun bear protection: **PASS**; B DD -28.25%, E DD -28.25%, E−B +0.00 pp.
11. V3.3 2023 NEW_BULL: **2023-01-27**; delay versus V3.1 was +0 days (**PASS**).
12. After NEW_BULL, V3.3 reached 85% in **8 days** (2023-02-04) and 95% in **not reached** (Not reached).
13. V3.3 longest confirmed cycle: **1275 days**.
14. Any V3.3 cycle crossing five years: **NO**.
15. Material Tactical Cash Time: **96.23%**.
16. BEAR↔DEEP_BEAR churn: B **223**, E **29**, reduction **87.00%**.
17. Tactical turnover: **9.3677x**.
18. Preserved bear protection + improved exposure control/state stability + no bull re-entry sacrifice: **NO**. Bear protection, state stability, and bull re-entry passed, but Patch 1 executed **0** drift sells, so there is no realized exposure-control improvement versus B on this path.
19. Replace V3.1: **NO** — **C. V3.3 NEEDS REDESIGN**.

## Performance

| model | initial_capital | external_contributions_after_inception | total_capital_supplied | final_portfolio_value | net_profit | xirr | twr_cagr | maximum_drawdown | peak_date | trough_date | recovery_date | dd_duration_days | sharpe | sortino | calmar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H0 | 20000 | 0 | 20000 | 197657 | 177657 | 0.409612 | 0.409612 | -0.772206 | 2021-11-10 12:00:00+00:00 | 2022-06-18 16:00:00+00:00 | 2024-12-05 00:00:00+00:00 | 1120.5 | 0.863846 | 0.838158 | 0.530444 |
| A | 20000 | 29248 | 49248 | 279201 | 229953 | 0.383868 | 0.424998 | -0.76869 | 2021-11-10 12:00:00+00:00 | 2022-06-18 16:00:00+00:00 | 2024-11-21 20:00:00+00:00 | 1107.33 | 0.88587 | 0.859291 | 0.552885 |
| B | 20000 | 29248 | 49248 | 348747 | 299499 | 0.437168 | 0.476915 | -0.395131 | 2020-02-14 20:00:00+00:00 | 2020-03-16 08:00:00+00:00 | 2020-07-27 00:00:00+00:00 | 163.167 | 1.24939 | 1.21365 | 1.20698 |
| E | 20000 | 29248 | 49248 | 348747 | 299499 | 0.437168 | 0.476915 | -0.395131 | 2020-02-14 20:00:00+00:00 | 2020-03-16 08:00:00+00:00 | 2020-07-27 00:00:00+00:00 | 163.167 | 1.24939 | 1.21365 | 1.20698 |

## E V3.3 versus B V3.1

| comparison | delta_final_value | delta_cagr_percentage_points | delta_max_drawdown_percentage_points | delta_calmar | delta_material_tactical_cash_time_percentage_points | delta_turnover | delta_state_churn_count | state_churn_reduction_fraction | delta_2021nov_2022jun_dd_percentage_points | 2023_new_bull_delay_calendar_days | delta_2023_exposure_60_date_days | delta_2023_exposure_85_date_days | delta_2023_exposure_90_date_days | delta_2023_exposure_95_date_days | maximum_accumulation_exposure_E |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E V3.3 vs B V3.1 | 0 | 0 | 0 | 0 | 0 | 0 | -194 | 0.869955 | 0 | 0 | 0 | 0 | 0 |  | 0.658152 |

## B/E exposure, cash, turnover, and cost

| model | average_crypto_exposure | median_crypto_exposure | average_tactical_cash | median_tactical_cash | average_tactical_cash_ratio | median_tactical_cash_ratio | material_tactical_cash_time | tactical_turnover | tactical_trade_count | fees | slippage | total_trading_costs | accumulation_drift_sell_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B | 0.515042 | 0.560806 | 103052 | 115289 | 0.432306 | 0.411909 | 0.96232 | 9.36769 | 212 | 2047.6 | 1023.84 | 3071.44 | 0 |
| E | 0.515042 | 0.560806 | 103052 | 115289 | 0.432306 | 0.411909 | 0.96232 | 9.36769 | 212 | 2047.6 | 1023.84 | 3071.44 | 0 |

## Frozen promotion gates

| gate | pass |
| --- | --- |
| maximum_drawdown_gte_minus_0_30 | False |
| twr_cagr_gte_0_45 | True |
| calmar_gte_1_50 | False |
| final_value_gte_95pct_of_v31_b | True |
| material_tactical_cash_time_strictly_below_v31_b | False |
| tactical_turnover_lte_9_3677 | True |
| bear_deep_bear_churn_reduced_at_least_50pct | True |
| no_lookahead_pass | True |
| execution_integrity_pass | True |
| fsm_audit_pass | True |
| cycle_reset_audit_pass | False |

## Explicit regression guardrails

| bear_protection_regression_pass | bull_reentry_regression_pass | bear_protection_regression_pp | bull_reentry_delay_calendar_days |
| --- | --- | --- | --- |
| True | True | 0 | 0 |

## Accumulation exposure statistics

| maximum_accumulation_exposure | average_accumulation_exposure | days_exposure_above_target_plus_10pp | days_exposure_above_target_plus_20pp | days_exposure_above_80pct_with_target_lte_60pct | days_exposure_above_90pct_with_target_lte_60pct | longest_consecutive_days_above_80pct_with_target_lte_60pct | drift_sell_signal_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.658152 | 0.392194 | 0 | 0 | 0 | 0 | 0 | 0 |

## Cycle duration and reset

| model | cycle_id | start_date | confirmed_date | stage1 | stage2 | stage3 | stage4 | accumulation_date | new_bull_date | bull_date | end_date | duration_days | status | cycle_closed | warning | warning_reason | cash_reset_audit | cash_reset_reason | tactical_bear_cash_ratio_at_close |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B | 1 | 2020-02-20 00:00:00+00:00 | 2020-02-27 00:00:00+00:00 | 2020-02-20 00:00:00+00:00 | 2020-02-27 00:00:00+00:00 | 2020-02-29 00:00:00+00:00 | 2020-03-12 00:00:00+00:00 | 2020-03-13 00:00:00+00:00 | 2020-05-08 00:00:00+00:00 | 2020-05-17 00:00:00+00:00 | 2020-05-17 00:00:00+00:00 | 87 | COMPLETED_NEW_BULL | True | NONE | cycle closed by the recorded NEW_BULL-to-BULL redeploy completion | NOT_RECORDED |  |  |
| B | 2 | 2020-06-16 00:00:00+00:00 | 2020-06-20 00:00:00+00:00 | 2020-06-16 00:00:00+00:00 | 2020-06-20 00:00:00+00:00 | 2021-05-22 00:00:00+00:00 | 2021-05-24 00:00:00+00:00 | 2022-06-14 00:00:00+00:00 | 2023-01-27 00:00:00+00:00 | 2023-02-05 00:00:00+00:00 | 2023-02-05 00:00:00+00:00 | 964 | COMPLETED_NEW_BULL | True | LONG_CYCLE_WARNING | cycle closed by the recorded NEW_BULL-to-BULL redeploy completion | NOT_RECORDED |  |  |
| B | 3 | 2023-03-07 00:00:00+00:00 | 2023-03-08 00:00:00+00:00 | 2023-03-07 00:00:00+00:00 | 2023-03-08 00:00:00+00:00 | 2023-03-11 00:00:00+00:00 | 2025-11-20 00:00:00+00:00 | 2026-02-05 00:00:00+00:00 |  |  | 2026-09-02 00:00:00+00:00 | 1275 | OPEN_AT_END | False | EXTREME_CYCLE_WARNING | cycle remains open at the formal cutoff | NOT_RECORDED |  |  |
| E | 1 | 2020-02-20 00:00:00+00:00 | 2020-02-27 00:00:00+00:00 | 2020-02-20 00:00:00+00:00 | 2020-02-27 00:00:00+00:00 | 2020-02-29 00:00:00+00:00 | 2020-03-12 00:00:00+00:00 | 2020-03-13 00:00:00+00:00 | 2020-05-08 00:00:00+00:00 | 2020-05-17 00:00:00+00:00 | 2020-05-17 00:00:00+00:00 | 87 | COMPLETED_NEW_BULL | True | NONE | cycle closed by the recorded NEW_BULL-to-BULL redeploy completion | PASS | TACTICAL_BEAR_CASH_AT_OR_BELOW_1_PERCENT | 0 |
| E | 2 | 2020-06-16 00:00:00+00:00 | 2020-06-20 00:00:00+00:00 | 2020-06-16 00:00:00+00:00 | 2020-06-20 00:00:00+00:00 | 2021-05-22 00:00:00+00:00 | 2021-05-24 00:00:00+00:00 | 2022-06-14 00:00:00+00:00 | 2023-01-27 00:00:00+00:00 | 2023-02-05 00:00:00+00:00 | 2023-02-05 00:00:00+00:00 | 964 | COMPLETED_NEW_BULL | True | LONG_CYCLE_WARNING | cycle closed by the recorded NEW_BULL-to-BULL redeploy completion | FAIL | TACTICAL_BEAR_CASH_ABOVE_1_PERCENT_AFTER_REDEPLOY | 0.0545167 |
| E | 3 | 2023-03-07 00:00:00+00:00 | 2023-03-08 00:00:00+00:00 | 2023-03-07 00:00:00+00:00 | 2023-03-08 00:00:00+00:00 | 2023-03-11 00:00:00+00:00 | 2025-11-20 00:00:00+00:00 | 2026-02-05 00:00:00+00:00 |  |  | 2026-09-02 00:00:00+00:00 | 1275 | OPEN_AT_END | False | EXTREME_CYCLE_WARNING | cycle remains open at the formal cutoff | NOT_APPLICABLE |  |  |

## FSM churn and dwell

| model | record_type | state | count | average_dwell_days | median_dwell_days |
| --- | --- | --- | --- | --- | --- |
| B | transition_count | BEAR->DEEP_BEAR | 113 |  |  |
| B | transition_count | DEEP_BEAR->BEAR | 110 |  |  |
| B | state_dwell | BEAR | 113 | 11.2124 | 1 |
| B | state_dwell | DEEP_BEAR | 144 | 2.34028 | 1 |
| E | transition_count | BEAR->DEEP_BEAR | 16 |  |  |
| E | transition_count | DEEP_BEAR->BEAR | 13 |  |  |
| E | state_dwell | BEAR | 16 | 72.5625 | 1 |
| E | state_dwell | DEEP_BEAR | 47 | 9.42553 | 1 |

## Cash persistence after NEW_BULL

| model | cycle_id | new_bull_date | days_after_new_bull | observation_date | tactical_bear_cash_ratio | tactical_cash_ratio | crypto_exposure | state |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B | 1 | 2020-05-08 00:00:00+00:00 | 5 | 2020-05-13 00:00:00+00:00 | 0.0659758 | 0.0659758 | 0.710728 | NEW_BULL |
| B | 1 | 2020-05-08 00:00:00+00:00 | 10 | 2020-05-18 00:00:00+00:00 | 0 | 0 | 0.786707 | BULL |
| B | 1 | 2020-05-08 00:00:00+00:00 | 20 | 2020-05-28 00:00:00+00:00 | 0 | 0 | 0.787716 | BULL |
| B | 1 | 2020-05-08 00:00:00+00:00 | 30 | 2020-06-07 00:00:00+00:00 | 0 | 0 | 0.79756 | BULL |
| B | 2 | 2023-01-27 00:00:00+00:00 | 5 | 2023-02-01 00:00:00+00:00 | 0.267343 | 0.267343 | 0.699333 | NEW_BULL |
| B | 2 | 2023-01-27 00:00:00+00:00 | 10 | 2023-02-06 00:00:00+00:00 | 0.0549228 | 0.0549228 | 0.910848 | BULL |
| B | 2 | 2023-01-27 00:00:00+00:00 | 20 | 2023-02-16 00:00:00+00:00 | 0.0536826 | 0.0536826 | 0.912861 | BULL |
| B | 2 | 2023-01-27 00:00:00+00:00 | 30 | 2023-02-26 00:00:00+00:00 | 0.0535576 | 0.0535576 | 0.913064 | BULL |
| E | 1 | 2020-05-08 00:00:00+00:00 | 5 | 2020-05-13 00:00:00+00:00 | 0.0659758 | 0.0659758 | 0.710728 | NEW_BULL |
| E | 1 | 2020-05-08 00:00:00+00:00 | 10 | 2020-05-18 00:00:00+00:00 | 0 | 0 | 0.786707 | BULL |
| E | 1 | 2020-05-08 00:00:00+00:00 | 20 | 2020-05-28 00:00:00+00:00 | 0 | 0 | 0.787716 | BULL |
| E | 1 | 2020-05-08 00:00:00+00:00 | 30 | 2020-06-07 00:00:00+00:00 | 0 | 0 | 0.79756 | BULL |
| E | 2 | 2023-01-27 00:00:00+00:00 | 5 | 2023-02-01 00:00:00+00:00 | 0.267343 | 0.267343 | 0.699333 | NEW_BULL |
| E | 2 | 2023-01-27 00:00:00+00:00 | 10 | 2023-02-06 00:00:00+00:00 | 0.0549228 | 0.0549228 | 0.910848 | BULL |
| E | 2 | 2023-01-27 00:00:00+00:00 | 20 | 2023-02-16 00:00:00+00:00 | 0.0536826 | 0.0536826 | 0.912861 | BULL |
| E | 2 | 2023-01-27 00:00:00+00:00 | 30 | 2023-02-26 00:00:00+00:00 | 0.0535576 | 0.0535576 | 0.913064 | BULL |

## Event-window audit

| event | model | start | end | peak_to_trough_dd | minimum_crypto_exposure | average_crypto_exposure | maximum_tactical_cash_ratio | ending_tactical_cash_ratio | tactical_trade_notional | transition_dates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2020_COVID | B | 2020-02-15 00:00:00+00:00 | 2020-04-30 23:59:59+00:00 | -0.373362 | 0.238542 | 0.538421 | 0.470777 | 0.135602 | 18483.6 | 2020-02-20:BULL->DISTRIBUTION\|2020-02-27:DISTRIBUTION->EARLY_BEAR\|2020-02-29:EARLY_BEAR->BEAR\|2020-03-12:BEAR->DEEP_BEAR\|2020-03-13:DEEP_BEAR->ACCUMULATION\|2020-03-27:ACCUMULATION->DEEP_BEAR\|2020-03-29:DEEP_BEAR->ACCUMULATION |
| 2020_COVID | E | 2020-02-15 00:00:00+00:00 | 2020-04-30 23:59:59+00:00 | -0.373362 | 0.238542 | 0.538421 | 0.470777 | 0.135602 | 18483.6 | 2020-02-20:BULL->DISTRIBUTION\|2020-02-27:DISTRIBUTION->EARLY_BEAR\|2020-02-29:EARLY_BEAR->BEAR\|2020-03-12:BEAR->DEEP_BEAR\|2020-03-13:DEEP_BEAR->ACCUMULATION\|2020-03-27:ACCUMULATION->DEEP_BEAR\|2020-03-29:DEEP_BEAR->ACCUMULATION |
| 2021_MAY_DAILY | B | 2021-05-01 00:00:00+00:00 | 2021-07-31 23:59:59+00:00 | -0.331995 | 0.186742 | 0.34263 | 0.773307 | 0.716819 | 72534.1 | 2021-05-03:EARLY_BEAR->DISTRIBUTION\|2021-05-14:DISTRIBUTION->EARLY_BEAR\|2021-05-22:EARLY_BEAR->BEAR\|2021-05-24:BEAR->DEEP_BEAR\|2021-05-25:DEEP_BEAR->BEAR\|2021-05-26:BEAR->DEEP_BEAR\|2021-05-27:DEEP_BEAR->BEAR\|2021-05-28:BEAR->DEEP_BEAR\|2021-05-29:DEEP_BEAR->BEAR\|2021-05-30:BEAR->DEEP_BEAR\|2021-05-31:DEEP_BEAR->BEAR\|2021-06-01:BEAR->DEEP_BEAR\|2021-06-02:DEEP_BEAR->BEAR\|2021-06-03:BEAR->DEEP_BEAR\|2021-06-04:DEEP_BEAR->BEAR\|2021-06-05:BEAR->DEEP_BEAR\|2021-06-06:DEEP_BEAR->BEAR\|2021-06-07:BEAR->DEEP_BEAR\|2021-06-08:DEEP_BEAR->BEAR\|2021-06-09:BEAR->DEEP_BEAR\|2021-06-10:DEEP_BEAR->BEAR\|2021-06-11:BEAR->DEEP_BEAR\|2021-06-12:DEEP_BEAR->BEAR\|2021-06-13:BEAR->DEEP_BEAR\|2021-06-14:DEEP_BEAR->BEAR\|2021-06-15:BEAR->DEEP_BEAR\|2021-06-16:DEEP_BEAR->BEAR\|2021-06-17:BEAR->DEEP_BEAR\|2021-06-18:DEEP_BEAR->BEAR\|2021-06-19:BEAR->DEEP_BEAR\|2021-06-20:DEEP_BEAR->BEAR\|2021-06-21:BEAR->DEEP_BEAR\|2021-06-22:DEEP_BEAR->BEAR\|2021-06-23:BEAR->DEEP_BEAR\|2021-06-24:DEEP_BEAR->BEAR\|2021-06-25:BEAR->DEEP_BEAR\|2021-06-26:DEEP_BEAR->BEAR\|2021-06-27:BEAR->DEEP_BEAR\|2021-06-28:DEEP_BEAR->BEAR\|2021-06-29:BEAR->DEEP_BEAR\|2021-06-30:DEEP_BEAR->BEAR\|2021-07-01:BEAR->DEEP_BEAR\|2021-07-02:DEEP_BEAR->BEAR\|2021-07-03:BEAR->DEEP_BEAR\|2021-07-04:DEEP_BEAR->BEAR\|2021-07-05:BEAR->DEEP_BEAR\|2021-07-06:DEEP_BEAR->BEAR\|2021-07-07:BEAR->DEEP_BEAR\|2021-07-08:DEEP_BEAR->BEAR\|2021-07-09:BEAR->DEEP_BEAR\|2021-07-10:DEEP_BEAR->BEAR\|2021-07-11:BEAR->DEEP_BEAR\|2021-07-12:DEEP_BEAR->BEAR\|2021-07-13:BEAR->DEEP_BEAR\|2021-07-14:DEEP_BEAR->BEAR\|2021-07-15:BEAR->DEEP_BEAR\|2021-07-16:DEEP_BEAR->BEAR\|2021-07-17:BEAR->DEEP_BEAR\|2021-07-18:DEEP_BEAR->BEAR\|2021-07-19:BEAR->DEEP_BEAR\|2021-07-20:DEEP_BEAR->BEAR\|2021-07-21:BEAR->DEEP_BEAR\|2021-07-22:DEEP_BEAR->BEAR\|2021-07-23:BEAR->DEEP_BEAR\|2021-07-24:DEEP_BEAR->BEAR\|2021-07-25:BEAR->DEEP_BEAR\|2021-07-26:DEEP_BEAR->BEAR\|2021-07-27:BEAR->DEEP_BEAR\|2021-07-28:DEEP_BEAR->BEAR\|2021-07-29:BEAR->DEEP_BEAR\|2021-07-30:DEEP_BEAR->BEAR\|2021-07-31:BEAR->DEEP_BEAR |
| 2021_MAY_DAILY | E | 2021-05-01 00:00:00+00:00 | 2021-07-31 23:59:59+00:00 | -0.331995 | 0.186742 | 0.34263 | 0.773307 | 0.716819 | 72534.1 | 2021-05-03:EARLY_BEAR->DISTRIBUTION\|2021-05-14:DISTRIBUTION->EARLY_BEAR\|2021-05-22:EARLY_BEAR->BEAR\|2021-05-24:BEAR->DEEP_BEAR\|2021-07-29:DEEP_BEAR->BEAR\|2021-07-30:BEAR->DEEP_BEAR |
| 2021_NOV_TO_2022_JUN | B | 2021-11-01 00:00:00+00:00 | 2022-06-30 23:59:59+00:00 | -0.282452 | 0.103439 | 0.247889 | 0.857326 | 0.628707 | 119362 | 2022-01-03:BEAR->DEEP_BEAR\|2022-01-04:DEEP_BEAR->BEAR\|2022-01-05:BEAR->DEEP_BEAR\|2022-01-06:DEEP_BEAR->BEAR\|2022-01-07:BEAR->DEEP_BEAR\|2022-01-08:DEEP_BEAR->BEAR\|2022-01-09:BEAR->DEEP_BEAR\|2022-01-10:DEEP_BEAR->BEAR\|2022-01-11:BEAR->DEEP_BEAR\|2022-01-12:DEEP_BEAR->BEAR\|2022-01-13:BEAR->DEEP_BEAR\|2022-01-14:DEEP_BEAR->BEAR\|2022-01-15:BEAR->DEEP_BEAR\|2022-01-16:DEEP_BEAR->BEAR\|2022-01-17:BEAR->DEEP_BEAR\|2022-01-18:DEEP_BEAR->BEAR\|2022-01-19:BEAR->DEEP_BEAR\|2022-01-20:DEEP_BEAR->BEAR\|2022-01-21:BEAR->DEEP_BEAR\|2022-01-22:DEEP_BEAR->BEAR\|2022-01-23:BEAR->DEEP_BEAR\|2022-01-24:DEEP_BEAR->BEAR\|2022-01-25:BEAR->DEEP_BEAR\|2022-01-26:DEEP_BEAR->BEAR\|2022-01-27:BEAR->DEEP_BEAR\|2022-01-28:DEEP_BEAR->BEAR\|2022-01-29:BEAR->DEEP_BEAR\|2022-01-30:DEEP_BEAR->BEAR\|2022-01-31:BEAR->DEEP_BEAR\|2022-02-01:DEEP_BEAR->BEAR\|2022-02-02:BEAR->DEEP_BEAR\|2022-02-03:DEEP_BEAR->BEAR\|2022-02-04:BEAR->DEEP_BEAR\|2022-02-05:DEEP_BEAR->BEAR\|2022-02-06:BEAR->DEEP_BEAR\|2022-02-07:DEEP_BEAR->BEAR\|2022-02-08:BEAR->DEEP_BEAR\|2022-02-09:DEEP_BEAR->BEAR\|2022-02-10:BEAR->DEEP_BEAR\|2022-02-11:DEEP_BEAR->BEAR\|2022-02-12:BEAR->DEEP_BEAR\|2022-02-13:DEEP_BEAR->BEAR\|2022-02-14:BEAR->DEEP_BEAR\|2022-02-15:DEEP_BEAR->BEAR\|2022-02-16:BEAR->DEEP_BEAR\|2022-02-17:DEEP_BEAR->BEAR\|2022-02-18:BEAR->DEEP_BEAR\|2022-02-19:DEEP_BEAR->BEAR\|2022-02-20:BEAR->DEEP_BEAR\|2022-02-21:DEEP_BEAR->BEAR\|2022-02-22:BEAR->DEEP_BEAR\|2022-02-23:DEEP_BEAR->BEAR\|2022-02-24:BEAR->DEEP_BEAR\|2022-02-25:DEEP_BEAR->BEAR\|2022-02-26:BEAR->DEEP_BEAR\|2022-02-27:DEEP_BEAR->BEAR\|2022-02-28:BEAR->DEEP_BEAR\|2022-03-01:DEEP_BEAR->BEAR\|2022-03-02:BEAR->DEEP_BEAR\|2022-03-03:DEEP_BEAR->BEAR\|2022-03-04:BEAR->DEEP_BEAR\|2022-03-20:DEEP_BEAR->BEAR\|2022-03-21:BEAR->DEEP_BEAR\|2022-03-24:DEEP_BEAR->BEAR\|2022-03-25:BEAR->DEEP_BEAR\|2022-03-26:DEEP_BEAR->BEAR\|2022-03-27:BEAR->DEEP_BEAR\|2022-03-28:DEEP_BEAR->BEAR\|2022-03-30:BEAR->DEEP_BEAR\|2022-03-31:DEEP_BEAR->BEAR\|2022-04-01:BEAR->DEEP_BEAR\|2022-04-02:DEEP_BEAR->BEAR\|2022-04-03:BEAR->DEEP_BEAR\|2022-04-04:DEEP_BEAR->BEAR\|2022-04-05:BEAR->DEEP_BEAR\|2022-04-06:DEEP_BEAR->BEAR\|2022-04-07:BEAR->DEEP_BEAR\|2022-04-08:DEEP_BEAR->BEAR\|2022-04-09:BEAR->DEEP_BEAR\|2022-04-10:DEEP_BEAR->BEAR\|2022-04-11:BEAR->DEEP_BEAR\|2022-06-14:DEEP_BEAR->ACCUMULATION\|2022-06-17:ACCUMULATION->DEEP_BEAR\|2022-06-18:DEEP_BEAR->ACCUMULATION\|2022-06-25:ACCUMULATION->DEEP_BEAR\|2022-06-26:DEEP_BEAR->ACCUMULATION |
| 2021_NOV_TO_2022_JUN | E | 2021-11-01 00:00:00+00:00 | 2022-06-30 23:59:59+00:00 | -0.282452 | 0.103439 | 0.247889 | 0.857326 | 0.628707 | 119362 | 2022-01-03:BEAR->DEEP_BEAR\|2022-03-20:DEEP_BEAR->BEAR\|2022-03-21:BEAR->DEEP_BEAR\|2022-03-31:DEEP_BEAR->BEAR\|2022-04-01:BEAR->DEEP_BEAR\|2022-06-14:DEEP_BEAR->ACCUMULATION\|2022-06-17:ACCUMULATION->DEEP_BEAR\|2022-06-18:DEEP_BEAR->ACCUMULATION\|2022-06-25:ACCUMULATION->DEEP_BEAR\|2022-06-26:DEEP_BEAR->ACCUMULATION |
| 2023_BULL_RECOVERY | B | 2023-01-01 00:00:00+00:00 | 2023-12-31 23:59:59+00:00 | -0.148282 | 0.250125 | 0.619845 | 0.711747 | 0.376062 | 196270 | 2023-01-02:ACCUMULATION->DEEP_BEAR\|2023-01-03:DEEP_BEAR->ACCUMULATION\|2023-01-27:ACCUMULATION->NEW_BULL\|2023-02-05:NEW_BULL->BULL\|2023-03-07:BULL->DISTRIBUTION\|2023-03-08:DISTRIBUTION->EARLY_BEAR\|2023-03-11:EARLY_BEAR->BEAR |
| 2023_BULL_RECOVERY | E | 2023-01-01 00:00:00+00:00 | 2023-12-31 23:59:59+00:00 | -0.148282 | 0.250125 | 0.619845 | 0.711747 | 0.376062 | 196270 | 2023-01-02:ACCUMULATION->DEEP_BEAR\|2023-01-03:DEEP_BEAR->ACCUMULATION\|2023-01-27:ACCUMULATION->NEW_BULL\|2023-02-05:NEW_BULL->BULL\|2023-03-07:BULL->DISTRIBUTION\|2023-03-08:DISTRIBUTION->EARLY_BEAR\|2023-03-11:EARLY_BEAR->BEAR |

## 2023 bull re-entry

| model | cycle_id | new_bull_date | first_60_date | days_new_bull_to_60 | first_85_date | days_new_bull_to_85 | first_90_date | days_new_bull_to_90 | first_95_date | days_new_bull_to_95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B | 2 | 2023-01-27 00:00:00+00:00 | 2023-01-31 00:00:00+00:00 | 4 | 2023-02-04 00:00:00+00:00 | 8 | 2023-02-05 00:00:00+00:00 | 9 |  |  |
| E | 2 | 2023-01-27 00:00:00+00:00 | 2023-01-31 00:00:00+00:00 | 4 | 2023-02-04 00:00:00+00:00 | 8 | 2023-02-05 00:00:00+00:00 | 9 |  |  |

## J Law

| Dimension | Finding |
| --- | --- |
| Champion | V3.1 B before evaluation |
| Challenger | V3.3 E |
| Return Edge | Delta final US$0.00; CAGR +0.00 pp |
| Drawdown Edge | +0.00 pp |
| Calmar Edge | +0.000 |
| Bear Protection | PASS |
| Bull Participation | PASS |
| Accumulation Exposure Control | No breach, but no realized edge: 0 drift sells; max 65.82% |
| Cycle Reset Quality | Lifecycle reset PASS; cash reset FAIL |
| Cash Drag | material-time 96.23% |
| State Stability | churn reduction 87.00% |
| Turnover | 9.3677x |
| Execution Integrity | PASS |
| Overfit Risk | One frozen rule set and one realized market path; forward paper test still required |

## Independent interpretation

V3.3 changed the FSM labels and reduced churn, but it did not change a single trade on this history: Patch 1 never triggered, while the hysteresis transitions did not cross an executable exposure/notional target. Therefore identical return, drawdown, turnover, and cash metrics are a factual consequence—not evidence that the new exposure cap improved performance.

The cycle lifecycle reset itself worked: the 2020-started cycle closed on 2023-02-05 rather than surviving to 2025. The aggregate gate still fails because 5.45% tactical bear cash remained at that close, above the explicit 1% CASH_RESET limit; the original V3.1 trade guard also prevented exact 95% exposure from being reached.

H0 receives no periodic contributions, so normalized TWR—not absolute ending wealth—is the fair strategy-performance comparison. Passing a historical promotion gate would mean eligibility for a forward paper test, not live-trading approval. The test contains one realized crypto path, exchange/source history may contain survivorship and venue-basis effects, and the final 2025–2026 episode is right-censored at the data cutoff.

## Integrity

NO_LOOK_AHEAD=PASS; EXECUTION_INTEGRITY=PASS; CYCLE_RESET_AUDIT=FAIL; V3_1_REPLAY_INTEGRITY=PASS; promotion terms in trading engine=False; V3.2 trading imports/tokens in V3.3 engine=False.