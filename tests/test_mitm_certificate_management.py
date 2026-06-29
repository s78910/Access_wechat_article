from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.modules.proxy.certificate import (
    check_mitm_ca_certificate,
    delete_mitm_ca_certificates,
    install_mitm_ca_certificate,
    list_mitm_ca_certificates,
)


class FakeCertificateRunner:
    """模拟 PowerShell 证书查询和删除，避免单元测试改动真实系统证书。"""

    def __init__(self, query_payload: list[dict], delete_returncode: int = 0) -> None:
        self.query_payload = query_payload
        self.delete_returncode = delete_returncode
        self.commands: list[list[str]] = []

    def __call__(self, command, **_kwargs):
        self.commands.append(list(command))
        script = str(command[-1])
        if "Remove-Item" in script:
            return subprocess.CompletedProcess(command, self.delete_returncode, stdout="", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(self.query_payload, ensure_ascii=False),
            stderr="",
        )


class MitmCertificateManagementTest(unittest.TestCase):
    def test_check_mitm_ca_certificate_reports_current_confdir_thumbprint_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cert_path = Path(temp_dir) / "mitmproxy-ca-cert.cer"
            cert_path.write_text("fake cert", encoding="utf-8")

            def runner(command, **_kwargs):
                script = str(command[-1])
                self.assertIn("X509Certificate2", script)
                self.assertNotIn("Get-FileHash", script)
                if "X509Certificate2" in script:
                    payload = {
                        "currentCaPath": str(cert_path),
                        "currentCaThumbprint": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
                        "installedCertificates": [
                            {
                                "storePath": "Cert:\\CurrentUser\\Root",
                                "thumbprint": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
                                "subject": "O=mitmproxy, CN=mitmproxy",
                                "issuer": "O=mitmproxy, CN=mitmproxy",
                                "friendlyName": "mitmproxy",
                                "notBefore": "2026-06-12 21:32:31",
                                "notAfter": "2036-06-09 21:32:31",
                            }
                        ],
                    }
                    return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            payload = check_mitm_ca_certificate(
                platform_name="Windows",
                runner=runner,
                current_ca_cert_path=cert_path,
            )

        self.assertTrue(payload["installed"])
        self.assertEqual(payload["currentCaThumbprint"], "ABCDEF1234567890ABCDEF1234567890ABCDEF12")
        self.assertTrue(payload["currentCaTrusted"])

    def test_list_mitm_ca_certificates_returns_displayable_items(self) -> None:
        runner = FakeCertificateRunner(
            [
                {
                    "storePath": "Cert:\\CurrentUser\\Root",
                    "thumbprint": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
                    "subject": "O=mitmproxy, CN=mitmproxy",
                    "issuer": "O=mitmproxy, CN=mitmproxy",
                    "friendlyName": "mitmproxy",
                    "notBefore": "2026-06-12 21:32:31",
                    "notAfter": "2036-06-09 21:32:31",
                }
            ]
        )

        payload = list_mitm_ca_certificates(platform_name="Windows", runner=runner)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "found")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["certificates"][0]["storePath"], "Cert:\\CurrentUser\\Root")
        self.assertEqual(payload["certificates"][0]["thumbprint"], "ABCDEF1234567890ABCDEF1234567890ABCDEF12")

    def test_delete_mitm_ca_certificates_only_deletes_listed_mitm_certificates(self) -> None:
        runner = FakeCertificateRunner(
            [
                {
                    "storePath": "Cert:\\CurrentUser\\Root",
                    "thumbprint": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
                    "subject": "O=mitmproxy, CN=mitmproxy",
                    "issuer": "O=mitmproxy, CN=mitmproxy",
                    "friendlyName": "mitmproxy",
                    "notBefore": "2026-06-12 21:32:31",
                    "notAfter": "2036-06-09 21:32:31",
                }
            ]
        )

        payload = delete_mitm_ca_certificates(
            [
                "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
                "1111111111111111111111111111111111111111",
                "not-a-thumbprint",
            ],
            platform_name="Windows",
            runner=runner,
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["deletedCount"], 1)
        self.assertEqual(payload["skippedCount"], 2)
        self.assertEqual(payload["deleted"][0]["thumbprint"], "ABCDEF1234567890ABCDEF1234567890ABCDEF12")
        remove_commands = [command for command in runner.commands if "Remove-Item" in command[-1]]
        self.assertEqual(len(remove_commands), 1)
        self.assertIn("Cert:\\CurrentUser\\Root\\ABCDEF1234567890ABCDEF1234567890ABCDEF12", remove_commands[0][-1])

    def test_install_mitm_ca_certificate_imports_current_ca_to_current_user_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cert_path = Path(temp_dir) / "mitmproxy-ca-cert.cer"
            cert_path.write_text("fake cert", encoding="utf-8")
            calls: list[list[str]] = []

            def runner(command, **_kwargs):
                calls.append(list(command))
                script = str(command[-1])
                self.assertIn("Import-Certificate", script)
                self.assertIn("Cert:\\CurrentUser\\Root", script)
                self.assertIn(str(cert_path).replace("'", "''"), script)
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps(
                        {
                            "ok": True,
                            "storePath": "Cert:\\CurrentUser\\Root",
                            "thumbprint": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
                            "subject": "O=mitmproxy, CN=mitmproxy",
                        },
                        ensure_ascii=False,
                    ),
                    stderr="",
                )

            payload = install_mitm_ca_certificate(
                platform_name="Windows",
                runner=runner,
                current_ca_cert_path=cert_path,
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "installed")
        self.assertEqual(payload["storePath"], "Cert:\\CurrentUser\\Root")
        self.assertEqual(payload["thumbprint"], "ABCDEF1234567890ABCDEF1234567890ABCDEF12")
        self.assertEqual(len(calls), 1)

    def test_install_mitm_ca_certificate_reports_missing_ca_file(self) -> None:
        payload = install_mitm_ca_certificate(
            platform_name="Windows",
            current_ca_cert_path=Path("Z:/missing/mitmproxy-ca-cert.cer"),
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "missing-ca-file")
        self.assertIn("未找到", payload["message"])


if __name__ == "__main__":
    unittest.main()
