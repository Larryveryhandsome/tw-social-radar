"""品牌設定：brands/<key>/brand.yaml。

一個品牌一個資料夾，取代以前寫死在程式裡的模板檔。
產業範本在 brands/_presets/<產業>.yaml，用 `python -m radar brand new` 複製一份來改。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")  # Threads 帳號（不含 @）
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}

BRAND_DEFAULTS = {
    "enabled": True,
    "handle": "",
    "industry": "",
    "keywords": [],
    "indicators": [],
    "exclude_words": [],
    "competitor_handle_hints": [],
    "filters": {"skip_japanese_korean": True, "max_post_age_days": 30, "min_length": 8},
    "limits": {"max_drafts_per_day": 6, "max_drafts_per_run": 3},
    "voice": {"tone": "", "self_reference": "我們", "emoji": [], "cta": "", "avoid": [], "examples": []},
    "triggers": [],
}


class BrandError(ValueError):
    pass


LIST_FIELDS = ["keywords", "indicators", "exclude_words", "competitor_handle_hints"]


def _clean_list(v) -> list[str]:
    """yaml 裡的清單：轉成字串、去空白、丟掉空的。空字串很危險——「"" in 任何文字」永遠成立，會讓每篇貼文都命中。"""
    if v is None:
        return []
    if isinstance(v, (str, int, float)):
        v = [v]
    if not isinstance(v, list):
        raise BrandError(f"應該是清單，卻是 {type(v).__name__}")
    return [str(x).strip() for x in v if x is not None and str(x).strip()]


def normalize(b: dict, where: str = "brand.yaml") -> dict:
    try:
        for f in LIST_FIELDS:
            b[f] = _clean_list(b.get(f))
        trig = b.get("triggers") or []
        if not isinstance(trig, list):
            raise BrandError("triggers 應該是清單")
        clean = []
        for t in trig:
            if not isinstance(t, dict):
                raise BrandError("triggers 每一項都要有 id、match_any、templates")
            t = dict(t)
            t["id"] = str(t.get("id") or "").strip()
            for f in ("match_any", "negative_any", "templates"):
                t[f] = _clean_list(t.get(f))
            clean.append(t)
        b["triggers"] = clean
        v = b.get("voice") or {}
        for f in ("emoji", "avoid", "examples"):
            v[f] = _clean_list(v.get(f))
        b["voice"] = v
    except BrandError as e:
        raise BrandError(f"{where}: {e}") from None
    return b


def validate(b: dict, where: str = "brand.yaml") -> list[str]:
    """回傳錯誤清單；空清單代表沒問題。"""
    errs = []
    for sect, fields in (("limits", ("max_drafts_per_day", "max_drafts_per_run")),
                         ("filters", ("max_post_age_days", "min_length", "min_intent"))):
        for f in fields:
            val = (b.get(sect) or {}).get(f)
            if val is not None and (not isinstance(val, int) or isinstance(val, bool) or val < 0):
                errs.append(f"{where}: {sect}.{f} 要是 0 以上的整數（現在是 {val!r}）")
    key = b.get("key", "")
    if not KEY_RE.match(str(key)):
        errs.append(f"{where}: key「{key}」只能用小寫英數、- 和 _，2–32 字")
    if not b.get("display_name"):
        errs.append(f"{where}: 缺 display_name")
    if not b.get("keywords"):
        errs.append(f"{where}: keywords 至少要一個（雷達搜尋詞）")
    ids = set()
    for i, t in enumerate(b.get("triggers") or []):
        tid = t.get("id")
        if not tid:
            errs.append(f"{where}: triggers[{i}] 缺 id")
        elif tid in ids:
            errs.append(f"{where}: trigger id「{tid}」重複")
        ids.add(tid)
        if not t.get("match_any"):
            errs.append(f"{where}: trigger「{tid}」缺 match_any")
        if not t.get("templates"):
            errs.append(f"{where}: trigger「{tid}」缺 templates（至少一則回覆模板）")
    if not b.get("triggers"):
        errs.append(f"{where}: triggers 至少要一個")
    lim = b.get("limits") or {}
    if isinstance(lim.get("max_drafts_per_day"), int) and lim["max_drafts_per_day"] > 30:
        errs.append(f"{where}: max_drafts_per_day 上限 30（草稿太多人審不完，也容易變洗版）")
    return errs


def _with_defaults(raw: dict) -> dict:
    b = dict(BRAND_DEFAULTS)
    for k, v in raw.items():
        if isinstance(v, dict) and isinstance(b.get(k), dict):
            b[k] = {**b[k], **v}
        else:
            b[k] = v
    return b


def load_file(path: Path) -> dict:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise BrandError(f"{path}: YAML 格式錯誤（常見原因：縮排不一致、冒號後面少空格）：{e}") from None
    if not isinstance(raw, dict):
        raise BrandError(f"{path}: 內容應該是「欄位: 值」的格式")
    b = normalize(_with_defaults(raw), str(path))
    errs = validate(b, str(path))
    if errs:
        raise BrandError("\n".join(errs))
    b["_path"] = str(path)
    return b


def load_all(brands_dir: Path, enabled_only: bool = True, strict: bool = True) -> dict[str, dict]:
    """strict=False：壞掉的品牌檔印警告後跳過，不讓其他品牌跟著停（排程用）。"""
    out = {}
    if not brands_dir.exists():
        return out
    for p in sorted(brands_dir.glob("*/brand.yaml")):
        if p.parent.name.startswith("_"):
            continue
        try:
            b = load_file(p)
        except BrandError as e:
            if strict:
                raise
            print(f"⚠️ 略過有錯的品牌檔：{e}")
            continue
        if b["key"] != p.parent.name:
            msg = f"{p}: key「{b['key']}」要和資料夾名稱「{p.parent.name}」一樣"
            if strict:
                raise BrandError(msg)
            print(f"⚠️ 略過：{msg}")
            continue
        if b["key"] in out:
            raise BrandError(f"品牌 key「{b['key']}」重複")
        if enabled_only and not b.get("enabled", True):
            continue
        out[b["key"]] = b
    return out


# 審核頁可以新增／停用的清單欄位（存在資料庫，不改 brand.yaml，免得洗掉使用者的註解）
OVERRIDE_FIELDS = {"keywords": "雷達搜尋詞", "indicators": "上下文詞",
                   "exclude_words": "排除詞", "competitor_handle_hints": "同業帳號提示"}
WORD_MIN, WORD_MAX = 2, 40


def clean_word(field: str, word) -> str:
    """網頁輸入的關鍵字：跟 yaml 一樣用 _clean_list 去空白，再加長度限制。不合格丟 BrandError。"""
    if field not in OVERRIDE_FIELDS:
        raise BrandError(f"不能改這個欄位：{field}")
    if not isinstance(word, str):
        raise BrandError("關鍵字要是文字")
    cleaned = _clean_list(word)
    if not cleaned:
        raise BrandError("關鍵字不能空白（空字串會讓每一篇貼文都命中）")
    w = cleaned[0]
    if any(ord(c) < 32 for c in w):
        raise BrandError("關鍵字不能換行")
    if not WORD_MIN <= len(w) <= WORD_MAX:
        raise BrandError(f"關鍵字要 {WORD_MIN}–{WORD_MAX} 個字（太短的字幾乎每篇都會命中）")
    return w


def apply_overrides(b: dict, rows: list[dict]) -> dict:
    """把資料庫裡的新增／停用合併進品牌設定，回傳新的 dict（不動原本的）。

    enabled=1：清單裡沒有就加上；enabled=0：從清單拿掉（brand.yaml 原有的詞也能停用）。
    另外記 _yaml（原檔清單）、_added、_disabled，給審核頁標示來源。
    """
    b = dict(b)
    b["_yaml"], b["_added"], b["_disabled"] = {}, {}, {}
    for f in OVERRIDE_FIELDS:
        orig = list(b.get(f) or [])
        cur = list(orig)
        added, disabled = [], []
        for r in rows:
            if r.get("field") != f:
                continue
            w = str(r.get("word") or "").strip()
            if not w:
                continue  # 資料庫被手動塞了空字串也不讓它進清單
            low = w.lower()
            if r.get("enabled"):
                if all(x.lower() != low for x in cur):
                    cur.append(w)
                    added.append(w)
            else:
                cur = [x for x in cur if x.lower() != low]
                disabled.append(w)
        b[f] = cur
        b["_yaml"][f], b["_added"][f], b["_disabled"][f] = orig, added, disabled
    return b


def presets_dir(brands_dir: Path) -> Path:
    return brands_dir / "_presets"


def list_presets(brands_dir: Path) -> list[str]:
    return sorted(p.stem for p in presets_dir(brands_dir).glob("*.yaml"))


def create_from_preset(brands_dir: Path, key: str, preset: str, display_name: str,
                       handle: str = "", force: bool = False) -> Path:
    if not KEY_RE.match(key):
        raise BrandError(f"key「{key}」只能用小寫英數、- 和 _，2–32 字")
    if key in WINDOWS_RESERVED:
        raise BrandError(f"key「{key}」是 Windows 保留名稱，請換一個")
    handle = handle.strip().lstrip("@")
    if handle and not HANDLE_RE.match(handle):
        raise BrandError(f"Threads 帳號「{handle}」只能用英數、. 和 _，最多 30 字")
    if not display_name.strip() or any(ord(c) < 32 for c in display_name):
        raise BrandError("品牌名稱不能空白，也不能換行")
    if preset not in list_presets(brands_dir):  # 也擋 ../ 這類路徑
        raise BrandError(f"找不到產業範本 {preset}，可用：{', '.join(list_presets(brands_dir))}")
    src = presets_dir(brands_dir) / f"{preset}.yaml"
    dest = brands_dir / key / "brand.yaml"
    if dest.exists() and not force:
        raise BrandError(f"{dest} 已存在；要覆蓋請加 --force")
    text = src.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^key:.*$", f"key: {key}", text, count=1)
    name_yaml = yaml.safe_dump(display_name, allow_unicode=True, width=10_000).strip().splitlines()[0]
    text = re.sub(r"(?m)^display_name:.*$", lambda _: f"display_name: {name_yaml}", text, count=1)
    text = re.sub(r"(?m)^handle:.*$", f"handle: \"{handle}\"", text, count=1)
    new_dir = not dest.parent.exists()
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(dest, "w" if force else "x", encoding="utf-8") as f:  # "x"：兩個人同時建同一個 key 也不會互相覆蓋
            f.write(text)
    except FileExistsError:
        raise BrandError(f"{dest} 已存在；要覆蓋請加 --force") from None
    try:
        load_file(dest)  # 驗證
    except BrandError:
        if not force:  # 新建失敗就收掉，不留半成品
            dest.unlink(missing_ok=True)
            if new_dir:
                dest.parent.rmdir()
        raise
    return dest
