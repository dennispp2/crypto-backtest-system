# 歷史視窗修復與執行摘要 — 2026-09-07

## 變更

- 原版歷史視窗開啟後被主畫面遮住；原生視窗清單仍可找到它。
- 設為主視窗的 owned/transient 視窗，在 CustomTkinter Windows 重繪後取得焦點；不使用全域置頂或阻塞主畫面的 grab。
- 重複開啟會更新並呈現同一個歷史視窗；關閉可重新建立，關閉時取消待執行的顯示回呼。
- 新增「執行摘要」分頁，完成每日執行後自動開啟。比對執行前後帳本前綴，只報告新增紀錄。
- 顯示 V3.10 戰術成交時間、買賣方向、BTC/ETH 名目金額、原因代碼與已知中文說明、手續費和滑價。
- Fixed DCA 資料來自對照模型 A，不冒充 V3.10 或 V3.1 的逐筆定投成交。
- 幣數、成交價及逐筆定投幣種拆分未在現有帳本提供，明示缺漏，不以即時行情或目標配置推算。
- 缺檔、欄位錯誤、無時區、非有限金額、重複 ID、帳本改寫均不能報為「沒有成交」。
- 保存於 data/latest_execution_summary.txt 及 archive/execution_summaries/；重複執行防護不產生重複摘要封存。
- 首次升級若尚無新版摘要，顯示「最近帳本日」回顧，明確標註不是本次執行新增交易。

## 驗證

- `python -m unittest discover -s tests -q`：65 tests PASS。
- 模型執行整合測試使用假執行器、臨時資料及合成帳本；未執行正式 forward engine。
- 正式 EXE 原生介面：開啟歷史、點選資料列、切換全部範圍、關閉歷史、開啟執行摘要均成功。
- 原始策略、持倉、成交 CSV、dist/config.json 未修改；最後正式模型執行時間仍為 2026-09-07T17:32:50.598500+08:00。
- 既有 FORWARD SAFETY FAIL 不因本次 UI 修正而被清除或改判。

## 發行與回復

- 正式程式：dist/CryptoForwardMonitor.exe
- SHA256：147E8F760ABA4DF7EBD12B2B69B1FEF8DC0BA14C3FE4EE56FF688801B69FD534
- 舊版 EXE 與主要原始碼備份：build/history_fix_20260907/previous/
- 如需回復，先正常關閉程式，將備份 EXE 複製回 dist 同名檔案；不覆蓋設定或 data/archive。

## 保全雜湊（SHA256）

- forward_trade_log_v310.csv：2FA05707B83C2C16513E23AD071EA92A87C1C92D0D141BEA9A3967378FA25EBD
- forward_fixed_dca_log.csv：E4F92CF5AF58600214FCFA6C6697A1C4182AA8FA4C05D6645BA0B9B2F18E69BF
- forward_v310_portfolio.csv：51D5F7216148CBFFADB79BA482D90DC990766A9D00C62704D8C3F7B1ADAE62CA
- forward_v31_shadow_portfolio.csv：7C7ED5BBF9319A670EF60E676480F6C2C16E6190FDE318681527F75C5E707C84
- dist/config.json：7346D75F411ECF0360C643635C8E88FDFAD1204133C3AF79E9006F8AFB41224E
