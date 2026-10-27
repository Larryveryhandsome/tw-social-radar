"""SQLite 資料層：貼文、草稿、審核紀錄。

只存「公開貼文」做判斷需要的最少欄位（作者帳號、內文、連結、時間），
超過 retention_days 的貼文自動刪除（見 purge_old），降低個資保存風險。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    post_id        TEXT PRIMARY KEY,
    platform       TEXT NOT NULL DEFAULT 'threads',
    author         TEXT,
    content        TEXT,
    url            TEXT,
    posted_at      TEXT,
    discovered_at  TEXT NOT NULL,
    source         TEXT,
    source_keyword TEXT,
    reply_count    INTEGER DEFAULT 0,
    like_count     INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_posts_discovered ON posts(discovered_at);

CREATE TABLE IF NOT EXISTS drafts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_key      TEXT NOT NULL,
    post_id        TEXT NOT NULL,
    trigger_id     TEXT,
    intent_score   INTEGER,
    reply_text     TEXT NOT NULL,
    origin         TEXT,               -- template | llm
    guard_notes    TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',
                   -- pending 待審 | approved 已核准待回覆 | rejected 退回 | sent 已回覆 | expired 過期
                   -- publishing 外掛送出中（已鎖定，避免重複發文）| failed 外掛發送失敗
    created_at     TEXT NOT NULL,
    reviewed_at    TEXT,
    sent_at        TEXT,
    error          TEXT,
    UNIQUE(brand_key, post_id)
);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(brand_key, status);

CREATE TABLE IF NOT EXISTS feedback (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id      INTEGER NOT NULL,
    brand_key     TEXT NOT NULL,
    trigger_id    TEXT,
    action        TEXT NOT NULL,        -- approve | edit | reject
    reason        TEXT,
    original_text TEXT,
    final_text    TEXT,
    created_at    TEXT NOT NULL,
    reviewer      TEXT
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

-- 每一輪每個品牌的統計（審核頁「巡邏中」用）；跟著 retention_days 刪
CREATE TABLE IF NOT EXISTS run_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    brand         TEXT NOT NULL,
    source        TEXT,
    started_at    TEXT NOT NULL,
    fetched       INTEGER DEFAULT 0,
    new           INTEGER DEFAULT 0,
    candidates    INTEGER DEFAULT 0,
    drafts        INTEGER DEFAULT 0,
    skipped_json  TEXT,                -- {"同業帳號": 3, ...}
    triggers_json TEXT,                -- {"trigger id": 命中數}
    samples_json  TEXT,                -- 最近被過濾的幾則：[{author, snippet(前 40 字), reason}]
    note          TEXT,
    error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_run_log_brand ON run_log(brand, id);

-- 在網頁上新增／停用的關鍵字（不改 brand.yaml，載入品牌後合併）
CREATE TABLE IF NOT EXISTS keyword_override (
    brand_key  TEXT NOT NULL,
    field      TEXT NOT NULL,          -- keywords | indicators | exclude_words | competitor_handle_hints
    word       TEXT NOT NULL,
    enabled    INTEGER NOT NULL,       -- 1 = 加入／重新啟用，0 = 停用
    changed_by TEXT,
    at         TEXT NOT NULL,
    PRIMARY KEY (brand_key, field, word)
);
CREATE TABLE IF NOT EXISTS keyword_override_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_key  TEXT NOT NULL,
    field      TEXT NOT NULL,
    word       TEXT NOT NULL,
    enabled    INTEGER NOT NULL,
    changed_by TEXT,
    at         TEXT NOT NULL
);
"""


class DB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.execute("PRAGMA journal_mode=WAL")  # 排程與審核頁同時開資料庫時，讀寫不互卡
            c.executescript(SCHEMA)
            cols = {r[1] for r in c.execute("PRAGMA table_info(feedback)")}
            if "reviewer" not in cols:  # 0.1.0 的舊資料庫補欄位
                c.execute("ALTER TABLE feedback ADD COLUMN reviewer TEXT")

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---------- meta ----------
    def get_meta(self, key: str, default: str = "") -> str:
        with self.conn() as c:
            r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return r["value"] if r else default

    def set_meta(self, key: str, value: str) -> None:
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, value))

    # ---------- posts ----------
    def upsert_post(self, p: dict) -> bool:
        """新貼文回傳 True。"""
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn() as c:
            if c.execute("SELECT 1 FROM posts WHERE post_id=?", (p["post_id"],)).fetchone():
                c.execute("UPDATE posts SET reply_count=?, like_count=? WHERE post_id=?",
                          (p.get("reply_count", 0), p.get("like_count", 0), p["post_id"]))
                return False
            c.execute(
                """INSERT INTO posts(post_id, platform, author, content, url, posted_at, discovered_at,
                                     source, source_keyword, reply_count, like_count)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (p["post_id"], p.get("platform", "threads"), p.get("author"), p.get("content", ""),
                 p.get("url"), p.get("posted_at"), now, p.get("source"), p.get("source_keyword"),
                 p.get("reply_count", 0), p.get("like_count", 0)),
            )
            return True

    def recent_posts(self, hours: int = 72 * 24) -> list[dict]:
        since = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM posts WHERE discovered_at >= ? ORDER BY discovered_at DESC", (since,))]

    def candidate_posts(self, brand_key: str, hours: int, limit: int = 2000) -> list[dict]:
        """近 N 小時、這個品牌還沒產過草稿的貼文（一次查完，不逐則查資料庫）。"""
        since = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                """SELECT p.* FROM posts p
                   LEFT JOIN drafts d ON d.post_id = p.post_id AND d.brand_key = ?
                   WHERE p.discovered_at >= ? AND d.id IS NULL
                   ORDER BY p.discovered_at DESC LIMIT ?""", (brand_key, since, limit))]

    def purge_old(self, days: int) -> int:
        cut = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        with self.conn() as c:
            n = c.execute("DELETE FROM posts WHERE discovered_at < ? AND post_id NOT IN "
                          "(SELECT post_id FROM drafts WHERE status IN ('pending','approved'))", (cut,)).rowcount
            c.execute("DELETE FROM drafts WHERE created_at < ? AND status IN ('rejected','expired','sent')", (cut,))
            c.execute("DELETE FROM run_log WHERE started_at < ?", (cut,))  # 過濾範例含內文片段，一起刪
            return n

    # ---------- run_log（巡邏統計）----------
    def add_run_log(self, stat: dict, source: str, started_at: str) -> None:
        with self.conn() as c:
            c.execute(
                """INSERT INTO run_log(brand, source, started_at, fetched, new, candidates, drafts,
                                       skipped_json, triggers_json, samples_json, note, error)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (stat["brand"], source, started_at, stat.get("fetched", 0), stat.get("new", 0),
                 stat.get("candidates", 0), len(stat.get("drafts") or []),
                 json.dumps(stat.get("skipped") or {}, ensure_ascii=False),
                 json.dumps(stat.get("triggers") or {}, ensure_ascii=False),
                 json.dumps(stat.get("samples") or [], ensure_ascii=False),
                 stat.get("note"), (str(stat["error"])[:500] if stat.get("error") else None)))

    def latest_run(self, brand: str) -> dict | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM run_log WHERE brand=? ORDER BY id DESC LIMIT 1", (brand,)).fetchone()
        if not r:
            return None
        d = dict(r)
        for k in ("skipped", "triggers", "samples"):
            try:
                d[k] = json.loads(d.pop(f"{k}_json") or "null") or ({} if k != "samples" else [])
            except ValueError:
                d[k] = {} if k != "samples" else []
        return d

    def keyword_post_counts(self, words: list[str], days: int = 7) -> dict[str, int]:
        """近 N 天每個搜尋詞抓到幾則貼文（posts.source_keyword）。"""
        if not words:
            return {}
        cut = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        q = ("SELECT source_keyword k, COUNT(*) n FROM posts WHERE discovered_at >= ? AND source_keyword IN (%s) "
             "GROUP BY source_keyword" % ",".join("?" * len(words)))
        with self.conn() as c:
            return {r["k"]: r["n"] for r in c.execute(q, [cut, *words])}

    def trigger_draft_counts(self, brand_key: str, days: int = 7) -> dict[str, int]:
        cut = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        with self.conn() as c:
            return {r["t"]: r["n"] for r in c.execute(
                "SELECT trigger_id t, COUNT(*) n FROM drafts WHERE brand_key=? AND created_at >= ? GROUP BY trigger_id",
                (brand_key, cut))}

    # ---------- keyword_override（網頁上改關鍵字）----------
    def set_keyword(self, brand_key: str, field: str, word: str, enabled: bool, by: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO keyword_override(brand_key, field, word, enabled, changed_by, at) "
                      "VALUES(?,?,?,?,?,?)", (brand_key, field, word, int(enabled), by, now))
            c.execute("INSERT INTO keyword_override_log(brand_key, field, word, enabled, changed_by, at) VALUES(?,?,?,?,?,?)",
                      (brand_key, field, word, int(enabled), by, now))

    def keyword_overrides(self, brand_key: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM keyword_override", []
        if brand_key:
            q, args = q + " WHERE brand_key=?", [brand_key]
        with self.conn() as c:
            return [dict(r) for r in c.execute(q + " ORDER BY at", args)]

    def keyword_log(self, brand_key: str, limit: int = 20) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM keyword_override_log WHERE brand_key=? ORDER BY id DESC LIMIT ?", (brand_key, limit))]

    # ---------- drafts ----------
    def has_draft(self, brand_key: str, post_id: str) -> bool:
        """同一則貼文、同一品牌一輩子只產一次草稿（退回的也算，避免重複出現）。"""
        with self.conn() as c:
            return c.execute("SELECT 1 FROM drafts WHERE brand_key=? AND post_id=?",
                             (brand_key, post_id)).fetchone() is not None

    def today_draft_count(self, brand_key: str) -> int:
        today = datetime.now().strftime("%Y-%m-%d")
        with self.conn() as c:
            return c.execute("SELECT COUNT(*) FROM drafts WHERE brand_key=? AND substr(created_at,1,10)=?",
                             (brand_key, today)).fetchone()[0]

    def add_draft(self, d: dict) -> int | None:
        """同一品牌同一貼文已經有草稿時回傳 None（兩個排程同時跑也不會重複或當掉）。"""
        with self.conn() as c:
            cur = c.execute(
                """INSERT OR IGNORE INTO drafts(brand_key, post_id, trigger_id, intent_score, reply_text, origin,
                                      guard_notes, status, created_at)
                   VALUES(?,?,?,?,?,?,?, 'pending', ?)""",
                (d["brand_key"], d["post_id"], d.get("trigger_id"), d.get("intent_score"), d["reply_text"],
                 d.get("origin", "template"), d.get("guard_notes", ""),
                 datetime.now().isoformat(timespec="seconds")),
            )
            return cur.lastrowid if cur.rowcount == 1 else None

    def get_draft(self, draft_id: int) -> dict | None:
        with self.conn() as c:
            r = c.execute("""SELECT d.*, p.author, p.content, p.url, p.posted_at, p.source
                             FROM drafts d LEFT JOIN posts p ON p.post_id=d.post_id WHERE d.id=?""",
                          (draft_id,)).fetchone()
            return dict(r) if r else None

    def list_drafts(self, status: str | None = "pending", brand_key: str | None = None,
                    limit: int = 200, brands: list[str] | None = None) -> list[dict]:
        q = """SELECT d.*, p.author, p.content, p.url, p.posted_at, p.source FROM drafts d
               LEFT JOIN posts p ON p.post_id=d.post_id WHERE 1=1"""
        args: list = []
        if status:
            q += " AND d.status=?"
            args.append(status)
        if brand_key:
            q += " AND d.brand_key=?"
            args.append(brand_key)
        if brands is not None:  # 審核帳號只看得到自己負責的品牌
            q += " AND d.brand_key IN (%s)" % ",".join("?" * len(brands)) if brands else " AND 0"
            args.extend(brands)
        q += " ORDER BY d.id DESC LIMIT ?"
        args.append(limit)
        with self.conn() as c:
            return [dict(r) for r in c.execute(q, args)]

    def counts(self, brands: list[str] | None = None) -> dict:
        q, args = "SELECT status, COUNT(*) n FROM drafts", []
        if brands is not None:
            q += " WHERE brand_key IN (%s)" % ",".join("?" * len(brands)) if brands else " WHERE 0"
            args = list(brands)
        with self.conn() as c:
            return {r["status"]: r["n"] for r in c.execute(q + " GROUP BY status", args)}

    def set_status(self, draft_id: int, status: str, text: str | None = None, error: str | None = None) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn() as c:
            if text is not None:
                c.execute("UPDATE drafts SET reply_text=? WHERE id=?", (text, draft_id))
            if status in ("approved", "rejected"):
                c.execute("UPDATE drafts SET status=?, reviewed_at=? WHERE id=?", (status, now, draft_id))
            elif status == "sent":
                c.execute("UPDATE drafts SET status='sent', sent_at=?, error=NULL WHERE id=?", (now, draft_id))
            else:
                c.execute("UPDATE drafts SET status=?, error=? WHERE id=?", (status, error, draft_id))

    def claim_for_publish(self, draft_id: int) -> bool:
        """外掛送出前先把狀態從 approved 原子地改成 publishing；搶不到代表別的程序或人已經處理。"""
        with self.conn() as c:
            return c.execute("UPDATE drafts SET status='publishing' WHERE id=? AND status='approved'",
                             (draft_id,)).rowcount == 1

    def expire_pending(self, days: int = 3) -> int:
        cut = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        with self.conn() as c:
            return c.execute("UPDATE drafts SET status='expired' WHERE status='pending' AND created_at < ?",
                             (cut,)).rowcount

    def today_sent_count(self, brand_key: str) -> int:
        today = datetime.now().strftime("%Y-%m-%d")
        with self.conn() as c:
            return c.execute("SELECT COUNT(*) FROM drafts WHERE brand_key=? AND status='sent' "
                             "AND substr(sent_at,1,10)=?", (brand_key, today)).fetchone()[0]

    def recent_reply_texts(self, brand_key: str, days: int = 7) -> set[str]:
        cut = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        with self.conn() as c:
            return {(r[0] or "").strip() for r in c.execute(
                "SELECT reply_text FROM drafts WHERE brand_key=? AND created_at>=? "
                "AND status IN ('pending','approved','sent')", (brand_key, cut))}

    # ---------- feedback（學習用）----------
    def log_feedback(self, draft: dict, action: str, reason: str, final_text: str, reviewer: str = "") -> None:
        with self.conn() as c:
            c.execute(
                """INSERT INTO feedback(draft_id, brand_key, trigger_id, action, reason, original_text,
                                        final_text, created_at, reviewer) VALUES(?,?,?,?,?,?,?,?,?)""",
                (draft["id"], draft["brand_key"], draft.get("trigger_id"), action, reason,
                 draft["reply_text"], final_text, datetime.now().isoformat(timespec="seconds"), reviewer),
            )

    def template_score(self, brand_key: str, text: str) -> dict:
        with self.conn() as c:
            rows = c.execute("SELECT action, COUNT(*) n FROM feedback WHERE brand_key=? AND original_text=? "
                             "GROUP BY action", (brand_key, text)).fetchall()
        s = {"approve": 0, "edit": 0, "reject": 0}
        for r in rows:
            s[r["action"]] = r["n"]
        return s

    def learned_templates(self, brand_key: str, trigger_id: str, limit: int = 20) -> list[str]:
        """使用者改寫過、最後核准的文字，當作新的候選模板。"""
        with self.conn() as c:
            return [r[0] for r in c.execute(
                "SELECT DISTINCT final_text FROM feedback WHERE brand_key=? AND trigger_id=? "
                "AND action='edit' ORDER BY id DESC LIMIT ?", (brand_key, trigger_id, limit)) if r[0]]

    def feedback_examples(self, brand_key: str, action: str, limit: int = 5) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT reason, original_text, final_text FROM feedback WHERE brand_key=? AND action=? "
                "ORDER BY id DESC LIMIT ?", (brand_key, action, limit))]
