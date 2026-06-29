from __future__ import annotations

import unittest
from unittest.mock import patch

from src.modules.system import env_checker


class SystemStatusTest(unittest.TestCase):
    def test_system_status_reports_playwright_version_from_installed_package(self) -> None:
        def fake_version(package_name: str) -> str:
            if package_name == "playwright":
                return "1.57.0"
            if package_name == "mitmproxy":
                return "12.2.3"
            if package_name == "pywebview":
                return "6.2.1"
            raise env_checker.metadata.PackageNotFoundError(package_name)

        with patch.object(env_checker.metadata, "version", side_effect=fake_version):
            status = env_checker.get_system_status()

        self.assertEqual(status["playwrightVersion"], "1.57.0")
        self.assertEqual(status["mitmproxyVersion"], "12.2.3")
        self.assertEqual(status["pywebviewVersion"], "6.2.1")


if __name__ == "__main__":
    unittest.main()
