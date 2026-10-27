import copy
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from radar.config import DEFAULTS  # noqa: E402


def temp_settings(**over):
    """每個測試自己的資料夾，不碰 repo 的 data/。"""
    tmp = Path(tempfile.mkdtemp(prefix="radar_test_"))
    s = copy.deepcopy(DEFAULTS)
    s["data_dir"] = str(tmp / "data")
    s["brands_dir"] = str(ROOT / "brands")
    s["source"]["file"]["paths"] = [str(ROOT / "fixtures" / "demo_posts.jsonl")]
    for k, v in over.items():
        s[k] = v
    s["_tmp"] = tmp
    return s


def cleanup(s):
    shutil.rmtree(s["_tmp"], ignore_errors=True)


class FakeResp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(payload, calls):
    def _open(req, timeout=None):
        calls.append(req)
        return FakeResp(json.dumps(payload).encode("utf-8"))
    return _open
