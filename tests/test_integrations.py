"""對外串接（全部用假的 urlopen / subprocess，不連網、不花錢）。"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from helpers import ROOT, cleanup, fake_urlopen, temp_settings
from radar import llm as llm_mod
from radar import notify, pipeline, plugins
from radar.db import DB
from radar.sources import threads_api


class TestLLM(unittest.TestCase):
    def test_get_llm(self):
        s = temp_settings()
        try:
            self.assertEqual(llm_mod.get_llm(s).name, "mock")
            s["llm"]["provider"] = "nope"
            with self.assertRaises(llm_mod.LLMError):
                llm_mod.get_llm(s)
            s["llm"]["provider"] = "claude_api"
            with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
                with self.assertRaises(llm_mod.LLMError):  # 沒金鑰要講清楚
                    llm_mod.get_llm(s)
        finally:
            cleanup(s)

    def test_claude_api_request(self):
        calls = []
        payload = {"content": [{"type": "text", "text": '{"reply": "hi"}'}]}
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-not-real"}), \
                mock.patch("urllib.request.urlopen", fake_urlopen(payload, calls)):
            out = llm_mod.ClaudeAPI("claude-haiku-5-5").complete("問題", system="系統")
        self.assertEqual(out, '{"reply": "hi"}')
        req = calls[0]
        self.assertEqual(req.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(req.get_header("X-api-key"), "test-key-not-real")
        self.assertEqual(req.get_header("Anthropic-version"), "2023-06-01")
        body = json.loads(req.data)
        self.assertEqual((body["model"], body["system"]), ("claude-haiku-5-5", "系統"))

    def test_ollama_request(self):
        calls = []
        with mock.patch("urllib.request.urlopen", fake_urlopen({"response": "好"}, calls)):
            out = llm_mod.Ollama("http://127.0.0.1:11434/", "qwen2.5:7b").complete("嗨")
        self.assertEqual(out, "好")
        self.assertEqual(calls[0].full_url, "http://127.0.0.1:11434/api/generate")
        self.assertFalse(json.loads(calls[0].data)["stream"])

    def test_claude_cli_hidden_window(self):
        seen = {}

        def fake_run(cmd, **kw):
            seen.update(kw, cmd=cmd)
            return subprocess.CompletedProcess(cmd, 0, b'{"reply":"ok"}', b"")
        with mock.patch("subprocess.run", fake_run):
            out = llm_mod.ClaudeCLI(model="haiku", bin_path="claude").complete("p")
        self.assertIn("ok", out)
        self.assertEqual(seen["cmd"][:2], ["claude", "-p"])
        self.assertIn("--model", seen["cmd"])
        if os.name == "nt":
            self.assertEqual(seen["creationflags"], 0x08000000)  # 不跳黑色視窗


class TestThreadsAPI(unittest.TestCase):
    def test_search_and_rotation(self):
        s = temp_settings()
        try:
            s["source"]["type"] = "threads_api"
            s["source"]["threads_api"]["max_queries_per_run"] = 2
            db = DB(s["_tmp"] / "t.db")
            brand = {"key": "b", "keywords": ["k1", "k2", "k3"]}
            payload = {"data": [
                {"id": "111", "text": "想找清潔推薦", "permalink": "https://x/p/111", "timestamp": "2026-05-01T10:00:00+0000", "username": "u1"},
                {"id": "222", "text": "這是別人底下的留言", "is_reply": True, "username": "u2"}]}
            calls = []
            with mock.patch.dict(os.environ, {"THREADS_ACCESS_TOKEN": "t"}), \
                    mock.patch("urllib.request.urlopen", fake_urlopen(payload, calls)):
                got1 = threads_api.fetch(brand, s, db)
                threads_api.fetch(brand, s, db)
            qs = [parse_qs(urlparse(c if isinstance(c, str) else c.full_url).query) for c in calls]
            self.assertEqual([q["q"][0] for q in qs], ["k1", "k2", "k3", "k1"])  # 輪流查
            self.assertEqual(qs[0]["search_type"][0], "RECENT")
            self.assertTrue(urlparse(calls[0] if isinstance(calls[0], str) else calls[0].full_url).path.endswith("/keyword_search"))
            self.assertEqual([p["post_id"] for p in got1], ["111", "111"])  # 留言被排除
            self.assertEqual(got1[0]["source"], "threads_api")
            with mock.patch.dict(os.environ, {"THREADS_ACCESS_TOKEN": ""}):
                with self.assertRaises(threads_api.ThreadsAPIError):
                    threads_api.fetch(brand, s, db)
        finally:
            cleanup(s)


class TestNotify(unittest.TestCase):
    def test_line_and_discord(self):
        s = temp_settings()
        s["notify"].update(line=True, discord=True)
        calls = []
        env = {"LINE_CHANNEL_ACCESS_TOKEN": "x", "LINE_TO_ID": "Uxxx", "DISCORD_WEBHOOK_URL": "https://discord.invalid/hook"}
        try:
            with mock.patch.dict(os.environ, env), mock.patch("urllib.request.urlopen", fake_urlopen({}, calls)):
                r = notify.send(s, "測試")
            self.assertEqual(r, {"line": True, "discord": True})
            self.assertEqual(calls[0].full_url, "https://api.line.me/v2/bot/message/push")
            self.assertEqual(calls[0].get_header("Authorization"), "Bearer x")
        finally:
            cleanup(s)


class TestPublisherPlugin(unittest.TestCase):
    def setUp(self):
        self.s = temp_settings()
        self.tmp = Path(tempfile.mkdtemp())
        self.patch = mock.patch.object(plugins, "PLUGINS_DIR", self.tmp / "plugins")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        cleanup(self.s)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _approved(self, source):
        db = pipeline.open_db(self.s)
        db.upsert_post({"post_id": "m1", "content": "想找清潔", "source": source})
        did = db.add_draft({"brand_key": "demo", "post_id": "m1", "reply_text": "可以私訊聊聊"})
        db.set_status(did, "approved")
        return db, did

    def test_default_off(self):
        db, did = self._approved("threads_api")
        self.assertEqual(pipeline.publish_approved(self.s, db), [])  # 預設關閉
        self.s["auto_publish"]["enabled"] = True
        self.assertEqual(pipeline.publish_approved(self.s, db), [])  # 開了但沒安裝外掛
        self.assertEqual(db.get_draft(did)["status"], "approved")

    def test_installed_plugin_publishes_via_official_api(self):
        plugins.install("threads_publisher")
        self.assertEqual(plugins.installed(), ["threads_publisher"])
        db, did = self._approved("threads_api")
        db.upsert_post({"post_id": "f1", "content": "x", "source": "file"})
        fid = db.add_draft({"brand_key": "demo", "post_id": "f1", "reply_text": "y"})
        db.set_status(fid, "approved")
        self.s["auto_publish"].update(enabled=True, window_start_hour=0, window_end_hour=24)
        calls = []
        env = {"THREADS_ACCESS_TOKEN": "t", "THREADS_USER_ID": "42", "THREADS_PUBLISH_WAIT": "0"}
        with mock.patch.dict(os.environ, env), mock.patch("urllib.request.urlopen", fake_urlopen({"id": "999"}, calls)), \
                mock.patch("time.sleep"):
            done = dict(pipeline.publish_approved(self.s, db))
        self.assertEqual(done[did], "sent")
        self.assertTrue(done[fid].startswith("failed"))  # 匯入檔來的貼文不能自動回
        self.assertEqual([c.full_url for c in calls], ["https://graph.threads.com/v1.0/42/threads",
                                                       "https://graph.threads.com/v1.0/42/threads_publish"])
        self.assertIn(b"reply_to_id=m1", calls[0].data)
        self.assertEqual(db.get_draft(did)["status"], "sent")

    def test_publish_dry_run_sends_nothing(self):
        """只模擬不送出：不連網、不鎖定、不改狀態，連外掛開著也一樣。"""
        plugins.install("threads_publisher")
        db, did = self._approved("threads_api")
        self.s["auto_publish"].update(enabled=True, window_start_hour=0, window_end_hour=24)
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("dry-run 不可連網")),                 mock.patch.dict(os.environ, {"THREADS_ACCESS_TOKEN": "t", "THREADS_USER_ID": "42"}):
            lines = pipeline.preview_publish(self.s, db)
        self.assertTrue(any(l.startswith(f"#{did}") and "會送出" in l for l in lines))
        self.assertEqual(db.get_draft(did)["status"], "approved")

    def test_publish_dry_run_when_disabled(self):
        db, did = self._approved("threads_api")
        lines = pipeline.preview_publish(self.s, db)
        self.assertIn("關閉", lines[0])
        self.assertEqual(db.get_draft(did)["status"], "approved")


if __name__ == "__main__":
    unittest.main()
