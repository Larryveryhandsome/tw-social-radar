# 貢獻指南

歡迎 Issue 與 Pull Request！

## 開發

```bash
pip install -r requirements.txt
python -m unittest discover -s tests
```

- 核心程式只用 Python 標準函式庫＋PyYAML，請不要隨意加相依套件。
- 新功能請附測試；測試不可連網、不可需要真的金鑰（用 `unittest.mock` 假造回應）。
- 介面與文件用繁體中文、台灣用語。

## 歡迎的貢獻

- 新的產業範本（`brands/_presets/<產業>.yaml`），附一則能命中的假貼文到 `fixtures/demo_posts.jsonl`。
- 新的「合規」資料來源（官方 API、使用者自己匯出的檔案格式）。
- 新的 LLM provider。

## 不收的貢獻

為了使用者的帳號安全與法律風險，以下 PR 不會合併：

- 登入帳號爬網頁、模擬真人行為、養帳號、繞過驗證碼或偵測。
- 自動私訊、自動加好友、大量留言。
- 讓核心程式直接發文（自動發文只能做成 `extras/` 外掛，預設關閉，且只送人工核准的草稿）。
