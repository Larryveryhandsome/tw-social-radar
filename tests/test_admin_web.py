"""管理員頁：新增品牌精靈、成員管理（實際起伺服器，用 HTTP 操作）。"""
import base64
import json
import os
import shutil
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from helpers import ROOT, cleanup, temp_settings
from radar import accounts, brands as brands_mod, pipeline, review_server
from radar.config import data_dir

ADMIN_PW = "admin-pw-for-test"
AMY_PW = "amy-pw-for-test"


def _auth(name, pw):
    return {"Authorization": "Basic " + base64.b64encode(f"{name}:{pw}".encode()).decode()}


class Server:
    """每個測試自己的品牌資料夾副本，不動 repo 的 brands/。"""

    def __init__(self, password=ADMIN_PW, with_reviewer=True):
        self.s = temp_settings()
        bdir = self.s["_tmp"] / "brands"
        shutil.copytree(ROOT / "brands", bdir)
        self.s["brands_dir"] = str(bdir)
        self.bdir = bdir
        self.ddir = data_dir(self.s)
        self.ddir.mkdir(parents=True, exist_ok=True)
        pipeline.run_once(self.s)  # 示範草稿：demo、demo-food 都有
        if with_reviewer:
            accounts.add(self.ddir, "amy", AMY_PW, ["demo"])
        with mock.patch.dict(os.environ, {"RADAR_REVIEW_PASSWORD": password or ""}):
            self.httpd = review_server.serve(self.s, "localhost", 0)
        self.base = "http://{}:{}".format(*self.httpd.server_address[:2])
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        cleanup(self.s)

    def req(self, path, body=None, headers=None, who=("admin", ADMIN_PW)):
        h = {"X-Radar": "1", "content-type": "application/json"}
        if who:
            h.update(_auth(*who))
        h.update(headers or {})
        r = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                   headers=h, method="GET" if body is None else "POST")
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, resp.read().decode("utf-8"), dict(resp.headers)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read().decode("utf-8"), dict(e.headers)


NEW_BRAND = {"preset": "local_service", "key": "good-clean", "display_name": "好鄰居清潔", "handle": "@good.clean_tw"}


class TestAdminAccess(unittest.TestCase):
    def setUp(self):
        self.srv = Server()

    def tearDown(self):
        self.srv.close()

    def test_admin_can_open_pages(self):
        code, page, hdr = self.srv.req("/admin/brands")
        self.assertEqual(code, 200)
        self.assertIn("新增品牌", page)
        self.assertIn("local_service", page)
        self.assertIn("default-src 'none'", hdr["Content-Security-Policy"])  # 沿用同一套 CSP
        code, page, _ = self.srv.req("/admin/members")
        self.assertEqual(code, 200)
        self.assertIn("amy", page)
        self.assertIn("/admin/members", self.srv.req("/")[1])  # 管理員的審核頁有入口

    def test_custom_ad_in_backend_footer(self):
        """作者客製化資訊在審核／巡邏／管理頁尾都看得到，但不會混進任何草稿資料。"""
        for path in ("/", "/patrol", "/admin/brands", "/admin/members"):
            code, page, _ = self.srv.req(path)
            self.assertEqual(code, 200, path)
            self.assertIn('class="custom-ad"', page, path)
            self.assertIn("https://line.me/ti/p/xzHT2IywOM", page, path)

    def test_reviewer_gets_403(self):
        amy = ("amy", AMY_PW)
        self.assertEqual(self.srv.req("/")[0], 200)
        self.assertNotIn("/admin/members", self.srv.req("/", who=amy)[1])  # 審核員看不到入口
        for path in ("/admin/brands", "/admin/members"):
            self.assertEqual(self.srv.req(path, who=amy)[0], 403, path)
        posts = {"/api/admin/brands": NEW_BRAND,
                 "/api/admin/members": {"name": "bob", "password": "x" * 12, "password2": "x" * 12, "brands": ["*"]},
                 "/api/admin/members/brands": {"name": "amy", "brands": ["*"]},
                 "/api/admin/members/delete": {"name": "amy"}}
        for path, body in posts.items():
            self.assertEqual(self.srv.req(path, body, who=amy)[0], 403, path)
        self.assertFalse((self.srv.bdir / "good-clean").exists())
        self.assertEqual(accounts.load(self.srv.ddir)["amy"]["brands"], ["demo"])  # 沒被偷改成全部品牌
        self.assertNotIn("bob", accounts.load(self.srv.ddir))

    def test_login_host_and_csrf_still_enforced(self):
        self.assertEqual(self.srv.req("/admin/members", who=None)[0], 401)
        self.assertEqual(self.srv.req("/api/admin/brands", NEW_BRAND, who=None)[0], 401)
        self.assertEqual(self.srv.req("/admin/brands", headers={"Host": "evil.example"})[0], 421)
        self.assertEqual(self.srv.req("/api/admin/brands", NEW_BRAND, headers={"X-Radar": "0"})[0], 403)
        self.assertFalse((self.srv.bdir / "good-clean").exists())

    def test_login_lockout_applies(self):
        with mock.patch.object(review_server, "FAIL_LIMIT", 2):
            for _ in range(2):
                self.assertEqual(self.srv.req("/admin/members", who=("admin", "wrong-password"))[0], 401)
            self.assertEqual(self.srv.req("/admin/members")[0], 429)  # 密碼對了也先擋

    def test_bad_body(self):
        code, _, _ = self.srv.req("/api/admin/brands", headers={"content-type": "application/json"}, body=[1, 2])
        self.assertEqual(code, 400)
        self.assertEqual(self.srv.req("/api/admin/nope", {})[0], 404)


class TestBrandWizard(unittest.TestCase):
    def setUp(self):
        self.srv = Server()

    def tearDown(self):
        self.srv.close()

    def test_create_brand(self):
        code, body, _ = self.srv.req("/api/admin/brands", NEW_BRAND)
        self.assertEqual(code, 201, body)
        b = brands_mod.load_file(self.srv.bdir / "good-clean" / "brand.yaml")
        self.assertEqual((b["key"], b["display_name"], b["handle"]), ("good-clean", "好鄰居清潔", "good.clean_tw"))
        self.assertEqual(brands_mod.validate(b), [])
        self.assertIn("good-clean", brands_mod.load_all(self.srv.bdir, enabled_only=False))
        self.assertIn("好鄰居清潔", self.srv.req("/admin/brands")[1])
        # 建好就能指派給成員
        code, body, _ = self.srv.req("/api/admin/members/brands", {"name": "amy", "brands": ["demo", "good-clean"]})
        self.assertEqual(code, 200, body)

    def test_never_overwrites_existing_brand(self):
        demo = self.srv.bdir / "demo" / "brand.yaml"
        before = demo.read_bytes()
        code, body, _ = self.srv.req("/api/admin/brands", {**NEW_BRAND, "key": "demo", "display_name": "搶走"})
        self.assertEqual(code, 409, body)
        self.assertEqual(demo.read_bytes(), before)
        self.assertEqual(self.srv.req("/api/admin/brands", NEW_BRAND)[0], 201)
        made = (self.srv.bdir / "good-clean" / "brand.yaml").read_bytes()
        self.assertEqual(self.srv.req("/api/admin/brands", {**NEW_BRAND, "display_name": "第二次"})[0], 409)
        self.assertEqual((self.srv.bdir / "good-clean" / "brand.yaml").read_bytes(), made)
        # 資料夾在但沒有 brand.yaml，也不碰
        (self.srv.bdir / "half").mkdir()
        self.assertEqual(self.srv.req("/api/admin/brands", {**NEW_BRAND, "key": "half"})[0], 409)
        self.assertEqual(list((self.srv.bdir / "half").iterdir()), [])

    def test_input_validation(self):
        bad = [
            {"preset": ""},
            {"preset": "../demo/brand"},
            {"preset": "nope"},
            {"key": "Bad Key"},
            {"key": "../evil"},
            {"key": "_presets"},
            {"key": "a"},
            {"key": "con"},
            {"display_name": ""},
            {"display_name": "第一行\n第二行"},
            {"display_name": "長" * 41},
            {"handle": 'a"b'},
            {"handle": "has space"},
            {"handle": "x" * 31},
        ]
        dirs_before = sorted(p.name for p in self.srv.bdir.iterdir())
        for over in bad:
            code, body, _ = self.srv.req("/api/admin/brands", {**NEW_BRAND, **over})
            self.assertEqual(code, 400, f"{over} → {body}")
            self.assertIn("error", json.loads(body))
        self.assertEqual(sorted(p.name for p in self.srv.bdir.iterdir()), dirs_before)

    def test_odd_display_name_round_trips(self):
        name = '小美: "工作室" \\ #1'
        code, body, _ = self.srv.req("/api/admin/brands", {**NEW_BRAND, "display_name": name, "handle": ""})
        self.assertEqual(code, 201, body)
        b = brands_mod.load_file(self.srv.bdir / "good-clean" / "brand.yaml")
        self.assertEqual((b["display_name"], b["handle"]), (name, ""))

    def test_name_is_escaped_on_page(self):
        self.srv.req("/api/admin/brands", {**NEW_BRAND, "display_name": "<script>alert(1)</script>"})
        page = self.srv.req("/admin/brands")[1]
        self.assertNotIn("<script>alert(1)", page)
        self.assertIn("&lt;script&gt;", page)


class TestMembers(unittest.TestCase):
    def setUp(self):
        self.srv = Server()

    def tearDown(self):
        self.srv.close()

    def add(self, **over):
        body = {"name": "bob", "password": "bob-pw-12345", "password2": "bob-pw-12345", "brands": ["demo-food"], **over}
        return self.srv.req("/api/admin/members", body)

    def test_add_assign_remove(self):
        code, body, _ = self.add()
        self.assertEqual(code, 201, body)
        bob = ("bob", "bob-pw-12345")
        self.assertEqual(self.srv.req("/", who=bob)[0], 200)
        drafts = json.loads(self.srv.req("/api/drafts", who=bob)[1])
        self.assertTrue(drafts)
        self.assertTrue(all(d["brand_key"] == "demo-food" for d in drafts))
        self.assertEqual(self.srv.req("/admin/members", who=bob)[0], 403)
        # 改負責品牌（不動密碼）
        self.assertEqual(self.srv.req("/api/admin/members/brands", {"name": "bob", "brands": ["*"]})[0], 200)
        self.assertEqual(accounts.load(self.srv.ddir)["bob"]["brands"], ["*"])
        self.assertEqual(self.srv.req("/", who=bob)[0], 200)
        self.assertIn("bob", self.srv.req("/admin/members")[1])
        # 刪除後登入不了
        self.assertEqual(self.srv.req("/api/admin/members/delete", {"name": "bob"})[0], 200)
        self.assertEqual(self.srv.req("/", who=bob)[0], 401)
        self.assertEqual(self.srv.req("/api/admin/members/delete", {"name": "bob"})[0], 404)
        self.assertEqual(self.srv.req("/api/admin/members/brands", {"name": "bob", "brands": ["demo"]})[0], 404)

    def test_member_validation(self):
        cases = [
            ({"password2": "different-pw-1"}, 400),
            ({"password": "short", "password2": "short"}, 400),
            ({"password": None, "password2": None}, 400),
            ({"name": "admin"}, 400),
            ({"name": "a"}, 400),
            ({"name": "bad name!"}, 400),
            ({"brands": []}, 400),
            ({"brands": "demo"}, 400),
            ({"brands": ["no-such-brand"]}, 400),
            ({"name": "amy"}, 409),  # 已存在：不覆蓋密碼
        ]
        for over, want in cases:
            code, body, _ = self.add(**over)
            self.assertEqual(code, want, f"{over} → {body}")
        self.assertEqual(set(accounts.load(self.srv.ddir)), {"amy"})
        self.assertEqual(self.srv.req("/", who=("amy", AMY_PW))[0], 200)  # amy 密碼沒被改
        self.assertEqual(self.srv.req("/api/admin/members/brands", {"name": "amy", "brands": []})[0], 400)
        self.assertEqual(self.srv.req("/api/admin/members/brands", {"name": "amy", "brands": ["nope"]})[0], 400)
        self.assertEqual(accounts.load(self.srv.ddir)["amy"]["brands"], ["demo"])


class TestNoPasswordMode(unittest.TestCase):
    """本機、沒設密碼、沒有帳號：那個人就是管理員，但不能新增成員（不然下次開不起來）。"""

    def setUp(self):
        self.srv = Server(password=None, with_reviewer=False)

    def tearDown(self):
        self.srv.close()

    def test_local_owner(self):
        self.assertEqual(self.srv.req("/admin/brands", who=None)[0], 200)
        code, page, _ = self.srv.req("/admin/members", who=None)
        self.assertEqual(code, 200)
        self.assertIn("RADAR_REVIEW_PASSWORD", page)
        self.assertEqual(self.srv.req("/api/admin/brands", NEW_BRAND, who=None)[0], 201)
        body = {"name": "bob", "password": "bob-pw-12345", "password2": "bob-pw-12345", "brands": ["*"]}
        self.assertEqual(self.srv.req("/api/admin/members", body, who=None)[0], 400)
        self.assertEqual(accounts.load(self.srv.ddir), {})


class TestCreateFromPreset(unittest.TestCase):
    def setUp(self):
        self.s = temp_settings()
        self.bdir = Path(self.s["_tmp"]) / "brands"
        shutil.copytree(ROOT / "brands", self.bdir)

    def tearDown(self):
        cleanup(self.s)

    def test_failed_create_leaves_nothing(self):
        bad = self.bdir / "_presets" / "broken.yaml"
        bad.write_text("key: x\ndisplay_name: x\nhandle: \"\"\nkeywords: []\n", encoding="utf-8")
        with self.assertRaises(brands_mod.BrandError):
            brands_mod.create_from_preset(self.bdir, "new-one", "broken", "新品牌")
        self.assertFalse((self.bdir / "new-one").exists())

    def test_cli_rejects_bad_input(self):
        for kw in ({"handle": 'x"\nkeywords: []'}, {"preset": "../demo/brand"}):
            args = {"key": "new-one", "preset": "local_service", "display_name": "新品牌", **kw}
            with self.assertRaises(brands_mod.BrandError):
                brands_mod.create_from_preset(self.bdir, **args)
        self.assertFalse((self.bdir / "new-one").exists())


if __name__ == "__main__":
    unittest.main()


class TestCustomAdConsole(unittest.TestCase):
    def test_ad_prints_on_big5_console(self):
        # 繁中 Windows 主控台是 cp950，沒有「衞」；印不出的字不能讓審核後台一啟動就當掉
        import io
        from radar import print_custom_ad
        buf = io.TextIOWrapper(io.BytesIO(), encoding="cp950")
        print_custom_ad(buf)
        buf.flush()
        self.assertIn("0928-880-392", buf.buffer.getvalue().decode("cp950"))
