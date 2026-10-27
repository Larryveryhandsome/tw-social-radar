"""一輪流程：抓貼文 → 存資料庫 → 每個品牌過濾＋比對 → 產草稿 → 通知。

只產草稿，不發文。草稿一律是 pending（待審），要人到審核頁核准。
"""
from __future__ import annotations

import os
import random
import time
from contextlib import contextmanager
from datetime import datetime

from . import brands as brands_mod
from . import drafter, filters, intent, matcher, notify, sources
from .config import brands_dir, data_dir
from .db import DB

LOCK_STALE_SECONDS = 2 * 3600


class Busy(RuntimeError):
    pass


@contextmanager
def run_lock(settings: dict, name: str = "run"):
    """排程重疊（上一輪還沒跑完、下一輪又觸發）時，第二個直接跳過，不會兩個一起產草稿或發文。"""
    path = data_dir(settings) / f".{name}.lock"
    try:
        if path.exists() and time.time() - path.stat().st_mtime > LOCK_STALE_SECONDS:
            path.unlink()  # 上次當掉留下的舊鎖
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise Busy(f"上一輪 {name} 還在跑（{path.name}），這次跳過") from None
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def open_db(settings: dict) -> DB:
    return DB(data_dir(settings) / "radar.db")


def load_brands(settings: dict, db: DB, enabled_only: bool = True, strict: bool = False) -> dict[str, dict]:
    """讀 brand.yaml，再合併審核頁上新增／停用的關鍵字。排程和審核頁都用這個，兩邊看到的一樣。"""
    rows = db.keyword_overrides()
    out = {}
    for k, b in brands_mod.load_all(brands_dir(settings), enabled_only=enabled_only, strict=strict).items():
        out[k] = brands_mod.apply_overrides(b, [r for r in rows if r["brand_key"] == k])
    return out


SAMPLE_LIMIT = 5  # 每輪每品牌留幾則「被過濾」範例（只留帳號＋前 40 字）


def _skip(stat: dict, p: dict, why: str) -> None:
    stat["skipped"][why] = stat["skipped"].get(why, 0) + 1
    if len(stat["samples"]) < SAMPLE_LIMIT:
        snippet = " ".join((p.get("content") or "").split())[:40]
        stat["samples"].append({"author": p.get("author") or "", "snippet": snippet, "reason": why})


def alert_once_a_day(settings: dict, db: DB, key: str, message: str) -> bool:
    """同一種錯誤一天只通知一次（排程每 30 分鐘跑，不能每次都推 LINE 洗版）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    mk = f"alert:{key}"
    if db.get_meta(mk) == today:
        return False
    db.set_meta(mk, today)
    notify.send(settings, message)
    return True


def scan_brand(brand: dict, settings: dict, db: DB, llm=None, rng=None, do_fetch: bool = True,
               notify_on: bool = True) -> dict:
    rng = rng or random.Random()
    stat = {"brand": brand["key"], "fetched": 0, "new": 0, "candidates": 0, "drafts": [], "skipped": {},
            "triggers": {}, "samples": []}
    if do_fetch:
        try:
            got = sources.fetch(brand, settings, db)
        except Exception as e:
            got = list(getattr(e, "partial", []) or [])  # 出錯前已抓到的照樣收
            stat["error"] = str(e)
            print(f"  [{brand['key']}] 抓貼文失敗：{e}")
            kind = getattr(e, "kind", "other")
            if kind in ("token", "other"):
                alert_once_a_day(settings, db, f"source:{brand['key']}:{kind}",
                                 f"⚠️ {brand.get('display_name')} 雷達抓不到貼文：{str(e)[:200]}")
        stat["fetched"] = len(got)
        stat["new"] = sum(1 for p in got if db.upsert_post(p))

    lim = brand.get("limits") or {}
    left_today = int(lim.get("max_drafts_per_day", 6)) - db.today_draft_count(brand["key"])
    cap = min(int(lim.get("max_drafts_per_run", 3)), left_today)
    if cap <= 0:
        stat["note"] = "今天草稿已達上限"
        return stat

    max_age = int((brand.get("filters") or {}).get("max_post_age_days", 30))
    matched = []
    for p in db.candidate_posts(brand["key"], hours=max_age * 24 + 72):
        why = filters.skip_reason(p, brand)
        if why:
            _skip(stat, p, why)
            continue
        t = matcher.find_trigger(brand, p["content"])
        if not t:
            _skip(stat, p, "沒命中觸發詞")
            continue
        stat["triggers"][t["id"]] = stat["triggers"].get(t["id"], 0) + 1
        matched.append((p, t))
    stat["candidates"] = len(matched)

    # 先用規則排序；要問 LLM 的只取前面幾則（避免候選很多時每輪都花大量額度）
    scored = sorted(((intent.rule_score(p["content"]), rng.random(), p, t) for p, t in matched),
                    key=lambda x: (-x[0], x[1]))
    if bool((settings.get("llm") or {}).get("classify")) and llm is not None:
        top = scored[:cap * 3]
        rescored = [((intent.llm_score(llm, brand, p["content"]) or s), r, p, t) for s, r, p, t in top]
        scored = sorted(rescored, key=lambda x: (-x[0], x[1])) + scored[cap * 3:]
    min_intent = int((brand.get("filters") or {}).get("min_intent", 1))
    scored = [x for x in scored if x[0] >= min_intent]

    for score, _, p, t in scored:
        if len(stat["drafts"]) >= cap:
            break
        res = drafter.make_draft(brand, p, t, settings, db=db, llm=llm)
        if not res:
            continue
        text, origin, notes = res
        did = db.add_draft({"brand_key": brand["key"], "post_id": p["post_id"], "trigger_id": t["id"],
                            "intent_score": score, "reply_text": text, "origin": origin, "guard_notes": notes})
        if did:  # None = 另一個程序剛好先產了，不重複
            stat["drafts"].append(did)

    if stat["drafts"] and notify_on:
        notify.send(settings, notify.draft_message(settings, brand, stat["drafts"]))
    return stat


def run_once(settings: dict, only: str | None = None, llm=None, rng=None) -> list[dict]:
    try:
        with run_lock(settings):
            return _run(settings, only, llm, rng)
    except Busy as e:
        print(f"⏭ {e}")
        return []


def _run(settings: dict, only: str | None, llm, rng) -> list[dict]:
    db = open_db(settings)
    expired = db.expire_pending(days=3)
    purged = db.purge_old(int(settings.get("retention_days", 60)))
    if expired or purged:
        print(f"[清理] 過期草稿 {expired} 筆、刪除舊貼文 {purged} 筆")
    all_brands = load_brands(settings, db)  # strict=False：一個品牌檔寫錯不拖累其他品牌
    if only:
        if only not in all_brands:
            raise SystemExit(f"找不到啟用中的品牌 {only}（brands/{only}/brand.yaml）")
        all_brands = {only: all_brands[only]}
    if llm is None:
        mode = settings.get("llm") or {}
        if mode.get("draft_mode") == "llm" or mode.get("classify"):
            from .llm import LLMError, get_llm
            try:
                llm = get_llm(settings)
            except LLMError as e:
                print(f"⚠️ LLM 無法使用，這輪改用模板：{e}")
                alert_once_a_day(settings, db, "llm", f"⚠️ 社群雷達的 AI 無法使用，暫時改用模板：{str(e)[:200]}")
    stats = []
    source_type = (settings.get("source") or {}).get("type", "file")
    fetched_shared = False
    for b in all_brands.values():
        # file 來源是共用的，抓一次給所有品牌比對；threads_api 依品牌關鍵字分別查
        do_fetch = source_type != "file" or not fetched_shared
        started = datetime.now().isoformat(timespec="seconds")
        try:
            st = scan_brand(b, settings, db, llm=llm, rng=rng, do_fetch=do_fetch)
        except Exception as e:  # 單一品牌出錯不影響其他品牌
            st = {"brand": b["key"], "fetched": 0, "new": 0, "candidates": 0, "drafts": [], "error": str(e)}
            print(f"[{b['key']}] 出錯：{e}")
        fetched_shared = True
        stats.append(st)
        try:
            db.add_run_log(st, source_type, started)
        except Exception as e:  # 統計寫不進去不影響草稿
            print(f"[{b['key']}] 統計沒存到：{e}")
        print(f"[{b['key']}] 抓到 {st['fetched']}（新 {st['new']}）→ 命中 {st['candidates']} → 草稿 {len(st['drafts'])}"
              + (f"｜{st['note']}" if st.get("note") else ""))
    db.set_meta("last_run", datetime.now().isoformat(timespec="seconds"))
    return stats


def preview_publish(settings: dict, db: DB | None = None) -> list[str]:
    """「只模擬不送出」：列出現在執行 publish 會發生什麼事，不連網、不鎖定草稿、不改任何狀態。"""
    from .plugins import installed
    ap = settings.get("auto_publish") or {}
    out = []
    if ap.get("enabled") is not True:
        out.append("自動發文是關閉的（auto_publish.enabled 不是 true）；真正執行 publish 不會送出任何東西。以下是假設開啟時的模擬：")
    elif ap.get("plugin", "threads_publisher") not in installed():
        out.append(f"auto_publish.enabled=true，但還沒安裝外掛 {ap.get('plugin', 'threads_publisher')}；真正執行也不會送出。以下是模擬：")
    hour = datetime.now().hour
    if not (int(ap.get("window_start_hour", 8)) <= hour < int(ap.get("window_end_hour", 22))):
        out.append("現在不在發送時段，真正執行會略過（以下仍列出已核准的草稿）。")
    db = db or open_db(settings)
    cap = int(ap.get("max_per_brand_per_day", 4))
    planned: dict[str, int] = {}
    for d in reversed(db.list_drafts(status="approved")):
        k = d["brand_key"]
        if db.today_sent_count(k) + planned.get(k, 0) >= cap:
            out.append(f"#{d['id']} [{k}] 今天已到上限 {cap} 則，會略過")
            continue
        if d.get("source") != "threads_api":
            out.append(f"#{d['id']} [{k}] 來源不是官方 API，會標成失敗，請人工回覆")
            continue
        planned[k] = planned.get(k, 0) + 1
        out.append(f"#{d['id']} [{k}] 會送出：{d['reply_text'][:60]}")
    if not any(x.startswith("#") for x in out):
        out.append("沒有已核准、可送出的草稿。")
    return out


def publish_approved(settings: dict, db: DB | None = None) -> list[tuple[int, str]]:
    """外掛模式才會用到：把「已核准」的草稿交給外掛送出。沒裝外掛就什麼都不做。"""
    from .plugins import publisher
    mod = publisher(settings)
    if mod is None:
        return []
    db = db or open_db(settings)
    ap = settings.get("auto_publish") or {}
    hour = datetime.now().hour
    if not (int(ap.get("window_start_hour", 8)) <= hour < int(ap.get("window_end_hour", 22))):
        print("[publish] 不在發送時段，略過")
        return []
    try:
        with run_lock(settings, "publish"):
            done = []
            for d in reversed(db.list_drafts(status="approved")):
                if db.today_sent_count(d["brand_key"]) >= int(ap.get("max_per_brand_per_day", 4)):
                    continue
                if not db.claim_for_publish(d["id"]):  # 搶不到 = 別人已經在處理（或已手動回覆）
                    continue
                d["status"] = "publishing"
                try:
                    mod.publish_reply(d, settings)
                    db.set_status(d["id"], "sent")
                    done.append((d["id"], "sent"))
                except Exception as e:
                    db.set_status(d["id"], "failed", error=str(e)[:300])
                    done.append((d["id"], f"failed: {e}"))
            return done
    except Busy as e:
        print(f"⏭ {e}")
        return []
