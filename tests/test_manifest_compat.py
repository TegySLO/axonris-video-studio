import json
import os
import unittest

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

_MANIFEST_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "manifest.json")


def _is_compatible(manifest: dict, hub_version: str) -> bool:
    """Local copy of axonris-hub/module_manifest.py's is_compatible() contract --
    this repo is public and standalone, so it can't import the private Hub repo;
    this shim exists only to prove our own manifest.json parses under the exact
    same real logic Hub uses, not to reimplement Hub itself."""
    range_str = manifest.get("engines", {}).get("axonris_hub")
    if not range_str:
        return True
    try:
        specifier = SpecifierSet(range_str)
    except InvalidSpecifier:
        return False
    return Version(hub_version) in specifier


class TestManifestCompat(unittest.TestCase):

    def setUp(self):
        with open(_MANIFEST_PATH, encoding="utf-8") as f:
            self.manifest = json.load(f)

    def test_manifest_has_required_fields(self):
        for field in ("id", "version", "entry_exe", "engines", "publisher", "description"):
            self.assertIn(field, self.manifest)

    def test_manifest_id_matches_repo_name(self):
        self.assertEqual(self.manifest["id"], "axonris-video-studio")

    def test_engines_field_is_valid_pep440(self):
        # Same failure mode Hub itself guards against (I4, module_manifest.py) --
        # an npm-style "engines" string would silently make this module always
        # report incompatible rather than crashing Hub's module list.
        self.assertTrue(_is_compatible(self.manifest, "1.0.0"))

    def test_incompatible_with_far_future_hub_requirement(self):
        bad_manifest = dict(self.manifest, engines={"axonris_hub": ">=99.0.0"})
        self.assertFalse(_is_compatible(bad_manifest, "1.0.0"))
