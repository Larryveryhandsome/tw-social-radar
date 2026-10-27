"""審核後台（標準函式庫 http.server，免安裝）。

- 預設只聽 127.0.0.1。要給其他裝置連，必須設 RADAR_REVIEW_PASSWORD（Basic 認證），
  並建議自己接 HTTPS 通道；沒設密碼卻聽 0.0.0.0 會直接拒絕啟動。
- 多人審核：`python -m radar user add 名字 --brands a,b` 建審核帳號，只看得到、只能審自己的品牌。
- 「巡邏中」（/patrol）：雷達在巡什麼、上一輪結果、被過濾的原因；可新增／停用關鍵字（只限自己負責的品牌）。
- 管理員另有「新增品牌」「成員管理」兩頁（/admin/brands、/admin/members），審核員連進來回 403。
- 安全：檢查 Host 標頭（擋 DNS rebinding）、連續登入失敗暫時封鎖、CSP、CSRF 標頭、輸出跳脫。
- 核准／改寫／退回都要留原因，系統拿來學習模板權重。
- 核准後：按「複製並開啟原文」→ 自己貼上留言 → 按「我已回覆」。
"""
from __future__ import annotations

import base64
import html
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import CUSTOM_AD_HTML, print_custom_ad
from . import accounts
from . import admin_web, patrol_web
from . import brands as brands_mod
from .config import brands_dir, data_dir
from .pipeline import load_brands, open_db
from .sources.file_source import safe_url

LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}
FAIL_LIMIT, FAIL_WINDOW = 10, 600  # 10 分鐘內錯 10 次 → 封鎖 10 分鐘
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'")

REJECT_REASONS = ["不是潛在客人", "語氣不對", "太像廣告", "內容不符", "對方在抱怨／敏感話題", "重複", "其他"]
TABS = {"pending": "待審", "approved": "已核准待回覆", "sent": "已回覆", "rejected": "退回", "expired": "過期",
        "failed": "外掛發送失敗"}

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#1d2330;--mut:#667085;--line:#e4e7ec;--pri:#2563eb;--ok:#16a34a;--bad:#dc2626;--warn:#b45309}
@media (prefers-color-scheme:dark){:root{--bg:#0f1218;--card:#181c25;--fg:#e6e8ee;--mut:#98a2b3;--line:#2a303c;--pri:#60a5fa;--ok:#4ade80;--bad:#f87171;--warn:#fbbf24}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,-apple-system,"Noto Sans TC","Microsoft JhengHei",sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}h1{font-size:20px;margin:4px 0 12px}
nav a{display:inline-block;margin:0 6px 8px 0;padding:4px 10px;border:1px solid var(--line);border-radius:99px;color:var(--fg);text-decoration:none;font-size:14px}
nav a.on{background:var(--pri);border-color:var(--pri);color:#fff}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:12px 0}
.meta{color:var(--mut);font-size:13px}.post{white-space:pre-wrap;border-left:3px solid var(--line);padding:6px 10px;margin:8px 0;max-height:220px;overflow:auto}
textarea{width:100%;min-height:76px;font:inherit;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)}
select,input[type=text]{font:inherit;padding:6px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);max-width:100%}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:8px}
button{font:inherit;border:0;border-radius:8px;padding:7px 14px;cursor:pointer;color:#fff;background:var(--pri)}
button.ok{background:var(--ok)}button.bad{background:var(--bad)}button.ghost{background:transparent;color:var(--fg);border:1px solid var(--line)}
.warn{color:var(--warn);font-size:13px}.empty{color:var(--mut);text-align:center;padding:40px 0}
.badge{font-size:12px;border:1px solid var(--line);border-radius:6px;padding:0 6px;margin-left:4px}
.custom-ad{margin:28px 0 8px;color:var(--mut);font-size:12px;text-align:center;overflow-wrap:anywhere}.custom-ad a{color:inherit}
"""

JS = """
async function act(id, action){
  const card=document.getElementById('d'+id), body={};
  const ta=card.querySelector('textarea'); if(ta) body.text=ta.value;
  const sel=card.querySelector('select'); const note=card.querySelector('input[type=text]');
  body.reason=[sel?sel.value:'', note?note.value.trim():''].filter(Boolean).join('：');
  if(action==='reject' && !(sel&&sel.value)){alert('請選退回原因（系統用來學習）');return;}
  const r=await fetch('/api/drafts/'+id+'/'+action,{method:'POST',headers:{'content-type':'application/json','X-Radar':'1'},body:JSON.stringify(body)});
  const j=await r.json(); if(!r.ok){alert(j.error||'失敗');return;}
  card.style.opacity=.35; card.querySelectorAll('button').forEach(b=>b.disabled=true);
}
async function copyOpen(id,url){
  const t=document.getElementById('d'+id).querySelector('.reply').innerText;
  try{await navigator.clipboard.writeText(t);}catch(e){}
  if(url) window.open(url,'_blank','noopener');
}
"""


def _e(s) -> str:
    return html.escape(str(s or ""))


def render_page(db, brands: dict, tab: str, brand_key: str | None, allowed: list[str] | None = None,
                user: str = "", admin: bool = False) -> str:
    tab = tab if tab in TABS else "pending"
    if allowed is not None:
        brands = {k: v for k, v in brands.items() if k in allowed}
    counts = db.counts(brands=allowed)
    drafts = db.list_drafts(status=tab, brand_key=brand_key or None, brands=allowed)
    nav = "".join(f'<a class="{"on" if k == tab else ""}" href="/?tab={k}{"&brand=" + _e(brand_key) if brand_key else ""}">'
                  f'{v} {counts.get(k, 0)}</a>' for k, v in TABS.items())
    bnav = '<a class="{}" href="/?tab={}">全部品牌</a>'.format("" if brand_key else "on", tab) + "".join(
        f'<a class="{"on" if k == brand_key else ""}" href="/?tab={tab}&brand={_e(k)}">{_e(b["display_name"])}</a>'
        for k, b in brands.items())
    cards = []
    for d in drafts:
        b = brands.get(d["brand_key"], {})
        url = safe_url(d.get("url"))  # 只放 http(s) 連結，擋 javascript:
        link = ' ｜ <a href="{}" target="_blank" rel="noopener noreferrer">原文</a>'.format(_e(url)) if url else ""
        head = (f'<div class="meta">#{d["id"]}｜{_e(b.get("display_name", d["brand_key"]))}｜@{_e(d.get("author"))}'
                f'｜情境 {_e(d.get("trigger_id"))}｜需求 {_e(d.get("intent_score"))}/5'
                f'<span class="badge">{"AI" if d.get("origin") == "llm" else "模板"}</span>'
                f'{link}</div>')
        post = f'<div class="post">{_e(d.get("content"))}</div>'
        warn = f'<div class="warn">⚠️ {_e(d["guard_notes"])}</div>' if d.get("guard_notes") else ""
        if tab == "pending":
            opts = "".join(f"<option>{_e(r)}</option>" for r in REJECT_REASONS)
            body = (f'<textarea>{_e(d["reply_text"])}</textarea>{warn}'
                    f'<div class="row"><button class="ok" onclick="act({d["id"]},\'approve\')">✅ 核准</button>'
                    f'<select><option value="">退回原因…</option>{opts}</select>'
                    f'<input type="text" placeholder="補充（選填，改寫也可以寫原因）">'
                    f'<button class="bad" onclick="act({d["id"]},\'reject\')">❌ 退回</button></div>')
        elif tab == "approved":
            url = json.dumps(safe_url(d.get("url")))
            body = (f'<div class="post reply">{_e(d["reply_text"])}</div>'
                    f'<div class="row"><button onclick=\'copyOpen({d["id"]},{_e(url)})\'>📋 複製並開啟原文</button>'
                    f'<button class="ok" onclick="act({d["id"]},\'sent\')">我已回覆</button>'
                    f'<button class="ghost" onclick="act({d["id"]},\'reject\')">不回了</button>'
                    f'<select hidden><option selected>核准後放棄</option></select></div>')
        else:
            err = f'<div class="warn">{_e(d["error"])}</div>' if d.get("error") else ""
            body = f'<div class="post reply">{_e(d["reply_text"])}</div>{err}'
        cards.append(f'<div class="card" id="d{d["id"]}">{head}{post}{body}</div>')
    who_html = '<span class="meta">（{}）</span>'.format(_e(user)) if user else ""
    admin_nav = ('<a href="/admin/brands">⚙️ 新增品牌</a><a href="/admin/members">👥 成員管理</a>' if admin else "")
    admin_nav = f'<nav><a href="/patrol">📡 巡邏中</a>{admin_nav}</nav>'
    content = "".join(cards) or '<div class="empty">這裡目前沒有草稿 🎉</div>'
    return (f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>社群雷達審核</title>'
            f'<style>{CSS}</style></head><body><main><h1>📡 社群雷達・審核{who_html}</h1>{admin_nav}<nav>{nav}</nav><nav>{bnav}</nav>'
            f'{content}<p class="meta">草稿只是建議。開源版不會替你發文：核准後請自己到原文底下留言，再按「我已回覆」。</p>'
            f'{CUSTOM_AD_HTML}</main><script>{JS}</script></body></html>')


def make_handler(settings: dict, password: str | None, host: str = "127.0.0.1"):
    db = open_db(settings)
    ddir = data_dir(settings)
    need_auth = bool(password) or bool(accounts.load(ddir))
    allowed_hosts = {h.lower() for h in ((settings.get("review") or {}).get("allowed_hosts") or [])}
    if host in LOOPBACK:
        allowed_hosts |= {"127.0.0.1", "localhost", "[::1]"}
    fails: dict[str, list[float]] = {}
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        server_version = "tw-social-radar"

        def log_message(self, fmt, *args):
            pass

        def _host_ok(self) -> bool:
            """擋 DNS rebinding：惡意網站把自己的網域指到 127.0.0.1 來操作你的審核頁。"""
            if not allowed_hosts:
                return True
            h = (self.headers.get("Host") or "").lower()
            h = h.rsplit(":", 1)[0] if not h.endswith("]") else h
            return h in allowed_hosts

        def _blocked(self) -> bool:
            ip = self.client_address[0]
            with lock:
                now = time.time()
                fails[ip] = [t for t in fails.get(ip, []) if now - t < FAIL_WINDOW]
                return len(fails[ip]) >= FAIL_LIMIT

        def _fail(self):
            with lock:
                fails.setdefault(self.client_address[0], []).append(time.time())

        def _login(self):
            """回傳 (帳號, 可看的品牌；None=全部)；沒通過回 None。"""
            if not need_auth:
                return ("", None)
            h = self.headers.get("Authorization", "")
            if h.startswith("Basic "):
                try:
                    name, pw = base64.b64decode(h[6:]).decode("utf-8").split(":", 1)
                except (ValueError, UnicodeDecodeError):
                    name, pw = "", ""
                who = accounts.authenticate(ddir, name, pw, password) if pw else None
                if who:
                    return who
                self._fail()
            return None

        def _gate(self, as_json: bool):
            if not self._host_ok():
                self._send(421, "Host 不允許（要從其他網址連，請在 settings.yaml 的 review.allowed_hosts 加上它）")
                return None
            if self._blocked():
                self._send(429, "登入失敗太多次，請 10 分鐘後再試")
                return None
            who = self._login()
            if who is None:
                if as_json:
                    self._json(401, {"error": "需要登入"})
                else:
                    self._send(401, "需要帳號密碼")
                return None
            return who

        def _is_admin(self, user: str) -> bool:
            # 帳號 admin＝管理員；完全沒設密碼又沒帳號時只能本機連，那個人就是管理員
            return user == "admin" or not need_auth

        def _body(self):
            """讀 JSON body；失敗時已經回應錯誤，回傳 None。"""
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > 20000:
                self._json(413, {"error": "too large"})
                return None
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                body = None
            if not isinstance(body, dict):
                self._json(400, {"error": "bad json"})
                return None
            return body

        def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8"):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Cache-Control", "no-store")
            if code == 401:
                self.send_header("WWW-Authenticate", 'Basic realm="radar"')
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/healthz":
                return self._json(200, {"ok": True})
            who = self._gate(as_json=u.path.startswith("/api/"))
            if who is None:
                return
            user, allowed = who
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/":
                brands = brands_mod.load_all(brands_dir(settings), enabled_only=False, strict=False)
                return self._send(200, render_page(db, brands, q.get("tab", "pending"), q.get("brand"), allowed, user,
                                                   self._is_admin(user)))
            if u.path == "/patrol":
                brands = load_brands(settings, db, enabled_only=False)
                return self._send(200, patrol_web.render_patrol(CSS, settings, db, brands, allowed, user,
                                                                self._is_admin(user)))
            if u.path in ("/admin/brands", "/admin/members"):
                if not self._is_admin(user):
                    return self._send(403, "只有管理員可以使用這一頁")
                if u.path == "/admin/brands":
                    return self._send(200, admin_web.render_brands(CSS, brands_dir(settings), user))
                return self._send(200, admin_web.render_users(CSS, ddir, brands_dir(settings), user, bool(password)))
            if u.path == "/api/drafts":
                return self._json(200, db.list_drafts(status=q.get("status") or None, brand_key=q.get("brand"),
                                                      brands=allowed))
            self._send(404, "not found")

        def do_POST(self):
            who = self._gate(as_json=True)
            if who is None:
                return
            user, allowed = who
            if self.headers.get("X-Radar") != "1":  # 擋跨站表單（CSRF）
                return self._json(403, {"error": "forbidden"})
            path = urlparse(self.path).path
            if path.startswith("/api/admin/"):
                return self._admin_post(path, user)
            if path == "/api/patrol/keywords":
                body = self._body()
                if body is None:
                    return
                brands = load_brands(settings, db, enabled_only=False)
                return self._json(*patrol_web.set_keyword(db, brands, allowed, user, body))
            m = re.fullmatch(r"/api/drafts/(\d+)/(approve|reject|sent)", path)
            if not m:
                return self._json(404, {"error": "not found"})
            body = self._body()
            if body is None:
                return
            did, action = int(m.group(1)), m.group(2)
            d = db.get_draft(did)
            if not d or (allowed is not None and d["brand_key"] not in allowed):
                return self._json(404, {"error": "找不到草稿"})  # 別的品牌的草稿：當作不存在
            reason = str(body.get("reason") or "")[:300]
            if action == "approve":
                if d["status"] != "pending":
                    return self._json(409, {"error": f"這則已經是 {d['status']}"})
                text = str(body.get("text") or d["reply_text"]).strip()[:1000]
                if not text:
                    return self._json(400, {"error": "留言不能空白"})
                kind = "edit" if text != d["reply_text"].strip() else "approve"
                db.log_feedback(d, kind, reason, text, user)
                db.set_status(did, "approved", text=text)
            elif action == "reject":
                if d["status"] not in ("pending", "approved"):
                    return self._json(409, {"error": f"這則已經是 {d['status']}"})
                if not reason:
                    return self._json(400, {"error": "退回要填原因"})
                db.log_feedback(d, "reject", reason, "", user)
                db.set_status(did, "rejected")
            else:  # sent
                if d["status"] != "approved":
                    return self._json(409, {"error": "要先核准"})
                db.set_status(did, "sent")
            return self._json(200, {"ok": True, "id": did, "status": db.get_draft(did)["status"]})

        def _admin_post(self, path: str, user: str):
            if not self._is_admin(user):
                return self._json(403, {"error": "只有管理員可以做這件事"})
            routes = {
                "/api/admin/brands": lambda b: admin_web.create_brand(brands_dir(settings), b),
                "/api/admin/members": lambda b: admin_web.add_user(ddir, brands_dir(settings), b, bool(password)),
                "/api/admin/members/brands": lambda b: admin_web.set_user_brands(ddir, brands_dir(settings), b),
                "/api/admin/members/delete": lambda b: admin_web.delete_user(ddir, b),
            }
            if path not in routes:
                return self._json(404, {"error": "not found"})
            body = self._body()
            if body is None:
                return
            code, obj = routes[path](body)
            return self._json(code, obj)

    return H


def serve(settings: dict, host: str | None = None, port: int | None = None):
    cfg = settings.get("review") or {}
    host = host or cfg.get("host", "127.0.0.1")
    port = int(port or cfg.get("port", 8590))
    password = os.environ.get("RADAR_REVIEW_PASSWORD") or None
    if host not in LOOPBACK and not password:
        raise SystemExit("要讓其他裝置連（host 不是 127.0.0.1），必須先設 RADAR_REVIEW_PASSWORD")
    if password and len(password) < 10:
        raise SystemExit("RADAR_REVIEW_PASSWORD 太短，至少 10 個字")
    if accounts.load(data_dir(settings)) and not password:
        raise SystemExit("已經建立審核帳號，請也設定管理員密碼 RADAR_REVIEW_PASSWORD（帳號 admin）")
    httpd = ThreadingHTTPServer((host, port), make_handler(settings, password, host))
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print(f"審核後台：http://{shown}:{httpd.server_address[1]}/  （Ctrl+C 停止）")
    print_custom_ad()
    return httpd
