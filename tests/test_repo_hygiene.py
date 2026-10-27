"""repo 自我檢查：沒有金鑰格式、沒有寫死的本機路徑、核心沒有發文或爬網頁的程式、指令列能跑。"""
import re
import subprocess
import sys
import unittest

from helpers import ROOT

SECRET_PATTERNS = {
    "GitHub": r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})",
    "Anthropic/OpenAI": r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}",
    "Google": r"\bAIza[0-9A-Za-z_\-]{30,}",
    "Discord bot token": r"\b[MN][A-Za-z\d]{23,}\.[\w-]{6}\.[\w-]{27,}",
    "私鑰": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "LINE userId": r"\bU[0-9a-f]{32}\b",
    "Windows 使用者路徑": r"[A-Za-z]:\\\\?Users\\\\",
}
TEXT = {".py", ".md", ".yaml", ".yml", ".txt", ".jsonl", ".json", ".example", ".vbs", ".sh", ".bat", ".gitignore"}


def repo_files():
    for p in ROOT.rglob("*"):
        if not p.is_file() or any(x in p.parts for x in (".git", "data", "__pycache__", "plugins", "inbox")):
            continue
        if p.suffix in TEXT or p.name in (".env.example", ".gitignore", "LICENSE", "NOTICE"):
            yield p


class TestHygiene(unittest.TestCase):
    def test_no_secrets(self):
        hits = []
        for p in repo_files():
            if p.name == "test_repo_hygiene.py":
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            for name, pat in SECRET_PATTERNS.items():
                for m in re.finditer(pat, text):
                    hits.append(f"{p.relative_to(ROOT)}: {name}")
        self.assertEqual(hits, [])

    def test_core_has_no_browser_automation(self):
        """核心程式不准有瀏覽器自動化、模擬真人、繞過驗證（開源範圍的硬邊界）。"""
        banned = ["playwright", "selenium", "pyautogui", "undetected", "stealth", "warmup", "captcha"]
        for p in (ROOT / "radar").rglob("*.py"):
            low = p.read_text(encoding="utf-8").lower()
            for w in banned:
                self.assertNotIn(w, low, f"{p.name} 含 {w}")

    def test_core_never_posts_to_threads(self):
        for p in (ROOT / "radar").rglob("*.py"):
            t = p.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"threads_publish(?!er)", t), p.name)
            self.assertNotIn("reply_to_id", t, p.name)

    def test_cli_runs(self):
        for args in (["brand", "check"], ["brand", "presets"], ["plugin", "list"], ["--help"]):
            r = subprocess.run([sys.executable, "-m", "radar", *args], cwd=ROOT, capture_output=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))

    def test_docs_links(self):
        """README 和 docs 裡的相對連結都要指到存在的檔案。"""
        bad = []
        for md in [ROOT / "README.md", *(ROOT / "docs").glob("*.md"), ROOT / "skill" / "SKILL.md"]:
            for link in re.findall(r"\]\(([^)#\s]+)", md.read_text(encoding="utf-8")):
                if link.startswith(("http", "mailto")):
                    continue
                if not (md.parent / link).exists():
                    bad.append(f"{md.name} → {link}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
