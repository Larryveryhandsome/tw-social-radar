"""審核帳號：讓新成員只看得到、只能審自己負責的品牌。

- 管理員：帳號 admin，密碼 = 環境變數 RADAR_REVIEW_PASSWORD，看得到全部品牌。
- 審核員：`python -m radar user add 小美 --brands demo,demo-food`，密碼只存雜湊（PBKDF2-SHA256）在 data/reviewers.json。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import Path

ITERATIONS = 200_000
NAME_RE = re.compile(r"^[\w.\-]{2,32}$")


def path(data_dir: Path) -> Path:
    return Path(data_dir) / "reviewers.json"


def load(data_dir: Path) -> dict:
    p = path(data_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _save(data_dir: Path, users: dict) -> None:
    p = path(data_dir)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(users, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _hash(pw: str, salt: str, it: int = ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), it).hex()


def add(data_dir: Path, name: str, password: str, brands: list[str]) -> None:
    if name == "admin" or not NAME_RE.match(name):
        raise ValueError("帳號名稱 2–32 字（中英數、. - _），而且不能叫 admin")
    if len(password) < 10:
        raise ValueError("密碼至少 10 個字")
    brands = [b.strip() for b in brands if b.strip()]
    if not brands:
        raise ValueError("至少要指定一個品牌（--brands demo,demo-food；全部品牌用 *）")
    users = load(data_dir)
    salt = secrets.token_hex(16)
    users[name] = {"salt": salt, "hash": _hash(password, salt), "iterations": ITERATIONS, "brands": brands}
    _save(data_dir, users)


def set_brands(data_dir: Path, name: str, brands: list[str]) -> bool:
    """只改負責的品牌，不動密碼。沒有這個帳號回 False。"""
    brands = [b.strip() for b in brands if b.strip()]
    if not brands:
        raise ValueError("至少要指定一個品牌（全部品牌用 *）")
    users = load(data_dir)
    if name not in users:
        return False
    users[name]["brands"] = brands
    _save(data_dir, users)
    return True


def remove(data_dir: Path, name: str) -> bool:
    users = load(data_dir)
    if name not in users:
        return False
    del users[name]
    _save(data_dir, users)
    return True


def authenticate(data_dir: Path, name: str, password: str, admin_password: str | None):
    """回傳 (帳號名稱, 可看的品牌清單；None 代表全部)；失敗回 None。"""
    if name == "admin" or (admin_password and not load(data_dir).get(name)):
        # 只設管理員密碼時，帳號欄隨便填都當管理員（和 0.1.0 相容）
        if admin_password and hmac.compare_digest(password.encode(), admin_password.encode()):
            return "admin", None
        return None
    u = load(data_dir).get(name)
    if not u:
        return None
    if not hmac.compare_digest(_hash(password, u["salt"], u.get("iterations", ITERATIONS)), u["hash"]):
        return None
    brands = u.get("brands") or []
    return name, (None if "*" in brands else brands)
