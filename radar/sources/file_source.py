"""從檔案匯入貼文：JSON（陣列）、JSONL（一行一則）、CSV（第一列是欄名）。

欄位（名稱可用別名）：
  post_id / id            必填，平台上的貼文 ID
  content / text          必填，內文
  author / username       發文者帳號
  url / permalink         貼文連結
  posted_at / timestamp   發文時間（ISO 或 Unix 秒）；也可以給 posted_relative「3小時」或 hours_ago
匯入過的檔案會記在資料庫，同一個檔案（路徑＋修改時間）不會重複處理。
"""
from __future__ import annotations

import csv
import glob
import io
import json
from datetime import datetime, timedelta
from pathlib import Path

from ..config import ROOT
from ..filters import parse_relative_time, parse_time


def safe_url(u) -> str:
    """只收 http(s) 網址；javascript: 之類的連結在審核頁點下去會執行程式，一律丟掉。"""
    u = str(u or "").strip()
    return u if u.lower().startswith(("https://", "http://")) and not any(c in u for c in "\"'<> ") else ""


def normalize(raw: dict, source: str = "file") -> dict | None:
    pid = str(raw.get("post_id") or raw.get("id") or "").strip()
    content = str(raw.get("content") or raw.get("text") or "").strip()
    if not pid or not content:
        return None
    posted = raw.get("posted_at") or raw.get("timestamp")
    if posted:
        dt = parse_time(posted)
        posted = dt.isoformat(timespec="seconds") if dt else None
    elif raw.get("posted_relative"):
        posted = parse_relative_time(str(raw["posted_relative"]))
    elif raw.get("hours_ago") not in (None, ""):
        posted = (datetime.now() - timedelta(hours=float(raw["hours_ago"]))).isoformat(timespec="seconds")
    return {
        "post_id": pid,
        "platform": _text(raw.get("platform"), 20) or "threads",
        "author": str(raw.get("author") or raw.get("username") or "").strip().lstrip("@")[:100],
        "content": content,
        "url": safe_url(raw.get("url") or raw.get("permalink")),
        "posted_at": posted,
        "source": source,
        "source_keyword": _text(raw.get("source_keyword") or raw.get("keyword"), 100) or None,
        "reply_count": _int(raw.get("reply_count")),
        "like_count": _int(raw.get("like_count")),
    }


def _text(v, limit: int) -> str:
    """匯入檔的選填文字欄位可能是清單或數字；一律轉成短字串，避免寫進資料庫時整批失敗。"""
    if isinstance(v, (list, tuple)):
        v = ",".join(str(x) for x in v)
    return str(v or "").strip()[:limit]


def _int(v) -> int:
    """按讚／回覆數：壞值或超過 SQLite INTEGER 範圍（例如 1e20）一律夾在 0～2^63-1。"""
    try:
        return max(0, min(int(float(v or 0)), 2**63 - 1))
    except (TypeError, ValueError, OverflowError):
        return 0


def read_file(path: Path) -> list[dict]:
    """壞掉的那幾列略過並提示，不讓整個檔案（和整輪）失敗。"""
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    bad = 0
    if path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(io.StringIO(text, newline="")))  # 保留引號內的換行
    elif path.suffix.lower() == ".jsonl":
        rows = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                bad += 1
    else:
        try:
            data = json.loads(text)
        except ValueError:
            print(f"  [file] {path.name} 不是合法的 JSON，略過")
            return []
        rows = data.get("data", data) if isinstance(data, dict) else data
    out = []
    for r in rows if isinstance(rows, list) else []:
        try:
            p = normalize(r) if isinstance(r, dict) else None
        except (TypeError, ValueError, AttributeError, OverflowError):
            p = None
        if p:
            out.append(p)
        else:
            bad += 1
    if bad:
        print(f"  [file] {path.name} 有 {bad} 列格式不對（缺 post_id 或內文），已略過")
    return out


def fetch(brand: dict, settings: dict, db) -> list[dict]:
    patterns = ((settings.get("source") or {}).get("file") or {}).get("paths") or []
    out: list[dict] = []
    for pat in patterns:
        full = pat if Path(pat).is_absolute() else str(ROOT / pat)
        for f in sorted(glob.glob(full)):
            p = Path(f)
            mark = f"imported:{p.resolve()}:{int(p.stat().st_mtime)}"
            if db.get_meta(mark):
                continue
            out.extend(read_file(p))
            db.set_meta(mark, datetime.now().isoformat(timespec="seconds"))
    return out
