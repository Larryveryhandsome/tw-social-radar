"""審核頁「巡邏中」：一眼看懂雷達在巡什麼，並可在網頁上新增／停用關鍵字。

- 每個品牌：搜尋詞、上下文詞、同業、排除詞、主題情境；資料來源最後一輪的結果；被過濾的原因與範例；下一輪時間。
- 審核員只看得到、只能改自己負責的品牌；admin 看全部。
- 關鍵字改動存在資料庫（keyword_override），不改 brand.yaml；每次停用／啟用都記錄是誰改的。
函式回傳 (HTTP 狀態碼, JSON) 或 HTML，登入／Host／CSP／X-Radar 由 review_server 處理。
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timedelta

from . import CUSTOM_AD_HTML
from . import brands as brands_mod

KEYWORD_CAP = 200  # 每品牌每欄位最多幾個詞（擋手滑或惡意灌爆）

PATROL_CSS = """
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:99px;padding:2px 4px 2px 10px;font-size:14px}
.chip.off{opacity:.55;text-decoration:line-through}.chip .n{color:var(--mut);font-size:12px}
.chip button{padding:1px 8px;font-size:12px;border-radius:99px}
.sect{margin-top:12px}.sect h3{font-size:15px;margin:0 0 2px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:8px 0}
.stat{border:1px solid var(--line);border-radius:8px;padding:6px 8px}.stat b{display:block;font-size:18px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:5px 4px;text-align:left;vertical-align:top}
.add{display:flex;gap:6px;flex-wrap:wrap;margin-top:4px}.add input{flex:1;min-width:140px}
#msg{min-height:1.6em}#msg.err{color:var(--bad)}#msg.ok{color:var(--ok)}
"""

PATROL_JS = """
async function kw(brand, field, word, enabled){
  const m=document.getElementById('msg'); m.className=''; m.textContent='處理中…';
  try{
    const r=await fetch('/api/patrol/keywords',{method:'POST',headers:{'content-type':'application/json','X-Radar':'1'},
      body:JSON.stringify({brand:brand,field:field,word:word,enabled:enabled})});
    const j=await r.json();
    if(!r.ok){m.className='err'; m.textContent='❌ '+(j.error||'失敗'); return;}
    m.className='ok'; m.textContent='✅ '+j.message; setTimeout(()=>location.reload(),700);
  }catch(e){m.className='err'; m.textContent='❌ 連線失敗';}
}
function addKw(ev, brand, field){
  ev.preventDefault(); const i=ev.target.querySelector('input'); kw(brand, field, i.value, true);
}
"""

FIELD_HELP = {
    "keywords": "threads_api 來源拿這些去搜尋（每輪輪流查一部分）",
    "indicators": "貼文至少要提到其中一個，才繼續比對主題情境",
    "exclude_words": "貼文有這些字就跳過",
    "competitor_handle_hints": "發文帳號含這些字就當同業跳過",
}


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _j(s) -> str:
    """放進 onclick 的 JS 字串：先 JSON 再 HTML 跳脫。"""
    return _e(json.dumps(s, ensure_ascii=False))


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


def next_run_text(settings: dict, last_run: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    try:
        every = int(((settings.get("schedule") or {}).get("interval_minutes")) or 30)
    except (TypeError, ValueError):
        every = 30
    last = _parse(last_run)
    if not last:
        return f"還沒跑過。排程設定每 {every} 分鐘一輪（依設定推算）"
    nxt = last + timedelta(minutes=every)
    late = "；⚠️ 已經過了預定時間，排程可能沒在跑" if now > nxt + timedelta(minutes=5) else ""
    return f"約 {nxt:%m/%d %H:%M}（上一輪 {last:%m/%d %H:%M}＋每 {every} 分鐘，依設定推算{late}）"


def next_keywords(brand: dict, settings: dict, db) -> list[str]:
    """threads_api 下一輪會查哪幾個詞（跟 sources.threads_api.fetch 一樣的輪流規則）。"""
    kws = list(dict.fromkeys(brand.get("keywords") or []))
    if not kws:
        return []
    cfg = (settings.get("source") or {}).get("threads_api") or {}
    n = max(1, int(cfg.get("max_queries_per_run", 8)))
    start = int(db.get_meta(f"threads_api_cursor:{brand['key']}", "0") or 0) % len(kws)
    return [kws[(start + i) % len(kws)] for i in range(min(n, len(kws)))]


def _chips(b: dict, field: str, counts: dict, can_edit: bool) -> str:
    key = b["key"]
    added = set(b.get("_added", {}).get(field, []))
    out = []
    for w in b.get(field) or []:
        n = f'<span class="n">7天 {counts.get(w, 0)} 則</span>' if field == "keywords" else ""
        tag = '<span class="n">網頁新增</span>' if w in added else ""
        btn = (f'<button class="ghost" onclick=\'kw({_j(key)},{_j(field)},{_j(w)},false)\'>停用</button>'
               if can_edit else "")
        out.append(f'<span class="chip">{_e(w)}{n}{tag}{btn}</span>')
    for w in b.get("_disabled", {}).get(field, []):
        btn = (f'<button class="ghost" onclick=\'kw({_j(key)},{_j(field)},{_j(w)},true)\'>啟用</button>'
               if can_edit else "")
        out.append(f'<span class="chip off" title="已停用">{_e(w)}{btn}</span>')
    chips = "".join(out) or '<span class="meta">（沒有）</span>'
    add = (f'<form class="add" onsubmit=\'addKw(event,{_j(key)},{_j(field)})\'>'
           f'<input type="text" maxlength="{brands_mod.WORD_MAX}" placeholder="新增{_e(brands_mod.OVERRIDE_FIELDS[field])}">'
           f'<button type="submit">新增</button></form>') if can_edit else ""
    return (f'<div class="sect"><h3>{_e(brands_mod.OVERRIDE_FIELDS[field])} <span class="hint meta">{_e(FIELD_HELP[field])}</span></h3>'
            f'<div class="chips">{chips}</div>{add}</div>')


def _brand_card(b: dict, settings: dict, db, can_edit: bool) -> str:
    key = b["key"]
    src = (settings.get("source") or {}).get("type", "file")
    run = db.latest_run(key)
    if run:
        err = f'<div class="warn">⚠️ 錯誤：{_e(run["error"])}</div>' if run.get("error") else ""
        note = f'<div class="meta">{_e(run["note"])}</div>' if run.get("note") else ""
        last = (f'<div class="grid"><div class="stat">抓到<b>{run["fetched"]}</b></div>'
                f'<div class="stat">新貼文<b>{run["new"]}</b></div><div class="stat">命中<b>{run["candidates"]}</b></div>'
                f'<div class="stat">產草稿<b>{run["drafts"]}</b></div></div>'
                f'<div class="meta">最後一輪：{_e(run["started_at"].replace("T", " "))}｜來源 {_e(run.get("source"))}</div>'
                f'{note}{err}')
    else:
        last = '<div class="meta">還沒有巡邏紀錄（跑過一輪 python -m radar run 之後就會出現）</div>'
    kw_counts = db.keyword_post_counts(b.get("keywords") or [])
    if src == "threads_api":
        nk = next_keywords(b, settings, db)
        src_note = f'下一輪會搜尋：{"、".join(_e(w) for w in nk) or "（沒有搜尋詞）"}'
    else:
        src_note = "file 來源：從 inbox/ 匯入的檔案拿貼文，不會拿搜尋詞去查；搜尋詞改成 threads_api 才會用到"
    fields = "".join(_chips(b, f, kw_counts, can_edit) for f in brands_mod.OVERRIDE_FIELDS)

    hits = (run or {}).get("triggers") or {}
    drafted = db.trigger_draft_counts(key)
    trows = "".join(
        f'<tr><td>{_e(t["id"])}</td><td>{_e("、".join(t.get("match_any") or []))}</td>'
        f'<td>{hits.get(t["id"], 0)}</td><td>{drafted.get(t["id"], 0)}</td></tr>' for t in b.get("triggers") or [])
    triggers = (f'<div class="sect"><h3>主題情境 <span class="hint meta">命中＝最後一輪符合的貼文數；草稿＝近 7 天產生的草稿</span></h3>'
                f'<table><tr><th>情境</th><th>比對詞</th><th>命中</th><th>草稿</th></tr>{trows}</table></div>')

    skipped = (run or {}).get("skipped") or {}
    srows = "".join(f'<tr><td>{_e(k)}</td><td>{v}</td></tr>'
                    for k, v in sorted(skipped.items(), key=lambda x: -x[1]))
    samples = "".join(f'<tr><td>@{_e(s.get("author"))}</td><td>{_e(s.get("snippet"))}</td><td>{_e(s.get("reason"))}</td></tr>'
                      for s in (run or {}).get("samples") or [])
    filt = (f'<div class="sect"><h3>被過濾掉的貼文 <span class="hint meta">最後一輪</span></h3>'
            + (f'<table><tr><th>原因</th><th>則數</th></tr>{srows}</table>' if srows else '<div class="meta">（沒有）</div>')
            + (f'<div class="meta" style="margin-top:6px">最近幾則範例（只留帳號與前 40 字）</div>'
               f'<table><tr><th>帳號</th><th>內文</th><th>原因</th></tr>{samples}</table>' if samples else "")
            + '</div>')

    log = ""
    if can_edit:
        rows = db.keyword_log(key, 8)
        if rows:
            items = "".join(f'<li>{_e(r["at"].replace("T", " "))}　{_e(r["changed_by"] or "（本機）")} '
                            f'{"啟用" if r["enabled"] else "停用"} {_e(brands_mod.OVERRIDE_FIELDS.get(r["field"], r["field"]))}「{_e(r["word"])}」</li>'
                            for r in rows)
            log = f'<details class="sect"><summary>關鍵字異動紀錄</summary><ul class="meta">{items}</ul></details>'
    state = "" if b.get("enabled", True) else ' <span class="badge">已停用</span>'
    return (f'<div class="card" id="b-{_e(key)}"><h2 style="font-size:17px;margin:0">{_e(b["display_name"])}'
            f'<span class="meta">［{_e(key)}］</span>{state}</h2>{last}<div class="meta">{src_note}</div>'
            f'{fields}{triggers}{filt}{log}</div>')


def render_patrol(css: str, settings: dict, db, brands: dict, allowed: list[str] | None, user: str,
                  admin: bool) -> str:
    if allowed is not None:
        brands = {k: v for k, v in brands.items() if k in allowed}
    cards = "".join(_brand_card(b, settings, db, True) for b in brands.values()) or \
        '<div class="empty">沒有你負責的品牌</div>'
    who = f'<span class="meta">（{_e(user)}）</span>' if user else ""
    admin_nav = '<a href="/admin/brands">⚙️ 新增品牌</a><a href="/admin/members">👥 成員管理</a>' if admin else ""
    head = (f'<div class="card"><b>下一輪</b>：{_e(next_run_text(settings, db.get_meta("last_run")))}<br>'
            f'<span class="meta">資料來源：{_e((settings.get("source") or {}).get("type", "file"))}。'
            f'在這裡新增／停用的詞存在資料庫、不改 brand.yaml，下一輪起生效。</span></div>')
    return (f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>巡邏中</title>'
            f'<style>{css}{PATROL_CSS}</style></head><body><main>'
            f'<h1>📡 雷達巡邏中{who}</h1><nav><a href="/">← 回審核頁</a><a class="on" href="/patrol">巡邏中</a>{admin_nav}</nav>'
            f'<div id="msg" role="status"></div>{head}{cards}{CUSTOM_AD_HTML}</main><script>{PATROL_JS}</script></body></html>')


def set_keyword(db, brands: dict, allowed: list[str] | None, user: str, body: dict) -> tuple[int, dict]:
    key = str(body.get("brand") or "")
    field = str(body.get("field") or "")
    enabled = body.get("enabled")
    if allowed is not None and key not in allowed:
        return 403, {"error": "你沒有負責這個品牌"}
    if key not in brands:
        return 404, {"error": "找不到這個品牌"}
    if not isinstance(enabled, bool):
        return 400, {"error": "enabled 要是 true 或 false"}
    if field not in brands_mod.OVERRIDE_FIELDS:
        return 400, {"error": f"只能改：{'、'.join(brands_mod.OVERRIDE_FIELDS.values())}"}
    b = brands[key]
    current = [w.lower() for w in b.get(field) or []]
    try:
        word = brands_mod.clean_word(field, body.get("word"))
    except brands_mod.BrandError as e:
        # brand.yaml 原有的短詞（例如「吃」）停用／重新啟用不受新增的長度限制；空白一律拒絕
        raw = body.get("word").strip() if isinstance(body.get("word"), str) else ""
        was_off = [w.lower() for w in (b.get("_disabled") or {}).get(field, [])]
        if raw and field in brands_mod.OVERRIDE_FIELDS and raw.lower() in (was_off if enabled else current):
            word = raw
        else:
            return 400, {"error": str(e)}
    label = brands_mod.OVERRIDE_FIELDS[field]
    if enabled:
        if word.lower() in current:
            return 409, {"error": f"「{word}」已經在{label}裡了"}
        if len(current) >= KEYWORD_CAP:
            return 400, {"error": f"{label}最多 {KEYWORD_CAP} 個"}
    else:
        if word.lower() not in current:
            return 404, {"error": f"{label}裡沒有「{word}」"}
        if field == "keywords" and len(current) <= 1:
            return 400, {"error": "至少要留一個雷達搜尋詞"}
    db.set_keyword(key, field, word, enabled, user or "")
    return 200, {"ok": True, "brand": key, "field": field, "word": word, "enabled": enabled,
                 "message": f"已{'啟用' if enabled else '停用'}{label}「{word}」，下一輪起生效"}
