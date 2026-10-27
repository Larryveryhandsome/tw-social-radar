"""管理員專用頁：新增品牌精靈、成員管理。

只有管理員（帳號 admin；或本機沒設任何密碼時的唯一使用者）看得到，審核員連進來一律 403。
登入、Host 檢查、登入失敗鎖定、CSP、X-Radar 標頭都由 review_server 統一處理，這裡只管表單內容。
這裡的函式都回傳 (HTTP 狀態碼, JSON)，方便測試。
"""
from __future__ import annotations

import html
import json
import re
import threading
from pathlib import Path

import yaml

from . import CUSTOM_AD_HTML
from . import accounts
from . import brands as brands_mod

_lock = threading.Lock()  # 建品牌、改帳號檔一次只讓一個請求動

ADMIN_CSS = """
table{width:100%;border-collapse:collapse;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:6px 4px;text-align:left;vertical-align:top}
label{display:block;margin:10px 0 4px;font-weight:600}.hint{color:var(--mut);font-size:13px;font-weight:400}
input[type=text],input[type=password]{width:100%;font:inherit;padding:7px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)}
.chk{display:inline-flex;gap:4px;align-items:center;margin:2px 10px 2px 0;font-weight:400}
#msg{min-height:1.6em;margin-top:8px}#msg.err{color:var(--bad)}#msg.ok{color:var(--ok)}
"""

ADMIN_JS = """
async function post(url, body){
  const m=document.getElementById('msg'); m.className=''; m.textContent='處理中…';
  try{
    const r=await fetch(url,{method:'POST',headers:{'content-type':'application/json','X-Radar':'1'},body:JSON.stringify(body)});
    const j=await r.json();
    if(!r.ok){m.className='err'; m.textContent='❌ '+(j.error||'失敗'); return null;}
    m.className='ok'; m.textContent='✅ '+(j.message||'完成'); return j;
  }catch(e){m.className='err'; m.textContent='❌ 連線失敗'; return null;}
}
function checked(root){return [...root.querySelectorAll('input[type=checkbox]:checked')].map(x=>x.value);}
async function newBrand(ev){
  ev.preventDefault(); const f=ev.target;
  const j=await post('/api/admin/brands',{preset:f.preset.value,key:f.key.value.trim(),
    display_name:f.display_name.value.trim(),handle:f.handle.value.trim()});
  if(j) setTimeout(()=>location.reload(),1200);
}
async function addUser(ev){
  ev.preventDefault(); const f=ev.target;
  if(f.password.value!==f.password2.value){const m=document.getElementById('msg');m.className='err';m.textContent='❌ 兩次密碼不一樣';return;}
  const j=await post('/api/admin/members',{name:f.name.value.trim(),password:f.password.value,
    password2:f.password2.value,brands:checked(f)});
  if(j){f.reset(); setTimeout(()=>location.reload(),800);}
}
async function saveBrands(name){
  const row=document.getElementById('u-'+name);
  if(await post('/api/admin/members/brands',{name:name,brands:checked(row)})) setTimeout(()=>location.reload(),800);
}
async function delUser(name){
  if(!confirm('確定刪除審核帳號「'+name+'」？刪除後他就登入不了。')) return;
  if(await post('/api/admin/members/delete',{name:name})) setTimeout(()=>location.reload(),800);
}
"""


def _e(s) -> str:
    return html.escape(str(s or ""))


def _page(css: str, title: str, body: str, user: str) -> str:
    who = f'<span class="meta">（{_e(user)}）</span>' if user else ""
    return (f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(title)}</title>'
            f'<style>{css}{ADMIN_CSS}</style></head><body><main>'
            f'<h1>⚙️ {_e(title)}{who}</h1>'
            f'<nav><a href="/">← 回審核頁</a><a href="/patrol">巡邏中</a><a href="/admin/brands">新增品牌</a><a href="/admin/members">成員管理</a></nav>'
            f'{body}<div id="msg" role="status"></div>{CUSTOM_AD_HTML}</main><script>{ADMIN_JS}</script></body></html>')


def preset_label(bdir: Path, name: str) -> str:
    """範本第一行註解「# 產業範本：在地服務業（…）」→「在地服務業（…）」。"""
    try:
        first = (brands_mod.presets_dir(bdir) / f"{name}.yaml").read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return name
    m = re.match(r"#\s*產業範本[:：]\s*(.+)", first)
    return f"{m.group(1).strip()}［{name}］" if m else name


def _all_brands(bdir: Path) -> dict:
    return brands_mod.load_all(bdir, enabled_only=False, strict=False)


# ---------- 新增品牌精靈 ----------

def render_brands(css: str, bdir: Path, user: str) -> str:
    existing = _all_brands(bdir)
    rows = "".join(f'<tr><td>{_e(k)}</td><td>{_e(b["display_name"])}</td><td>{"@" + _e(b.get("handle")) if b.get("handle") else ""}</td>'
                   f'<td>{"啟用" if b.get("enabled", True) else "停用"}</td></tr>' for k, b in existing.items())
    table = (f'<table><tr><th>key</th><th>名稱</th><th>Threads</th><th>狀態</th></tr>{rows}</table>'
             if rows else '<p class="meta">還沒有品牌。</p>')
    opts = "".join(f'<option value="{_e(p)}">{_e(preset_label(bdir, p))}</option>' for p in brands_mod.list_presets(bdir))
    form = f"""
<form class="card" onsubmit="newBrand(event)" autocomplete="off">
 <b>步驟 1：選產業範本</b>
 <label for="preset">產業</label><select id="preset" name="preset" required><option value="">請選擇…</option>{opts}</select>
 <b style="display:block;margin-top:14px">步驟 2：填品牌資料</b>
 <label for="display_name">品牌名稱 <span class="hint">（顯示在審核頁，例如「好鄰居清潔」）</span></label>
 <input type="text" id="display_name" name="display_name" maxlength="40" required>
 <label for="key">品牌代號 key <span class="hint">（小寫英數、- 和 _，2–32 字；建好後當資料夾名稱，不能改）</span></label>
 <input type="text" id="key" name="key" maxlength="32" pattern="[a-z0-9][a-z0-9_\\-]{{1,31}}" required placeholder="例如 good-clean">
 <label for="handle">自己的 Threads 帳號 <span class="hint">（選填，不含 @；用來排除自己的貼文）</span></label>
 <input type="text" id="handle" name="handle" maxlength="31">
 <div class="row"><button type="submit">建立品牌</button></div>
 <p class="meta">會在 brands/&lt;key&gt;/brand.yaml 產生設定檔。已經存在的品牌不會被覆蓋。<br>
 建好後原則上還要打開那個檔案，把關鍵字與回覆模板改成自己的口吻；下一輪排程會自動納入。</p>
</form>"""
    return _page(css, "新增品牌", f'<div class="card"><b>現有品牌</b>{table}</div>{form}', user)


def create_brand(bdir: Path, body: dict) -> tuple[int, dict]:
    preset = str(body.get("preset") or "").strip()
    key = str(body.get("key") or "").strip()
    name = str(body.get("display_name") or "").strip()
    handle = str(body.get("handle") or "").strip().lstrip("@")
    errs = []
    if preset not in brands_mod.list_presets(bdir):
        errs.append("請選產業範本")
    if not brands_mod.KEY_RE.match(key):
        errs.append("品牌代號只能用小寫英數、- 和 _，2–32 字，開頭要是英數")
    elif key in brands_mod.WINDOWS_RESERVED:
        errs.append(f"「{key}」是 Windows 保留名稱，請換一個")
    if not name or len(name) > 40 or any(ord(c) < 32 for c in name):
        errs.append("品牌名稱要 1–40 字，不能換行")
    if handle and not brands_mod.HANDLE_RE.match(handle):
        errs.append("Threads 帳號只能用英數、. 和 _，最多 30 字")
    if errs:
        return 400, {"error": "；".join(errs)}
    with _lock:
        if (bdir / key).exists():
            return 409, {"error": f"品牌「{key}」已經存在，網頁不會覆蓋；要修改請直接編輯 brands/{key}/brand.yaml"}
        # 先用範本＋填的值跑一次 validate，不合格就不寫檔
        try:
            raw = yaml.safe_load((brands_mod.presets_dir(bdir) / f"{preset}.yaml").read_text(encoding="utf-8")) or {}
            raw.update(key=key, display_name=name, handle=handle)
            errs = brands_mod.validate(brands_mod.normalize(brands_mod._with_defaults(raw)), f"範本 {preset}")
        except (yaml.YAMLError, brands_mod.BrandError, AttributeError) as e:
            errs = [f"範本 {preset} 讀取失敗：{e}"]
        if errs:
            return 400, {"error": "；".join(errs)}
        try:
            brands_mod.create_from_preset(bdir, key, preset, name, handle)  # force=False：絕不覆蓋
        except brands_mod.BrandError as e:
            return 409 if "已存在" in str(e) else 400, {"error": str(e)}
    return 201, {"ok": True, "key": key, "path": f"brands/{key}/brand.yaml",
                 "message": f"已建立品牌「{name}」→ brands/{key}/brand.yaml"}


# ---------- 成員管理 ----------

def _brand_checks(all_brands: dict, picked: list[str]) -> str:
    out = [f'<label class="chk"><input type="checkbox" value="*"{" checked" if "*" in picked else ""}>全部品牌</label>']
    for k, b in all_brands.items():
        out.append(f'<label class="chk"><input type="checkbox" value="{_e(k)}"{" checked" if k in picked else ""}>'
                   f'{_e(b["display_name"])}</label>')
    return "".join(out)


def render_users(css: str, ddir: Path, bdir: Path, user: str, has_admin_password: bool) -> str:
    users = accounts.load(ddir)
    all_brands = _all_brands(bdir)
    rows = []
    for n, u in users.items():
        nj = _e(json.dumps(n))
        rows.append(f'<tr id="u-{_e(n)}"><td><b>{_e(n)}</b></td><td>{_brand_checks(all_brands, u.get("brands") or [])}</td>'
                    f'<td><div class="row" style="margin:0"><button class="ghost" onclick=\'saveBrands({nj})\'>儲存品牌</button>'
                    f'<button class="bad" onclick=\'delUser({nj})\'>刪除</button></div></td></tr>')
    table = (f'<table><tr><th>帳號</th><th>負責的品牌</th><th></th></tr>{"".join(rows)}</table>' if rows
             else '<p class="meta">還沒有審核帳號。管理員用帳號 admin＋RADAR_REVIEW_PASSWORD 登入。</p>')
    warn = "" if has_admin_password else (
        '<div class="card warn">⚠️ 還沒設定管理員密碼 RADAR_REVIEW_PASSWORD。請先在 .env 設定（至少 10 字）並重開審核頁，'
        '才能新增成員——不然新帳號登入不了，你自己也會被擋在門外。</div>')
    form = f"""
<form class="card" onsubmit="addUser(event)" autocomplete="off">
 <b>新增審核帳號</b>
 <label for="name">帳號名稱 <span class="hint">（2–32 字，中英數、. - _；不能叫 admin）</span></label>
 <input type="text" id="name" name="name" maxlength="32" required>
 <label for="password">密碼 <span class="hint">（至少 10 字；請本人當面輸入，只存雜湊，忘了只能刪掉重建）</span></label>
 <input type="password" id="password" name="password" minlength="10" required autocomplete="new-password">
 <label for="password2">再輸入一次密碼</label>
 <input type="password" id="password2" name="password2" minlength="10" required autocomplete="new-password">
 <label>負責的品牌 <span class="hint">（只看得到、只能審勾選的品牌）</span></label>
 <div>{_brand_checks(all_brands, [])}</div>
 <div class="row"><button type="submit"{"" if has_admin_password else " disabled"}>新增帳號</button></div>
</form>"""
    return _page(css, "成員管理", f'{warn}<div class="card"><b>審核帳號</b>{table}</div>{form}', user)


def _check_brands(bdir: Path, wanted) -> tuple[list[str], str]:
    if not isinstance(wanted, list) or not all(isinstance(b, str) for b in wanted):
        return [], "品牌格式不對"
    wanted = [b.strip() for b in wanted if b.strip()]
    if not wanted:
        return [], "至少要勾一個品牌"
    known = set(_all_brands(bdir))
    unknown = [b for b in wanted if b != "*" and b not in known]
    if unknown:
        return [], f"沒有這些品牌：{', '.join(unknown)}"
    return wanted, ""


def add_user(ddir: Path, bdir: Path, body: dict, has_admin_password: bool) -> tuple[int, dict]:
    if not has_admin_password:
        return 400, {"error": "請先在 .env 設定 RADAR_REVIEW_PASSWORD 並重開審核頁，再新增成員"}
    name = str(body.get("name") or "").strip()
    pw = body.get("password")
    if not isinstance(pw, str) or pw != body.get("password2"):
        return 400, {"error": "兩次密碼不一樣"}
    wanted, err = _check_brands(bdir, body.get("brands"))
    if err:
        return 400, {"error": err}
    with _lock:
        if name in accounts.load(ddir):
            return 409, {"error": f"帳號「{name}」已經存在；要換密碼請先刪除再重建"}
        try:
            accounts.add(ddir, name, pw, wanted)
        except ValueError as e:
            return 400, {"error": str(e)}
    return 201, {"ok": True, "name": name, "brands": wanted,
                 "message": f"已建立審核帳號 {name}，可審：{', '.join(wanted)}"}


def set_user_brands(ddir: Path, bdir: Path, body: dict) -> tuple[int, dict]:
    name = str(body.get("name") or "")
    wanted, err = _check_brands(bdir, body.get("brands"))
    if err:
        return 400, {"error": err}
    with _lock:
        if not accounts.set_brands(ddir, name, wanted):
            return 404, {"error": "沒有這個帳號"}
    return 200, {"ok": True, "name": name, "brands": wanted, "message": f"{name} 現在負責：{', '.join(wanted)}"}


def delete_user(ddir: Path, body: dict) -> tuple[int, dict]:
    name = str(body.get("name") or "")
    with _lock:
        if not accounts.remove(ddir, name):
            return 404, {"error": "沒有這個帳號"}
    return 200, {"ok": True, "message": f"已刪除 {name}"}
