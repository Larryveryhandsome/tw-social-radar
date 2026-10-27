"""貼文來源。開源版只收兩種「合規」來源：

- file：匯入 JSON／JSONL／CSV（你自己整理、從官方匯出、或其他合法工具產生的資料）
- threads_api：Meta 官方 Threads API 的關鍵字搜尋（需要你自己的開發者帳號與權杖）

不提供登入帳號爬網頁、模擬真人滑動、繞過驗證的程式。
要接其他平台，照 file_source.normalize 的欄位格式寫一個 fetch(brand, settings, db) -> list[dict] 即可。
"""
from __future__ import annotations


def fetch(brand: dict, settings: dict, db) -> list[dict]:
    kind = (settings.get("source") or {}).get("type", "file")
    if kind == "file":
        from .file_source import fetch as f
    elif kind == "threads_api":
        from .threads_api import fetch as f
    else:
        raise ValueError(f"不認得的 source.type：{kind}（可用 file / threads_api）")
    return f(brand, settings, db)
