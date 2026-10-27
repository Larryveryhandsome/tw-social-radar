"""草稿品質檢查：擋掉「互動誘餌」、「標題殺人法」、太重的 AI 腔、誇大承諾。

回傳 (等級, 說明)：BLOCK 退回不存、WARN 存但標記給審核的人看、OK 通過。
"""
from __future__ import annotations

import os
import re

# 這些環境變數的值絕不能出現在草稿裡（防 prompt injection 把金鑰騙出來）
SECRET_ENV = ["ANTHROPIC_API_KEY", "THREADS_ACCESS_TOKEN", "LINE_CHANNEL_ACCESS_TOKEN", "DISCORD_WEBHOOK_URL",
              "RADAR_REVIEW_PASSWORD", "THREADS_USER_ID", "LINE_TO_ID"]
CONTACT_PATTERNS = {
    "網址": r"https?://|www\.|[\w-]+\.(?:com|net|org|tw|io|cc|me|xyz|top|link)",
    "Email": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "電話": r"(?<!\d)0\d{1,3}[- ]?\d{3,4}[- ]?\d{3,4}(?!\d)",
    "LINE ID": r"(?i)line\s*(?:id)?\s*[:：]",
    "標記其他帳號": r"(?<![\w.])@[A-Za-z0-9_.]{3,}",
}

ENGAGEMENT_BAIT = ["分享給朋友", "轉發到限動", "分享出去", "tag 一個", "tag一個", "按讚如果你同意",
                   "覺得有用按愛心", "留言+1", "留言 +1", "留言1", "私訊我拿"]
CLICKBAIT = ["你絕對不會相信", "99%的人", "震驚", "你不知道的秘密", "沒人告訴你的"]
AI_MARKERS = ["讓我們來看看", "讓我們一起", "想像一下", "說白了就是", "但真正的問題是",
              "事情沒那麼簡單", "在這個瞬息萬變的時代", "在這個時代", "值得注意的是", "綜上所述",
              "總結而言", "不僅如此", "由此可見", "作為一個專業", "我們需要深入", "身為AI", "作為AI"]
# 廣告用語風險（公平交易法、各業別廣告規範）：原則上別在留言裡講
RISKY_CLAIMS = ["保證", "百分之百", "100%", "最便宜", "全台最", "第一名", "穩賺", "零風險", "無效退費"]


def leaks_secret(text: str) -> bool:
    for k in SECRET_ENV:
        v = (os.environ.get(k) or "").strip()
        if len(v) >= 6 and v in (text or ""):
            return True
    return False


def check(text: str, brand: dict | None = None, max_len: int = 220, strict: bool = False) -> tuple[str, list[str]]:
    """strict=True 用在 AI 寫的草稿：網址、聯絡方式、標記別人一律擋（貼文可能藏了 prompt injection）。"""
    notes: list[str] = []
    block = False
    low = (text or "").lower()
    if not low.strip():
        return "BLOCK", ["空白草稿"]
    if leaks_secret(text):
        return "BLOCK", ["草稿含有金鑰或密碼"]
    if strict:
        for name, pat in CONTACT_PATTERNS.items():
            if re.search(pat, text):
                notes.append(f"AI 草稿含{name}")
                block = True
    for w in ENGAGEMENT_BAIT:
        if w in low:
            notes.append(f"互動誘餌「{w}」")
            block = True
    for w in CLICKBAIT:
        if w in low:
            notes.append(f"標題殺人法「{w}」")
            block = True
    hits = [w for w in AI_MARKERS if w.lower() in low]
    if len(hits) >= 2:
        notes.append(f"AI 腔太重：{'、'.join(hits)}")
        block = True
    elif hits:
        notes.append(f"有一點 AI 腔：{hits[0]}")
    avoid = list(RISKY_CLAIMS) + list(((brand or {}).get("voice") or {}).get("avoid") or [])
    for w in avoid:
        if w and w.lower() in low:
            notes.append(f"避免用語「{w}」")
    if not strict and re.search(r"https?://", low):
        notes.append("含網址（留言貼連結容易被當成垃圾訊息）")
    if len(re.findall(r"#\S+", text)) > 2:
        notes.append("hashtag 太多")
    if re.search(r"([\U00010000-\U0010ffff])\1{2,}", text):
        notes.append("同一個 emoji 連續 3 個以上")
    if len(text) > max_len:
        notes.append(f"太長（{len(text)} 字，留言建議 {max_len} 字內）")
    level = "BLOCK" if block else ("WARN" if notes else "OK")
    return level, notes
