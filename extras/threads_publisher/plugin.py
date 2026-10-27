"""外掛：用 Meta 官方 Threads API 送出「已人工核准」的回覆。預設不安裝、不啟用。

流程（官方兩段式）：
  1. POST /{user-id}/threads          media_type=TEXT、text、reply_to_id → 取得 creation_id
  2. POST /{user-id}/threads_publish  creation_id → 發布
需要：THREADS_ACCESS_TOKEN（含 threads_basic、threads_content_publish、threads_manage_replies 權限）、THREADS_USER_ID。
只處理來源是 threads_api 的貼文（post_id 必須是官方的媒體 ID）；匯入檔來的貼文請人工回覆。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://graph.threads.com/v1.0"
WAIT_SECONDS = int(os.environ.get("THREADS_PUBLISH_WAIT", "30"))  # 官方建議建立後等約 30 秒再發布


def _post(url: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode("utf-8")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method="POST"), timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Threads API HTTP {e.code}：{e.read().decode('utf-8', 'replace')[:300]}") from None


def publish_reply(draft: dict, settings: dict) -> str:
    if draft.get("status") not in ("approved", "publishing"):  # publishing = 已由 pipeline 鎖定
        raise RuntimeError("只能送出已核准的草稿")
    if draft.get("source") != "threads_api":
        raise RuntimeError("這則貼文不是從官方 API 來的，沒有可回覆的媒體 ID，請人工回覆")
    token, uid = os.environ.get("THREADS_ACCESS_TOKEN"), os.environ.get("THREADS_USER_ID")
    if not token or not uid:
        raise RuntimeError("缺 THREADS_ACCESS_TOKEN 或 THREADS_USER_ID")
    c = _post(f"{API}/{uid}/threads", {"media_type": "TEXT", "text": draft["reply_text"],
                                        "reply_to_id": draft["post_id"], "access_token": token})
    cid = c.get("id")
    if not cid:
        raise RuntimeError(f"建立回覆失敗：{c}")
    time.sleep(WAIT_SECONDS)
    r = _post(f"{API}/{uid}/threads_publish", {"creation_id": cid, "access_token": token})
    if not r.get("id"):
        raise RuntimeError(f"發布失敗：{r}")
    return r["id"]
