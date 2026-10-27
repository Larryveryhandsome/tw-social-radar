"""貼文過濾規則（純規則，零 AI）。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_REL_RE = re.compile(r"(\d+)\s*(秒|分鐘?|小時|天|週|星期|月|年|s|m|h|d|w|y)")


def parse_relative_time(s: str, now: datetime | None = None) -> str | None:
    """把「3小時」「2天」「5d」轉成 ISO 時間；看不懂回 None。"""
    if not s:
        return None
    now = now or datetime.now()
    m = _REL_RE.match(s.strip())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    if n > 10000:  # 防怪數字（例如內文的「9999年」）讓時間溢位
        return None
    table = {"秒": "seconds", "s": "seconds", "分": "minutes", "分鐘": "minutes", "m": "minutes",
             "小時": "hours", "h": "hours", "天": "days", "d": "days",
             "週": "weeks", "星期": "weeks", "w": "weeks"}
    try:
        if unit in table:
            return (now - timedelta(**{table[unit]: n})).isoformat(timespec="seconds")
        if unit == "月":
            return (now - timedelta(days=30 * n)).isoformat(timespec="seconds")
        if unit in ("年", "y"):
            return (now - timedelta(days=365 * n)).isoformat(timespec="seconds")
    except (OverflowError, ValueError):
        return None
    return None


def parse_time(value) -> datetime | None:
    """接受 ISO 字串（含 +0000 / Z）、Unix 秒數。回傳不帶時區的本地時間。"""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            return datetime.fromtimestamp(int(value))
        v = str(value).strip().replace("Z", "+00:00")
        v = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", v)  # Threads API 給 +0000
        dt = datetime.fromisoformat(v)
        if dt.tzinfo:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except (ValueError, OSError, OverflowError):
        return None


def has_japanese_or_korean(text: str) -> bool:
    """含日文假名或韓文就跳過（台灣繁中市場，避免語境錯亂）。"""
    for c in text or "":
        if "぀" <= c <= "ヿ" or "가" <= c <= "힯":
            return True
    return False


def is_competitor(author: str, hints: list[str]) -> bool:
    a = (author or "").lower()
    return any(h.lower() in a for h in hints or [] if h)


def is_fresh(post: dict, max_age_days: int, now: datetime | None = None) -> bool:
    """貼文時間在 max_age_days 天內才收。沒有時間的貼文，看發現時間（3 天內收）。"""
    now = now or datetime.now()
    dt = parse_time(post.get("posted_at"))
    if dt:
        return now - dt <= timedelta(days=max_age_days)
    found = parse_time(post.get("discovered_at"))
    return bool(found and now - found <= timedelta(days=3))


def skip_reason(post: dict, brand: dict) -> str | None:
    """回傳跳過原因；可以用回傳 None。"""
    f = brand.get("filters") or {}
    text = post.get("content") or ""
    if len(text.strip()) < int(f.get("min_length", 8)):
        return "內文太短"
    if f.get("skip_japanese_korean", True) and has_japanese_or_korean(text):
        return "日韓文貼文"
    author = (post.get("author") or "").lower()
    if brand.get("handle") and author == brand["handle"].lower().lstrip("@"):
        return "自己的貼文"
    if is_competitor(author, brand.get("competitor_handle_hints")):
        return "同業帳號"
    low = text.lower()
    if any(w and w.lower() in low for w in brand.get("exclude_words") or []):
        return "命中排除詞"
    if not is_fresh(post, int(f.get("max_post_age_days", 30))):
        return "貼文太舊"
    return None
