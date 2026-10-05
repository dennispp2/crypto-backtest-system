# BTC+ETH Macro Hedge V3.9 — Final Report

## 結論

**D. V3.9 REJECTED - NO MATERIAL BULL EDGE**

Formal data end: `2026-09-03T04:00:00+00:00`. V3.9 的規則與 promotion gates 均在 Challenger 執行前凍結；沒有結果後調參，也沒有建立 V3.10。

## 正式績效

| model | Initial | External | Final | XIRR | TWR CAGR | Max DD | Sharpe | Sortino | Calmar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H0 | 20,000.00 | 0.00 | 197,656.93 | 40.96% | 40.96% | -77.22% | 0.8638 | 0.8382 | 0.5304 |
| A | 20,000.00 | 29,248.00 | 279,201.22 | 38.39% | 42.50% | -76.87% | 0.8859 | 0.8593 | 0.5529 |
| B | 20,000.00 | 29,248.00 | 348,746.85 | 43.72% | 47.69% | -39.51% | 1.2494 | 1.2136 | 1.2070 |
| P | 20,000.00 | 29,248.00 | 367,407.51 | 44.98% | 48.89% | -39.51% | 1.2694 | 1.2340 | 1.2374 |

## Promotion gates

- G0_INTEGRITY_ALL_PASS: **PASS**
- G1_BULL_AVG_EXPOSURE_DELTA_GTE_10PP: **FAIL**
- G2_BULL_TIME_GTE85_DELTA_GTE_15PP: **FAIL**
- G3_FINAL_VALUE_GTE_V31: **PASS**
- G4_TWR_CAGR_GTE_47_5PCT: **PASS**
- G5_2021NOV_2022JUN_DD_WORSEN_LTE_2PP: **PASS**
- G6_2025_2026_DD_WORSEN_LTE_2PP: **PASS**
- G7_COVID_DD_WORSEN_LTE_1PP: **PASS**
- G8_MAY_2021_DD_WORSEN_LTE_1PP: **PASS**
- G9_2025_11_STAGE4_EXECUTED: **PASS**
- G10_CRASH_L1_L2_NOT_SUPPRESSED: **PASS**
- G11_CALMAR_NOT_BELOW_V31: **PASS**
- G12_TURNOVER_INCREASE_LTE_10PCT: **PASS**

## Integrity

- V3_1_REPLAY: **PASS**
- FIXED_DCA_INTEGRITY: **PASS**
- NO_LOOK_AHEAD: **PASS**
- EXECUTION_INTEGRITY: **PASS**
- FROZEN_SOURCE_HASHES: **PASS**

## 24 個指定問題

1. **B 是否完整重現？** 是；Final US$348,746.85、CAGR 47.69%、Max DD -39.51%、turnover 9.3677x。
2. **P 最終資產？** US$367,407.51。
3. **B/P CAGR？** 47.69% / 48.89%。
4. **B/P Max DD？** -39.51% / -39.51%。
5. **2023–2025 平均曝險？** B 58.84%；P 59.56%，差 +0.72 pp。
6. **>=85% 曝險時間？** B 3.09%；P 3.09%，差 +0.00 pp。
7. **阻擋多少 Drift Sell？** 0 筆。Audit 共列出 3 個 V3.1 shadow drift 日；其餘會明示 `NOT_EXECUTED_GUARD_INACTIVE`，不能冒充 Guard 功效。
8. **阻擋後 30/60 日 BTC 上漲幾筆？** 0/0；這是 ex-post audit，沒有進入訊號。
9. **Stage3 candidate 最終 Reject？** 2 個。
10. **真正確認 Bear Re-entry？** 0 個。
11. **2023/3 是否仍過早重新 Bear？** 沒有；原 Stage3 candidate 被三日規則拒絕。
12. **2023/11 是否仍過早降低曝險？** P 沒有執行該 Drift Sell，但不是直接被 Guard 阻擋；Persistence 已於 2023/8 SMA200 hard failure 結束，P 因較晚執行 Stage3 而未達 drift +10pp 觸發門檻。
13. **2024/2 是否仍過早降低曝險？** P 沒有執行該 Drift Sell；同樣是前述曝險路徑差異，不是 Guard 當日直接阻擋。
14. **2024/11 風險動作？** B 執行 Drift Sell，P 未執行；Guard 當日已關閉，故不可歸功於 direct blocking。
15. **2021 大頂是否因 Guard 多虧？** 沒有可見交易差異。Guard 曾在 2020/5 NEW_BULL 後啟動，並於 2021/5 Crash 解除；B/P 在 2021–2022 窗口的 DD 相同，為 -28.25% / -28.25%。
16. **2022 Bear DD 是否保持？** 是；B/P -28.25% / -28.25%。
17. **2025→2026 DD 是否仍約 30% 內？** 是；P 為 -26.68%。
18. **2025/11 Stage4 完整執行？** 是；詳見 `stage4_integrity_v3_9.csv`。
19. **COVID 是否惡化？** B/P -29.71% / -29.71%，未超過 1pp。
20. **May Crash 是否惡化？** B/P -33.20% / -33.20%，未超過 1pp。
21. **Final Wealth 高於 V3.1？** 是；差額 US$18,660.65。
22. **提高 bull participation 是否付出不可接受 DD？** 沒有通過既定事件 DD 門檻判定出不可接受代價。
23. **是否解決健康牛市過早 Bear，而非製造熊市反應過慢？** 不能這樣下結論；bull edge 或 bear-safety 證據至少一項不足。
24. **值得取代 V3.1？** 否；未通過全部 frozen promotion gates。

## J Law Verdict

| Dimension | Finding |
| --- | --- |
| Champion | V3.1 B |
| Challenger | V3.9 P |
| Bull Persistence Quality | FAIL |
| Bear Re-entry Quality | 0 confirmed / 2 rejected |
| Bull Participation Edge | avg exposure +0.72 pp |
| Return Edge | final wealth +18,660.65 |
| 2022 Bear Protection | PASS |
| 2025-2026 Bear Protection | PASS |
| COVID Protection | PASS |
| May Crash Protection | PASS |
| Stage4 Integrity | PASS |
| Crash Integrity | PASS |
| Cash Drag | B 96.23%; P 96.23% |
| Turnover | B 9.3677x; P 9.3664x |
| Rolling Start Robustness | P higher final value in 4/4 starts |
| No Look Ahead | PASS |
| Overfit Risk | HIGH: one historical path and audit-motivated one-change hypothesis |

## Rolling-start sensitivity

| fresh_start | end | B_final_portfolio_value | B_twr_cagr | B_maximum_drawdown | B_calmar | P_final_portfolio_value | P_twr_cagr | P_maximum_drawdown | P_calmar | delta_final_p_minus_b | delta_cagr_p_minus_b_pp | delta_max_dd_p_minus_b_pp | delta_calmar_p_minus_b |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2020-01-01 | 2026-09-03 04:00:00+00:00 | 348746.8528777533 | 0.4769146261923145 | -0.3951313419600695 | 1.2069774668507813 | 367407.5071839701 | 0.4889459126578033 | -0.3951313419600695 | 1.2374262953486852 | 18660.654306216806 | 1.2031286465488789 | 0.0 | 0.030448828497903868 |
| 2021-01-01 | 2026-09-03 04:00:00+00:00 | 113504.2214857935 | 0.26212659448560016 | -0.39170703601425116 | 0.6691904162683037 | 115196.28412236723 | 0.266479344292992 | -0.39170703601425116 | 0.6803026746838853 | 1692.0626365737262 | 0.43527498073918647 | 0.0 | 0.01111225841558161 |
| 2022-01-01 | 2026-09-03 04:00:00+00:00 | 65294.44073718971 | 0.13453363012623698 | -0.3040240153990946 | 0.4425098785358573 | 66601.42178368322 | 0.14161922595033927 | -0.3053581252362788 | 0.4637807683707702 | 1306.9810464935144 | 0.7085595824102286 | -0.1334109837184183 | 0.021270889834912876 |
| 2023-01-01 | 2026-09-03 04:00:00+00:00 | 67876.75965553417 | 0.2649287529201856 | -0.3028888191623995 | 0.8746732667544888 | 71864.1200072798 | 0.2887670186914304 | -0.2758579034154309 | 1.0467962495044374 | 3987.3603517456213 | 2.3838265771244815 | 2.7030915746968587 | 0.17212298274994864 |

## Regime transition audit

| model | bull_to_bear_transitions | bear_to_bull_transitions | average_bull_duration_days | average_bear_duration_days | false_short_bear_episodes_lt_30d |
| --- | --- | --- | --- | --- | --- |
| B | 3 | 2 | 160.66666666666666 | 652.0 | 0 |
| P | 3 | 2 | 214.33333333333334 | 598.3333333333334 | 0 |

## 事實、推論與限制

- **事實：** 表中數字是同一批 frozen BTC/ETH bars、同一費用／滑價、同一 Model A DCA commitment 下的實際回放結果。
- **推論：** 「避免過早 Bear」只表示在這條歷史路徑上，指定事件與 gates 呈現該特徵；不是未來報酬保證，也不是因果證明。
- **成本與偏差：** 研究假說源自先前 Necessity Audit，存在 selection / multiple-testing 風險；四個 rolling starts 共用大量重疊資料與同一終點，不能視為四個獨立樣本。
- **容易忽略的變數：** 實盤容量、稅務、交易所中斷、stablecoin／託管風險、滑價尾部、BTC/ETH 權重漂移，以及 V3.1 FSM 在深熊／累積狀態的高頻轉換，都不由這個單一路徑回測充分識別。

## Reproduction

Run `.venv\Scripts\python.exe run_backtest_v3_9.py`. Frozen interpretation details are in `design/V39_ASSUMPTIONS.md`; hashes and environment are in `artifacts/run_manifest_v3_9.json`.
