"""審核後台：實際起一個伺服器，用 HTTP 操作核准／改寫／退回／已回覆。"""
import base64
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from helpers import cleanup, temp_settings
from radar import pipeline, review_server


class TestReview(unittest.TestCase):
    def setUp(self):
        self.s = temp_settings()
        pipeline.run_once(self.s)
        self.db = pipeline.open_db(self.s)
        self.httpd = review_server.serve(self.s, "127.0.0.1", 0)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        cleanup(self.s)

    def req(self, path, body=None, headers=None):
        h = {"X-Radar": "1", "content-type": "application/json", **(headers or {})}
        r = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                   headers=h, method="GET" if body is None else "POST")
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    def test_flow(self):
        drafts = self.db.list_drafts()
        self.assertGreaterEqual(len(drafts), 3)
        a, b, c = drafts[:3]
        code, page = self.req("/")
        self.assertEqual(code, 200)
        self.assertIn("社群雷達", page)
        self.assertIn(a["reply_text"][:10], page)
        # 沒帶自訂標頭 → 擋（CSRF）
        code, _ = self.req(f"/api/drafts/{a['id']}/approve", {}, {"X-Radar": "0"})
        self.assertEqual(code, 403)
        # 原文核准
        self.assertEqual(self.req(f"/api/drafts/{a['id']}/approve", {"reason": ""})[0], 200)
        # 改寫後核准 → 記成 edit
        self.assertEqual(self.req(f"/api/drafts/{b['id']}/approve", {"text": "我改過的留言", "reason": "語氣更自然"})[0], 200)
        # 退回不填原因 → 400；填了 → 200
        self.assertEqual(self.req(f"/api/drafts/{c['id']}/reject", {"reason": ""})[0], 400)
        self.assertEqual(self.req(f"/api/drafts/{c['id']}/reject", {"reason": "太像廣告"})[0], 200)
        # 不能重複核准、未核准不能標已回覆
        self.assertEqual(self.req(f"/api/drafts/{a['id']}/approve", {})[0], 409)
        self.assertEqual(self.req(f"/api/drafts/{c['id']}/sent", {})[0], 409)
        self.assertEqual(self.req(f"/api/drafts/{a['id']}/sent", {})[0], 200)
        st = {d["id"]: d for d in self.db.list_drafts(status=None)}
        self.assertEqual((st[a["id"]]["status"], st[b["id"]]["status"], st[c["id"]]["status"]), ("sent", "approved", "rejected"))
        self.assertEqual(st[b["id"]]["reply_text"], "我改過的留言")
        with self.db.conn() as cx:
            acts = [r[0] for r in cx.execute("SELECT action FROM feedback ORDER BY id")]
        self.assertEqual(acts, ["approve", "edit", "reject"])
        # 各分頁都打得開
        for tab in ("approved", "sent", "rejected", "expired"):
            self.assertEqual(self.req(f"/?tab={tab}")[0], 200)
        self.assertEqual(json.loads(self.req("/api/drafts?status=sent")[1])[0]["id"], a["id"])

    def test_xss_escaped(self):
        self.db.upsert_post({"post_id": "x1", "content": "<script>alert(1)</script>", "author": "<b>"})
        self.db.add_draft({"brand_key": "demo", "post_id": "x1", "reply_text": "<img src=x onerror=1>"})
        page = self.req("/")[1]
        self.assertNotIn("<script>alert(1)", page)
        self.assertNotIn("<img src=x", page)


class TestReviewSecurity(unittest.TestCase):
    def test_public_bind_requires_password(self):
        s = temp_settings()
        try:
            with mock.patch.dict(os.environ, {"RADAR_REVIEW_PASSWORD": ""}):
                with self.assertRaises(SystemExit):
                    review_server.serve(s, "0.0.0.0", 0)
        finally:
            cleanup(s)

    def test_password(self):
        s = temp_settings()
        with mock.patch.dict(os.environ, {"RADAR_REVIEW_PASSWORD": "pw-for-test"}):
            httpd = review_server.serve(s, "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{httpd.server_address[1]}/"
        try:
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(url, timeout=5)
            self.assertEqual(e.exception.code, 401)
            tok = base64.b64encode(b"any:pw-for-test").decode()
            with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Basic {tok}"}), timeout=5) as r:
                self.assertEqual(r.status, 200)
        finally:
            httpd.shutdown()
            httpd.server_close()
            cleanup(s)


if __name__ == "__main__":
    unittest.main()
