"""端到端：假資料 → 雷達 → 草稿（不連網、用 mock LLM）。"""
import json
import random
import unittest

from helpers import ROOT, cleanup, temp_settings
from radar import drafter, pipeline
from radar.llm import MockLLM


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.s = temp_settings()

    def tearDown(self):
        cleanup(self.s)

    def test_demo_run(self):
        stats = pipeline.run_once(self.s, rng=random.Random(1))
        by = {x["brand"]: x for x in stats}
        self.assertEqual(by["demo"]["fetched"], 18)
        self.assertEqual(len(by["demo"]["drafts"]), 3)  # 每輪上限 3
        db = pipeline.open_db(self.s)
        posts = {d["post_id"] for d in db.list_drafts()}
        # 一定不會出現的：日文、同業、自己、徵人、太舊、與品牌無關、單純心得
        for bad in ("demo0004", "demo0005", "demo0006", "demo0007", "demo0008", "demo0012", "demo0016", "demo0018"):
            self.assertNotIn(bad, posts)
        # 餐飲品牌找到團訂與包場
        self.assertTrue({"demo0010", "demo0011"} <= posts)
        for d in db.list_drafts():
            self.assertEqual(d["status"], "pending")  # 只產草稿，不發文

    def test_no_duplicates_and_daily_cap(self):
        pipeline.run_once(self.s)
        pipeline.run_once(self.s)
        stats = pipeline.run_once(self.s)
        db = pipeline.open_db(self.s)
        ids = [(d["brand_key"], d["post_id"]) for d in db.list_drafts(status=None)]
        self.assertEqual(len(ids), len(set(ids)))  # 同一則貼文同一品牌只產一次
        self.assertLessEqual(db.today_draft_count("demo"), 6)
        self.assertEqual(len(stats[0]["drafts"]), 0)

    def test_file_import_once(self):
        pipeline.run_once(self.s)
        st = pipeline.run_once(self.s)
        self.assertEqual(st[0]["fetched"], 0)  # 同一個檔案不重複匯入

    def test_llm_mode_and_fallback(self):
        self.s["llm"]["draft_mode"] = "llm"
        stats = pipeline.run_once(self.s, llm=MockLLM())
        db = pipeline.open_db(self.s)
        self.assertTrue(all(d["origin"] == "llm" for d in db.list_drafts()))
        self.assertTrue(stats[0]["drafts"])

        class BaitLLM:
            def complete(self, prompt, system=""):
                return json.dumps({"reply": "覺得有用按愛心，分享給朋友！"}, ensure_ascii=False)

        class BrokenLLM:
            def complete(self, prompt, system=""):
                raise RuntimeError("down")

        brand = {"key": "demo", "display_name": "x", "voice": {}, "triggers": []}
        trig = {"id": "t", "templates": ["看到你在找～有需要可以私訊聊聊"]}
        post = {"content": "想找清潔", "author": "a"}
        for llm in (BaitLLM(), BrokenLLM()):
            text, origin, _ = drafter.make_draft(brand, post, trig, self.s, llm=llm)
            self.assertEqual(origin, "template")  # AI 寫壞或掛掉 → 退回模板

        class SilentLLM:
            def complete(self, prompt, system=""):
                return '{"reply": ""}'
        self.assertIsNone(drafter.make_draft(brand, post, trig, self.s, llm=SilentLLM()))  # AI 判斷不該留言

    def test_llm_classify_with_mock(self):
        self.s["llm"]["classify"] = True
        stats = pipeline.run_once(self.s, llm=MockLLM())
        self.assertTrue(stats[0]["drafts"])

    def test_purge(self):
        pipeline.run_once(self.s)
        db = pipeline.open_db(self.s)
        with db.conn() as c:
            c.execute("UPDATE posts SET discovered_at='2000-01-01T00:00:00'")
        n = db.purge_old(60)
        left = len(db.recent_posts(hours=10 ** 7))
        self.assertGreater(n, 0)
        self.assertEqual(left, len(db.list_drafts()))  # 只留下還在待審的草稿對應的貼文


if __name__ == "__main__":
    unittest.main()
