# Crypto Backtest & Forward Monitor

## 加密貨幣定投、週期避險與前瞻紙上驗證

這個專案研究一個問題：**長期持有 BTC／ETH 並固定投入資金時，加入牛熊週期判斷、分階段減碼與買回，能否改善單純定投的報酬與回撤？**

從 BTC／ETH／BNB 的歷史策略比較出發，專案逐步建立可追溯的回測引擎、獨立的 BNB 依賴性診斷，以及目前的 **BTC+ETH Macro Hedge V3.10**。V3.10 凍結後，再透過 Windows 桌面程式 **Crypto Forward Monitor**，與 V3.1 基準模型並行記錄新的紙上交易。

這是策略研究與監控工具，**不連接真實帳戶、不自動下單**。歷史 Champion 不代表未來保證；目前前瞻快照仍記錄 `FORWARD SAFETY FAIL`，詳見下方驗證狀態。

## 先看結果：四種做法有什麼不同？

以下是既有 BTC+ETH 凍結回測，期間為 **2020-01-01 至 2026-09-03 04:00 UTC**。

![BTC與ETH四套策略資產成長比較](v3_10/figures/08_asset_growth_comparison_2020.png)

| 策略 | 做法 | 最終總資產（USD） | TWR 年化報酬 | 最大回撤 | Calmar |
| --- | --- | ---: | ---: | ---: | ---: |
| 期初配置後持有 H0 | 起初配置 US$20,000，之後不追加、不交易 | $197,656.93 | 40.96% | -77.22% | 0.5304 |
| 單純定投 A | 固定追加資金，不做戰術減碼或買回 | $279,201.22 | 42.50% | -76.87% | 0.5529 |
| V3.1 基準模型 B | 定投 + 牛熊有限狀態機 + 分階段避險／買回 | $348,746.85 | 47.69% | -39.51% | 1.2070 |
| V3.10 歷史 Champion Q | V3.1 + 獨立 Stage3 熊市再進入確認 | $367,407.51 | 48.89% | -39.51% | 1.2374 |

四組起始資產皆為 US$20,000。A／B／Q 另追加 US$29,248，累計投入 US$49,248；H0 不追加，累計投入仍是 US$20,000。因此最終資產不能直接當作投資報酬率比較。

圖中橘線是 V3.10、藍線是單純定投、紫色點劃線是 V3.1、深灰虛線是期初配置後持有；淺灰點線只是定投型策略的累計投入本金，不是另一套策略。V3.9 與 V3.10 在這次歷史路徑上重疊，沒有另畫一條線。

**這段歷史中，V3.10 的期末資產較高、回撤較單純定投淺；但最大回撤仍達 39.51%，不是低風險策略，也未達「回撤不超過 30%」。**

數字來源：[比較 CSV](v3_10/results/asset_growth_comparison_summary_2020.csv) · [V3.10 完整報告與各項驗收門檻](v3_10/report/FINAL_REPORT_V3_10.md)。本 README 整理既有輸出，沒有重新跑回測或調整參數。

## 資金如何投入？

目前 BTC+ETH 主線沿用以下凍結條件：

- 起始 US$20,000：BTC US$8,750、ETH US$5,250、現金 US$6,000，即 70% 加密資產、30% 現金。
- 加密資產目標比例：**BTC 62.5%、ETH 37.5%**；這是加密部位內的比例，不是總資產永遠維持的比例。
- 每 4 小時固定追加 **US$2**。完整一天相當於 US$12，資金先進入帳本，不代表每 4 小時都一定成交。
- 單純定投按凍結的配置規則分配：權重在容許範圍內時按比例投入，偏離時優先補不足權重的資產；每筆買入不一定都是 62.5：37.5。
- 各資產待買資金先累積，達到模擬最低名目額 **US$5** 才能成交，因此沒有固定「每 8 小時買一次」的保證。
- 基準成本：手續費 **0.10%**、滑價 **0.05%**。US$5 最低額是歷史建模代理值，不是所有歷史時點交易所規則的證明。

避險模型重播 Model A 的固定定投承諾，額外的戰術減碼與買回使用分離帳本；不靠增加外部投入美化績效。詳見 [V3.1 凍結設定](config/config_frozen_v3_1.json)。

## V3.10 模型在做什麼？

主體是 **V3.1 FSM-only Model B**：根據已完成的市場資料，在牛市、派發、早期熊市、熊市、深熊、累積與新牛市等狀態間轉移，依凍結的 Stage、Crash Brake、Recovery 與 Buyback 規則調整加密資產曝險。

V3.10 的直接修改範圍僅限於原本的 **Stage3 熊市再進入**：符合資格後，以三個已完成日收盤的序列確認（候選當天算第 1 個），目的在減少過早進入熊市減碼。Stage4 與 Crash L1／L2 保留優先執行，不被這項等待延遲。它不是網格策略，也不是會自行訓練或調參的 AI 模型。

模型的**市場狀態、目標曝險與紙上持倉可以隨新資料改變；凍結的規則與參數不會自動改寫**。CAGR、回撤及 Calmar 等 Promotion Gates 只用於回測後評估，不能直接控制交易或反向搜尋參數。

精確語義：[V3.10 凍結設定](config/config_frozen_v3_10.json) · [執行前解讀凍結](design/V310_ASSUMPTIONS.md)。

## 避免 Look-ahead Bias 與可重現設計

- 訊號只使用當時已完成、已可取得的日 K 資料，於下一個可交易的 4H 開盤執行。
- 保存原始行情、來源清單、SHA-256 雜湊、凍結規則與執行環境紀錄。
- 缺失 K 線不捏造價格；尚未能成交的資金與意圖保留至合法執行時點。
- 每筆交易、訊號、每日資產與 FSM 轉移皆保留輸出，便於對帳及追溯版本差異。
- 候選事件的後續 30／60 日表現僅供事後診斷，不進入交易決策。

既有 V3.10 報告的 `NO_LOOK_AHEAD`、`EXECUTION_INTEGRITY` 與 `FSM_AUDIT` 為 PASS；這些是該次凍結執行的稽核結果，不代表所有版本或任何未來執行都自動通過。

## 為什麼還有 BNB 診斷？

早期三幣定投結果很強，因此另做完全獨立的 **Fixed DCA Universe Diagnostic**，比較 BTC-only、BTC+ETH、BTC+ETH+BNB，並以 2020／2021／2022／2023 四個起點重建新投資組合。

既有診斷分類為 **C. FIXED DCA RESULT STRONGLY BNB-DEPENDENT**：2020 起點中，BNB 占三幣組總獲利約 **50.33%**；移除 BNB、按原比例改配 BTC／ETH 後，期末資產下降約 **34.03%**。優勢在 2022 起點明顯縮小，2023 起點則略為反轉。

這份診斷的截止日是 **2026-09-02 08:00 UTC**，與上方 V3.10 比較不同，不應混用數字。診斷結果沒有回寫 V3 的牛熊判斷、Stage、Floor 或 Buyback 參數，也不能證明定投普遍優於一次買入。

詳見 [獨立診斷報告](universe_diagnostic/report/FIXED_DCA_UNIVERSE_DIAGNOSTIC.md)。

## Crypto Forward Monitor：從回測走向新資料驗證

Windows 繁體中文桌面介面提供：

- BTC／ETH 行情，以及並排的 V3.10 與 V3.1 紙上總資產、幣種／現金配置。
- 持倉均價與未實現盈虧；持倉盈虧不等於帳戶總報酬。
- 每日模型動作摘要：何時買賣、幣種、數量、金額與原因。
- 白話報告、歷史紀錄、執行日誌、凍結雜湊與前瞻樣本進度。

兩個前瞻帳戶是獨立的紙上測試，並非直接承接歷史回測的期末資產。行情自動刷新不會執行每日模型；模型須由使用者啟動。App 不會向交易所送出訂單。

### 前瞻驗證狀態（2026-10-05 快照）

既有 [前瞻檢查點](v3_10_forward/V310_FORWARD_CHECKPOINT.md) 記錄：

- 樣本外累積 **32 個日曆日**、已完成判定 Stage3 候選 **0 個**。
- 正式評估至少需要 **180 日**及 **3 個已完成候選**，目前不足。
- 當前判決仍為 **`D. V3.10 FORWARD SAFETY FAIL`**；凍結雜湊 PASS 不能取代整體安全驗收。

歷史回測的 Promotion 與前瞻安全判決是不同層級。原始異常及基礎設施修補紀錄均保留，沒有因介面改版而清除，也沒有為了通過驗收修改策略門檻。

操作及建置方式見 [桌面 App 說明](CryptoForwardMonitor/README.md)。GitHub 保存的是提交當下快照，新產生的本機紀錄不會自動同步。

## 專案導航

| 路徑 | 內容 |
| --- | --- |
| `src/crypto_backtest/`、`run_backtest*.py` | 策略引擎與各版本執行入口 |
| `config/`、`design/` | 凍結參數、設計決策與規則解讀 |
| `data/` | 原始行情及來源清單 |
| `v2/`、`v3/`、`v3_1/` 至 `v3_10/` | 歷代實驗的結果、報告、圖表與稽核；並非每版皆獲晉升 |
| `universe_diagnostic/` | 獨立的 BTC／ETH／BNB 定投診斷 |
| `v31_necessity_audit/` | V3.1 戰術事件與交易往返的反事實必要性稽核 |
| `v3_10_forward/` | 凍結 V3.10 與 V3.1 影子模型的前瞻帳本及檢查點 |
| `CryptoForwardMonitor/` | Windows 桌面監控介面與測試 |
| `tests/` | 回測引擎、輸出與完整性測試 |

早期版本入口：[V1 報告](report/FINAL_REPORT.md) · [V2 說明](v2/README_V2.md) · [V3 Macro FSM 報告](v3/report/FINAL_REPORT_V3.md) · [V3.1 說明](v3_1/README_V3_1.md)。

## 安裝、檢查與重現

在 Windows PowerShell、儲存庫根目錄建立環境：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r CryptoForwardMonitor\requirements.txt
```

先執行程式測試，不刷新行情或重跑策略：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests universe_diagnostic\tests
Push-Location CryptoForwardMonitor
..\.venv\Scripts\python.exe -m unittest discover -s tests -q
Pop-Location
```

如需重現 V3.10，建議在另一份工作副本執行，避免覆寫現有輸出：

```powershell
.\.venv\Scripts\python.exe run_backtest_v3_10.py
```

獨立 Universe 診斷使用 `universe_diagnostic/run_universe_diagnostic.py`。早期 V1 使用 `run_backtest.py`；精確重跑交付的行情時不要加入 `--refresh-data`，刷新資料會改變雜湊與截止日期。

桌面 App 首次使用前，請依 [GitHub 還原說明](GITHUB_README.md) 建立本機 `config.json`，設定模型命令與資料位置，再執行 `CryptoForwardMonitor/run_app.bat`。儲存庫不包含 EXE、Python 環境或本機 App 操作日誌，不能當作已安裝的桌面程式直接啟動。

## 解讀限制

TWR 年化報酬排除外部現金流影響；XIRR 反映資金投入時點；最大回撤使用現金流調整後的淨值，不能只由總資產圖直接讀取。完整報告另提供 Sharpe、Sortino、周轉率與事件分析。

即使沒有交易執行上的 Look-ahead Bias，反覆看歷史後提出版本仍有研究者選擇與過度擬合風險。V3.10 規則受到已觀察的 2023 路徑啟發；不同 rolling starts 又共用大部分行情，不能視為多次獨立驗證。

選幣存續偏差、歷史低基期、固定手續費／滑價代理、稅務、交易所中斷、穩定幣及託管風險也限制結果外推。本專案用可追溯的歷史比較提出待驗證假說，並持續保存前瞻證據；不把歷史報酬當作未來承諾。
