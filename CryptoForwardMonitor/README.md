# Crypto Forward Monitor 使用說明

Windows 繁體中文紙上監控工具。**不會向交易所下真實訂單。**

## 每天怎麼用？

1. 開啟 App：讀取上次保存的持倉、更新 BTC／ETH 行情，不重設本金。
2. 按 **執行每日模型**：先執行純 V3.10；已啟用 AI 時，再進行資料整理、GPT 判讀、風控與紙上成交。
3. 看 **資產總覽**：左邊是 V3.10＋AI，右邊是純 V3.10。
4. 看 **執行摘要／AI 決策**：查看時間、買賣幣種、數量、價格、金額、原因及資料來源。

「更新行情／自動更新」只重估資產，不呼叫 GPT、不交易。模型尚在執行時不要重複按；同日重複判讀另有防重複機制。

## 第一次連結 AI

1. **工具與設定 → ChatGPT 與 AI 設定 → Continue with ChatGPT**。
2. 在官方瀏覽器登入自己的 ChatGPT，允許 **ChatGPT Plan Usage**。
3. 回 App，按 **載入此帳號可用模型**，選擇模型。
4. 按 **啟用 V3.10＋AI／建立新綜合帳本**，確認接續目前 V3.10 的 BTC／ETH 數量與現金。
5. 之後使用同一個 **執行每日模型** 按鈕即可；不用每天登入或建立新帳本。

連線使用官方 OAuth，不需要 API Key，也沒有付費 API 備援。資格、可選模型及用量以帳號實際回傳為準；不是每個帳號都保證能使用。失敗、額度不足或資料過期時會提示，不會捏造 AI 成交。[官方連線說明](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)。

新安裝的 AI 預設關閉；既有設定會保留。換模型、帳號、政策或風控時，要另建新實驗，舊帳本不刪除。建立新帳本是新比較起點，**不是把本金重設 US$20,000，更不會匯入歷史回測的獲利**。

## 兩個版本有什麼不同？

- **純 V3.10**：固定定投、市場週期判斷、分階段避險及買回；Stage3 再進入需三個完成日確認。
- **V3.10＋AI**：以純版技術狀態為主要依據，加上可驗證外部資料，讓 GPT 提出配置；通過風控後在自己的紙上帳本執行。
- 原凍結規則與右側帳本不受 AI 改寫。綜合版不自動複製純版後續交易；HOLD 代表 AI 不調倉。
- V3.1 原比較模型仍保留於原始資料及帳本。

更完整的模型邏輯、AI 作用與限制見 [專案首頁](../README.md)。

## 均價、盈虧與時間怎麼看？

綜合版啟用時以當時市價建立成本基準，**不是原 V3.10 的歷史買入均價**。浮動盈虧是目前持倉相對帳本成本，不等於總投資報酬，也不包含未來賣出費用。

資產卡依最新可取得行情估值；批准配置及 AI 決策頁績效是最後一次成功判讀的快照。持倉時間、估值時間與 AI 判讀時間分開顯示，行情刷新不代表 AI 重新決策。斷線時會標示沿用舊估值。

## 安裝與 EXE

第一次安裝依 [專案首頁](../README.md#第一次啟動windows) 建立 Python 環境與本機設定。搬到其他位置時，核對 `config.json` 的模型命令、工作資料夾、狀態檔與資料路徑。

要建立 EXE，可在本資料夾執行 `build_exe.bat`，輸出為 `dist/CryptoForwardMonitor.exe`。打包不覆蓋既有 `dist/config.json`；若從 `dist` 啟動，設定的路徑須指向實際模型專案及資料位置，而不是誤用範例的相對位置。桌面捷徑可用 `install_shortcut.bat` 建立。

## 常見問題

- **關閉 App 會清空嗎？** 不會。下次讀取保存的持倉；成功執行時依已完成的 4H 時段補入紙上外部本金。關閉期間不會跑 GPT，也沒有真實下單。
- **AI 失敗會影響純版嗎？** 純 V3.10 的成功結果仍保留；AI 本次不成交。凍結完整性與資料新鮮度檢查仍適用。
- **CSV 被 Excel 占用？** 關閉檔案後，到「AI 決策 → 重建 CSV／JSON 匯出」。只重建匯出，不呼叫 GPT、不重做成交。
- **看到安全驗收失敗？** 原前瞻 `FORWARD SAFETY FAIL` 仍保留；介面改版不代表失敗已修復，也不會清除紀錄或降低門檻。

## 資料保存與隱私

App 紀錄依 `app_data_dir` 保存於 `data/`、`archive/`、`logs/`；AI 實驗預設在專案根目錄 `ai_shadow/data/experiments/<UUID>/`。正式 AI 帳本是 `journal.sqlite3`，CSV／JSON 為可重建匯出。

登入 token 在 **Windows Credential Manager**，不放進帳本或 GitHub。分析用的市場快照及紙上持倉會送給 OpenAI；私人帳本、帳號資料、本機設定與 EXE 不上傳 GitHub。GitHub 不會自動備份每日新紀錄。

## 程式測試

從專案根目錄執行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests universe_diagnostic\tests ai_shadow\tests
Push-Location CryptoForwardMonitor
..\.venv\Scripts\python.exe -m unittest discover -s tests -q
Pop-Location
```

這些是本機回歸測試，不呼叫真實 GPT；歷史探索另外記錄於 [首月測試](../docs/FIRST_MONTH_AI_REPLAY.md)，不能當成目前 App 已通過完整實際運行驗收。
