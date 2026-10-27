"""Meta 官方 Threads API 關鍵字搜尋。

  GET https://graph.threads.com/v1.0/keyword_search?q=...&search_type=RECENT
需要權限 threads_basic + threads_keyword_search，權杖放環境變數 THREADS_ACCESS_TOKEN。
⚠️ 你的 App 還沒通過 Meta 審查前，原則上只搜得到「你自己帳號」的貼文；
   要搜公開貼文須先送審（流程見 docs/金鑰申請.md）。
官方有每人 24 小時查詢次數上限，所以每輪只查一部分關鍵字（輪流），不會一次全查。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .file_source import normalize

API = "https://graph.threads.com/v1.0/keyword_search"
FIELDS = "id,text,permalink,timestamp,username,has_replies,is_reply"


class ThreadsAPIError(RuntimeError):
    """kind：token（權杖過期／無效）、rate（額度用完）、other。partial：出錯前已抓到的貼文。"""

    def __init__(self, msg: str, kind: str = "other", partial: list | None = None):
        super().__init__(msg)
        self.kind, self.partial = kind, partial or []


def _classify(code: int, body: str) -> str:
    try:
        err = json.loads(body).get("error", {})
    except ValueError:
        err = {}
    ec = err.get("code")
    if ec in (190, 102, 463, 467) or code == 401 or err.get("type") == "OAuthException" and ec in (None, 190):
        return "token"
    if code == 429 or ec in (4, 17, 32, 613):
        return "rate"
    return "other"


def _get(url: str, timeout: int = 30, retries: int = 1) -> dict:
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            kind = _classify(e.code, body)
            if e.code >= 500 and attempt < retries:
                time.sleep(2)
                continue
            hint = {"token": "（權杖過期或無效：重新產生長效權杖，見 docs/金鑰申請.md）",
                    "rate": "（官方查詢額度用完，下一輪再試）"}.get(kind, "")
            # 錯誤訊息不含網址，避免把 access_token 寫進 log
            raise ThreadsAPIError(f"Threads API HTTP {e.code}{hint}：{body[:200]}", kind) from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise ThreadsAPIError(f"連不上 Threads API：{getattr(e, 'reason', e)}") from None
        except ValueError:
            raise ThreadsAPIError("Threads API 回應不是 JSON（格式可能改了）") from None
    raise ThreadsAPIError("Threads API 重試後仍失敗")


def search(keyword: str, token: str, search_type: str = "RECENT", limit: int = 25,
           since: int | None = None) -> list[dict]:
    q = {"q": keyword, "search_type": search_type, "fields": FIELDS,
         "limit": min(int(limit), 100), "access_token": token}
    if since:
        q["since"] = max(int(since), 1688540400)  # 官方最早只到這個時間
    data = _get(f"{API}?{urllib.parse.urlencode(q)}")
    out = []
    for raw in data.get("data", []) if isinstance(data.get("data"), list) else []:
        if not isinstance(raw, dict):
            continue
        if raw.get("is_reply"):
            continue  # 只看主貼文，不看別人底下的留言
        p = normalize(raw, source="threads_api")
        if p:
            p["source_keyword"] = keyword
            out.append(p)
    return out


def fetch(brand: dict, settings: dict, db) -> list[dict]:
    token = os.environ.get("THREADS_ACCESS_TOKEN", "")
    if not token:
        raise ThreadsAPIError("缺 THREADS_ACCESS_TOKEN（申請方式見 docs/金鑰申請.md）")
    cfg = (settings.get("source") or {}).get("threads_api") or {}
    kws = list(dict.fromkeys(brand.get("keywords") or []))
    if not kws:
        return []
    n = max(1, int(cfg.get("max_queries_per_run", 8)))
    # 關鍵字輪流查：記住上次查到哪裡，這輪接著查
    cursor_key = f"threads_api_cursor:{brand['key']}"
    start = int(db.get_meta(cursor_key, "0") or 0) % len(kws)
    picked = [kws[(start + i) % len(kws)] for i in range(min(n, len(kws)))]
    since = int(time.time() - float(cfg.get("fresh_hours", 72)) * 3600)
    out: list[dict] = []
    done = 0
    for kw in picked:
        try:
            out.extend(search(kw, token, cfg.get("search_type", "RECENT"), cfg.get("limit_per_keyword", 25), since))
        except ThreadsAPIError as e:
            # 權杖過期、額度用完：這輪停在這裡，下一輪從這個關鍵字接著查；已抓到的照樣收
            db.set_meta(cursor_key, str((start + done) % len(kws)))
            e.partial = out
            raise
        done += 1
    db.set_meta(cursor_key, str((start + done) % len(kws)))
    return out
