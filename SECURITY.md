# 資安政策

## 回報漏洞

發現資安問題時，**請不要開公開的 Issue**。請用 GitHub 的「Report a vulnerability」（Security → Advisories）私下回報，內容包含：

- 影響範圍（哪個功能、哪個檔案）
- 重現步驟
- 可能的影響

我們原則上會在 7 天內回覆，修好後在版本說明中致謝（你不想具名也可以）。

## 設計上的安全措施

- 審核頁預設只聽 `127.0.0.1`；要聽其他位址必須設 `RADAR_REVIEW_PASSWORD`（至少 10 字），否則拒絕啟動。
- 檢查 `Host` 標頭，擋 DNS rebinding（惡意網站把網域指到 127.0.0.1 來操作你的審核頁）。
- 同一個來源 10 分鐘內登入失敗 10 次，暫時封鎖 10 分鐘。
- 審核帳號密碼用 PBKDF2-SHA256（20 萬次）加鹽雜湊；每個帳號只能看、只能審自己負責的品牌。
- 回應帶 Content-Security-Policy（不載入外部資源）、`Cache-Control: no-store`。
- 貼文連結只收 `http(s)://`，擋 `javascript:` 連結。
- 匯出 CSV 時，`=`、`+`、`-`、`@` 開頭的內容前面加 `'`，避免 Excel 當公式執行。
- Prompt injection：`claude_cli` 以 `--tools "" --strict-mcp-config` 在空資料夾執行；AI 草稿含網址、聯絡方式、標記他人或任何金鑰值一律擋下。
- 自動發文：設定必須是 yaml 的 `true`（字串 "true"／"yes" 都不算）；送出前先把草稿原子地鎖成 publishing，兩個程序同時跑也不會重複發文；已人工回覆的不會再送。
- 排程重疊時第二輪直接跳過（`data/.run.lock`），不會重複產草稿。
- Threads API 錯誤訊息不含網址，權杖不會寫進 log。
- POST 請求要帶自家頁面才有的標頭（擋跨站請求偽造）；頁面輸出一律跳脫（擋 XSS）；回應帶 `X-Frame-Options: DENY`。
- 金鑰只從環境變數或 `.env` 讀；`.env`、`data/`、`config/settings.yaml`、`plugins/` 都在 `.gitignore`。
- 核心程式沒有任何發文功能；自動發文外掛要另外安裝、手動啟用，且只送人工核准過的草稿。
- 貼文資料預設 60 天自動刪除。

## 使用者自己要注意

- 不要把 `.env`、`data/` 上傳到 git 或公開的雲端資料夾。
- 從外網連審核頁，一定要透過 HTTPS 通道或反向代理。
- 金鑰外流時，立刻到發放處撤銷或重新產生（各金鑰位置見 `docs/金鑰申請.md`）。
