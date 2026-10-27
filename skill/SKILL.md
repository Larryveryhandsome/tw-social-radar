---
name: tw-social-radar
description: "帶使用者從零架設 tw-social-radar 品牌社群雷達：安裝、建立品牌、校準品牌口吻、接資料來源（匯入檔或官方 Threads API）、選 LLM、審核流程、排程、通知與診斷。使用者說「幫我架社群雷達」「建立海巡」「加入新品牌」「品牌校準」「雷達沒有草稿」「設定排程」時使用。"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# tw-social-radar 架設技能

這個技能帶使用者把 tw-social-radar 架起來，讓 Threads 上「正在找服務」的貼文自動變成待審的回覆草稿。

## 硬邊界（每一步都要遵守）

1. **只產草稿、人工審核、人工回覆。** 不要幫使用者寫自動發文、自動私訊、自動按讚的程式。
2. **不寫爬蟲與規避偵測。** 不用 Playwright／Selenium 登入帳號爬網頁、不做隨機延遲裝真人、不做養帳號（warmup）、不繞驗證碼。使用者要求時，說明風險並改走官方 Threads API 或匯入檔案。
3. **自動發文只能用 `extras/threads_publisher` 外掛**（只走官方 API、只送已核准草稿、預設關閉）。要啟用前先讓使用者讀過 `extras/threads_publisher/README.md`，並取得使用者明確同意。
4. **金鑰只放 `.env`。** 不寫進 yaml、程式、commit；使用者把金鑰貼在對話裡時，提醒他用完到發放處重新產生。
5. **不動使用者正在運作的其他系統。** 改設定前先備份；刪除前先讀內容。
6. **AI 只能回文字**：`claude_cli` 已經用 `--tools "" --strict-mcp-config` 在空資料夾執行。不要為了「讓 AI 更聰明」幫它打開工具或 MCP——貼文是陌生人寫的，可能藏 prompt injection。
7. **Windows 背景程序一律不開視窗**：排程用 `wscript.exe 背景掃描.vbs`；程式呼叫 claude CLI 已經帶 `CREATE_NO_WINDOW`。
8. **說「完成」前要有證據**：跑 `python -m radar doctor`、`python -m unittest discover -s tests`、`python -m radar run` 的實際輸出。

## 意圖路由

| 使用者說 | 從哪裡開始 |
|---|---|
| 幫我架社群雷達、從頭設定 | Phase 0 → 依序走完 |
| 加入新品牌、新增品牌 | Phase 1 |
| 品牌校準、口吻不像、重跑語音分析 | Phase 2 |
| 接 Threads API、改資料來源 | Phase 3 |
| 換 AI、用 Ollama、用 Claude | Phase 4 |
| 怎麼審核、後台怎麼用、手機看 | Phase 5 |
| 設定排程、自動跑 | Phase 6 |
| LINE 通知、Discord 通知 | Phase 7 |
| 沒有草稿、跑不起來、錯誤 | Phase 8 |
| 雷達在巡什麼、加關鍵字、停用關鍵字 | Phase 5「看雷達在巡什麼」 |

每個 Phase 完成後，給使用者看驗證輸出，確認後再進下一個。

---

## Phase 0：環境

1. 確認 Python 3.10 以上：`python --version`（macOS／Linux 用 `python3`）。
2. 取得專案：`git clone https://github.com/Larryveryhandsome/tw-social-radar.git`，或下載 ZIP 解壓。
3. 安裝：`pip install -r requirements.txt`（只有 PyYAML）。
4. 驗證：
   - `python -m unittest discover -s tests` → 全部 OK
   - `python -m radar demo --reset` → 看到「示範完成：產生 N 則草稿」
   - `python -m radar review --demo` → 打開 http://127.0.0.1:8590 看得到示範草稿
5. 讓使用者在審核頁實際按一次核准、改寫、退回，理解流程。

## Phase 1：建立品牌

先問清楚（一次問完）：

| 要問的 | 用途 |
|---|---|
| 品牌名稱、產業、服務地區 | `display_name`、選產業範本、`industry` |
| 自己的 Threads 帳號 | `handle`（排除自己的貼文） |
| 主要服務（3–6 項） | 寫 `triggers` |
| 客人通常怎麼描述需求 | `keywords`、`match_any` |
| 同業帳號常見字 | `competitor_handle_hints` |
| 不想碰的話題 | `exclude_words` |
| 每天大概能審幾則 | `limits.max_drafts_per_day` |

步驟（使用者不會用指令列時，改走審核頁的「⚙️ 新增品牌」精靈：用 admin 登入 → `/admin/brands` → 選產業、填名稱／key／Threads 帳號 → 建立；第 1、2 步就完成了，接著照第 3 步改檔）：

1. `python -m radar brand presets` 列出範本（local_service、restaurant、beauty、education、real_estate）。
2. `python -m radar brand new <key> --preset <範本> --name "<品牌名>" --handle <帳號>`
3. 依訪談內容改 `brands/<key>/brand.yaml`（欄位說明：`docs/brand-yaml.md`）：
   - `keywords` 用客人會打的字，不是行話（「冷氣好臭」比「冷氣保養」好）。
   - `indicators` 要夠寬，`match_any` 要夠準。
   - 每個情境 3–5 則模板，先回應對方再說能幫什麼；不放網址、不放電話。
   - 不用誇大用語（保證、最便宜、第一名）；美業不用醫療用語；房仲注意經紀業名稱揭露。
4. 示範品牌不需要的話，把 `brands/demo*/brand.yaml` 的 `enabled` 改 `false`。
5. 驗證：`python -m radar brand check` 全部 ✅。

## Phase 2：品牌口吻校準

目的：讓模板與 AI 草稿聽起來像品牌本人，不像罐頭。

1. 請使用者提供 20 則以上自己帳號的貼文或留言（貼文字、或匯出檔）。**不要**為了拿貼文去爬使用者的帳號頁面。
2. 分析並寫進 `voice`：
   - `tone`：一句話描述（例如「溫暖、像熱心的鄰居，先同理再提供幫忙」）
   - `self_reference`：自稱（我們／小編／本店）
   - `emoji`：常用的 2–4 個
   - `cta`：常用的結尾引導
   - `avoid`：品牌不會講的字
   - `examples`：挑 3–5 則最像品牌的句子
3. 依分析結果改寫各情境的 `templates`。
4. 給使用者看 3 則改寫前後對照，確認口吻。
5. **可選外掛**：想要更細的語感分析，可以另外安裝第三方的 [AK-Threads-booster](https://github.com/akseolabs-seo/AK-Threads-booster)（MIT 授權，作者 AK SEO Labs）的 `/voice` 模組，把產出的品牌語音摘要手動整理進 `voice`。本專案沒有內附它，請依它的說明自行安裝。

## Phase 3：資料來源

| 來源 | 適合 | 設定 |
|---|---|---|
| `file`（預設） | 先試用、或 API 還沒送審通過 | 把 JSON／JSONL／CSV 放進 `inbox/`，或 `python -m radar import 檔案` |
| `threads_api` | 正式使用 | `source.type: threads_api`＋`.env` 的 `THREADS_ACCESS_TOKEN` |

接官方 API：

1. 帶使用者照 `docs/金鑰申請.md` 第一節申請（建立 App → 開 `threads_basic`、`threads_keyword_search` → 測試人員 → 產生長效權杖）。
2. 說清楚：**App 沒通過 `threads_keyword_search` 審查前，原則上只搜得到自己的貼文**。送審前先用 `file` 來源。
3. `max_queries_per_run` 預設 8，配合每 30–60 分鐘一輪，不會超過官方每 24 小時查詢上限。
4. 驗證：`python -m radar doctor` 無 ❌ → `python -m radar run` 看到「抓到 N」。

## Phase 4：選 LLM

| provider | 什麼時候選 |
|---|---|
| `mock` | 只示範、測試 |
| `claude_cli` | 使用者已有 Claude 訂閱、在自己電腦跑 |
| `claude_api` | 要放伺服器跑、需要穩定；記得在 Console 設每月花費上限 |
| `ollama` | 不想把貼文送雲端；需要電腦夠力 |

- `draft_mode: template`：完全不呼叫 LLM（零成本），建議剛開始先用這個，模板穩了再開 `llm`。
- `draft_mode: llm`：AI 依 `voice` 寫；被品質檢查擋下或 AI 掛掉會自動退回模板。
- `classify: true`：請 AI 判斷需求強度（每則候選貼文多一次呼叫）。
- 驗證：`python -m radar doctor`，再 `python -m radar run --brand <key>`，到審核頁看草稿標「AI」還是「模板」。

## Phase 5：審核與回覆

1. 開審核頁：`python -m radar review`（Windows 可雙擊 `開啟審核後台.vbs`）。
2. 每則草稿：✅ 核准（可先改字）、❌ 退回（**一定選原因**，系統用來學習）。
3. 「已核准待回覆」分頁 → 「📋 複製並開啟原文」→ 到 Threads 貼上 → 回來按「我已回覆」。
4. 要用手機審核：`.env` 設 `RADAR_REVIEW_PASSWORD`（至少 10 字），`review.host: 0.0.0.0`；從外網連一定要經過 HTTPS 通道（例如 Cloudflare Tunnel），並把網域加進 `review.allowed_hosts`。不要直接開路由器連接埠。
5. 多人審核（新成員、代管客戶品牌）：`python -m radar user add 名字 --brands 品牌1,品牌2`（請使用者自己輸入密碼，不要幫他想、也不要寫進對話）。新成員只看得到自己的品牌；離職用 `user remove`。
   - 不會用指令列：用 admin 登入審核頁 → 「👥 成員管理」（`/admin/members`）新增帳號、勾選負責品牌、刪除帳號。密碼一樣請本人在表單輸入。要先設好 `RADAR_REVIEW_PASSWORD` 才能新增成員。
   - 兩個管理員頁只有 admin 看得到，審核員連進去回 403；網頁上建品牌不會覆蓋已存在的品牌，要改既有品牌請直接編輯 yaml。
6. 草稿 3 天沒審會自動過期。

### 看雷達在巡什麼

1. 審核頁上方按「📡 巡邏中」（`/patrol`）。先帶使用者看：上一輪抓到／命中／產草稿幾則、被過濾的原因（哪個原因最多）、下一輪時間。
2. 「被過濾」裡「沒命中觸發詞」很多 → `match_any` 或上下文詞太窄；「同業帳號」很多 → 檢查 `competitor_handle_hints` 是否太寬（例如把一般人的帳號也擋掉）。
3. 要加／停用雷達搜尋詞、上下文詞、排除詞、同業提示：直接在該品牌卡片上操作，**不用改 yaml**（存在資料庫，下一輪生效，誰改的會記錄）。新增的詞 2–40 字、不能空白；雷達搜尋詞至少留一個。
4. 主題情境（triggers）與模板還是改 `brands/<key>/brand.yaml`。
5. 「下一輪」是用 `schedule.interval_minutes`（預設 30）推算的；請把它設成和工作排程器／crontab 相同。顯示「排程可能沒在跑」時，回 Phase 6 檢查排程。

## Phase 6：排程（只產草稿）

Windows（不跳視窗）：

```bash
schtasks /Create /TN "tw-social-radar-scan" /SC MINUTE /MO 30 /TR "wscript.exe \"<專案完整路徑>\背景掃描.vbs\""
```

- 建立前先跟使用者確認任務名稱與頻率；不要覆蓋使用者原有的同名任務（先 `schtasks /Query /TN tw-social-radar-scan`）。
- log 在 `data/run.log`。
- macOS／Linux：crontab `*/30 * * * * cd <路徑> && python3 -m radar run >> data/run.log 2>&1`

驗證：等下一次觸發後看 `data/run.log` 有新的一輪紀錄。

## Phase 7：通知（選用）

- LINE：`notify.line: true`＋`.env` 的 `LINE_CHANNEL_ACCESS_TOKEN`、`LINE_TO_ID`（`docs/金鑰申請.md` 第六節）。
- Discord：`notify.discord: true`＋`DISCORD_WEBHOOK_URL`（第七節）。
- `notify.review_url` 改成使用者實際打得開的審核頁網址。
- 驗證：`python -m radar run` 有產生新草稿時，確認收到一則合併通知。

## Phase 8：診斷

| 現象 | 檢查 |
|---|---|
| 一直 0 則草稿 | `python -m radar run` 的輸出：「抓到」是 0 → 來源問題（Phase 3）；「命中」是 0 → `indicators`／`match_any` 太窄；有命中沒草稿 → `min_intent` 太高或今天已達上限 |
| 草稿都不相關 | `indicators` 太寬、`match_any` 太短；加 `exclude_words`、`negative_any` |
| 同一句一直出現 | 模板太少；每情境補到 5 則以上 |
| 被品質檢查擋 | 看終端機「[guard]」訊息，改掉互動誘餌或 AI 腔 |
| 關鍵字搜尋只找到自己的貼文 | App 還沒通過審查 |
| `doctor` 有 ❌ | 照訊息補 `.env`，對照 `docs/金鑰申請.md` 疑難排解 |
| 審核頁打不開 | 有沒有在跑 `python -m radar review`？埠號 8590 被占用就加 `--port 8591` |
| 「Host 不允許」 | 把連線用的網域加進 `review.allowed_hosts` |
| 終端機顯示「上一輪 run 還在跑」 | 排程間隔太短或上一輪卡住；超過 2 小時的舊鎖會自動清掉 |
| 收到「雷達抓不到貼文」通知 | 多半是 Threads 權杖過期（60 天），照 `docs/金鑰申請.md` 續期 |

查資料庫狀態：`python -m radar drafts --status pending`、`python -m radar export`。

## 新品牌 SOP（摘要）

1. Phase 1 建品牌 → 2. Phase 2 校準口吻 → 3. `python -m radar brand check` → 4. `python -m radar run --brand <key>` → 5. 審核頁審 5–10 則，依退回原因改模板 → 6. 排程已經在跑的話不用另外設定，新品牌下一輪自動納入。
