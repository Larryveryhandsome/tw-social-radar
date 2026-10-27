"""純規則：時間解析、過濾、觸發詞、模板學習、草稿檢查。"""
import random
import unittest
from datetime import datetime, timedelta

from helpers import ROOT, cleanup, temp_settings
from radar import brands, filters, guard, intent, matcher
from radar.db import DB


def demo_brand():
    return brands.load_file(ROOT / "brands" / "demo" / "brand.yaml")


class TestTime(unittest.TestCase):
    def test_relative(self):
        now = datetime(2026, 5, 10, 12, 0, 0)
        self.assertEqual(filters.parse_relative_time("3小時", now), "2026-05-10T09:00:00")
        self.assertEqual(filters.parse_relative_time("2天", now), "2026-05-08T12:00:00")
        self.assertEqual(filters.parse_relative_time("5d", now), "2026-05-05T12:00:00")
        self.assertIsNone(filters.parse_relative_time("9999999年", now))
        self.assertIsNone(filters.parse_relative_time("剛剛", now))

    def test_parse_time_formats(self):
        self.assertIsNotNone(filters.parse_time("2026-05-10T09:00:00+0000"))  # Threads API 格式
        self.assertIsNotNone(filters.parse_time("2026-05-10T09:00:00Z"))
        self.assertIsNotNone(filters.parse_time(1747000000))
        self.assertIsNone(filters.parse_time("not a date"))

    def test_fresh(self):
        now = datetime.now()
        self.assertTrue(filters.is_fresh({"posted_at": (now - timedelta(days=2)).isoformat()}, 14))
        self.assertFalse(filters.is_fresh({"posted_at": (now - timedelta(days=20)).isoformat()}, 14))
        self.assertTrue(filters.is_fresh({"discovered_at": now.isoformat()}, 14))  # 沒有發文時間，看發現時間


class TestFilters(unittest.TestCase):
    def setUp(self):
        self.b = demo_brand()
        self.now = datetime.now().isoformat()

    def p(self, text, author="someone"):
        return {"content": text, "author": author, "posted_at": self.now}

    def test_reasons(self):
        self.assertEqual(filters.skip_reason(self.p("短"), self.b), "內文太短")
        self.assertEqual(filters.skip_reason(self.p("大掃除の季節ですね、おすすめは"), self.b), "日韓文貼文")
        self.assertEqual(filters.skip_reason(self.p("大掃除時段開放預約喔", "demo_clean_studio"), self.b), "自己的貼文")
        self.assertEqual(filters.skip_reason(self.p("大掃除時段開放預約喔", "happy_cleaning"), self.b), "同業帳號")
        self.assertEqual(filters.skip_reason(self.p("清潔公司徵人，有經驗佳"), self.b), "命中排除詞")
        self.assertIsNone(filters.skip_reason(self.p("想找人來大掃除，有沒有推薦"), self.b))


class TestMatcher(unittest.TestCase):
    def setUp(self):
        self.b = demo_brand()

    def test_indicator_gate(self):
        self.assertIsNone(matcher.find_trigger(self.b, "有沒有推薦的電影"))  # 沒提到清潔相關
        self.assertEqual(matcher.find_trigger(self.b, "想找人大掃除")["id"], "deep_clean")

    def test_negative(self):
        # deep_clean 有 negative「掃完了」→ 落到下一個能命中的 trigger 或 None
        t = matcher.find_trigger(self.b, "大掃除掃完了好累")
        self.assertTrue(t is None or t["id"] != "deep_clean")

    def test_learning(self):
        s = temp_settings()
        try:
            db = DB(s["_tmp"] / "t.db")
            trig = {"id": "x", "match_any": ["a"], "templates": ["壞模板", "好模板"]}
            db.upsert_post({"post_id": "p1", "content": "c"})
            for i in range(3):
                did = db.add_draft({"brand_key": "demo", "post_id": f"p{i}", "trigger_id": "x", "reply_text": "壞模板"})
                db.log_feedback(db.get_draft(did), "reject", "語氣不對", "")
            db.set_meta("dummy", "1")
            # 被退 3 次、0 次核准 → 停用；剩下「好模板」
            picks = {matcher.pick_reply(self.b, trig, db, random.Random(i)) for i in range(20)}
            self.assertEqual(picks, {"好模板"})
            # 改寫過的文字變成新候選
            did = db.add_draft({"brand_key": "demo", "post_id": "p9", "trigger_id": "x", "reply_text": "好模板"})
            db.log_feedback(db.get_draft(did), "edit", "", "我改過的版本")
            self.assertIn("我改過的版本", db.learned_templates("demo", "x"))
        finally:
            cleanup(s)


class TestGuardIntent(unittest.TestCase):
    def test_guard(self):
        self.assertEqual(guard.check("覺得有用按愛心，分享給朋友！")[0], "BLOCK")
        self.assertEqual(guard.check("讓我們一起看看，值得注意的是這個")[0], "BLOCK")
        self.assertEqual(guard.check("")[0], "BLOCK")
        lvl, notes = guard.check("我們保證最便宜，詳見 https://example.com")
        self.assertEqual(lvl, "WARN")
        self.assertTrue(any("網址" in n for n in notes))
        self.assertEqual(guard.check("看到你在找～有需要可以私訊聊聊 ☺️")[0], "OK")

    def test_intent(self):
        self.assertEqual(intent.rule_score("今天天氣真好"), 1)
        self.assertGreaterEqual(intent.rule_score("急！有沒有推薦的清潔？明天要退租"), 4)


if __name__ == "__main__":
    unittest.main()
