"""指令列：python -m radar <指令>

  doctor                       檢查設定、品牌檔、LLM、金鑰是否齊全
  demo                         用假資料跑一次「雷達 → 草稿」（不連網）
  run [--brand KEY]            跑一輪：抓貼文 → 產草稿（只產草稿，不發文）
  import FILE...               匯入貼文檔（JSON / JSONL / CSV）後跑一輪
  review [--host H --port P]   開審核後台
  drafts [--status S]          在終端機列出草稿
  export [--out FILE]          匯出草稿 CSV
  brand list | brand presets | brand new KEY --preset P --name 名稱 [--handle H] | brand check
  plugin list | plugin install NAME
  user list | user add 名字 --brands a,b | user remove 名字    審核帳號（新成員只看得到自己的品牌）
  publish [--dry-run]          （外掛模式）送出已核准的草稿；沒裝外掛不會做任何事；--dry-run 只模擬不送出
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

from . import brands as brands_mod
from . import plugins, pipeline
from .config import ROOT, brands_dir, data_dir, load_settings


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass


def cmd_doctor(s, a) -> int:
    import os
    ok = True
    print(f"設定檔：{s['_path']}")
    print(f"資料夾：{data_dir(s)}")
    try:
        bs = brands_mod.load_all(brands_dir(s), enabled_only=False)
        names = [k + ("" if b.get("enabled", True) else "(停用)") for k, b in bs.items()]
        print(f"品牌：{len(bs)} 個 → {', '.join(names) or '（還沒有，先跑 brand new）'}")
    except brands_mod.BrandError as e:
        ok = False
        print(f"❌ 品牌檔有錯：\n{e}")
    llm = s["llm"]
    print(f"LLM：provider={llm['provider']}、draft_mode={llm['draft_mode']}、classify={llm['classify']}")
    need = {"claude_api": "ANTHROPIC_API_KEY"}.get(llm["provider"])
    if need and not os.environ.get(need):
        ok = False
        print(f"❌ 缺 {need}（見 docs/金鑰申請.md）")
    if llm["provider"] == "claude_cli" and not (shutil.which("claude") or shutil.which("claude.cmd")):
        ok = False
        print("❌ 找不到 claude 指令（先安裝 Claude Code）")
    src = s["source"]["type"]
    print(f"來源：{src}")
    if src == "threads_api" and not os.environ.get("THREADS_ACCESS_TOKEN"):
        ok = False
        print("❌ 缺 THREADS_ACCESS_TOKEN（見 docs/金鑰申請.md）")
    for k, env in (("line", ("LINE_CHANNEL_ACCESS_TOKEN", "LINE_TO_ID")), ("discord", ("DISCORD_WEBHOOK_URL",))):
        if s["notify"].get(k):
            miss = [e for e in env if not os.environ.get(e)]
            if miss:
                ok = False
                print(f"❌ notify.{k} 開了但缺 {', '.join(miss)}")
    ap = s["auto_publish"]
    if ap.get("enabled") not in (True, False):
        ok = False
        print(f"❌ auto_publish.enabled 只能是 true 或 false（現在是 {ap.get('enabled')!r}，視為關閉）")
    print(f"自動發文外掛：{'啟用' if ap.get('enabled') is True else '關閉（預設）'}；已安裝：{', '.join(plugins.installed()) or '無'}")
    from . import accounts
    users = accounts.load(data_dir(s))
    names = ["{}({})".format(n, ",".join(u.get("brands", []))) for n, u in users.items()]
    print(f"審核帳號：{', '.join(names) or '無（只有本機或管理員）'}")
    if users and not os.environ.get("RADAR_REVIEW_PASSWORD"):
        ok = False
        print("❌ 有審核帳號時要設管理員密碼 RADAR_REVIEW_PASSWORD")
    print("✅ 檢查通過" if ok else "⚠️ 有項目要處理")
    return 0 if ok else 1


def cmd_demo(s, a) -> int:
    """用 fixtures/ 的假貼文＋brands/demo，在獨立的 data/demo/ 跑一次。"""
    s = dict(s)
    s["data_dir"] = str(data_dir(s) / "demo")
    s["source"] = {**s["source"], "type": "file", "file": {"paths": ["fixtures/demo_posts.jsonl"]}}
    s["notify"] = {**s["notify"], "line": False, "discord": False}
    if a.reset:
        shutil.rmtree(data_dir(s), ignore_errors=True)
    stats = pipeline.run_once(s)
    total = sum(len(x["drafts"]) for x in stats)
    print(f"\n示範完成：產生 {total} 則草稿。看草稿：python -m radar review --demo")
    return 0


def _demo_settings(s, a):
    if getattr(a, "demo", False):
        s = dict(s)
        s["data_dir"] = str(data_dir(s) / "demo")
    return s


def cmd_run(s, a) -> int:
    stats = pipeline.run_once(s, only=a.brand)
    return 1 if any(x.get("error") for x in stats) else 0


def cmd_import(s, a) -> int:
    s = dict(s)
    s["source"] = {**s["source"], "type": "file", "file": {"paths": [str(Path(p).resolve()) for p in a.files]}}
    pipeline.run_once(s, only=a.brand)
    return 0


def cmd_review(s, a) -> int:
    from .review_server import serve
    httpd = serve(_demo_settings(s, a), a.host, a.port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_drafts(s, a) -> int:
    db = pipeline.open_db(_demo_settings(s, a))
    for d in db.list_drafts(status=a.status or None, brand_key=a.brand):
        print(f"#{d['id']} [{d['status']}] {d['brand_key']} @{d.get('author')} 需求{d.get('intent_score')}/5")
        print(f"   貼文：{(d.get('content') or '')[:60]}")
        print(f"   草稿：{d['reply_text']}")
    return 0


def excel_safe(v):
    """貼文是陌生人寫的：開頭是 = + - @ 的儲存格，Excel 會當公式執行（CSV injection），前面加 ' 擋掉。"""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def cmd_export(s, a) -> int:
    db = pipeline.open_db(_demo_settings(s, a))
    rows = db.list_drafts(status=None, limit=100000)
    out = Path(a.out or (data_dir(s) / "drafts_export.csv"))
    cols = ["id", "brand_key", "status", "author", "url", "intent_score", "trigger_id", "reply_text",
            "content", "created_at", "reviewed_at", "sent_at"]
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows({k: excel_safe(v) for k, v in r.items()} for r in rows)
    print(f"已匯出 {len(rows)} 筆 → {out}")
    return 0


def cmd_brand(s, a) -> int:
    bd = brands_dir(s)
    if a.action == "presets":
        for p in brands_mod.list_presets(bd):
            print(p)
    elif a.action == "list":
        for k, b in brands_mod.load_all(bd, enabled_only=False).items():
            print(f"{k}\t{b['display_name']}\t{'啟用' if b.get('enabled', True) else '停用'}\t{b['_path']}")
    elif a.action == "check":
        errs = []
        for p in sorted(bd.glob("*/brand.yaml")) + sorted(brands_mod.presets_dir(bd).glob("*.yaml")):
            try:
                brands_mod.load_file(p)
                print(f"✅ {p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}")
            except brands_mod.BrandError as e:
                errs.append(str(e))
        for e in errs:
            print(f"❌ {e}")
        return 1 if errs else 0
    elif a.action == "new":
        if not (a.key and a.preset and a.name):
            raise SystemExit("用法：python -m radar brand new KEY --preset 產業 --name 顯示名稱 [--handle 帳號]")
        p = brands_mod.create_from_preset(bd, a.key, a.preset, a.name, a.handle or "", a.force)
        print(f"已建立 {p}\n下一步：打開它，改 keywords、triggers 的模板，讓口吻像你自己。")
    return 0


def cmd_plugin(s, a) -> int:
    if a.action == "list":
        print(f"可安裝：{', '.join(plugins.available()) or '無'}")
        print(f"已安裝：{', '.join(plugins.installed()) or '無'}")
    elif a.action == "install":
        if not a.name:
            raise SystemExit("用法：python -m radar plugin install NAME")
        d = plugins.install(a.name, a.force)
        print(f"已安裝到 {d}\n⚠️ 外掛預設仍是關閉的；請先讀 {d / 'README.md'} 的風險說明，"
              f"確定要用再把 settings.yaml 的 auto_publish.enabled 改成 true。")
    return 0


def cmd_user(s, a) -> int:
    from . import accounts
    d = data_dir(s)
    if a.action == "list":
        users = accounts.load(d)
        for n, u in users.items():
            print(f"{n}  {','.join(u.get('brands', []))}")
        if not users:
            print("（沒有審核帳號；管理員用帳號 admin＋RADAR_REVIEW_PASSWORD 登入）")
    elif a.action == "add":
        if not (a.name and a.brands):
            raise SystemExit("用法：python -m radar user add 名字 --brands demo,demo-food（全部品牌用 *）")
        known = set(brands_mod.load_all(brands_dir(s), enabled_only=False, strict=False))
        wanted = [b.strip() for b in a.brands.split(",") if b.strip()]
        unknown = [b for b in wanted if b != "*" and b not in known]
        if unknown:
            raise SystemExit(f"沒有這些品牌：{', '.join(unknown)}（現有：{', '.join(sorted(known))}）")
        if a.password_stdin:
            pw = sys.stdin.readline().rstrip("\r\n")
        else:
            import getpass
            pw = getpass.getpass("密碼（至少 10 字，不會顯示）：")
            if pw != getpass.getpass("再輸入一次："):
                raise SystemExit("兩次密碼不一樣")
        try:
            accounts.add(d, a.name, pw, wanted)
        except ValueError as e:
            raise SystemExit(f"❌ {e}")
        print(f"已建立審核帳號 {a.name}，可審：{', '.join(wanted)}")
        import os
        if not os.environ.get("RADAR_REVIEW_PASSWORD"):
            print("⚠️ 記得也在 .env 設管理員密碼 RADAR_REVIEW_PASSWORD，否則審核頁不會啟動")
    elif a.action == "remove":
        print("已刪除" if accounts.remove(d, a.name or "") else "沒有這個帳號")
    return 0


def cmd_publish(s, a) -> int:
    if getattr(a, "dry_run", False):
        print("【只模擬，不送出、不連網、不改狀態】")
        for line in pipeline.preview_publish(s):
            print(" ", line)
        return 0
    done = pipeline.publish_approved(s)
    if not done:
        print("沒有送出任何東西（外掛沒啟用、沒安裝、不在時段，或沒有已核准的草稿）")
    for i, r in done:
        print(f"#{i} {r}")
    return 0


def main(argv=None) -> int:
    _utf8()
    ap = argparse.ArgumentParser(prog="python -m radar", description="tw-social-radar 品牌社群雷達")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    p = sub.add_parser("demo"); p.add_argument("--reset", action="store_true", help="清掉上次的示範資料")
    p = sub.add_parser("run"); p.add_argument("--brand")
    p = sub.add_parser("import"); p.add_argument("files", nargs="+"); p.add_argument("--brand")
    p = sub.add_parser("review"); p.add_argument("--host"); p.add_argument("--port", type=int); p.add_argument("--demo", action="store_true")
    p = sub.add_parser("drafts"); p.add_argument("--status", default="pending"); p.add_argument("--brand"); p.add_argument("--demo", action="store_true")
    p = sub.add_parser("export"); p.add_argument("--out"); p.add_argument("--demo", action="store_true")
    p = sub.add_parser("brand"); p.add_argument("action", choices=["list", "presets", "new", "check"])
    p.add_argument("key", nargs="?"); p.add_argument("--preset"); p.add_argument("--name"); p.add_argument("--handle"); p.add_argument("--force", action="store_true")
    p = sub.add_parser("plugin"); p.add_argument("action", choices=["list", "install"]); p.add_argument("name", nargs="?"); p.add_argument("--force", action="store_true")
    p = sub.add_parser("user"); p.add_argument("action", choices=["list", "add", "remove"]); p.add_argument("name", nargs="?")
    p.add_argument("--brands"); p.add_argument("--password-stdin", action="store_true", help="從標準輸入讀密碼（給腳本用）")
    p = sub.add_parser("publish"); p.add_argument("--dry-run", action="store_true", help="只模擬：列出會送出什麼，不連網、不改狀態")
    a = ap.parse_args(argv)
    s = load_settings()
    fn = {"doctor": cmd_doctor, "demo": cmd_demo, "run": cmd_run, "import": cmd_import, "review": cmd_review,
          "drafts": cmd_drafts, "export": cmd_export, "brand": cmd_brand, "plugin": cmd_plugin,
          "publish": cmd_publish, "user": cmd_user}[a.cmd]
    try:
        return fn(s, a) or 0
    except (brands_mod.BrandError, FileNotFoundError, FileExistsError, ValueError) as e:
        print(f"❌ {e}")
        return 1
