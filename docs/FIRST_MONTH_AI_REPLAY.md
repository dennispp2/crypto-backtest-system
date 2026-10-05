# V3.10＋GPT 首月探索性重播

這個測試只回答：在原前瞻帳本的最初 30 天，加入 GPT 額外曝險調整，
與純 V3.10 的資產、報酬、回撤與成本差多少。它不證明長期 AI 優勢，
也不是 AI 已實際前瞻運行一個月的紀錄。

## 2026-10-05 完成結果

Run：`artifacts/ai_shadow_local/v310_gpt_first_month/20261005T151124673749Z`。
實際完成 30 / 30 次 `gpt-5.6-sol` 判讀，必需宏觀資料可用 30 / 30 日。
兩組初始估值 US$20,000，各追加 US$360。

| 指標 | 純 V3.10 | V3.10＋AI 歷史 overlay |
| --- | ---: | ---: |
| 最終資產 USD | 21,943.35 | 21,966.55 |
| TWR | +7.84% | +7.96% |
| Maximum Drawdown | -4.85% | -4.92% |
| 成交筆數 | 87 | 89 |

AI 多 US$23.20，但回撤略大；不構成 AI 長期優勢的證據。
有 2 次 ADD 請求、28 次 HOLD；一次 ADD 被保護現金規則阻擋，另一次產生 2 筆資產買入。
原凍結雜湊及原前瞻帳本前後一致，無干預重播一致性 PASS。
完整 AI `NO_LOOK_AHEAD` 仍為 `NOT_CERTIFIED_MODEL_MEMORY_RISK`。

本歷史 overlay 在合成帳本上執行完整凍結 V3.10 引擎，再加 AI 干預。
目前 App 的 `v310_combined_v1` 是 AI 以量化狀態為基線決策、分離紙上執行；
HOLD 不自動複製純版交易。兩者政策／執行方式不同，不能把本次歷史績效當成
目前 App 合成策略已驗證的績效。即時綜合帳本只接續目前保存的持倉，未匯入本測試獲利。

介面驗證用的 mock 視窗必須有「模擬資料，非正式帳戶」提示，不使用正式帳本。

## 資金與策略邊界

- 時間：2026-09-03 08:00 至 2026-10-03 08:00 UTC，180 根完整 4H。
- 從保存的前瞻截點部位、一般現金、DCA 緩衝及戰術現金開始；
  截點估值為 US$20,000，不重建 70/30 的新組合。
- 不把今天的持倉回填過去，不把歷史 Champion 的 US$367k 當本金。
- 兩組各追加 US$360，即原規則 US$2 / 4H。
- 先執行凍結 V3.10 原交易引擎，再允許 GPT 額外提議加減曝險；
  AI 決策在下一根 4H 開盤才可執行。
- 原本的 Stage4 / Crash 優先、20% floor、單次 20 個百分點限制、
  95% 最大主動目標、信心門檻、保護現金、費用與滑價規則不變。
- 僅紙上歷史模擬；不下真實單，不寫目前 App 的資產帳本。原始重播資料留本機，不推送 GitHub；本說明與重播程式可公開。

前瞻資料截點和正式凍結執行時間不是同一概念。原前瞻設定的凍結時間在
2026-09-04；本測試以原帳本 9/3 的估值截點作比較起點。這是回溯重播，
不能把整段宣稱為 AI 的真正 out-of-sample forward test。
原帳本的早期執行異常紀錄與正式評估狀態不因此被清除或改判。

## 資料與限制

Python 從已保存的 Binance 日 K 計算技術指標，依每個決策截點排除未完成日 K。
宏觀使用 ALFRED 歷史版本，不以最新修訂值倒填；可用時間沿用已批准的
保守規則：vintage date 後兩天 UTC00。月統計、日序列新鮮度門檻不因測試結果調整。

必需資料：V3.10／持倉、BTC／ETH 技術面、2Y／10Y、美國利率、CPI、PCE、NFP。
必需資料不足則不呼叫 GPT 干預，原 V3.10 繼續。缺漏的新聞、DXY、衍生品、
ETF、穩定幣、鏈上資料不能自行補值。此次 VIX 匯出未通過時間順序檢查，排除。
不讓歷史 GPT 呼叫當前 web search。

目前 GPT 可能記得後來的事件，無法僅靠提示排除。
所以資料輸入的 point-in-time 檢查可以通過，但完整 AI 的
`NO_LOOK_AHEAD` 不能認證 PASS。這是使用者已接受此限制的有限資料探索版。

## 執行與重現

在專案根目錄執行，使用既有 ChatGPT 方案授權及 `gpt-5.6-sol`，沒有付費 API 備援：

```powershell
.venv/Scripts/python.exe -X utf8 -u scripts/backtest_v310_gpt_month.py `
  --source-audit artifacts/ai_shadow_local/historical_external_data_v1/audit_20261005T133255568224Z `
  --accept-model-memory-risk --user-approved-limited-data --verify-only
```

先核對保留部位、原帳本雜湊、全部月份估值、以及無干預 hook 的行列一致性，
再用上述輸出目錄作 `--resume` 跑真實 GPT。只有已完整回覆並保存的決策才能重用；
snapshot、政策、程式或資料雜湊不一致則拒絕續跑。不可為重現較好績效反覆重抽決策。

```powershell
.venv/Scripts/python.exe -X utf8 -u scripts/backtest_v310_gpt_month.py `
  --source-audit artifacts/ai_shadow_local/historical_external_data_v1/audit_20261005T133255568224Z `
  --accept-model-memory-risk --user-approved-limited-data --resume <驗證完成的目錄>
```

輸出在忽略上傳的 `artifacts/ai_shadow_local/v310_gpt_first_month/<UTC run>/`。
`run_receipt.json` 的 `gpt_decisions_completed / total_daily_decision_dates` 是實際進度；
`test_window_completed` 才代表這個 30 天測試完成。
`full_period_completed=false` 表示沒有重新跑完原本 2020–2026 的全期任務。

保存原始宏觀下載、獨立重解析結果、逐日 snapshot／GPT 回覆／成交原因、
程式與政策副本、兩組 4H 資產曲線及費用。中斷或關機後不會自行繼續，
必須明確執行 `--resume`，已保存且匹配的決策不重複呼叫。

績效獨立核算：TWR 逐根排除外部追加資金，回撤採 unit NAV 並包含起始估值。
只測 30 天不輸出年化 CAGR／Sharpe／Calmar，也不因輸出結果調整交易門檻。

完成後生成圖表：

```powershell
.venv/Scripts/python.exe -X utf8 -u scripts/plot_month_gpt_comparison.py --run <完成的目錄>
```

未完成或完整性未通過的 run 不可產生「整月完成」圖。
