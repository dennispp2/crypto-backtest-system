# Crypto Fixed DCA + Macro Cycle Hedge V3.0 — Final Report

## Validity

- Formal period: 2020-01-01T00:00:00+00:00 to 2026-09-02T08:00:00+00:00; 2019 is indicator warm-up only.
- Model A is the unchanged V1 Fixed DCA engine; V3 only replays its DCA ledger.
- Frozen models: A, V3-E20, V3-E30, V3-E40. No threshold search or audit-date trading logic.
- Fixed DCA row integrity: **PASS**.
- No-look-ahead audit: **PASS**.
- FSM illegal transitions: **0**.
- Buy/sell conflicts: **0**.

## Performance

| strategy | final_portfolio_value | external_contributions | xirr | time_weighted_cagr | maximum_drawdown | calmar | average_crypto_exposure | material_tactical_cash_time | tactical_turnover | total_trading_costs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A - Fixed DCA Champion | US$419,364.04 | US$49,238.00 | 48.26% | 52.29% | -74.30% | 0.7038 | 95.13% | 0.00% | 0.000x | US$64.78 |
| V3-E20 - Fixed DCA + Macro Cycle Hedge | US$706,543.72 | US$49,238.00 | 61.60% | 65.34% | -42.16% | 1.5497 | 60.73% | 91.63% | 11.479x | US$6,276.87 |
| V3-E30 - Fixed DCA + Macro Cycle Hedge | US$663,337.58 | US$49,238.00 | 59.94% | 63.73% | -45.45% | 1.4021 | 62.21% | 91.63% | 9.845x | US$5,183.56 |
| V3-E40 - Fixed DCA + Macro Cycle Hedge | US$618,319.95 | US$49,238.00 | 58.11% | 61.94% | -49.38% | 1.2544 | 63.85% | 91.63% | 8.562x | US$4,297.12 |

## Required answers

1. Fixed DCA final value: **US$419,364.04**.
2. V3-E20 final value: **US$706,543.72**.
3. Max DD — A -74.30%; E20 -42.16%; improvement 32.13 pp.
4. Peak/trough — A 2021-11-10T12:00:00+00:00 → 2022-06-18T16:00:00+00:00; E20 2021-11-10T12:00:00+00:00 → 2022-06-18T16:00:00+00:00.
5. 2021/05 — first risk-off signal inside 5/10–5/31: 2021-05-17T00:00:00+00:00; Stage 1 inside that window: none. The active episode had already entered Stage 1 on 2021-04-20T00:00:00+00:00 and executed on 2021-04-21T00:00:00+00:00. Crash events 1; maximum May exposure 60.25%; exposure by first BTC intraday low at/below US$30K 47.45%.
6. 2022/02 NEW_BULL misclassification: **NO**; confirmations 0, maximum E20 exposure 55.36%.
7. 2022/06 BTC completed-daily low date 2022-06-19T00:00:00+00:00: E20 crypto exposure 26.59%, tactical cash US$158,624.49, AHR999 0.2563, state DEEP_BEAR/Stage 4.
8. Confirmed Macro Cycle count: **12**; maximum in one year 3.
9. Tactical turnover: V2-E20 14.502x → V3-E20 11.479x; reduction 20.85%.
10. E20 Calmar improvement: **YES**; A 0.7038, E20 1.5497, delta 0.8460.
11. Forward paper test: **NO** under the frozen gates.
12. J Law verdict: **V3 NEEDS REDESIGN**.

## V3-E20 versus A

- Delta final value: US$287,179.68.
- Delta TWR CAGR: 13.06 pp.
- Delta Max DD: 32.13 pp.
- Delta Calmar: 0.8460.
- CAGR sacrificed per 1 pp Max-DD improvement: -0.406 pp (negative means CAGR increased rather than being sacrificed).

## 2021/11 top to 2022 bear: stage path

| stage | signal_date | execution | btc_signal_close | post_trade_exposure |
| --- | --- | --- | --- | --- |
| 1 | 2021-11-18T00:00:00+00:00 | 2021-11-19T00:00:00+00:00 | US$56,891.62 | 85.00% |
| 2 | 2021-11-19T00:00:00+00:00 | 2021-11-20T00:00:00+00:00 | US$58,052.24 | 70.00% |
| 3 | 2021-11-28T00:00:00+00:00 | 2021-11-29T00:00:00+00:00 | US$57,274.88 | 55.00% |
| 4 | 2022-04-16T00:00:00+00:00 | 2022-04-17T00:00:00+00:00 | US$40,378.71 | 25.00% |

## 2022/01–06 E20 exposure path

| month | minimum_exposure | maximum_exposure | month_end_exposure | month_end_tactical_cash |
| --- | --- | --- | --- | --- |
| 2022-01 | 49.39% | 58.51% | 51.53% | US$115,790.59 |
| 2022-02 | 50.51% | 55.36% | 53.90% | US$115,790.59 |
| 2022-03 | 50.74% | 56.69% | 55.88% | US$115,790.59 |
| 2022-04 | 23.75% | 56.90% | 23.75% | US$191,803.95 |
| 2022-05 | 19.25% | 24.74% | 20.95% | US$191,803.95 |
| 2022-06 | 15.63% | 50.30% | 26.01% | US$158,624.49 |

## 2022/06 tactical actions

| timestamp | action | reason | before_exposure | after_exposure | gross_notional |
| --- | --- | --- | --- | --- | --- |
| 2022-06-15T00:00:00+00:00 | TACTICAL_BUYBACK_AHR_030_035 | ahr_030_035 | 15.63% | 35.00% | US$45,398.82 |
| 2022-06-17T00:00:00+00:00 | TACTICAL_BUYBACK_AHR_BELOW_030 | ahr_below_030 | 33.00% | 50.00% | US$38,623.12 |
| 2022-06-19T00:00:00+00:00 | TACTICAL_SELL_STAGE_4 | accumulation_failure_deep_bear | 48.24% | 25.00% | US$51,045.11 |

## Later-cycle checks

- 2023–2025 NEW_BULL confirmations: 6; completed NEW_BULL → BULL resets: 6; maximum crypto exposure 93.90%.
- 2023–2025 material tactical-cash time: 100.00%. This fails the qualitative goal of avoiding persistent large cash balances even though the frozen numerical promotion gates did not assign a separate threshold to it.
- Latest 2025–2026 correction row: 2026-09-02T00:00:00+00:00, state ACCUMULATION/Stage 4, crypto exposure 31.00%, tactical cash US$481,531.54.

## Audit-case summary

| case | start | end | regimes | maximum_stage | minimum_crypto_exposure | maximum_crypto_exposure | ending_crypto_exposure | maximum_tactical_cash_ratio | ending_tactical_cash | minimum_portfolio_drawdown | crash_override_events | new_bull_confirmations | tactical_trade_rows |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| covid_2020 | 2020-03-01 00:00:00+00:00 | 2020-04-30 00:00:00+00:00 | BEAR\|ACCUMULATION | 3 | 0.398787 | 0.727169 | 0.722097 | 0.29347 | 2118.03 | -0.385855 | 1 | 0 | 4 |
| may_2021 | 2021-05-10 00:00:00+00:00 | 2021-05-31 00:00:00+00:00 | BEAR\|ACCUMULATION | 3 | 0.444244 | 0.602455 | 0.489963 | 0.52973 | 122184 | -0.296693 | 1 | 0 | 0 |
| top_to_bear_2021_2022 | 2021-11-01 00:00:00+00:00 | 2022-06-30 00:00:00+00:00 | NEW_BULL\|BULL\|DISTRIBUTION\|EARLY_BEAR\|BEAR\|ACCUMULATION\|DEEP_BEAR | 4 | 0.156252 | 0.925201 | 0.260116 | 0.818142 | 158624 | -0.405366 | 3 | 0 | 16 |
| feb_2022_rally | 2022-02-01 00:00:00+00:00 | 2022-03-31 00:00:00+00:00 | BEAR\|ACCUMULATION | 3 | 0.505094 | 0.566906 | 0.558787 | 0.470513 | 115791 | -0.329899 | 0 | 0 | 0 |
| june_2022_low | 2022-06-01 00:00:00+00:00 | 2022-06-30 00:00:00+00:00 | DEEP_BEAR\|ACCUMULATION | 4 | 0.156252 | 0.503032 | 0.260116 | 0.818142 | 158624 | -0.405366 | 1 | 0 | 8 |
| ftx_2022 | 2022-11-01 00:00:00+00:00 | 2022-11-30 00:00:00+00:00 | ACCUMULATION\|BEAR\|DEEP_BEAR | 4 | 0.204637 | 0.257066 | 0.219003 | 0.77034 | 184805 | -0.3552 | 1 | 0 | 0 |
| bull_2023_2025 | 2023-01-01 00:00:00+00:00 | 2025-12-31 00:00:00+00:00 | ACCUMULATION\|NEW_BULL\|BULL\|DISTRIBUTION\|EARLY_BEAR\|BEAR\|LATE_BULL\|DEEP_BEAR | 4 | 0.214733 | 0.938973 | 0.244745 | 0.760562 | 533025 | -0.363943 | 1 | 6 | 139 |
| correction_2025_2026 | 2025-01-01 00:00:00+00:00 | 2026-09-02 00:00:00+00:00 | EARLY_BEAR\|DISTRIBUTION\|BEAR\|ACCUMULATION\|NEW_BULL\|BULL\|DEEP_BEAR | 4 | 0.181173 | 0.93074 | 0.309971 | 0.809706 | 481532 | -0.287832 | 2 | 1 | 45 |

## J Law decision

- Champion: A — Fixed DCA.
- Challenger: V3-E20 — Fixed DCA + Macro Cycle Hedge.
- Return Edge: Challenger.
- Drawdown Edge: Challenger; substantive-gate PASS.
- Calmar Edge: Challenger.
- Cash Drag: average tactical cash 34.95%; material-cash time 91.63%; raw-positive time 91.63%.
- Timing Quality: May reaction PASS; February false-bull gate PASS.
- Crash Protection: 1 May-2021 event(s); all events and forward MAE/MFE are in `crash_override_audit_v3.csv`.
- False-Bull Risk: controlled in the February audit.
- Turnover: reduction gate FAIL versus V2-E20.
- Execution Integrity: PASS.
- Overfit Risk: Medium-high. The rules were frozen and no search was run, but the historical sample contains few independent macro cycles and a complex rule tree.

**FINAL VERDICT: V3 NEEDS REDESIGN**

## Important design boundary

The strict supplied FSM contains no bullish redeployment path for tactical cash produced by a Crash-only overlay or an aborted Distribution that never becomes a confirmed bear. This run does not invent one. Any resulting cash persistence is therefore a specification limitation, not silently relabelled as a successful hedge. The 20/30/40% floor remains a sell-time constraint; market moves may naturally push daily exposure below it.
