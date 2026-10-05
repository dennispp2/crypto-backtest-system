# GPT Shadow Portfolio Manager 本機試用驗證報告

驗證日期為 2026-10-05。此報告對應 Crypto Forward Monitor 的獨立 `AI_SHADOW_V1`，不是重新設計 V3.10，也不宣稱 AI 已有歷史超額報酬。

## 後續更新（2026-10-06）

以下 A–X 保留初版驗證當下的紀錄，並非目前功能、測試數量或發布狀態的總結。程式與文件先發布至 `feature/gpt-shadow-portfolio-manager`，隨後依使用者追加授權合併至 `main`；私人帳本及憑證仍留本機。

後續已完成 30 次真實 `gpt-5.6-sol` 首月歷史探索判讀，詳見 [首月重播結果](FIRST_MONTH_AI_REPLAY.md)。這不等於目前 App 完整即時運行驗收通過；歷史 overlay 與 App 的分離綜合帳本執行政策不同，完整 AI 無前視驗證仍不能認證 PASS。初版的 NOT_RUN／未推送等文字只描述當時狀態，不否定後續紀錄。

目前資產總覽左側是 V3.10＋AI，右側是純 V3.10；最新連線與操作方式以 [App 使用說明](../CryptoForwardMonitor/README.md) 為準。原始安全失敗與凍結門檻沒有改判。

本次發布前檢查：root／universe／AI 的 pytest 為 **236 passed**，App unittest 為 **93 tests OK**，合計 329；7 個凍結核心檔案雜湊一致。README 本地連結與程式碼區塊、Git whitespace 檢查通過。本次未呼叫真實 GPT，沒有因發布而重跑交易引擎或重設私人資產。

## 初版驗證快照

目前判定為 **LOCAL_TRIAL_READY**：程式、mock 回歸、Windows EXE 建置與離線啟動可供本機試用。真實 OAuth／GPT 為 **NOT_RUN**，完整 V3.10 逐資產成交筆數比較為 **PARTIAL**。因此不能宣稱所有 live／比較驗收已完成。依使用者最新授權，修改保留在本機，不提交、不推送；`main` 未改動。

## A 修改檔案

- `.gitignore`：隔離 AI runtime 與本機 QA 證據。
- `CryptoForwardMonitor/app.py`：單一每日流程、主執行緒顯示、離線 EXE smoke 模式、關閉時清理自身 callback。
- `CryptoForwardMonitor/controller.py`：原本 V3.10 runner 保持獨立，新增更上層 daily cycle。
- `CryptoForwardMonitor/ui.py`：新增 AI 決策導覽、GPT Shadow 卡片與設定入口。
- `CryptoForwardMonitor/requirements.txt`、`build_exe.bat`：OAuth／schema／安全憑證依賴與打包資源。
- `README.md`、`CryptoForwardMonitor/README.md`、`GITHUB_README.md`：試用、保存範圍和安全限制。

## B 新增檔案

以下依責任列出完整新增程式群；沒有將 AI 塞入 Frozen Engine。

| 位置 | 檔案 |
| --- | --- |
| 桌面整合 | `CryptoForwardMonitor/ai_integration.py`、`ai_ui.py`、`tests/test_ai_gui.py` |
| AI 流程 | `ai_shadow/orchestrator.py`、`daily_cycle.py`、`configuration.py`、`errors.py`、`__init__.py` |
| 快照與指標 | `snapshot.py`、`technical.py`、`schemas/market_snapshot.schema.json` |
| 決策 | `decision_engine.py`、`decision_models.py`、`schemas/ai_decision.schema.json`、`policy/decision_policy_v1.md` |
| 網路與 AI client | `http.py`、`clients/base.py`、`clients/chatgpt_plan.py`、`clients/mock.py`、`clients/__init__.py` |
| OAuth | `auth/chatgpt_auth.py`、`auth/oidc.py`、`auth/token_store.py`、`auth/__init__.py` |
| 公開來源 | `providers/base.py`、`binance.py`、`macro.py`、`liquidity.py`、`providers/__init__.py` |
| 紙上帳戶 | `portfolio.py`、`risk_gateway.py`、`paper_broker.py`、`storage.py`、`audit.py`、`metrics.py`、`benchmark_costs.py` |
| AI 依賴 | `ai_shadow/requirements.txt` |
| AI 測試 | `test_auth.py`、`test_security_auth.py`、`test_client.py`、`test_snapshot.py`、`test_technical.py`、`test_providers.py`、`test_risk.py`、`test_paper.py`、`test_storage.py`、`test_orchestrator.py`、`test_daily_cycle.py`、`test_contracts.py`、`test_delivery.py`、`test_benchmark_costs.py`，均在 `ai_shadow/tests/` |
| 驗證工具 | `scripts/audit_public_repository.py`、`validate_ai_shadow.py`、`qa_ai_ui.py`、`smoke_ai_exe.py`、`replay_frozen_v310.py` |
| 交付報告 | `docs/AI_SHADOW_V1_ACCEPTANCE_REPORT.md` |

## C Frozen SHA256 Before 與 After

下表的 Before 和 After 相等，7 項全部 PASS。完整兩欄機器紀錄在本機 `artifacts/ai_shadow_local/acceptance_receipt.json`。SHA256 能證明檔案位元組未變，不能替代策略經濟有效性的驗證。

| 檔案 | Before 等於 After 的 SHA256 | 結果 |
| --- | --- | --- |
| `run_forward_v3_10.py` | `ad1cc0c5d024909128da0ea2196978dd2e25375b61337d35d0752426c74aacad` | PASS |
| `src/crypto_backtest/v310_engine.py` | `7caaf9dfdaccf3d0d1c2c9fc9dcbadc808acfad27b45ff5d876f46d643507289` | PASS |
| `src/crypto_backtest/v310_forward.py` | `b1293cdeac5a3597a97d8ba21d76ed2f0f14dd97edb22d60c0f434f3225e7875` | PASS |
| `src/crypto_backtest/v31_engine.py` | `ea91309e5821431210998cf2289965adad8991cc97005105cceab9037aeae2a1` | PASS |
| `config/config_frozen_v3_10.json` | `a0a7db91f1c93782f01a158a807370dd80acc0f3378ce74c39d38186c6cf7e64` | PASS |
| `config/config_frozen_v3_10_forward.json` | `d30fff5b54f7a7e9d9eea6cce08912e08ccc8ec8b7e984f3c8893145de3b209d` | PASS |
| `config/config_frozen_v3_1.json` | `50adc23c620d068087842ca574f8d4f87a8b6de3d96ebca0392184c43574bc84` | PASS |

## D Security Audit

可達 Git 歷史有 2 個 commits、872 個 unique blobs；300 個含二進位資料的 blobs 未內容掃描。可版本化工作樹與歷史文字的 bounded pattern scan 未找到憑證候選；最終另掃描 66 個修改／新增文字檔，也為 0 個候選。既有 5 個來源／凍結設定仍含本機路徑，沒有為了公開化而改寫 Frozen 檔案。找不到 LICENSE，未自行替專案選擇授權。

這不是完整安全認證：未安裝／執行 gitleaks，任意二進位或編碼秘密不在模式掃描保證範圍。新的 runtime、帳號 metadata、EXE 與 QA 證據均被 Git 忽略。沒有修改歷史、清除使用者檔案、上傳 credentials 或改變 repository 權限。

## E OAuth 流程

依目前官方 [Sign in with ChatGPT 文件](https://developers.openai.com/siwc/token-sharing-open-source/sign-in) 實作：啟動 loopback listener 後開啟官方授權頁，使用 PKCE S256、隨機 state／nonce、穩定 host UUID 與必要 scopes。首次以 `dynamic_agent_client` 開始，保存回傳的 issued client ID，後續重新登入沿用該 registration，不使用 Codex runtime。

授權頁與 token endpoint 是 `auth.openai.com/api/accounts/authorize` 與 `auth.openai.com/api/accounts/oauth/token`；resource 為 `https://api.openai.com/v1`。Listener 只綁 `127.0.0.1` 的 `/auth/callback`。ID Token 依 OIDC discovery／JWKS 驗證簽名、issuer、issued audience、exp、nonce 及重新登入時 subject。Live discovery endpoint 已唯讀核實；未替使用者完成登入。

## F Credential Storage

明確使用 Windows `WinVaultKeyring`，不回退到 plaintext backend。Token bundle 分割為小段，全部寫入 Windows Credential Manager 後才原子更新 manifest 指標；載入時驗證 SHA256。Credential blobs 與 manifest 都不在 JSON／SQLite／Git 中。

App 本機 `accounts.json` 只含 host、registration、issued client、subject、email 與授權旗標，受 Git 忽略。Journal 拒絕 credential 欄位與可識別的 token 文字。大 token bundle／失敗 rotation 已用 fake Windows backend 驗證，EXE 已驗證 backend 可匯入；**沒有讀寫使用者真實 vault entries**。

## G Token Refresh

每個 registration 使用 OS process lock。Refresh 沿用 issued client，送 `grant_type=refresh_token`，不重送擴張 scope；遵守 earliest refresh time。成功後原子替換全部 rotating bundle，account subject 綁定不變。Invalid grant 要求重新登入，不無限 retry。

登出經 discovery 取得官方撤銷 endpoint，嘗試撤銷，無論遠端成功與否都清理該 registration 的本機憑證。若遠端未確認，UI 明確告知。遠端真實撤銷／refresh 尚未 live 驗證。參照 [profiles and sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)。

## H Responses API 格式

使用 `POST https://api.openai.com/v1/responses` 和 OAuth bearer，`store=false`、`stream=true`、array `input`、`instructions`、`text.format=json_schema`、`strict=true`。不送 temperature／max tokens 等未列入 allowlist 的預設；不使用 API Key、非官方 ChatGPT endpoint 或付費 API 備援。

只有完整 `response.completed` 才能產生決策；failed、incomplete、refusal、逾時或串流中斷都不成交。只讀 message output，不保存 hidden reasoning。`USAGE_UNAVAILABLE` 最多一次短暫 retry，usage limit 不 retry。官方格式來源：[models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)。Live inference 未執行。

## I Model selection

`GET /v1/models` 解析官方 `models` array，只顯示 visibility 為 list 的項目。UI 顯示 display name 及 slug，Genesis 保存 slug 和 account registration，每次執行重新檢查帳號模型可用性。不能因另一個帳號曾列出模型就沿用其資格；更換 account／model 需新實驗。

## J External Data sources

實測為 2026-10-05 的公開唯讀 GET，不需要交易所 API Key。每個 leaf 保留 source、source timestamp、fetched timestamp、status 與 freshness；FRED 的 observation date 另外保存，不能冒充發布時間。

| 資料 | 來源及 public 狀態 | Freshness 與實測 | Fallback |
| --- | --- | --- | --- |
| BTC／ETH spot、完成日 K | Binance Spot public REST | 399 根完成日 K；indicator asof 2026-10-04 UTC；spot 預設 60 秒、日 K 36 小時 | 核心過期／錯誤直接禁止 GPT 交易 |
| 宏觀／風險資產 | FRED 公開 CSV | daily observation 7 天、monthly 65 天；部分 PASS、部分 STALE／ERROR | 個別列保留缺失，不當成利多 |
| 資金費率、OI、long／short、taker、basis | Binance USD-M Futures public REST | 預設 12 小時；實測 PASS | MISSING／ERROR，不填零假裝有效 |
| 穩定幣 circulating USD | DefiLlama public stablecoins API | 預設 72 小時；7／30 日變化；實測 PASS | 缺失／過期明示 |
| 新聞／事件研究 | 選定 GPT 的可選 `web_search` | 執行當時查詢，24–72h 是研究範圍；引用 URL／retrieved timestamp 保存 | web 不支援則 provider-only；無 grounded citations 的 brief 不成為證據 |
| ETF／on-chain 詳細流向 | Provider interface 已保留 | MISSING | 不以新聞代替數值流量 |

Broad USD 是代理值，不是 ICE DXY；S&P500／NASDAQ Composite 是代理指數，不是 SPY／QQQ。Gold 原 FRED series 實測 ERROR；CPI／PCE、broad USD 的保守規則判為 STALE，未放寬門檻。FRED 是目前修訂版資料，只能在實際取得時間後用作前瞻證據，不宣稱 point-in-time 歷史 vintage。

Primary 依據：[Binance market data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)、[FRED CSV 說明](https://fred.stlouisfed.org/help/data/downloading/using-the-download-data-link)、[DefiLlama 免費 API 文件](https://api-docs.defillama.com/llms-free.txt)。DefiLlama 文件所列主站 stablecoin path 實測失敗，採唯讀核實能回傳資料的 `https://stablecoins.llama.fi/stablecoincharts/all`；此 host 差異沒有隱藏。

## K 目前 MISSING

BTC／ETH daily ETF net flow、清算統計、exchange inflow／outflow、whale／LTH 完整數據、可驗證的歷史外部資料 archive 未取得。新聞 publication timestamp 無法可靠取得時為 null，source timestamp 明確表示實際觀測時間，不能宣稱等於發布時間。

## L GPT Policy

`decision_policy_v1.md` 凍結並保存 hash。固定分析順序為 Risk Veto、Macro、Liquidity、ETF、Derivatives、On-chain、Relative Strength、Technical、Event、Portfolio、Scenarios、Decision、Post-Entry。Quant 是證據，不是 GPT 的服從命令；任何單一指標或新聞不應單獨決定重大調倉。

外部文本一律 `UNTRUSTED EXTERNAL DATA`；只能回覆權重，不輸出 units 或訂單，不補造缺失資料，只保存繁中摘要而非私有思考過程。此框架降低風險，但 prompt injection 防護不能被說成對所有 LLM 回覆的形式化保證。

## M Decision Schema

Strict schema 共 28 個 required 欄位，禁止額外欄位，包括五種 action、confidence、regime、九類 health scores、veto、三情境概率、BTC／ETH／cash weights、V3.10 view、論點／因素／風險／失效條件、data quality 與 post-entry thesis status。

本機再檢查型別、finite、非負、probability sum、weight sum、曝險等於 BTC+ETH 及上限。九類分數與情境機率是 GPT 判斷，不是已經校準的客觀勝率。

## N Risk Gateway

只有 ALLOW／CLAMP／BLOCK，不產生市場預測。Crypto 曝險最多 95%、單次曝險變動最多 20 個百分點、變動信心至少 0.65，只允許 spot、無槓桿、無放空。Critical stale、duplicate、poor data、非法 schema、risk veto 的加碼會擋住；低信心轉 HOLD。Frozen hash FAIL 至少禁止增加曝險。

Exposure cap／cycle cap／confidence 可收緊，不能用設定放寬安全上限。Clamped EXIT 仍可保留部位，不能將「要求退出」誤解為這次已全清。

## O Paper Broker

Final GPT response 結束後才開始取得新 bid／ask，不使用回覆前報價成交。預設 quote age 30 秒、spread 上限 1%，Python 使用 approved weights 計算 units，先 SELL 後 BUY，以 post-cost NAV 解算，費用 10 bps、滑價 5 bps、minimum US$5。

每筆記錄 ID、時間、asset／side／units、reference／bid／ask／fill、gross notional、fee、slippage 與 net cash change。保留既有 `MIN_NOTIONAL` skip 代碼，UI 顯示跳過；小額不是成交。最後對帳 cash／units 非負、NAV、95%／20pp postcondition；任何失敗不提交部分成交。沒有真實 order endpoint。

成本可以在本機 runtime config 修改，但需重開 App／新建實驗，舊實驗不能中途換成本。設定檔為 `ai_shadow/data/runtime_config.json`，受 Git 忽略。

## P Genesis 與公平比較

Genesis 必須手動確認，將最新 hash-verified V3.10 BTC／ETH 數量及四種現金 bucket 相加後複製，按啟用時新報價標價。保存來源 NAV、時間、file／record hash、live mark adjustment、model／policy／fees／risk／freshness／account binding。啟用時市價成本基準不是歷史原始平均買價。

每個實驗放在新的 UUID 目錄，正式 SQLite Genesis 不能覆寫。$2／4H 外部本金鏡像相同 frozen scheduled rows，當該 bar 完成、確實可知後入 AI cash；不自動 DCA。單位化扣除外部本金，V3.10 unit NAV 以同起點及兩端同報價重基準，顯示 return／alpha，不比較不同生命週期總報酬。

**公平比較仍有重要限制**：Frozen contribution 在 bar open 計算，AI 只能在 completed bar close 知道該 row。金額／schedule 可追溯，但不是完全同 tick 的 cash timing。V3.10 DD／volatility 目前按 AI 決策觀測點；AI DD 另含補入帳時的 completed 4H 標價。兩者觀測粒度不同，不能無條件排名風險。

Turnover 與 fees 另以驗證過 hash-chain 的 tactical／DCA logs 計算；DCA fees 可由 frozen executed budget 和 frozen `_buy` 公式精確推導。原本 DCA log 缺逐資產 fills，總 asset trade count 為 null，而不是捏造；tactical asset fill count 及 DCA active bar count 分開保存。此項 **PARTIAL**，沒有改原本凍結輸出來掩蓋缺失。

## Q 同日防重複

AI 採 UTC calendar day，一天至多一筆成功 cycle，與原 V3.10 本機日曆日 gate 不混用。Decision ID 由 status date、snapshot hash、policy hash、model slug、experiment ID 算出，SQLite identity／day unique，加上 OS process lock。強制重跑 V3.10 不會解除 AI 去重。

RECEIPTS 先獨立原子保存，GPT 失敗也不遺失或重複本金。決策／fills／state／benchmark 同 transaction 寫入。CSV 被 Excel 鎖住時交易不重做，export manifest head／file hashes 可持續顯示 pending，關閉佔用後只重建 projections。正式 events 有禁止 UPDATE／DELETE 的 triggers 及 previous／record hash chain。

## R No look ahead 範圍

K 線只用 close time 已過的完成 bars；Frozen row 是 open-labelled closing valuation，available time 明確加 4 小時。所有可用／取得／查詢／publication timestamps 都不得超過 final request 的 decision cutoff，拒絕 future outcome／resolved labels／tokens。Adapter 只 allowlist Quant state，不讀 candidate outcomes。

這證明的是**可追溯輸入與執行時序**，不是證明 GPT 訓練知識完全沒有歷史資訊。沒有使用今天新聞做歷史 AI 決策，沒有據 mock HOLD 回覆宣称「AI 具獲利能力」。Live future validation 才能檢驗實際方案。

## S UI 改動

保留原本高 DPI／深色圓角介面、V3.10／V3.1 卡片與 daily button。新增 compact GPT Shadow 卡片、AI 決策頁、ChatGPT 多帳號登入／重新登入／登出、帳號模型選單、新 Genesis confirmation 與 usage link。所有背景結果經 UiDispatcher 回主執行緒；關閉設定視窗不再更新其 widgets。

AI 頁呈現 request／approved allocation、confidence、九類 health、thesis、成交時間／數量／價格／原因、來源品質、同起點績效及 hashes。資產是最後一次紙上處理的估值，時間明示，不當作即時 AI 運作。

Usage settings 連結是核實的 `https://chatgpt.com/settings/usage`。資格與用量不足顯示可理解提示，不推測 reset。官方 [UI/UX guidelines](https://developers.openai.com/siwc/ui-ux-guidelines) 作為登入與使用量提示依據。

## T 測試數量

基線為 root／universe 112、App 79。此次 root／universe／AI 為 **192 passed**（原 112 + AI 80），App 為 **85 tests OK**（原 79 + AI GUI 6），合計 **277**。新增 case 確認 AI runtime config 損壞時，只停用 AI，原本量化監控仍可開啟。

## U 測試結果

完整 pytest、App unittest、compileall、Git whitespace check 均通過。覆蓋官方 request shape、JWT wrong issuer／audience／nonce／expired／signature／subject、refresh lock／rotation、usage limit、模型不可用、strict JSON、prompt injection framing、source future timestamps、核心 stale、coin quantities／fees／slippage／limits、receipt去重、export recovery、SQLite handle close、七檔 frozen hash 與 AI failure preserving V3.10。

測試程序沒有使用 live credentials／實際 GPT，prompt injection 測試是 policy／gateway contract，不是 live red-team 通過。Public provider probe 已實際執行，193 個 frozen portfolio rows 已驗證；正確性和新鮮度仍須每次重新檢查。

重現命令由專案根目錄執行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests universe_diagnostic/tests ai_shadow/tests
.\.venv\Scripts\python.exe -m compileall -q ai_shadow CryptoForwardMonitor scripts
.\.venv\Scripts\python.exe scripts/validate_ai_shadow.py --public-sources
```

App 測試從 `CryptoForwardMonitor` 目錄執行 `..\.venv\Scripts\python.exe -m unittest discover -s tests -q`。

## V EXE Build

PyInstaller 6.22.2／Python 3.12.14 的 Windows onefile、windowed EXE 已成功建置，並跑隔離設定的實際 EXE smoke，exit code 0。5 個分頁、AI 設定視窗、policy／schema 資源及 Windows vault backend import 通過；vault operations、OAuth、GPT requests、model runs 全部 0，AI 預設 disabled。

目前 EXE 為 27,632,291 bytes，SHA256 `d273e37b475e5986bee50bd6c3f610706c8e2c831520f939aa45a53f75e322de`。本機機器證據：`artifacts/ai_shadow_local/exe_smoke.json`。UI 離線截圖 `ui_qa/ai_decision_mock.png` 已檢視，可閱讀、沒有把 mock 數值寫進正式帳本；截圖不是正式績效。

試用檔案為 `CryptoForwardMonitor/dist/CryptoForwardMonitor.exe`。原版備份保留在 `artifacts/ai_shadow_local/previous_exe/CryptoForwardMonitor_before_ai.exe`。未做 clean Windows／SmartScreen／防毒簽署驗證；EXE 未簽章。

## W 已知限制

1. 真實 OAuth、plan eligibility、account models、web search 支援與推論／refresh／revoke 仍待使用者驗證；不能保證每個 ChatGPT account 都合資格。官方 [preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations) 仍適用。
2. AI benchmark cash timing 與觀測粒度不是完美配對，總 V3.10 asset fill count 缺失，詳 P。CAGR 少於 30 天不年化；波動／Sharpe／Sortino 少於 2 個連續日報酬不填數字。
3. 外部來源可缺失、限流或改規格；Gold／ETF／liquidations／詳盡 on-chain 目前缺失。不因資料少就調鬆交易或 freshness 門檻。
4. SQLite hash chain／triggers 防意外修改及可檢測破壞，不是能抵擋本機管理員同時重寫整個資料庫的外部時間戳認證。
5. 新 AI 帳本只從新 Genesis 開始；本次沒有真實 GPT 歷史回測、沒有績效最佳化、沒有承諾增加報酬。
6. 原本前瞻 `FORWARD SAFETY FAIL` 沒有被 UI／AI 修正或清除；凍結完整性 PASS 不等於原本所有 safety gates PASS。
7. 本次保持本機 working tree；不存在新的 commit、push 或 PR。全規格 live acceptance 尚未完成。

### 凍結歷史回測重現

依使用者追加要求，實際重跑原本 `run_backtest_v3_10.py`，僅在 process 內重導五個 output directory，沒有修改引擎、參數、資料或 Promotion Gate。期間仍為 2020-01-01 至原始完整共同 4H cutoff 2026-09-03 04:00 UTC，未用目前新聞／GPT 補歷史訊號，也沒有更新到今天行情。

| 模型 | 期末資產 USD | TWR 年化 | Max DD | Calmar |
| --- | ---: | ---: | ---: | ---: |
| H0 期初配置後持有 | 197,656.93 | 40.96% | -77.22% | 0.5304 |
| A 單純 Fixed DCA | 279,201.22 | 42.50% | -76.87% | 0.5529 |
| B V3.1 FSM | 348,746.85 | 47.69% | -39.51% | 1.2070 |
| Q V3.10 Frozen | 367,407.51 | 48.89% | -39.51% | 1.2374 |

H0 外部追加為 0，其餘追加 US$29,248，不能只看最終資產排名。Q 的 Max DD 仍不符合「不超過 30%」，沒有把既有 frozen promotion verdict 擅自替換成其他版本的門檻。

重現結果與原始 summary 的五項關鍵指標最大絕對差都是 0；daily portfolio 與 trade log CSV 的 SHA256 也逐位元組相同。No-look-ahead／所有原始 integrity PASS，prefix trade identity 通過；243 個 protected 檔案的 before／after 全部未變。

新增輸出僅在本機 `artifacts/ai_shadow_local/historical_replay_20261005T121652_475197Z/`，含 results、figures、report、run manifest、replay receipt。重現入口：`scripts/replay_frozen_v310.py`。這是凍結策略回歸，不是新增 OOS 證據或 GPT 獲利證明。

## X 實際使用教學

第一次：啟動新版 EXE → **工具與設定** → **ChatGPT 與 AI 設定** → **Continue with ChatGPT** → 瀏覽器登入並允許 Plan Usage → 回 App → **載入此帳號可用模型** → 選擇模型 → **建立 AI Shadow Genesis／新實驗**。

之後每天：開 EXE → **執行每日模型** → 等 V3.10、External、GPT、Risk Gateway、Paper Execution → 左側 **AI 決策** 查看結果。AI 失敗時，V3.10 成功結果仍保留。不需 Codex、API key、複製 prompt 或手動輸入行情。

若使用量不足：開 **管理 ChatGPT 用量**，由帳號設定管理，不無限重試。若 exported CSV 被占用：關閉 Excel／相關檔案，按 **重建 CSV／JSON 匯出**。若換模型／account／policy／成本：建立新 Genesis，不覆寫舊帳本。

關閉 App 不會刪除記錄；下次會按可用 completed rows 補入外部本金。但關閉期間沒有自動 GPT 決策，也沒有任何真實下單。這是紙上研究工具，不應把紙上成交通知當成真實交易所資產。
