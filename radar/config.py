"""讀取 config/settings.yaml 與 .env。

設定檔找不到時用 config/settings.example.yaml，所以剛 clone 下來就能跑示範。
金鑰一律從環境變數（或專案根目錄的 .env）讀，不寫在 yaml 裡。
"""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("RADAR_HOME") or Path(__file__).resolve().parent.parent)

DEFAULTS: dict = {
    "data_dir": "data",
    "brands_dir": "brands",
    "timezone_offset_hours": 8,
    "retention_days": 60,
    "llm": {
        "provider": "mock",            # mock | claude_cli | claude_api | ollama
        "draft_mode": "template",      # template（只用 brand.yaml 的模板）| llm（AI 依品牌口吻寫）
        "classify": False,             # True = 用 LLM 判斷需求強度（會多花額度）
        "timeout_seconds": 90,
        "claude_cli": {"model": "", "bin": ""},
        "claude_api": {"model": "claude-haiku-5-5", "max_tokens": 400},
        "ollama": {"host": "http://127.0.0.1:11434", "model": "qwen2.5:7b"},
    },
    "source": {
        "type": "file",                # file | threads_api
        "file": {"paths": ["inbox/*.jsonl", "inbox/*.json", "inbox/*.csv"]},
        "threads_api": {
            "search_type": "RECENT",
            "limit_per_keyword": 25,
            "max_queries_per_run": 8,
            "fresh_hours": 72,
        },
    },
    "review": {"host": "127.0.0.1", "port": 8590},
    "schedule": {"interval_minutes": 30},  # 排程多久跑一輪；審核頁「巡邏中」用來推算下一輪
    "notify": {"line": False, "discord": False, "review_url": "http://127.0.0.1:8590"},
    "auto_publish": {"enabled": False, "plugin": "threads_publisher", "max_per_brand_per_day": 4,
                     "window_start_hour": 8, "window_end_hour": 22},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_env(path: Path | None = None) -> None:
    """讀 .env（簡易版：KEY=VALUE，# 開頭是註解）。已存在的環境變數不覆蓋。"""
    p = path or (ROOT / ".env")
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def settings_path() -> Path:
    p = ROOT / "config" / "settings.yaml"
    return p if p.exists() else ROOT / "config" / "settings.example.yaml"


def load_settings(path: Path | None = None) -> dict:
    load_env()
    p = path or settings_path()
    data = {}
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    s = _merge(DEFAULTS, data)
    s["_path"] = str(p)
    return s


def data_dir(s: dict) -> Path:
    d = Path(s["data_dir"])
    d = d if d.is_absolute() else ROOT / d
    d.mkdir(parents=True, exist_ok=True)
    return d


def brands_dir(s: dict) -> Path:
    d = Path(s["brands_dir"])
    return d if d.is_absolute() else ROOT / d


def no_window_flags() -> int:
    """Windows 上呼叫子程式時不開黑色視窗（CREATE_NO_WINDOW）。"""
    return 0x08000000 if sys.platform == "win32" else 0
