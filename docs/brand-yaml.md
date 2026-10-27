# brand.yaml 欄位說明

一個品牌一個資料夾：`brands/<key>/brand.yaml`。用 `python -m radar brand new` 從產業範本建立，改完跑 `python -m radar brand check` 檢查。

```yaml
key: myshop                  # 品牌代號：小寫英數、- 和 _（建立後不要改，資料庫用它分品牌）
display_name: 我的清潔工作室   # 審核頁顯示的名字
handle: my_threads_id        # 你自己的 Threads 帳號（不含 @），用來排除自己的貼文
industry: 在地服務業           # 給 AI 參考的產業說明
enabled: true                # false = 暫停這個品牌

keywords: [清潔推薦, 大掃除]  # 雷達搜尋詞（threads_api 來源拿去查；輪流查）
indicators: [清潔, 打掃]      # 上下文詞：貼文至少要有一個，才繼續比對情境（擋掉短詞亂抓）
exclude_words: [徵人, 業配]   # 命中任一個就整篇跳過
competitor_handle_hints: [clean]  # 帳號名稱含這些字視為同業，不回

filters:
  skip_japanese_korean: true # 跳過日韓文貼文
  max_post_age_days: 14      # 超過幾天的貼文不回
  min_length: 8              # 內文太短不看
  min_intent: 2              # 需求強度（1–5）低於這個不產草稿

limits:
  max_drafts_per_day: 6      # 每天最多產幾則草稿（上限 30）
  max_drafts_per_run: 3      # 每輪最多幾則

voice:                       # 品牌口吻（llm 模式給 AI 參考；品質檢查也會用 avoid）
  tone: 溫暖、像熱心的鄰居
  self_reference: 我們
  emoji: ["✨", "☺️"]
  cta: 有需要可以私訊我們聊聊
  avoid: [最便宜, 保證]       # 草稿出現這些字會標警告
  examples:                  # 你最滿意的幾則留言，AI 會照語氣寫
    - 大掃除自己弄真的會累到腰斷⋯⋯有需要私訊聊聊 ☺️

triggers:                    # 情境：由上往下比對，命中第一個就用
  - id: deep_clean           # 情境代號（審核頁會顯示、學習也用它分組）
    match_any: [大掃除, 深度清潔]   # 貼文含任一個就命中
    negative_any: [掃完了]         # 含任一個就跳過這個情境（改比對下一個）
    templates:                     # 回覆模板，隨機挑一則；越多則越不像機器人
      - 大掃除自己弄一天下來腰都要斷了⋯⋯有需要私訊聊聊 ☺️
```

## 寫模板的建議

- **先回應對方，再說你能幫什麼**。不要一開口就是店名和價格。
- 一個情境至少 3–5 則不同寫法；系統會避開 7 天內用過的同一句。
- 不要放網址、不要放電話；請對方私訊或看你的個人簡介。
- 不要寫「留言+1」「分享給朋友」這種互動誘餌（品質檢查會直接擋掉）。
- 比對順序是由上往下：比較精準的情境放上面，「求推薦」這種寬的放最後。

## 學習怎麼運作

| 你在審核頁做的事 | 系統怎麼學 |
|---|---|
| ✅ 原文核准 | 這則模板權重 +1 |
| ✅ 改寫後核准 | 原模板 +0.5；你改寫的版本變成這個情境的新候選模板 |
| ❌ 退回（要填原因） | 這則模板權重 −2；被退 3 次又從沒被核准就停用；llm 模式會把最近被退的例子和原因告訴 AI |
