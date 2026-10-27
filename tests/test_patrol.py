"""審核頁「巡邏中」：總覽數字、品牌隔離、網頁新增／停用關鍵字。"""
import os
import unittest
import urllib.parse
from datetime import datetime, timedelta
from unittest import mock

from helpers import cleanup, fake_urlopen, temp_settings
from test_admin_web import ADMIN_PW, AMY_PW, Server
from radar import brands as brands_mod, matcher, patrol_web, pipeline

AMY = ("amy", AMY_PW)


def kw(srv, word, enabled=True, field="keywords", brand="demo", who=("admin", ADMIN_PW), headers=None):
    return srv.req("/api/patrol/keywords", {"brand": brand, "field": field, "word": word, "enabled": enabled},
                   who=who, headers=headers)


class TestPatrolPage(unittest.TestCase):
    def setUp(self):
        self.srv = Server()  # 已經跑過一輪示範（pipeline.run_once）
        self.db = pipeline.open_db(self.srv.s)

    def tearDown(self):
        self.srv.close()

    def test_overview_numbers(self):
        run = self.db.latest_run("demo")
        self.assertIsNotNone(run)
        self.assertGreater(run["candidates"], 0)
        self.assertTrue(run["skipped"])
        # 被過濾的數字加起來 + 命中 = 這一輪看過的貼文
        self.assertEqual(sum(run["skipped"].values()) + run["candidates"], run["fetched"])
        self.assertEqual(sum(run["triggers"].values()), run["candidates"])
        self.db.upsert_post({"post_id": "k1", "content": "x", "source_keyword": "大掃除"})
        self.db.upsert_post({"post_id": "k2", "content": "y", "source_keyword": "大掃除"})
        code, page, hdr = self.srv.req("/patrol")
        self.assertEqual(code, 200)
        self.assertIn("default-src 'none'", hdr["Content-Security-Policy"])
        card = page.split('id="b-demo"')[1].split('id="b-demo-food"')[0]
        for label, n in (("抓到", run["fetched"]), ("新貼文", run["new"]), ("命中", run["candidates"]),
                         ("產草稿", run["drafts"])):
            self.assertIn(f"{label}<b>{n}</b>", card)
        for reason, n in run["skipped"].items():
            self.assertIn(f"<td>{reason}</td><td>{n}</td>", card)
        for tid, n in run["triggers"].items():
            drafted = self.db.trigger_draft_counts("demo").get(tid, 0)
            self.assertIn(f"<td>{tid}</td>", card)
            self.assertRegex(card, rf"<td>{tid}</td><td>[^<]*</td><td>{n}</td><td>{drafted}</td>")
        self.assertIn("大掃除<span class=\"n\">7天 2 則</span>", card)
        for s in run["samples"]:
            self.assertIn(f"@{s['author']}", card)
        self.assertLessEqual(max(len(s["snippet"]) for s in run["samples"]), 40)
        for word in ("清潔推薦", "漏水", "徵人", "housekeep", "deep_clean"):  # 五類設定都看得到
            self.assertIn(word, card)
        self.assertIn("依設定推算", page)
        self.assertIn("/patrol", self.srv.req("/")[1])  # 審核頁有入口

    def test_reviewer_only_sees_own_brands(self):
        code, page, _ = self.srv.req("/patrol", who=AMY)
        self.assertEqual(code, 200)
        self.assertIn('id="b-demo"', page)
        self.assertNotIn("b-demo-food", page)
        self.assertNotIn("示範便當屋", page)
        self.assertNotIn("/admin/members", page)
        self.assertEqual(self.srv.req("/patrol", who=None)[0], 401)
        self.assertEqual(self.srv.req("/patrol", headers={"Host": "evil.example"})[0], 421)

    def test_word_validation(self):
        bad = ["", "   ", "\t\n", "掃", "長" * 41, "第一行\n第二行", None, 123]
        for w in bad:
            code, body, _ = kw(self.srv, w)
            self.assertEqual(code, 400, f"{w!r} → {body}")
        self.assertEqual(kw(self.srv, "大掃除囉", field="triggers")[0], 400)
        self.assertEqual(kw(self.srv, "大掃除囉", enabled="yes")[0], 400)
        self.assertEqual(kw(self.srv, "大掃除")[0], 409)  # 已經有了
        self.assertEqual(kw(self.srv, "不存在的詞", enabled=False)[0], 404)
        self.assertEqual(kw(self.srv, "大掃除囉", brand="nope")[0], 404)
        self.assertEqual(kw(self.srv, "大掃除囉", headers={"X-Radar": "0"})[0], 403)  # CSRF
        self.assertEqual(self.db.keyword_overrides(), [])

    def test_cross_brand_forbidden(self):
        code, _, _ = kw(self.srv, "便當外送", brand="demo-food", who=AMY)
        self.assertEqual(code, 403)
        self.assertEqual(kw(self.srv, "便當推薦", enabled=False, brand="demo-food", who=AMY)[0], 403)
        self.assertEqual(self.db.keyword_overrides(), [])
        # 自己負責的品牌可以改，而且記錄是誰改的
        self.assertEqual(kw(self.srv, "居家清潔", who=AMY)[0], 200)
        self.assertEqual(self.db.keyword_log("demo")[0]["changed_by"], "amy")

    def test_add_disable_reenable_logged(self):
        demo_yaml = (self.srv.bdir / "demo" / "brand.yaml").read_bytes()
        self.assertEqual(kw(self.srv, " 居家清潔 ")[0], 200)
        self.assertEqual(kw(self.srv, "大掃除", enabled=False)[0], 200)
        self.assertEqual(kw(self.srv, "大掃除", enabled=False)[0], 404)  # 已經停用
        self.assertEqual(kw(self.srv, "大掃除", enabled=True, who=AMY)[0], 200)
        log = self.db.keyword_log("demo")
        self.assertEqual([(r["word"], r["enabled"], r["changed_by"]) for r in log],
                         [("大掃除", 1, "amy"), ("大掃除", 0, "admin"), ("居家清潔", 1, "admin")])
        b = pipeline.load_brands(self.srv.s, self.db)["demo"]
        self.assertIn("居家清潔", b["keywords"])
        self.assertIn("大掃除", b["keywords"])
        self.assertEqual((self.srv.bdir / "demo" / "brand.yaml").read_bytes(), demo_yaml)  # 不改 yaml
        page = self.srv.req("/patrol")[1]
        self.assertIn("網頁新增", page)
        self.assertIn("關鍵字異動紀錄", page)

    def test_short_yaml_word_toggle(self):
        self.assertEqual(kw(self.srv, "吃", enabled=False, field="indicators", brand="demo-food")[0], 200)
        self.assertNotIn("吃", pipeline.load_brands(self.srv.s, self.db)["demo-food"]["indicators"])
        self.assertEqual(kw(self.srv, "吃", enabled=True, field="indicators", brand="demo-food")[0], 200)
        self.assertIn("吃", pipeline.load_brands(self.srv.s, self.db)["demo-food"]["indicators"])

    def test_keep_last_keyword(self):
        kws = pipeline.load_brands(self.srv.s, self.db)["demo"]["keywords"]
        for w in kws[:-1]:
            self.assertEqual(kw(self.srv, w, enabled=False)[0], 200)
        self.assertEqual(kw(self.srv, kws[-1], enabled=False)[0], 400)

    def test_escaped(self):
        self.assertEqual(kw(self.srv, "<script>x", field="exclude_words")[0], 200)
        page = self.srv.req("/patrol")[1]
        self.assertNotIn("<script>x", page)
        self.assertIn("&lt;script&gt;x", page)


class TestDisabledWordTakesEffect(unittest.TestCase):
    def setUp(self):
        self.s = temp_settings()
        self.db = pipeline.open_db(self.s)

    def tearDown(self):
        cleanup(self.s)

    def test_not_searched_next_run(self):
        self.db.set_keyword("demo", "keywords", "大掃除", False, "admin")
        self.db.set_keyword("demo", "keywords", "居家清潔", True, "admin")
        self.s["source"]["type"] = "threads_api"
        self.s["source"]["threads_api"]["max_queries_per_run"] = 50
        calls = []
        with mock.patch.dict(os.environ, {"THREADS_ACCESS_TOKEN": "t"}), \
                mock.patch("urllib.request.urlopen", fake_urlopen({"data": []}, calls)):
            pipeline.run_once(self.s, only="demo")
        queried = [urllib.parse.parse_qs(urllib.parse.urlparse(c if isinstance(c, str) else c.full_url).query)["q"][0]
                   for c in calls]
        self.assertNotIn("大掃除", queried)
        self.assertIn("居家清潔", queried)
        self.assertIn("清潔推薦", queried)
        run = self.db.latest_run("demo")
        self.assertEqual(run["source"], "threads_api")

    def test_not_matched_after_disable(self):
        text = "家裡漏水好煩，有沒有人可以推薦"
        self.assertIsNotNone(matcher.find_trigger(pipeline.load_brands(self.s, self.db)["demo"], text))
        self.db.set_keyword("demo", "indicators", "漏水", False, "admin")
        self.assertIsNone(matcher.find_trigger(pipeline.load_brands(self.s, self.db)["demo"], text))
        # 新增排除詞 → 下一輪真的被過濾
        self.db.upsert_post({"post_id": "p1", "author": "someone", "content": "大掃除找人幫忙，有沒有推薦 測試排除",
                             "hours_ago": 1, "posted_at": datetime.now().isoformat(timespec="seconds")})
        self.db.set_keyword("demo", "exclude_words", "測試排除", True, "admin")
        pipeline.run_once(self.s, only="demo")
        run = self.db.latest_run("demo")
        self.assertGreaterEqual(run["skipped"].get("命中排除詞", 0), 1)

    def test_overrides_ignore_blank_rows(self):
        b = brands_mod.apply_overrides({"key": "x", "keywords": ["a1"]},
                                       [{"field": "keywords", "word": "  ", "enabled": 1}])
        self.assertEqual(b["keywords"], ["a1"])

    def test_run_log_purged_with_retention(self):
        old = (datetime.now() - timedelta(days=90)).isoformat(timespec="seconds")
        self.db.add_run_log({"brand": "demo", "samples": [{"author": "a", "snippet": "b", "reason": "c"}]}, "file", old)
        self.assertIsNotNone(self.db.latest_run("demo"))
        self.db.purge_old(60)
        self.assertIsNone(self.db.latest_run("demo"))

    def test_next_run_text(self):
        now = datetime(2026, 10, 21, 12, 0)
        s = {"schedule": {"interval_minutes": 30}}
        self.assertIn("10/21 12:20", patrol_web.next_run_text(s, "2026-10-21T11:50:00", now))
        self.assertIn("排程可能沒在跑", patrol_web.next_run_text(s, "2026-10-21T09:00:00", now))
        self.assertIn("還沒跑過", patrol_web.next_run_text(s, "", now))


if __name__ == "__main__":
    unittest.main()
