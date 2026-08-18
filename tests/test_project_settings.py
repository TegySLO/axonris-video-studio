import os
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import project_settings as ps


class TestProjectSettings(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_load_settings_returns_defaults_when_none_exist(self):
        settings = ps.load_settings(self._tmp)
        self.assertEqual(settings["template_id"], None)
        self.assertEqual(settings["zoom_style"], "moderate")
        self.assertEqual(settings["use_trimmer"], False)

    def test_save_then_load_roundtrip(self):
        ps.save_settings(self._tmp, {"template_id": "concept-explainer-short", "zoom_style": "aggressive"})
        loaded = ps.load_settings(self._tmp)
        self.assertEqual(loaded["template_id"], "concept-explainer-short")
        self.assertEqual(loaded["zoom_style"], "aggressive")

    def test_settings_live_under_axonris_folder(self):
        ps.save_settings(self._tmp, {"template_id": "product-demo"})
        self.assertTrue(os.path.exists(os.path.join(self._tmp, ".axonris", "video_studio_settings.json")))

    def test_list_templates_returns_registry_contents(self):
        templates = ps.list_templates()
        ids = [t["id"] for t in templates]
        self.assertIn("concept-explainer-short", ids)
        self.assertIn("product-demo", ids)
