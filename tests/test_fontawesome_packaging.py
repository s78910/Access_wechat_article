from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VUE_PROJECT_ROOT = PROJECT_ROOT / "vue-project"


class FontAwesomePackagingTest(unittest.TestCase):
    def test_vue_entry_does_not_load_full_fontawesome_css(self) -> None:
        html = (VUE_PROJECT_ROOT / "index.html").read_text(encoding="utf-8")

        self.assertNotIn("fontawesome-free-6.4.0-web/css/all.min.css", html)
        self.assertNotIn("vendor/fontawesome", html)

    def test_fontawesome_full_package_is_kept_outside_vite_public_dir(self) -> None:
        public_vendor = VUE_PROJECT_ROOT / "public" / "vendor"
        offline_vendor = VUE_PROJECT_ROOT / "vendor" / "fontawesome-free-6.4.0-web"

        self.assertFalse(public_vendor.exists())
        self.assertTrue((offline_vendor / "svgs").is_dir())
        self.assertTrue((offline_vendor / "LICENSE.txt").is_file())

    def test_built_webview_does_not_keep_stale_full_fontawesome_package(self) -> None:
        built_vendor = PROJECT_ROOT / "src" / "webview" / "vendor" / "fontawesome"

        self.assertFalse(built_vendor.exists())

    def test_vue_source_no_longer_uses_fontawesome_css_entrypoints(self) -> None:
        source_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (VUE_PROJECT_ROOT / "src").rglob("*")
            if path.suffix in {".vue", ".ts"}
        )

        self.assertIsNone(re.search(r"<i(?:\s|>)", source_text))
        self.assertNotIn('prefix-icon="fa-', source_text)

    def test_all_used_fontawesome_icons_are_copied_into_lightweight_registry(self) -> None:
        used_icons: set[str] = set()
        for path in (VUE_PROJECT_ROOT / "src").rglob("*"):
            if path.suffix not in {".vue", ".ts"}:
                continue
            if path.name == "fontAwesomeIcons.ts":
                continue
            text = path.read_text(encoding="utf-8")
            used_icons.update(re.findall(r"fa-(?:solid|regular|brands)\s+fa-[\w-]+", text))

        registry_text = (VUE_PROJECT_ROOT / "src" / "icons" / "fontAwesomeIcons.ts").read_text(encoding="utf-8")
        missing_icons = sorted(icon for icon in used_icons if f"'{icon}'" not in registry_text)

        self.assertEqual([], missing_icons)


if __name__ == "__main__":
    unittest.main()
