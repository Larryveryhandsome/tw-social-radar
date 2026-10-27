"""外掛載入。核心程式不會發文；自動發文只能透過「另外安裝、預設關閉」的外掛。

安裝外掛：python -m radar plugin install threads_publisher
  → 把 extras/threads_publisher/ 複製到 plugins/threads_publisher/
啟用條件（三個都要）：
  1. plugins/<名稱>/ 存在（你自己裝的）
  2. config/settings.yaml 的 auto_publish.enabled: true
  3. 外掛需要的金鑰都設好了
就算啟用，也只會送出「人工核准過」的草稿，並受每日上限、時段限制。
"""
from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path

from .config import ROOT

PLUGINS_DIR = ROOT / "plugins"
EXTRAS_DIR = ROOT / "extras"


def available() -> list[str]:
    return sorted(p.name for p in EXTRAS_DIR.iterdir() if (p / "plugin.py").exists()) if EXTRAS_DIR.exists() else []


def installed() -> list[str]:
    return sorted(p.name for p in PLUGINS_DIR.iterdir() if (p / "plugin.py").exists()) if PLUGINS_DIR.exists() else []


NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


def _check_name(name: str) -> str:
    if not NAME_RE.match(str(name or "")):
        raise ValueError(f"外掛名稱不合法：{name!r}")  # 擋 ../ 之類的路徑
    return name


def install(name: str, force: bool = False) -> Path:
    _check_name(name)
    src = EXTRAS_DIR / name
    if not (src / "plugin.py").exists():
        raise FileNotFoundError(f"沒有這個外掛：{name}（可用：{', '.join(available()) or '無'}）")
    dest = PLUGINS_DIR / name
    if dest.exists():
        if not force:
            raise FileExistsError(f"{dest} 已存在；要重裝請加 --force")
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return dest


def load(name: str):
    _check_name(name)
    path = PLUGINS_DIR / name / "plugin.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"radar_plugin_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def publisher(settings: dict):
    ap = settings.get("auto_publish") or {}
    if ap.get("enabled") is not True:  # 只認 yaml 的 true；"false"、"no"、1 之類都不算開
        return None
    mod = load(ap.get("plugin", "threads_publisher"))
    if mod is None:
        print(f"  [plugin] auto_publish.enabled=true，但沒有安裝外掛 {ap.get('plugin')}")
    return mod
