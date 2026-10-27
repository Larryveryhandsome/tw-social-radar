# threads_publisher（選用外掛，預設關閉）

把審核後台「已核准」的回覆，透過 **Meta 官方 Threads API** 送出。核心程式不會發文；只有你自己安裝這個外掛、
並把 `auto_publish.enabled` 改成 `true`，才會啟用。

## 先讀風險

- 原則上，自動留言仍可能被平台判定為垃圾訊息，帳號可能被限制。請遵守 [Threads 使用條款](https://help.instagram.com/769983657850450) 與 Meta 開發者政策。
- 本外掛**只用官方 API**，不模擬真人、不繞過驗證、不養帳號。
- 只會送出人工核准過的草稿；每品牌每日上限（預設 4 則）和發送時段（預設 8–22 點）由 `config/settings.yaml` 的 `auto_publish` 控制。
- 只能回覆從 `threads_api` 來源找到的貼文（要有官方媒體 ID）。用檔案匯入的貼文請人工回覆。
- 你的 App 要有 `threads_basic`、`threads_content_publish`、`threads_manage_replies` 權限；回覆別人的貼文通常要先通過 Meta 審查。

## 安裝與啟用

```bash
python -m radar plugin install threads_publisher
```

`.env` 補上：

```
THREADS_ACCESS_TOKEN=你的長效權杖
THREADS_USER_ID=你的 Threads 使用者 ID
```

`config/settings.yaml`：

```yaml
auto_publish:
  enabled: true
```

送出已核准的草稿（可以排程每 10–30 分鐘跑一次）：

```bash
python -m radar publish
```

申請方式見 [docs/金鑰申請.md](../../docs/金鑰申請.md)。
