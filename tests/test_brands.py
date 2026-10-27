"""品牌設定檔：所有產業範本都要合法，而且都能從假資料找到至少一則潛在客人。"""
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from helpers import ROOT, cleanup, temp_settings
from radar import brands, pipeline

PRESETS = ["local_service", "restaurant", "beauty", "education", "real_estate"]


class TestBrands(unittest.TestCase):
    def test_presets_exist_and_valid(self):
        self.assertEqual(sorted(brands.list_presets(ROOT / "brands")), sorted(PRESETS))
        for p in PRESETS:
            b = brands.load_file(ROOT / "brands" / "_presets" / f"{p}.yaml")
            self.assertTrue(b["triggers"])

    def test_validation_errors(self):
        errs = brands.validate({"key": "Bad Key", "display_name": "", "keywords": [], "triggers": [
            {"id": "a", "match_any": [], "templates": []}, {"id": "a", "match_any": ["x"], "templates": ["y"]}]})
        text = "\n".join(errs)
        for word in ("key", "display_name", "keywords", "重複", "match_any", "templates"):
            self.assertIn(word, text)

    def test_create_from_preset(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(ROOT / "brands" / "_presets", tmp / "_presets")
            p = brands.create_from_preset(tmp, "my-shop", "beauty", "小美工作室", "@my_shop")
            b = brands.load_file(p)
            self.assertEqual((b["key"], b["display_name"], b["handle"]), ("my-shop", "小美工作室", "my_shop"))
            with self.assertRaises(brands.BrandError):
                brands.create_from_preset(tmp, "my-shop", "beauty", "x")  # 不覆蓋
            with self.assertRaises(brands.BrandError):
                brands.create_from_preset(tmp, "x2", "nope", "x")
            # 停用的品牌不載入
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
            raw["enabled"] = False
            p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
            self.assertEqual(brands.load_all(tmp), {})
            self.assertIn("my-shop", brands.load_all(tmp, enabled_only=False))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_every_preset_finds_a_lead_in_demo_posts(self):
        """百工百業：每個產業範本套到假資料，都要產出至少一則草稿。"""
        for preset in PRESETS:
            with self.subTest(preset=preset):
                tmp = Path(tempfile.mkdtemp())
                s = temp_settings(brands_dir=str(tmp))
                try:
                    shutil.copytree(ROOT / "brands" / "_presets", tmp / "_presets")
                    brands.create_from_preset(tmp, "tt", preset, "測試")
                    stats = pipeline.run_once(s)
                    self.assertGreaterEqual(len(stats[0]["drafts"]), 1, stats)
                finally:
                    cleanup(s)
                    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
