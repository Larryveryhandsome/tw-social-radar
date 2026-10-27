"""可抽換的 LLM：mock（示範／測試，不連網）、claude_cli、claude_api、ollama。

每個 provider 只要實作 complete(prompt, system="") -> str。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..config import no_window_flags


class LLMError(RuntimeError):
    pass


RETRY_STATUS = {429, 500, 502, 503, 504, 529}  # 限流、伺服器忙：稍等再試


def _post_json(url: str, body: dict, headers: dict, timeout: int, retries: int = 2) -> dict:
    data = json.dumps(body).encode("utf-8")
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers={"content-type": "application/json", **headers},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in RETRY_STATUS and attempt < retries:
                wait = e.headers.get("retry-after") if e.headers else None
                try:
                    secs = min(30.0, float(wait)) if wait else 2 ** (attempt + 1)
                except ValueError:
                    secs = 2 ** (attempt + 1)
                time.sleep(secs)
                continue
            raise LLMError(f"HTTP {e.code}：{detail}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise LLMError(f"連不上 {url}：{getattr(e, 'reason', e)}") from None
        except ValueError:
            raise LLMError("回應不是 JSON") from None
    raise LLMError("重試後仍失敗")


class MockLLM:
    """不連網、結果固定。拿來跑示範和測試；正式使用請換其他 provider。"""
    name = "mock"

    def complete(self, prompt: str, system: str = "") -> str:
        if '"is_demand"' in prompt:
            from ..intent import rule_score
            body = prompt.split("<post>")[-1].split("</post>")[0]
            s = rule_score(body)
            return json.dumps({"is_demand": s >= 3, "intent": s, "reason": "規則估計"}, ensure_ascii=False)
        return json.dumps({"reply": "（示範草稿）看到你在找這個～我們剛好有在做，有需要可以私訊聊聊 ☺️"},
                          ensure_ascii=False)


class ClaudeCLI:
    """用本機 Claude Code CLI（`claude -p`）。有 Claude 訂閱就能用，不需 API 金鑰。

    ⚠️ 安全：貼文是陌生人寫的，可能藏「請讀取 .env」之類的指令（prompt injection）。
    所以一律關掉所有工具與 MCP（--tools "" --strict-mcp-config），並在一個空資料夾裡執行，
    讓 Claude 只能「回文字」，碰不到你的檔案、指令列或其他連線服務。
    """
    name = "claude_cli"
    SAFE_FLAGS = ["--tools", "", "--strict-mcp-config"]
    # 舊版 Claude Code 沒有 --tools 時的退路：明確禁止所有內建工具
    LEGACY_FLAGS = ["--disallowedTools", "Bash", "Edit", "Write", "Read", "Glob", "Grep", "WebFetch", "WebSearch",
                    "NotebookEdit", "Task", "--strict-mcp-config"]

    def __init__(self, model: str = "", bin_path: str = "", timeout: int = 90):
        self.model, self.timeout = model, timeout
        self.bin = bin_path or next((p for p in (shutil.which(n) for n in ("claude.cmd", "claude.exe", "claude")) if p), None)
        if not self.bin:
            raise LLMError("找不到 claude 指令；請先安裝 Claude Code，或改用其他 provider")

    @staticmethod
    def sandbox_dir() -> str:
        d = Path(tempfile.gettempdir()) / "tw-social-radar-llm-sandbox"
        d.mkdir(exist_ok=True)
        return str(d)

    def _run(self, full: str, flags: list):
        cmd = [self.bin, "-p", full, "--output-format", "text", *flags]
        if self.model:
            cmd += ["--model", self.model]
        try:
            return subprocess.run(cmd, capture_output=True, timeout=self.timeout, cwd=self.sandbox_dir(),
                                  creationflags=no_window_flags(),  # Windows 不跳黑色視窗
                                  stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise LLMError("claude CLI 逾時") from None

    def complete(self, prompt: str, system: str = "") -> str:
        full = f"{system}\n\n{prompt}" if system else prompt
        r = self._run(full, self.SAFE_FLAGS)
        err = r.stderr.decode("utf-8", "replace")
        if r.returncode != 0 and "--tools" in err:  # 舊版不認得 --tools
            r = self._run(full, self.LEGACY_FLAGS)
            err = r.stderr.decode("utf-8", "replace")
        if r.returncode != 0:
            raise LLMError(f"claude CLI 失敗（未登入或額度用完時請在終端機執行 claude 確認）：{err[:300]}")
        return r.stdout.decode("utf-8", "replace")


class ClaudeAPI:
    """Anthropic Messages API。金鑰放環境變數 ANTHROPIC_API_KEY。"""
    name = "claude_api"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, model: str, max_tokens: int = 400, timeout: int = 90):
        self.key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.key:
            raise LLMError("缺 ANTHROPIC_API_KEY（申請方式見 docs/金鑰申請.md）")
        self.model, self.max_tokens, self.timeout = model, max_tokens, timeout

    def complete(self, prompt: str, system: str = "") -> str:
        body = {"model": self.model, "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": prompt}]}
        if system:
            body["system"] = system
        d = _post_json(self.URL, body, {"x-api-key": self.key, "anthropic-version": "2023-06-01"}, self.timeout)
        return "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")


class Ollama:
    """本機開源模型（Ollama）。完全離線、免費，但中文品質看模型。"""
    name = "ollama"

    def __init__(self, host: str, model: str, timeout: int = 120):
        self.host, self.model, self.timeout = host.rstrip("/"), model, timeout

    def complete(self, prompt: str, system: str = "") -> str:
        body = {"model": self.model, "prompt": prompt, "stream": False}
        if system:
            body["system"] = system
        return _post_json(f"{self.host}/api/generate", body, {}, self.timeout).get("response", "")


def get_llm(settings: dict):
    cfg = settings.get("llm") or {}
    name = cfg.get("provider", "mock")
    t = int(cfg.get("timeout_seconds", 90))
    if name == "mock":
        return MockLLM()
    if name == "claude_cli":
        c = cfg.get("claude_cli") or {}
        return ClaudeCLI(c.get("model", ""), c.get("bin", ""), t)
    if name == "claude_api":
        c = cfg.get("claude_api") or {}
        return ClaudeAPI(c.get("model", "claude-haiku-5-5"), int(c.get("max_tokens", 400)), t)
    if name == "ollama":
        c = cfg.get("ollama") or {}
        return Ollama(c.get("host", "http://127.0.0.1:11434"), c.get("model", "qwen2.5:7b"), t)
    raise LLMError(f"不認得的 llm.provider：{name}（可用 mock / claude_cli / claude_api / ollama）")
