# GitHub 保存範圍與還原

此儲存庫保存加密貨幣回測專案及 Crypto Forward Monitor 原始碼。
GitHub 版本是提交當下的快照；桌面 App 每日產生的新紀錄不會自動推送。

## 已保存

- 策略引擎、執行入口、測試與設計文件。
- 凍結參數、原始行情、來源清單、雜湊與稽核證據。
- 各版本現有回測結果、報告與圖表。
- V3.10 前瞻模型的既有帳本與安全評估快照。
- Windows App 原始碼、圖示、建置腳本及設定範例。

保存既有結果不代表重新通過全部回測驗收。現有安全評估、失敗紀錄及凍結門檻保留原狀。
`.gitattributes` 關閉換行轉換，使複製後的檔案位元組與既有凍結雜湊一致。

## 留在本機

- `.venv`、Python 快取、App 的 `build`／`dist` 及 EXE。
- `CryptoForwardMonitor/config.json`、`data`、`archive`、`logs`。
- 已存在的重複 ZIP 交付套件及其套件雜湊檔。

以上檔案沒有被刪除。GitHub 儲存庫不等同於可直接啟動的完整桌面安裝包。

## Windows 還原

1. 複製儲存庫到 D 槽的工作資料夾。
2. 建立 Python 環境，依根目錄 `requirements.txt` 與
   `CryptoForwardMonitor/requirements.txt` 安裝相依套件。
3. 將 `CryptoForwardMonitor/config.example.json` 複製成 `config.json`。
4. 將 `model_command` 改成該環境 Python 的完整路徑加上
   `run_forward_v3_10.py`，例如：
   `"D:/虛擬貨幣/crypto_backtest_system/.venv/Scripts/python.exe" run_forward_v3_10.py`。
   若搬到含空白的路徑，Python 路徑必須加雙引號。
5. 其餘範例路徑以設定檔所在資料夾為基準；若使用打包 EXE，依
   `CryptoForwardMonitor/README.md` 將設定指向實際專案及 App 資料目錄。
6. 依各版本 README 執行測試或重現流程；需要刷新行情時另行執行相應入口。

本機原始位置：`D:\虛擬貨幣\crypto_backtest_system`。
