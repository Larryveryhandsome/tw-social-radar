# tw-social-radar 公開前檢查（RELEASE_CHECK）

- 檢查日：2026-10-24
- 檢查的版本：`96e1005`（起點）＋本次修正 commit（見最下方）
- 目前可見度：**PUBLIC**（2026-10-27 依店長決策 O02 公開）
- 測試環境：Windows 11、Python 3.14.2 與 3.10.22；乾淨 `gh repo clone` 後照 README 安裝

## 結論先講

**可以公開（2026-10-27 店長決策 O02「兩個都公開」）。** 第 7 道已用全新 git 歷史解決（只剩一個 commit，舊歷史打包備份在私人資料夾）。
其餘七道沒有阻斷項目；第 3 道有「真實帳號從沒實測」的已知限制，要店長接受才算過。

| # | 閘門 | 結果 | 一句話 |
|---|---|---|---|
| 1 | 需求與設計 | ✅ | 流程、角色權限、外部服務失效退路都有寫（`docs/合規與風險.md`、QA 報告） |
| 2 | 程式本身 | ✅ | 97 項測試全過、相依套件 0 個已知漏洞、QA 報告 🔴2／🟠14 全修 |
| 3 | 串接 | ⚠️ | 全部用假回應驗證；真實 Threads／LINE／Claude／Ollama 從沒連線實測 |
| 4 | 完成使用者任務 | ✅ | 審核主流程、失敗情境（空白、重複送出、無權限）實機跑過 |
| 5 | 安全／效能／環境 | ✅ | 越權（A 看不到 B）、注入、鎖定、自動發文預設關閉都實測 |
| 6 | 資料 | ✅ | 舊版資料庫升級、備份還原都實際做過一次 |
| 7 | 交付版本 | ✅ | 乾淨 clone 可裝可測；git 歷史已重建為全新單一 commit（2026-10-27） |
| 8 | 出事能恢復 | ✅ | 錯誤分類通知（一天一次）、LLM 失效退回模板、可還原備份 |

## 證據

### 第 2 道 程式本身
| 項目 | 指令 | 結果 |
|---|---|---|
| 全部測試 | `python -m unittest discover -s tests`（Python 3.14） | 97 項全過（本次新增 2 項，原 95） |
| 同上，本次修正後 | Python 3.10.22 | 97 項全過 |
| 相依套件漏洞 | `pip-audit -r requirements.txt` | No known vulnerabilities found |
| 靜態檢查 | `pyflakes radar extras tests` | 只有 3 個無害提示（沒用到的 import、沒有變數的 f-string） |
| 擴展性與漏洞檢視 | 見 `docs/`／QA 報告 | 🔴2、🟠14 已修並有測試 |

### 第 4、5 道 實機（本機啟動審核頁，真的用 HTTP 打）
測試帳號：admin、amy（只審 demo）、bob（只審 demo-food）。共 27 項檢查全過，重點：

| 需求 | 風險 | 測試 | 預期 | 結果 |
|---|---|---|---|---|
| 審核員只能看自己負責的品牌 | 越權讀取 | amy 讀 `/api/drafts`、加 `?brand=demo-food`、看畫面 HTML | 只看到 demo，其他品牌空白／不出現 | ✅ |
| 審核員不能動別人品牌的草稿 | 越權修改 | amy 對 bob 的草稿做核准／退回／已回覆 | 全部 404，bob 的草稿狀態不變 | ✅ |
| 審核員不能用管理功能 | 提權 | amy 開 `/admin/brands`、`/admin/members`、POST 新增成員／品牌 | 全部 403 | ✅ |
| 審核員不能改別人品牌的關鍵字 | 越權修改 | amy 改 demo-food 關鍵字 | 403「你沒有負責這個品牌」 | ✅ |
| 巡邏頁不外洩別的品牌 | 越權讀取 | amy 開 `/patrol` | 看不到 demo-food | ✅ |
| 沒登入不能用 | 未授權 | 不帶帳密開 `/`、`/api/drafts` | 401 | ✅ |
| 密碼猜測 | 暴力破解 | 連續 11 次錯誤密碼 | 該來源被鎖（429） | ✅（已知限制：走 Cloudflare Tunnel 時會連管理員一起鎖，QA 報告 V13） |
| 跨站請求 | CSRF | POST 不帶 `X-Radar` 標頭 | 403 | ✅ |
| 惡意貼文內容 | XSS | 核准文字含 `<script>` | 頁面只出現轉義後的文字 | ✅ |
| DNS rebinding | 外站操作本機頁 | Host 標頭改成別的網域 | 421 | ✅ |
| 重複點送出 | 重複寫入 | 同一則連按兩次核准／已回覆 | 第二次 409 | ✅ |
| 必填空白 | 輸入處理 | 退回不填原因、關鍵字空白、關鍵字 60 字 | 400 並說明 | ✅ |
| 新增品牌精靈 | 路徑穿越／注入 | key 用 `../evil`、Windows 保留名 `con`、帳號含換行引號 | 全部 400；重複 key 回 409 不覆蓋 | ✅ |
| 成員管理 | 弱密碼／覆蓋 | 密碼 5 字、重複帳號 | 400／409，原密碼不被覆蓋 | ✅ |
| 前端 console | 畫面壞掉 | 瀏覽器開審核頁、新增品牌頁、成員頁、巡邏頁 | console 無錯誤 | ✅ |

### 第 5 道 自動發文預設關閉、只模擬不送出、平台封號風險
| 項目 | 證據 |
|---|---|
| 核心程式沒有任何發文功能 | `test_core_never_posts_to_threads` ✅ |
| 外掛預設不安裝、不啟用；`enabled` 寫成 `"false"`／`"true"`／`yes`／`1` 都不算開，只認 yaml 的 `true` | `test_only_literal_true_enables`、`test_default_off` ✅ |
| 沒設定時執行 `python -m radar publish` | 不送出任何東西 ✅ |
| **只模擬不送出（本次新增）** | `python -m radar publish --dry-run`：列出現在執行會送出哪幾則，不連網、不鎖定草稿、不改狀態。新增 `test_publish_dry_run_sends_nothing`（把 `urlopen` 換成遇到就報錯）、`test_publish_dry_run_when_disabled` ✅ |
| 就算外掛開了：只送人工核准的草稿、每品牌每天 4 則上限、8–22 點、只處理官方 API 來源 | `test_installed_plugin_publishes_via_official_api` ✅ |
| 同一則不會送兩次 | `test_no_double_publish`、`test_publish_lock` ✅ |
| 平台封號風險 | 來源只有檔案匯入與 Meta 官方 Threads API；沒有爬蟲、沒有模擬真人；回覆由人工到 Threads 貼上。風險說明在 `docs/合規與風險.md` |

### 第 5 道 AI 提示詞注入（貼文是陌生人寫的，只當資料）
| 情境 | 測試 | 結果 |
|---|---|---|
| 貼文叫 Claude 讀本機檔案 | 真的 Claude CLI 實測（QA 報告 V1）；修正後工具全關、在空資料夾執行、`--strict-mcp-config` | ✅ 不外洩（`test_claude_cli_runs_without_tools_in_sandbox`） |
| 貼文誘導 AI 產出網址／電話／LINE ID／@別人 | `test_injected_reply_is_blocked_and_falls_back_to_template` | ✅ 擋下改用模板 |
| 貼文偽造 `</post><system>` 標籤 | `test_sanitize_post_tags` | ✅ |
| AI 回傳錯誤訊息（登入過期、額度用完）被當成草稿 | `test_error_text_is_not_a_draft` | ✅ |
| 草稿含金鑰值 | `test_secret_never_in_draft` | ✅ |
| 匯入檔含 `javascript:` 連結、`=HYPERLINK` 公式 | `test_javascript_url_dropped`、`test_csv_formula_escaped` | ✅ |
| LLM 成本失控 | `test_classify_calls_are_capped`（100 則候選，LLM 呼叫 ≤ 12 次）；預設 `provider: mock`、`draft_mode: template`＝零成本 | ✅ |

### 第 6 道 資料
| 項目 | 做法 | 結果 |
|---|---|---|
| 舊資料升級 | 用 `e1ef057`（舊版）產生資料庫，再用現在的程式 `run`、`drafts` | ✅ 舊的 5 則草稿都在，新增 `run_log`、`keyword_override`、`keyword_override_log` 三張表，沒有錯誤 |
| 備份還原 | 複製整個 `data/`（`radar.db`、`reviewers.json`）到新資料夾，用 SQLite 開啟 | ✅ `integrity_check = ok`，各狀態草稿筆數、關鍵字異動紀錄與原本一致 |
| 密碼不存明文 | 檢視 `reviewers.json` | ✅ 只有 salt＋hash（PBKDF2） |
| 個資保存 | `retention_days: 60` 超過自動刪除；巡邏頁被過濾的貼文只留帳號＋前 40 字 | ✅ |
| 並發寫入 | `test_wal_and_concurrent_writers`（4 個 writer 寫 200 則，0 錯誤） | ✅ |

### 第 7 道 交付版本
| 項目 | 結果 |
|---|---|
| 測的版本＝要發布的版本 | ✅ 乾淨 clone 的 `96e1005` 跑測試；修正後再從同一份工作副本重跑 97 項全過 |
| 乾淨環境照 README 安裝、跑 demo | ✅ `pip install -r requirements.txt`、`python -m radar demo --reset`、`python -m radar review` |
| 去識別化（現有檔案） | ✅ `deep_audit.py` 命中都已逐筆判讀：`velo` 是「Developers」字樣的誤判、測試用假電話 `0900-000-123`、作者署名「留白事務所」與客製化 LINE 為刻意保留（見下方請店長確認） |
| CI | ✅ 本次新增 `.github/workflows/test.yml`（Python 3.10、3.13、ubuntu）；GitHub Actions 實跑 `success`（run 40057978963，兩個版本都綠） |
| **git 歷史** | ⚠️ **歷史需全新（待店長同意 force push）**：第一個 commit `66cc455` 的 README 有一次本人真名（`deep_audit.py` 🟡 歷史命中）。作者信箱全部是 noreply，沒有其他個資 |

### 第 8 道 出事能恢復
| 失效情境 | 行為 | 證據 |
|---|---|---|
| Threads 權杖過期／額度用完 | 已抓到的照收；權杖錯誤推播通知，同一種錯誤一天一次；額度用完不推 | `test_threads_token_expired`、`test_threads_rate_limit_no_alert` |
| Claude／Ollama 連不上 | 這輪改用模板照常產草稿並通知 | `test_llm_unavailable_falls_back` |
| 單一品牌 yaml 打錯 | 其他品牌照跑 | `test_brand_yaml_empty_strings` |
| 排程重疊 | 程序鎖＋舊鎖 2 小時自動清 | `test_overlapping_runs_skip`、`test_stale_lock_cleared` |
| 回復方式 | 還原 `data/` 備份（已演練）；程式版本用 git 回到前一個 tag／commit | 第 6 道 |

## 已知問題（要寫進 README 讓使用者知道，原則上不影響公開）

1. **真實串接從沒實測**：沒有店長的 Threads App 與權杖（`threads_keyword_search` 還要通過 Meta 審查）、Claude API 金鑰、LINE／Discord 通知金鑰。這些只用假回應驗證「送出的內容」。第一次接真帳號時請先用 `publish --dry-run` 與檔案匯入。（店長已指示：不用提供金鑰。）
2. 走 HTTP 區網時審核密碼是明文（V12）；走 Cloudflare Tunnel 時猜錯密碼會把所有人鎖 10 分鐘（V13）。文件已要求外網一定走 HTTPS。
3. `python -m radar user add` 的審核帳號存在 `data/`，用 `review --demo`（資料在 `data/demo/`）時看不到這些帳號；示範模式請用管理員帳號。
4. 測試用 `brands/` 資料夾；使用者自己新增品牌後，舊版測試曾因多出的品牌失敗，本次已放寬該斷言。
5. 下一輪時間依 `schedule.interval_minutes` 推算，不會讀工作排程器；檔案匯入來源沒有每個關鍵字的命中統計（QA 報告 🟡）。

## 要店長決定／處理

1. **歷史要全新**：同意 force push 重建歷史，或另建新 repo 單一 commit 發布。（我沒有做，這是不可逆動作。）
2. **作者署名與客製化 LINE**：README 最後仍有「留白事務所」與 LINE `林其衞的 LINE`。這是上一個 commit 刻意改成的作者署名；若 10/24 的新規則要求連品牌名也去掉，需要店長說一聲。
3. 接受「真實串接未實測」的已知限制。
4. 公開與否的最後驗收。

## 發布決定

**目前不建議公開。** 第 7 道的歷史問題解決、店長驗收後，其餘條件都已具備。

## 本次修正

| 項目 | 內容 |
|---|---|
| 新增 | `python -m radar publish --dry-run`（只模擬不送出）＋2 個測試＋README 指令表一列 |
| 修正 | `tests/test_security.py` 的 `test_scope` 不再因使用者新增品牌而失敗 |
| 新增 | `.github/workflows/test.yml`（CI） |
| 新增 | 本檔 |


## 2026-10-27 公開前補充
| 項目 | 結果 |
|---|---|
| 店長決策 | O02「兩個都公開」（2026-10-27）；第 3 道「真實帳號未實測」的已知限制一併接受，README 已註明 |
| 新發現的 bug | 客製化服務資訊含「衞」，繁中 Windows 主控台（cp950）印不出 → 啟動直接當掉。已改成印不出的字換成 ?，並加回歸測試 |
| 全部測試 | 繁中 Windows cp950 主控台：99 項全過（原 97） |
| 去識別化掃描 | `deep_audit.py`（現有檔案＋全歷史＋作者信箱＋照片 GPS），報告 `_qa/deep/O02_公開前.md`：命中全部判讀為誤判或刻意保留（地名、velo 誤判、作者署名與 林其衞的 LINE 客製化廣告、測試用合成假值）；歷史命中 0、非 noreply 作者 0 |
| 授權 | —Apache-2.0＋NOTICE（轉散布須保留作者與客製化聯絡資訊） |
| 金鑰 | 沒有任何真實金鑰進過這個 repo，不需輪替 |
| 第 7 道 | 舊歷史 bundle 備份後，以目前內容建立全新單一 commit 並 force push，再改 PUBLIC，最後從乾淨 clone 重跑測試與掃描 |
