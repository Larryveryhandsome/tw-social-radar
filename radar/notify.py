"""有新草稿時通知（選用）：LINE Messaging API push、Discord webhook。

金鑰都放環境變數，不寫在程式或 yaml：
  LINE_CHANNEL_ACCESS_TOKEN、LINE_TO_ID（你的 userId 或群組 ID）
  DISCORD_WEBHOOK_URL
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def _post(url: str, body: dict, headers: dict | None = None) -> bool:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, OSError) as e:
        print(f"  [notify] 失敗：{e}")
        return False


def send(settings: dict, message: str) -> dict:
    cfg = settings.get("notify") or {}
    result = {}
    if cfg.get("line"):
        token, to = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"), os.environ.get("LINE_TO_ID")
        if token and to:
            result["line"] = _post("https://api.line.me/v2/bot/message/push",
                                   {"to": to, "messages": [{"type": "text", "text": message[:4900]}]},
                                   {"Authorization": f"Bearer {token}"})
        else:
            print("  [notify] notify.line=true 但缺 LINE_CHANNEL_ACCESS_TOKEN / LINE_TO_ID")
    if cfg.get("discord"):
        hook = os.environ.get("DISCORD_WEBHOOK_URL")
        if hook:
            result["discord"] = _post(hook, {"content": message[:1900]})
        else:
            print("  [notify] notify.discord=true 但缺 DISCORD_WEBHOOK_URL")
    return result


def draft_message(settings: dict, brand: dict, draft_ids: list[int]) -> str:
    url = (settings.get("notify") or {}).get("review_url", "").rstrip("/")
    ids = "、".join(f"#{i}" for i in draft_ids)
    return f"📡 {brand.get('display_name')} 有 {len(draft_ids)} 則新草稿（{ids}）\n審核：{url}/?brand={brand['key']}"
