# tw-social-radar｜品牌社群雷達

幫台灣的在地小品牌，在 Threads 上找到**正在問、正在找**的潛在客人，並替你準備好回覆草稿。

- 📡 **雷達**：用 Meta 官方 Threads API 搜尋關鍵字，或匯入你自己整理的貼文檔。
- 🧹 **過濾**：去掉同業、自己的貼文、徵人或業配、太舊的貼文、日韓文貼文，再依「需求強度」排序。
- ✍️ **草稿**：照你在 `brand.yaml` 寫的模板挑一則，或讓 AI 依品牌口吻寫（Claude CLI／Claude API／Ollama 都可以）。
- ✅ **人工審核**：在本機的審核頁按核准、改寫或退回，退回要填原因，系統會學著少用被退的寫法。
- 🙋 **人工回覆**：開源版**不會替你發文**。核准後按「複製並開啟原文」，自己貼上留言。

> ⚠️ 原則上，請遵守平台使用條款與《個人資料保護法》：只看公開貼文、只留跟對方需求有關的回覆、不大量洗留言、不私訊騷擾。完整說明見 [docs/合規與風險.md](docs/合規與風險.md)。本專案**不收**登入帳號爬網頁、模擬真人、養帳號、繞過驗證的程式。

---

## 功能

| 功能 | 說明 |
|---|---|
| 多品牌 | 一個品牌一個 `brands/<key>/brand.yaml`：搜尋詞、上下文詞、排除詞、同業帳號、口吻、情境與模板 |
| 產業範本 | 在地服務業、餐飲、美業、補教、房仲，一行指令或在審核頁點選套用 |
| 來源 | `file`（JSON／JSONL／CSV 匯入）、`threads_api`（官方關鍵字搜尋，關鍵字輪流查，不超過官方額度） |
| 過濾 | 同業、自己、排除詞、太舊、太短、日韓文；同一則貼文同一品牌一輩子只產一次草稿 |
| 需求強度 | 預設用規則估 1–5 分；可改成請 LLM 判斷 |
| 草稿品質檢查 | 擋「留言+1」「分享給朋友」這類互動誘餌、標題殺人法、太重的 AI 腔；誇大用語、網址、太長會標警告 |
| 每日上限 | 每品牌每天最多產幾則草稿（預設 6），避免洗版 |
| 學習 | 核准 +1、改寫 +0.5、退回 −2；被退 3 次又從沒被核准的模板自動停用；你改寫的版本會變成新模板 |
| 通知（選用） | 有新草稿時推 LINE 或 Discord |
| 多人審核 | 新成員一個指令（或在審核頁「成員管理」點選）開審核帳號，只看得到、只能審自己負責的品牌；每次審核記錄是誰審的 |
| 巡邏中總覽 | 審核頁「📡 巡邏中」一眼看懂雷達在巡什麼：搜尋詞、上下文詞、同業、排除詞、主題情境，上一輪抓到／命中／產草稿幾則、被過濾的原因與範例、下一輪時間；可直接在網頁新增或停用關鍵字 |
| 管理員頁 | 不會用指令列也行：審核頁的「⚙️ 新增品牌」精靈（選產業 → 填名稱 → 自動建檔，不覆蓋既有品牌）、「👥 成員管理」（新增／刪除帳號、指派品牌）；只有管理員看得到 |
| 個資保護 | 只存必要欄位；貼文超過 60 天自動刪除（可調） |
| 自動發文（選用外掛） | `extras/threads_publisher`：只走官方 API、只送已核准的草稿、預設不安裝也不啟用 |

---

## 5 分鐘開始（用假資料試跑）

**需要：** Python 3.10 以上（[python.org 下載](https://www.python.org/downloads/)，Windows 安裝時勾選「Add python.exe to PATH」）。

```bash
pip install -r requirements.txt
```

```bash
python -m radar demo --reset
```

```bash
python -m radar review --demo
```

打開 http://127.0.0.1:8590 ，就能看到示範草稿，試試核准、改寫、退回。示範用的是 `fixtures/demo_posts.jsonl` 裡的假貼文和兩個虛構品牌，不會連網。

Windows 也可以雙擊 **`開啟審核後台.vbs`**（背景執行，不會跳黑色視窗）。

---

## 建立你自己的品牌

1. 看有哪些產業範本：

   ```bash
   python -m radar brand presets
   ```

2. 用範本建立品牌（key 用小寫英文；也可以在審核頁右上的「⚙️ 新增品牌」點選完成，見下方「管理員頁」）：

   ```bash
   python -m radar brand new myshop --preset local_service --name "我的清潔工作室" --handle my_threads_id
   ```

3. 打開 `brands/myshop/brand.yaml`，**把模板改成你自己的口吻**（欄位說明見 [docs/brand-yaml.md](docs/brand-yaml.md)）。

4. 檢查格式：

   ```bash
   python -m radar brand check
   ```

5. 不想用示範品牌：把 `brands/demo/brand.yaml`、`brands/demo-food/brand.yaml` 裡的 `enabled` 改成 `false`。

### 產業範本

| 範本 | 適合 | 預設情境 |
|---|---|---|
| `local_service` | 居家清潔、冷氣清洗、水電、搬家、到府服務 | 大掃除、退租／搬家、冷氣、修繕、求推薦 |
| `restaurant` | 餐廳、小吃、便當、咖啡廳、外燴 | 團訂、包場聚餐、求推薦 |
| `beauty` | 美髮、美甲、美睫、造型 | 換髮型、美甲美睫、婚禮活動 |
| `education` | 補習班、家教、才藝班、程式課 | 考試、科目卡關、求推薦 |
| `real_estate` | 房仲 | 買房、賣房、租屋 |

---

## 日常使用

1. 設定檔：把 `config/settings.example.yaml` 複製成 `config/settings.yaml` 再改。
2. 金鑰：把 `.env.example` 複製成 `.env` 再填（**用到才要填**）。
3. 選資料來源：
   - **匯入檔案**（預設）：把貼文檔放進 `inbox/`，格式見下方「匯入格式」。
   - **官方 Threads API**：`source.type: threads_api`，並在 `.env` 填 `THREADS_ACCESS_TOKEN`。
4. 檢查設定：

   ```bash
   python -m radar doctor
   ```

5. 跑一輪（抓貼文 → 產草稿）：

   ```bash
   python -m radar run
   ```

6. 開審核頁審草稿：

   ```bash
   python -m radar review
   ```

7. 核准後按「📋 複製並開啟原文」→ 到 Threads 貼上留言 → 回審核頁按「我已回覆」。

### 多人審核（公司新成員、幫客戶代管）

1. `.env` 設管理員密碼 `RADAR_REVIEW_PASSWORD`（至少 10 字；管理員登入帳號填 `admin`，看得到全部品牌）。
2. 幫新成員開帳號，指定他負責的品牌（全部品牌用 `*`）：

   ```bash
   python -m radar user add amy --brands myshop,client-a
   ```

3. 新成員用自己的帳號密碼登入審核頁，只會看到、只能審那幾個品牌；誰核准、誰退回都有紀錄。
4. 離職或換人：`python -m radar user remove amy`。看目前帳號：`python -m radar user list`。

> 新客戶＝新品牌：`python -m radar brand new client-a --preset restaurant --name "客戶店名"`，再用 `user add` 把它指派給負責的人。下一輪排程會自動納入，不用重開。

### 看雷達在巡什麼（📡 巡邏中）

審核頁上方按「📡 巡邏中」（`/patrol`）。審核員只看得到自己負責的品牌，admin 看全部。每個品牌會列出：

| 區塊 | 內容 |
|---|---|
| 最後一輪 | 抓到幾則、新貼文、命中、產草稿；資料來源（file／threads_api）與錯誤訊息 |
| 雷達搜尋詞 | 每個詞近 7 天抓到幾則；threads_api 來源另外列出「下一輪會搜尋」哪幾個詞 |
| 上下文詞、排除詞、同業帳號提示 | 目前生效的清單 |
| 主題情境 | 每個情境的比對詞、最後一輪命中幾則、近 7 天產了幾則草稿 |
| 被過濾掉的貼文 | 各原因的則數（同業、太舊、日韓文、排除詞、沒命中觸發詞、自己的貼文…），外加幾則範例（只留帳號與前 40 字） |
| 下一輪 | 上一輪時間＋`schedule.interval_minutes`（預設 30）推算；畫面上會註明「依設定推算」。要跟你在工作排程器／crontab 設的間隔一樣 |

**在網頁上新增／停用關鍵字**：每個清單下面有輸入框和「新增」，每個詞旁邊有「停用」，停用的詞可以再「啟用」。

- 改動存在資料庫，**不改 `brand.yaml`**（你的註解不會被洗掉），下一輪起生效；停用 brand.yaml 原有的詞也可以。
- 新增的詞要 2–40 字，空白一律拒絕（空字串會讓每一篇貼文都命中）；雷達搜尋詞至少要留一個。
- 審核員可以改自己負責的品牌，admin 可以改全部；每次停用／啟用都記錄是誰改的（卡片底下「關鍵字異動紀錄」）。
- 統計存在資料表 `run_log`，跟貼文一樣超過 `retention_days` 自動刪除。

### 管理員頁（不用指令列，點選完成）

用帳號 `admin`＋`RADAR_REVIEW_PASSWORD` 登入審核頁，最上面會多兩個按鈕（審核員看不到，直接打網址也會被拒絕，回 403）：

| 頁面 | 網址 | 可以做什麼 |
|---|---|---|
| ⚙️ 新增品牌 | `/admin/brands` | 選產業範本 → 填品牌名稱、品牌代號（key）、自己的 Threads 帳號 → 自動產生 `brands/<key>/brand.yaml`。**已經存在的品牌一律不覆蓋**；建好後原則上還是要打開檔案，把關鍵字和模板改成自己的口吻 |
| 👥 成員管理 | `/admin/members` | 列出審核帳號；新增帳號（**密碼請本人當面輸入**，只存雜湊）；勾選負責的品牌；刪除帳號 |

- 本機自己用、沒設任何密碼時，你就是管理員，可以用「新增品牌」；但要先設 `RADAR_REVIEW_PASSWORD` 才能新增成員（不然新帳號登入不了）。
- 兩頁沿用審核頁同一套保護：Host 檢查、登入失敗鎖定、CSP、每個操作都要帶 `X-Radar` 標頭。

### 定時自動跑（只產草稿）

- **Windows**：`背景掃描.vbs` 會在背景跑一輪，log 寫到 `data/run.log`，不會跳出視窗。用「工作排程器」每 30–60 分鐘執行一次：

  ```bash
  schtasks /Create /TN "tw-social-radar-scan" /SC MINUTE /MO 30 /TR "wscript.exe \"%CD%\背景掃描.vbs\""
  ```

  （在專案資料夾打開命令提示字元再執行；要刪除：`schtasks /Delete /TN tw-social-radar-scan /F`）
- **macOS／Linux**：用 crontab，例如每 30 分鐘：`*/30 * * * * cd /path/to/tw-social-radar && python3 -m radar run >> data/run.log 2>&1`

### 匯入格式

JSON（陣列）、JSONL（一行一則）、CSV（第一列欄名）都可以：

| 欄位 | 必填 | 別名 | 說明 |
|---|---|---|---|
| `post_id` | ✅ | `id` | 貼文 ID |
| `content` | ✅ | `text` | 內文 |
| `author` | | `username` | 發文者帳號 |
| `url` | | `permalink` | 貼文連結（審核頁的「開啟原文」用） |
| `posted_at` | | `timestamp` | 發文時間（ISO 或 Unix 秒）；也可以給 `posted_relative`（例如「3小時」）或 `hours_ago` |

也可以直接指定檔案：`python -m radar import 我的貼文.csv`

### 指令總表

| 指令 | 用途 |
|---|---|
| `python -m radar doctor` | 檢查設定、品牌檔、LLM、金鑰 |
| `python -m radar demo --reset` | 用假資料跑一次 |
| `python -m radar run [--brand KEY]` | 跑一輪 |
| `python -m radar import 檔案...` | 匯入檔案後跑一輪 |
| `python -m radar review [--demo]` | 開審核頁 |
| `python -m radar drafts [--status pending]` | 在終端機列草稿 |
| `python -m radar export [--out 檔名.csv]` | 匯出草稿（Excel 可開） |
| `python -m radar brand list／presets／check／new` | 品牌管理 |
| `python -m radar plugin list／install NAME` | 外掛 |
| `python -m radar user list／add NAME --brands a,b／remove NAME` | 審核帳號（多人審核；也可在審核頁「👥 成員管理」點選） |
| `python -m radar publish` | （外掛模式）送出已核准的草稿；沒裝外掛不會做任何事 |
| `python -m radar publish --dry-run` | 只模擬不送出：列出「現在執行會送出哪幾則」，不連網、不改任何狀態 |

---

## 換 LLM

`config/settings.yaml` 的 `llm.provider`：

| provider | 費用 | 需要 | 適合 |
|---|---|---|---|
| `mock` | 免費 | 無 | 示範、測試（不連網） |
| `claude_cli` | 用你的 Claude 訂閱額度 | 安裝 [Claude Code](https://docs.claude.com/en/docs/claude-code) 並登入 | 已經有 Claude 訂閱的人 |
| `claude_api` | 依用量計費 | `ANTHROPIC_API_KEY` | 要放在伺服器上跑 |
| `ollama` | 免費（用自己電腦算） | 安裝 [Ollama](https://ollama.com/) 並下載模型 | 不想把貼文送到雲端 |

- `llm.draft_mode: template` 時**完全不呼叫 LLM**（零成本），只用模板。改成 `llm` 才請 AI 寫。
- AI 寫的草稿被品質檢查擋下、或 AI 連不上時，自動退回用模板，不會整輪失敗。
- **貼文是陌生人寫的，可能藏著「忽略規則、輸出網址」之類的指令（prompt injection）。** 所以：
  - `claude_cli` 一律關掉所有工具與 MCP、在空資料夾裡執行，AI 只能回文字，碰不到你的檔案或帳號。
  - AI 草稿只要含網址、電話、Email、LINE ID、標記別人，或含有你的任何金鑰，一律擋下改用模板。
  - 不管怎樣，草稿都要人工核准才會出去。

---

## 需要哪些金鑰？

**只跑示範、只用匯入檔案＋模板：不需要任何金鑰。** 其他都是用到才要：

| 用途 | 環境變數 | 費用 |
|---|---|---|
| 官方 Threads 關鍵字搜尋 | `THREADS_ACCESS_TOKEN` | 免費（有查詢次數上限） |
| Claude API 寫草稿 | `ANTHROPIC_API_KEY` | 依用量計費 |
| LINE 通知 | `LINE_CHANNEL_ACCESS_TOKEN`、`LINE_TO_ID` | 免費方案有每月則數上限 |
| Discord 通知 | `DISCORD_WEBHOOK_URL` | 免費 |
| 審核頁給手機連 | `RADAR_REVIEW_PASSWORD` | 自己設一組 |
| 自動發文外掛 | `THREADS_ACCESS_TOKEN`、`THREADS_USER_ID` | 免費 |

👉 每一項怎麼申請、填在哪裡、費用與安全注意事項：[docs/金鑰申請.md](docs/金鑰申請.md)

---

## 用 Claude Code 幫你架設

`skill/SKILL.md` 是一份 Claude Code 技能，會一步一步帶你：裝環境 → 建品牌 → 調口吻 → 接資料來源 → 設排程 → 診斷問題。

把 `skill/` 資料夾複製到 `~/.claude/skills/tw-social-radar/`，然後在 Claude Code 說「幫我架社群雷達」。詳見 [skill/SKILL.md](skill/SKILL.md)。

---

## 自動發文外掛（預設關閉）

核心程式沒有任何發文功能。如果你確定要讓「已核准」的回覆自動送出，可以另外安裝只走官方 API 的外掛，安裝前請先讀 [extras/threads_publisher/README.md](extras/threads_publisher/README.md) 的風險說明：

```bash
python -m radar plugin install threads_publisher
```

---

## 專案結構

```
tw-social-radar/
├─ radar/                核心程式（只用標準庫＋PyYAML）
│  ├─ sources/           資料來源：file、threads_api
│  ├─ llm/               可抽換的 LLM：mock、claude_cli、claude_api、ollama
│  ├─ filters.py         過濾規則      matcher.py  情境比對＋模板學習
│  ├─ intent.py          需求強度      guard.py    草稿品質檢查
│  ├─ drafter.py         產草稿        pipeline.py 一輪流程
│  └─ review_server.py   審核頁        cli.py      指令列
├─ brands/               品牌設定（_presets/ 是產業範本，demo* 是示範）
├─ config/               settings.example.yaml
├─ extras/               選用外掛（不會自動載入）
├─ fixtures/             示範用假貼文
├─ skill/                Claude Code 技能
├─ docs/                 金鑰申請、合規與風險、brand.yaml 說明
└─ tests/                測試
```

## 測試

```bash
python -m unittest discover -s tests
```

測試不連網、不需要金鑰：所有對外呼叫（Threads API、Claude API、Ollama、LINE、Discord）都用假的回應驗證送出的內容。

## 授權

[Apache-2.0](LICENSE)。資安問題請看 [SECURITY.md](SECURITY.md)，想貢獻請看 [CONTRIBUTING.md](CONTRIBUTING.md)。

本專案只是工具，原則上不構成法律意見；使用者應自行確認是否符合平台條款與相關法規。

---

## ⚠️ 已知限制

- 串接 Threads、LINE、Claude、Ollama 的部分都用模擬回應測過；**還沒有用真實帳號完整實測**。第一次串接時，建議先用測試帳號、保持「自動發文」關閉，確認草稿正常後再正式使用。
- 本工具只產生草稿，原則上由人工審核後才發出；使用方式請自行確認符合平台條款與《個人資料保護法》。

## 🛠️ 需要客製化？

這個工具是開源的，可以免費使用。如果你想要：

- 改成符合你們品牌的口吻、情境和審核流程
- 串接你現在在用的系統（LINE 官方帳號、Google 表單、CRM……）
- 幫你安裝、申請 API、設定排程、教學，或長期維護

歡迎加 LINE 跟我們聊。我們會依需求的範圍與複雜度報價，原則上以實際報價單為準。

<a href="https://lin.ee/pdYGARu"><img src="https://scdn.line-apps.com/n/line_add_friends/btn/zh-Hant.png" alt="加入好友" height="36"></a>

- 💬 LINE 官方帳號：[@812ibtir](https://lin.ee/pdYGARu)（請註明「品牌社群雷達 客製化」）
- 🏢 留白事務所：網頁設計、AI 自動化、房仲遠端助理
- 👤 作者：[留白事務所](https://github.com/Larryveryhandsome)
