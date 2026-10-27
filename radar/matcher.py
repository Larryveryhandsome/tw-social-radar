"""比對貼文 → 選 trigger → 挑回覆模板。純規則，零 AI。

模板權重會依審核結果學習：核准 +1、改寫 +0.5、退回 -2；
退回 3 次以上且從沒被核准的模板直接停用；使用者改寫後的文字會變成新的候選模板。
"""
from __future__ import annotations

import random

from .filters import has_japanese_or_korean


def find_trigger(brand: dict, text: str) -> dict | None:
    low = (text or "").lower()
    if has_japanese_or_korean(text) and (brand.get("filters") or {}).get("skip_japanese_korean", True):
        return None
    indicators = brand.get("indicators") or []
    # 第一關：要先提到品牌相關的詞，避免短詞亂抓
    if indicators and not any(i.lower() in low for i in indicators):
        return None
    for t in brand.get("triggers") or []:
        if any(n.lower() in low for n in t.get("negative_any") or []):
            continue
        if any(k.lower() in low for k in t.get("match_any") or []):
            return t
    return None


def pick_reply(brand: dict, trigger: dict, db=None, rng: random.Random | None = None) -> str:
    rng = rng or random
    templates = list(trigger.get("templates") or [])
    key = brand["key"]
    if db is not None:
        for t in db.learned_templates(key, trigger["id"]):
            if t not in templates:
                templates.append(t)
    recent = db.recent_reply_texts(key) if db is not None else set()

    def scored(skip_recent: bool):
        out = []
        for t in templates:
            if skip_recent and t.strip() in recent:
                continue
            w = 1.0
            if db is not None:
                s = db.template_score(key, t)
                if s["reject"] >= 3 and s["approve"] == 0:
                    continue
                w = max(0.1, 1.0 + s["approve"] + 0.5 * s["edit"] - 2.0 * s["reject"])
            out.append((t, w))
        return out

    cand = scored(True) or scored(False)  # 全部近 7 天用過 → 允許重複，總比沒有好
    if not cand:
        return ""
    texts, weights = zip(*cand)
    return rng.choices(texts, weights=weights, k=1)[0]
