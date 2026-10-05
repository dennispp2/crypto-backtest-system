# BTC+ETH Macro Hedge V3.10 — Final Report

## 結論

**A. V3.10 STAGE3 CONFIRMATION PROMOTED**

Formal data end: `2026-09-03T04:00:00+00:00`. V3.10 的規則、解讀、來源 hashes 與 promotion gates 均在 Q 執行前凍結；沒有結果後調參，也沒有建立 V3.11。

## 正式績效

| model | Initial | External | Final | XIRR | TWR CAGR | Max DD | Sharpe | Sortino | Calmar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H0 | 20,000.00 | 0.00 | 197,656.93 | 40.96% | 40.96% | -77.22% | 0.8638 | 0.8382 | 0.5304 |
| A | 20,000.00 | 29,248.00 | 279,201.22 | 38.39% | 42.50% | -76.87% | 0.8859 | 0.8593 | 0.5529 |
| B | 20,000.00 | 29,248.00 | 348,746.85 | 43.72% | 47.69% | -39.51% | 1.2494 | 1.2136 | 1.2070 |
| P39 | 20,000.00 | 29,248.00 | 367,407.51 | 44.98% | 48.89% | -39.51% | 1.2694 | 1.2340 | 1.2374 |
| Q | 20,000.00 | 29,248.00 | 367,407.51 | 44.98% | 48.89% | -39.51% | 1.2694 | 1.2340 | 1.2374 |

## Promotion gates

- G0_INTEGRITY_ALL_PASS: **PASS**
- G1_Q_FINAL_ABOVE_B: **PASS**
- G2_UPLIFT_CAPTURE_GTE_75PCT: **PASS**
- G3_TWR_CAGR_GTE_48_4PCT: **PASS**
- G4_OVERALL_DD_WORSEN_LTE_0_5PP: **PASS**
- G5_2022_BEAR_DD_WORSEN_LTE_1PP: **PASS**
- G6_2025_2026_DD_WORSEN_LTE_1PP: **PASS**
- G7_STAGE4_AND_CRASH_INTEGRITY: **PASS**
- G8_CALMAR_NOT_BELOW_B: **PASS**
- G9_TURNOVER_INCREASE_LTE_5PCT: **PASS**
- G10_ROLLING_START_ROBUSTNESS: **PASS**
- COVID_DD_WORSEN_LTE_0_5PP: **PASS**
- MAY_2021_DD_WORSEN_LTE_0_5PP: **PASS**

精確 75% uplift 門檻為 US$362,742.34；Q 捕捉率為 100.00%。

## Integrity

- V3_1_REPLAY: **PASS**
- V3_9_REPLAY: **PASS**
- FIXED_DCA_INTEGRITY: **PASS**
- NO_LOOK_AHEAD: **PASS**
- EXECUTION_INTEGRITY: **PASS**
- FSM_AUDIT: **PASS**
- STAGE3_SCOPE_INTEGRITY: **PASS**
- CAUSAL_LINEAGE: **PASS**
- BEARISH_REBREAK_SCOPE: **PASS**
- FROZEN_SOURCE_HASHES: **PASS**

## 27 個指定問題

1. **V3.1 是否完整重現？** 是；Final US$348,746.85。
2. **V3.9 是否完整重現？** 是；Final US$367,407.51。
3. **V3.10 Final？** US$367,407.51。
4. **B/P39/Q Final？** US$348,746.85 / US$367,407.51 / US$367,407.51。
5. **B/P39/Q CAGR？** 47.69% / 48.89% / 48.89%。
6. **B/P39/Q Max DD？** -39.51% / -39.51% / -39.51%。
7. **Q 捕捉多少 V3.9 Return Uplift？** 100.00%；Q-B US$18,660.65，P39-B US$18,660.65。
8. **Stage3 Candidates？** 2。
9. **Reject？** 2。
10. **Confirmed？** 0。
11. **SMA200 Hard Failure 結束？** 1。
12. **2023/3 是否再次正確 Reject？** 是。
13. **2023/8 真正弱化後是否回 Bear？** 是，hard failure 取消等待並交回 V3.1 FSM。
14. **2023/11 Drift 差異？** INDIRECT_PATH_DIFFERENCE；不是 direct Drift blocking。
15. **2024/2 Drift 差異？** INDIRECT_PATH_DIFFERENCE；不是 direct Drift blocking。
16. **2024/11 Drift 差異？** INDIRECT_PATH_DIFFERENCE；不是 direct Drift blocking。
17. **2021 大頂防守是否變差？** 沒有；2022 event guardrail 通過。
18. **2022 Bear DD？** B -28.25%；Q -28.25%。
19. **2025→2026 DD？** B -28.24%；P39 -26.68%；Q -26.68%。
20. **2025/11 Stage4 完整執行？** 是。
21. **COVID 是否惡化？** B -29.71%；Q -29.71%；未超過 0.5pp。
22. **May Crash 是否惡化？** B -33.20%；Q -33.20%；未超過 0.5pp。
23. **Turnover 是否明顯增加？** B 9.3677x；Q 9.3664x；通過 +5% 上限。
24. **Rolling Starts 幾組 Q>B？** 4/4；這些高度重疊，不是獨立樣本。
25. **無法追溯的交易差異？** 0 筆；scope unexpected 0 筆。
26. **V3.9 的約 +18.7K 主要來自 Stage3 Confirmation？** 支持：至少捕捉 frozen 75% 門檻；這是 deterministic path attribution，不是未來因果保證。
27. **單一修改是否值得取代 V3.1？** 是；且僅因全部 frozen gates 通過。

## J Law Verdict

| Dimension | Finding |
| --- | --- |
| Champion | V3.10 Q |
| Reference Challenger | V3.9 P39 |
| Isolated Challenger | V3.10 Q |
| Baseline Integrity | PASS |
| Stage3 Scope Integrity | PASS |
| Causal Isolation Quality | 0 unexplained trade differences |
| Stage3 Confirmation Edge | 支持：至少捕捉 frozen 75% 門檻 |
| Return Edge | Q-B US$18,660.65 |
| Uplift Capture | 100.00% |
| Overall Drawdown | B -39.51%; Q -39.51% |
| 2022 Bear Protection | B -28.25%; Q -28.25% |
| 2025-2026 Protection | B -28.24%; Q -26.68% |
| Stage4 Integrity | PASS |
| Crash Integrity | PASS |
| Rolling Start Robustness | Q>B in 4/4 starts |
| Turnover | B 9.3677x; Q 9.3664x |
| Path Dependency Risk | HIGH: one delayed transition changes all later notionals |
| Overfit Risk | HIGH: rule was motivated by the previously observed 2023 path |
| No Look Ahead | PASS |

## Rolling-start sensitivity

| fresh_start | end | B_final_portfolio_value | B_twr_cagr | B_maximum_drawdown | B_calmar | P39_final_portfolio_value | P39_twr_cagr | P39_maximum_drawdown | P39_calmar | Q_final_portfolio_value | Q_twr_cagr | Q_maximum_drawdown | Q_calmar | delta_final_P39_minus_B | delta_cagr_P39_minus_B_pp | delta_max_dd_P39_minus_B_pp | delta_calmar_P39_minus_B | delta_final_Q_minus_B | delta_cagr_Q_minus_B_pp | delta_max_dd_Q_minus_B_pp | delta_calmar_Q_minus_B |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2020-01-01 | 2026-09-03 04:00:00+00:00 | 348746.8528777533 | 0.4769146261923145 | -0.3951313419600695 | 1.2069774668507813 | 367407.5071839701 | 0.4889459126578033 | -0.3951313419600695 | 1.2374262953486852 | 367407.5071839701 | 0.4889459126578033 | -0.3951313419600695 | 1.2374262953486852 | 18660.654306216806 | 1.2031286465488789 | 0.0 | 0.030448828497903868 | 18660.654306216806 | 1.2031286465488789 | 0.0 | 0.030448828497903868 |
| 2021-01-01 | 2026-09-03 04:00:00+00:00 | 113504.2214857935 | 0.26212659448560016 | -0.39170703601425116 | 0.6691904162683037 | 115196.28412236723 | 0.266479344292992 | -0.39170703601425116 | 0.6803026746838853 | 115196.28412236723 | 0.266479344292992 | -0.39170703601425116 | 0.6803026746838853 | 1692.0626365737262 | 0.43527498073918647 | 0.0 | 0.01111225841558161 | 1692.0626365737262 | 0.43527498073918647 | 0.0 | 0.01111225841558161 |
| 2022-01-01 | 2026-09-03 04:00:00+00:00 | 65294.44073718971 | 0.13453363012623698 | -0.3040240153990946 | 0.4425098785358573 | 66601.42178368322 | 0.14161922595033927 | -0.3053581252362788 | 0.4637807683707702 | 66601.42178368322 | 0.14161922595033927 | -0.3053581252362788 | 0.4637807683707702 | 1306.9810464935144 | 0.7085595824102286 | -0.1334109837184183 | 0.021270889834912876 | 1306.9810464935144 | 0.7085595824102286 | -0.1334109837184183 | 0.021270889834912876 |
| 2023-01-01 | 2026-09-03 04:00:00+00:00 | 67876.75965553417 | 0.2649287529201856 | -0.3028888191623995 | 0.8746732667544888 | 71864.1200072798 | 0.2887670186914304 | -0.2758579034154309 | 1.0467962495044374 | 71864.1200072798 | 0.2887670186914304 | -0.2758579034154309 | 1.0467962495044374 | 3987.3603517456213 | 2.3838265771244815 | 2.7030915746968587 | 0.17212298274994864 | 3987.3603517456213 | 2.3838265771244815 | 2.7030915746968587 | 0.17212298274994864 |

## 事實、推論與限制

- **事實：** H0/A/B/P39/Q 使用同一 frozen BTC/ETH 資料、成本、滑價、最低名目額與 Model A DCA commitment；Q 沒有 Drift Sell Guard、AI、額外曝險目標或新 AHR 門檻。
- **推論：** Uplift capture 是這條歷史價格路徑上的 deterministic counterfactual attribution。它能回答程式路徑來源，不能證明未來市場的因果效果。
- **偏差：** Stage3 規則由先前看到的 2023 事件所啟發，存在研究者自由度、multiple-testing 與歷史事件選擇偏差。四個 rolling starts 共用終點及大部分資料，不能當作四次獨立驗證。
- **容易忽略的成本／變數：** 稅務、交易所中斷、stablecoin 與託管風險、滑價尾部、容量、BTC/ETH 權重漂移和 4H open 可成交性均未由此回測完全識別。

## Reproduction

Run `.venv\Scripts\python.exe run_backtest_v3_10.py`. Frozen semantics are in `design/V310_ASSUMPTIONS.md`; hashes and environment are in `v3_10/artifacts/run_manifest_v3_10.json`.
