# GitHub 保存範圍與還原

GitHub 保存程式與研究結果，不會自動同步你每天的私人帳本。AI 功能目前在 **feature/gpt-shadow-portfolio-manager** 分支，main 保持原狀。

## 換電腦怎麼用？

先把這個分支複製到 D 槽等工作資料夾：

```powershell
git clone --branch feature/gpt-shadow-portfolio-manager https://github.com/dennispp2/crypto-backtest-system.git
cd crypto-backtest-system
```

接著依 [專案首頁](README.md#第一次啟動windows) 安裝相依套件，首次複製 `CryptoForwardMonitor/config.example.json` 為 `config.json`，不要覆蓋已有設定。

若搬到其他路徑，請核對模型命令、工作資料夾、狀態檔與 App 資料位置。模型命令中的 Python 完整路徑若含空白，要加雙引號，例如：
`"D:/My Crypto/.venv/Scripts/python.exe" run_forward_v3_10.py`。

新電腦需要在 App 用自己的 ChatGPT 重新登入、授權方案用量及選模型。GitHub 不包含你的登入憑證或私人 AI 帳本，不會自動還原目前資產。[App 使用說明](CryptoForwardMonitor/README.md)。

## 有上傳什麼？

- 回測引擎、桌面 App、AI 整合程式、測試與文件。
- 凍結設定、原始行情、來源清單、雜湊、各版本報告及圖表。
- 原先已版本化的 `v3_10_forward/` 研究帳本與安全評估快照；不是新的私人 AI 帳本。

保留既有結果不代表重新通過全部驗收；原始失敗紀錄與凍結門檻照原樣保存。`.gitattributes` 保留檔案位元組，避免換行轉換破壞凍結雜湊。

## 什麼留在本機？

- ChatGPT token、帳號 metadata、私人 AI Genesis／SQLite／決策與成交紀錄。
- `ai_shadow/data/`、`artifacts/ai_shadow_local/`、App 本機 `config.json`、`data/`、`archive/`、`logs/`。
- Python 環境、快取、App `build/`／`dist/`／EXE，以及重複 ZIP 交付包。

這些資料沒有被刪除，只是不納入 Git。GitHub 是提交時的原始碼與研究快照，不是完整桌面安裝包，也不是私人操作紀錄的雲端備份。
