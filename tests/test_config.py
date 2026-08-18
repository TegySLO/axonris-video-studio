# tests/test_config.py
import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfigPersistence(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._patcher = patch.dict(os.environ, {"LOCALAPPDATA": self._tmp})
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_load_config_empty_dict_when_missing(self):
        import config
        self.assertEqual(config.load_config(), {})

    def test_save_then_load_roundtrip(self):
        import config
        config.save_config({"node_ok": True, "cloud_gpu_provider": "modal"})
        loaded = config.load_config()
        self.assertEqual(loaded["node_ok"], True)
        self.assertEqual(loaded["cloud_gpu_provider"], "modal")

    def test_save_config_merges_not_overwrites(self):
        import config
        config.save_config({"node_ok": True})
        config.save_config({"python_ok": True})
        loaded = config.load_config()
        self.assertTrue(loaded["node_ok"])
        self.assertTrue(loaded["python_ok"])

    def test_no_tmp_file_left_behind_after_save(self):
        import config
        config.save_config({"node_ok": True})
        config_dir = os.path.dirname(config.get_config_path())
        for name in os.listdir(config_dir):
            self.assertFalse(name.endswith(".tmp"))
