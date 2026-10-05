# Crypto Forward Monitor

Windows 桌面監控程式，僅用於 Frozen V3.10 Forward Paper Test 的監控、記錄、
稽核與手動啟動。它不會改寫模型規則，也不會自動下單。

正式安裝位置：`D:\虛擬貨幣\crypto_backtest_system\CryptoForwardMonitor`

## 第一次使用

1. 使用專案既有 Python 環境，或執行 `build_exe.bat` 建立 EXE。
2. 開啟 `config.json`。
3. `model_command` 填每日執行 Frozen V3.10 的完整命令。
4. `model_workdir` 填模型專案資料夾。
5. `status_file` 填 `DAILY_FORWARD_STATUS.md` 完整路徑。
6. 執行 `install_shortcut.bat`，桌面會建立 **Crypto Forward Monitor** 捷徑。

目前三個欄位已依本專案實際位置設定完成。Windows 中文與空白路徑均以完整
Unicode 路徑處理。

## 每天使用

1. 雙擊桌面的 **Crypto Forward Monitor**。
2. 查看主控台與市場資訊。
3. 按一次 **執行每日模型**。
4. 完成後查看最新報告、歷史紀錄、封存或日誌。
5. 關閉或保持程式開啟。

同一個本機日曆日，一般執行成功後會顯示「今天已成功執行過，未重複執行」。
強制執行需要二次確認，且不會重複寫入相同 `status_date` 的歷史紀錄。

## 安全邊界

- App 啟動不會執行模型。
- **更新行情** 只更新 Binance BTC/ETH、重讀狀態與歷史紀錄。
- **自動更新行情** 只做相同的唯讀刷新，永遠不呼叫 `model_command`。
- 只有 **執行每日模型** 與經確認的 **強制執行** 能呼叫模型。
- V3.1 僅顯示為 Comparator，不控制 V3.10 Action。
- 最新報告是確定性狀態摘要，不使用 LLM，不產生交易建議。
- **資產總覽** 並排顯示 V3.10 Champion 與 V3.1 Shadow 的總資產、BTC／ETH／現金配置；持倉來自各自的紙上帳本，估值使用目前 Binance 市價。
- Frozen Hash FAIL 仍會保存 History、Archive 與 Log，但顯示醒目警告。

## 新版介面（2026-09-06）

- 深色背景與放大金額；BTC 使用金色、ETH 使用藍色、現金使用綠色。
- **資產總覽**：行情、兩套模型資產卡片、配置比例、前瞻進度及風險狀態。視窗較窄時風險區移至下方，可用滑鼠滾輪捲動。
- **白話報告**：較大的繁體中文字級與分段標題；更新行情不會重設閱讀位置。
- **原始資料**：曝險差距、完整狀態時間、動作代碼及近期紀錄，方便稽核。
- **歷史紀錄** 位於左側；封存、日誌、設定、資料夾與強制執行位於左下方 **工具與設定**。
- 「帳本曝險」是最後一次模型紀錄的比例；下方持倉配置依目前可用市價估值，兩者可能不同。持倉時間與估值來源均另行標示。
- 既有 `FORWARD SAFETY FAIL` 或凍結檔案異常會醒目顯示；介面更新不會清除歷史異常、改動門檻或重新執行模型。

### 高 DPI／圓角更新

- 啟動前啟用 Per-Monitor DPI Awareness，EXE 內亦包含 DPI manifest。文字與元件依螢幕 DPI 繪製，不依賴 Windows 將低解析畫面整張拉大。
- CustomTkinter 圓角卡片、按鈕、選單控制與高解析 Bitcoin 圖示；交易所風格的側邊導覽及緊湊行情列。
- 資產總覽使用像素級平滑捲動；縮小視窗後風險欄移至下方。
- 更新中／模型執行中按鈕會顯示忙碌狀態。一般完成提示改成不阻擋操作的通知；失敗提示不自動消失。強制執行仍要求確認。
- 背景工作結果經佇列交由主介面執行緒更新；關閉後不再對已關閉視窗送出更新。
- 快捷鍵：F5 更新行情；Ctrl+1／2／3 切換總覽、報告、原始資料。
- 畫面數值直接使用既有帳本與行情，沒有加入假行情、假資產曲線或模擬成交動畫。

視覺布局集中在 `ui.py`，元件在 `ui_components.py`，背景顯示事件在 `ui_dispatch.py`；與模型執行、行情、帳本及儲存邏輯分離。

設計依據：[CustomTkinter DPI 文件](https://customtkinter.tomschimansky.com/documentation/scaling/)、[Microsoft High DPI 文件](https://learn.microsoft.com/en-us/windows/win32/hidpi/high-dpi-desktop-application-development-on-windows)。沒有改動 Windows 的顯示縮放或其他系統設定。

## 資料位置

- History：`data/history_forward.csv`
- Stage3：`data/stage3_candidates.csv`
- Runner state：`data/runner_state.json`
- 每日原始狀態備份：`archive/YYYY-MM-DD/`
- 執行紀錄：`logs/YYYY-MM-DD.log`

上述檔案不會自動刪除。CSV 與 runner state 使用同資料夾暫存檔後原子取代。

## EXE

執行 `build_exe.bat` 後產生：

`dist/CryptoForwardMonitor.exe`

打包時只在 `dist/config.json` 不存在時複製初始設定，不覆蓋現有設定；資料仍依 `app_data_dir` 保存於本資料夾。

## 測試

在此資料夾執行：

`..\.venv\Scripts\python.exe -m unittest discover -s tests -v`
