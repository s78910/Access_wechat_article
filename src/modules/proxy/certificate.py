from __future__ import annotations

import json
import platform
import re
import subprocess
from pathlib import Path
from typing import Callable, Sequence

from src.core.config import MITMPROXY_CONF_DIR


CertificateRunner = Callable[..., subprocess.CompletedProcess[str]]
MITM_CERTIFICATE_STORES = (
    "Cert:\\CurrentUser\\Root",
    "Cert:\\CurrentUser\\CA",
    "Cert:\\CurrentUser\\My",
    "Cert:\\LocalMachine\\Root",
    "Cert:\\LocalMachine\\CA",
    "Cert:\\LocalMachine\\My",
)
CURRENT_USER_ROOT_STORE = "Cert:\\CurrentUser\\Root"
THUMBPRINT_PATTERN = re.compile(r"^[A-Fa-f0-9]{40}$")


def check_mitm_ca_certificate(
    platform_name: str | None = None,
    runner: CertificateRunner | None = None,
    timeout_seconds: int = 6,
    current_ca_cert_path: str | Path | None = None,
) -> dict:
    """检测本机是否已经信任 mitmproxy 的 CA 根证书。"""
    current_platform = platform_name or platform.system()
    if current_platform != "Windows":
        return {
            "ok": False,
            "status": "unknown",
            "installed": False,
            "label": "无法检测",
            "message": "当前仅支持在 Windows 本机证书库中检测 mitmproxy CA 证书。",
        }

    current_ca_path = Path(current_ca_cert_path) if current_ca_cert_path else MITMPROXY_CONF_DIR / "mitmproxy-ca-cert.cer"
    command = _build_windows_ca_query_command(current_ca_path)
    run_command = runner or subprocess.run

    try:
        completed = run_command(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except Exception as exc:
        return _unknown_result(f"检测 CA 证书失败：{exc}")

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        message = f"检测 CA 证书失败：{detail}" if detail else "检测 CA 证书失败。"
        return _unknown_result(message)

    diagnostics = _parse_ca_check_output(completed.stdout)
    installed_certificates = diagnostics.get("installedCertificates")
    if not isinstance(installed_certificates, list):
        installed_certificates = []
    current_thumbprint = str(diagnostics.get("currentCaThumbprint") or "").upper()
    current_trusted = bool(
        current_thumbprint
        and any(
            str(item.get("thumbprint") or "").upper() == current_thumbprint
            for item in installed_certificates
            if isinstance(item, dict)
        )
    )

    if installed_certificates:
        return {
            "ok": True,
            "status": "installed",
            "installed": current_trusted,
            "label": "已安装" if current_trusted else "证书不匹配",
            "message": (
                "当前项目 mitmproxy CA 已在本机证书库中找到。"
                if current_trusted
                else "本机存在 mitmproxy CA，但不是当前项目 confdir 使用的那一张。"
            ),
            "subject": str(installed_certificates[0].get("subject") or ""),
            "currentCaPath": str(diagnostics.get("currentCaPath") or current_ca_path),
            "currentCaThumbprint": current_thumbprint,
            "currentCaTrusted": current_trusted,
            "installedCertificates": installed_certificates,
        }

    return {
        "ok": True,
        "status": "missing",
        "installed": False,
        "label": "未安装",
        "message": "未在本机证书库中找到 mitmproxy CA 证书。",
        "currentCaPath": str(current_ca_path),
        "currentCaThumbprint": current_thumbprint,
        "currentCaTrusted": False,
        "installedCertificates": [],
    }


def list_mitm_ca_certificates(
    platform_name: str | None = None,
    runner: CertificateRunner | None = None,
    timeout_seconds: int = 8,
) -> dict:
    """列出 Windows 证书库中所有 mitmproxy 相关证书，供前端确认后删除。"""
    current_platform = platform_name or platform.system()
    if current_platform != "Windows":
        return {
            "ok": False,
            "status": "unknown",
            "count": 0,
            "certificates": [],
            "message": "当前仅支持在 Windows 本机证书库中检索 mitmproxy CA 证书。",
        }

    command = _build_windows_ca_list_command()
    run_command = runner or subprocess.run

    try:
        completed = run_command(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except Exception as exc:
        return _certificate_operation_failed(f"检索 MITM 证书失败：{exc}", status="query-failed")

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return _certificate_operation_failed(
            f"检索 MITM 证书失败：{detail}" if detail else "检索 MITM 证书失败。",
            status="query-failed",
        )

    certificates = _parse_certificate_list_output(completed.stdout)
    return {
        "ok": True,
        "status": "found" if certificates else "empty",
        "count": len(certificates),
        "certificates": certificates,
        "message": (
            f"已检索到 {len(certificates)} 张 mitmproxy 相关证书。"
            if certificates
            else "未检索到 mitmproxy 相关证书。"
        ),
    }


def install_mitm_ca_certificate(
    platform_name: str | None = None,
    runner: CertificateRunner | None = None,
    timeout_seconds: int = 12,
    current_ca_cert_path: str | Path | None = None,
) -> dict:
    """把当前项目 mitmproxy CA 安装到当前用户根证书库。"""
    current_platform = platform_name or platform.system()
    if current_platform != "Windows":
        return {
            "ok": False,
            "status": "unsupported-platform",
            "installed": False,
            "label": "无法安装",
            "message": "当前仅支持在 Windows 当前用户证书库中安装 mitmproxy CA 证书。",
        }

    current_ca_path = Path(current_ca_cert_path) if current_ca_cert_path else MITMPROXY_CONF_DIR / "mitmproxy-ca-cert.cer"
    if not current_ca_path.exists():
        return {
            "ok": False,
            "status": "missing-ca-file",
            "installed": False,
            "label": "未找到证书",
            "message": f"未找到 mitmproxy CA 证书文件：{current_ca_path}。请先启动 MITM 代理生成证书。",
            "currentCaPath": str(current_ca_path),
        }

    command = _build_windows_ca_install_command(current_ca_path)
    run_command = runner or subprocess.run

    try:
        completed = run_command(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except Exception as exc:
        return _install_failed_result(f"安装 CA 证书失败：{exc}", current_ca_path)

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return _install_failed_result(
            f"安装 CA 证书失败：{detail}" if detail else "安装 CA 证书失败。",
            current_ca_path,
        )

    diagnostics = _parse_ca_check_output(completed.stdout)
    if not diagnostics.get("ok"):
        return _install_failed_result(
            str(diagnostics.get("message") or "安装 CA 证书后未能确认信任状态。"),
            current_ca_path,
        )

    thumbprint = str(diagnostics.get("thumbprint") or "").upper()
    return {
        "ok": True,
        "status": "installed",
        "installed": True,
        "label": "已安装",
        "message": "当前项目 mitmproxy CA 已安装到当前用户根证书库。",
        "storePath": str(diagnostics.get("storePath") or CURRENT_USER_ROOT_STORE),
        "currentCaPath": str(diagnostics.get("currentCaPath") or current_ca_path),
        "thumbprint": thumbprint,
        "currentCaThumbprint": thumbprint,
        "currentCaTrusted": True,
        "subject": str(diagnostics.get("subject") or ""),
        "issuer": str(diagnostics.get("issuer") or ""),
        "friendlyName": str(diagnostics.get("friendlyName") or ""),
        "notBefore": str(diagnostics.get("notBefore") or ""),
        "notAfter": str(diagnostics.get("notAfter") or ""),
    }


def delete_mitm_ca_certificates(
    thumbprints: list[str] | tuple[str, ...],
    platform_name: str | None = None,
    runner: CertificateRunner | None = None,
    timeout_seconds: int = 8,
) -> dict:
    """按指纹删除 mitmproxy 相关证书；删除前会重新扫描并校验证书来源。"""
    current_platform = platform_name or platform.system()
    if current_platform != "Windows":
        return {
            "ok": False,
            "status": "unknown",
            "deletedCount": 0,
            "skippedCount": 0,
            "deleted": [],
            "skipped": [],
            "message": "当前仅支持在 Windows 本机证书库中删除 mitmproxy CA 证书。",
        }

    requested = _normalize_thumbprints(thumbprints)
    invalid = [
        {"thumbprint": str(item or ""), "reason": "指纹格式无效"}
        for item in thumbprints
        if str(item or "").strip().upper() not in requested
    ]
    if not requested:
        return {
            "ok": False,
            "status": "empty-selection",
            "deletedCount": 0,
            "skippedCount": len(invalid),
            "deleted": [],
            "skipped": invalid,
            "message": "未选择可删除的 MITM 证书。",
        }

    run_command = runner or subprocess.run
    listed = list_mitm_ca_certificates(
        platform_name=current_platform,
        runner=run_command,
        timeout_seconds=timeout_seconds,
    )
    available = {
        str(item.get("thumbprint") or "").upper(): item
        for item in listed.get("certificates", [])
        if isinstance(item, dict)
    }

    deleted: list[dict] = []
    skipped: list[dict] = list(invalid)
    for thumbprint in requested:
        certificate = available.get(thumbprint)
        if not certificate:
            skipped.append({"thumbprint": thumbprint, "reason": "未在 mitmproxy 证书列表中找到，已跳过"})
            continue

        store_path = str(certificate.get("storePath") or "")
        if store_path not in MITM_CERTIFICATE_STORES:
            skipped.append({"thumbprint": thumbprint, "reason": "证书存储位置不在允许删除范围，已跳过"})
            continue

        command = _build_windows_ca_delete_command(store_path, thumbprint)
        try:
            completed = run_command(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except Exception as exc:
            skipped.append({"thumbprint": thumbprint, "reason": f"删除失败：{exc}"})
            continue

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            skipped.append({"thumbprint": thumbprint, "reason": detail or "删除失败"})
            continue

        deleted.append(certificate)

    return {
        "ok": len(deleted) > 0,
        "status": "deleted" if deleted and not skipped else ("partial" if deleted else "delete-failed"),
        "deletedCount": len(deleted),
        "skippedCount": len(skipped),
        "deleted": deleted,
        "skipped": skipped,
        "message": _build_delete_message(len(deleted), len(skipped)),
    }


def _build_windows_ca_query_command(current_ca_cert_path: Path) -> Sequence[str]:
    # 只读查询当前用户和本机根证书库，同时比对当前 confdir 里的 CA 指纹。
    safe_cert_path = str(current_ca_cert_path).replace("'", "''")
    script = (
        f"$currentCaPath = '{safe_cert_path}'; "
        "$currentThumbprint = ''; "
        "if (Test-Path -LiteralPath $currentCaPath) { "
        "$currentThumbprint = ([System.Security.Cryptography.X509Certificates.X509Certificate2]::new($currentCaPath)).Thumbprint.ToUpper(); "
        "} "
        "$stores = @('Cert:\\CurrentUser\\Root', 'Cert:\\LocalMachine\\Root'); "
        "$items = Get-ChildItem -Path $stores -ErrorAction SilentlyContinue | "
        "Where-Object { "
        "$_.Subject -match 'mitmproxy' -or "
        "$_.Issuer -match 'mitmproxy' -or "
        "$_.FriendlyName -match 'mitmproxy' "
        "} | ForEach-Object { "
        "[PSCustomObject]@{ "
        "storePath = $_.PSParentPath -replace '^.*Certificate::', 'Cert:'; "
        "thumbprint = $_.Thumbprint; "
        "subject = $_.Subject; "
        "issuer = $_.Issuer; "
        "friendlyName = $_.FriendlyName; "
        "notBefore = $_.NotBefore.ToString('yyyy-MM-dd HH:mm:ss'); "
        "notAfter = $_.NotAfter.ToString('yyyy-MM-dd HH:mm:ss') "
        "} "
        "}; "
        "[PSCustomObject]@{ "
        "currentCaPath = $currentCaPath; "
        "currentCaThumbprint = $currentThumbprint; "
        "installedCertificates = @($items) "
        "} | ConvertTo-Json -Depth 5"
    )
    return ["powershell", "-NoProfile", "-Command", script]


def _parse_ca_check_output(output: str) -> dict:
    text = str(output or "").strip()
    if not text:
        return {}
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {"installedCertificates": [{"subject": text}]}
    return loaded if isinstance(loaded, dict) else {}


def _build_windows_ca_list_command() -> Sequence[str]:
    stores = "@(" + ", ".join(f"'{item}'" for item in MITM_CERTIFICATE_STORES) + ")"
    script = (
        f"$stores = {stores}; "
        "$items = foreach ($store in $stores) { "
        "Get-ChildItem -Path $store -ErrorAction SilentlyContinue | "
        "Where-Object { "
        "$_.Subject -match 'mitmproxy' -or "
        "$_.Issuer -match 'mitmproxy' -or "
        "$_.FriendlyName -match 'mitmproxy' "
        "} | ForEach-Object { "
        "[PSCustomObject]@{ "
        "storePath = $store; "
        "thumbprint = $_.Thumbprint; "
        "subject = $_.Subject; "
        "issuer = $_.Issuer; "
        "friendlyName = $_.FriendlyName; "
        "notBefore = $_.NotBefore.ToString('yyyy-MM-dd HH:mm:ss'); "
        "notAfter = $_.NotAfter.ToString('yyyy-MM-dd HH:mm:ss') "
        "} "
        "} "
        "}; "
        "$items | Sort-Object notBefore -Descending | ConvertTo-Json -Depth 4"
    )
    return ["powershell", "-NoProfile", "-Command", script]


def _build_windows_ca_install_command(current_ca_cert_path: Path) -> Sequence[str]:
    # 安装到当前用户根证书库，通常不需要管理员权限；安装后按当前 CA 指纹复查。
    safe_cert_path = str(current_ca_cert_path).replace("'", "''")
    script = (
        f"$currentCaPath = '{safe_cert_path}'; "
        f"$storePath = '{CURRENT_USER_ROOT_STORE}'; "
        "if (-not (Test-Path -LiteralPath $currentCaPath)) { "
        "throw \"未找到 mitmproxy CA 证书文件：$currentCaPath\" "
        "} "
        "$currentCert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($currentCaPath); "
        "Import-Certificate -FilePath $currentCaPath -CertStoreLocation $storePath -ErrorAction Stop | Out-Null; "
        "$trusted = Get-ChildItem -Path $storePath -ErrorAction Stop | "
        "Where-Object { $_.Thumbprint -eq $currentCert.Thumbprint } | Select-Object -First 1; "
        "if (-not $trusted) { "
        "throw \"证书导入后未在当前用户根证书库中找到：$($currentCert.Thumbprint)\" "
        "} "
        "[PSCustomObject]@{ "
        "ok = $true; "
        "storePath = $storePath; "
        "currentCaPath = $currentCaPath; "
        "thumbprint = $trusted.Thumbprint; "
        "subject = $trusted.Subject; "
        "issuer = $trusted.Issuer; "
        "friendlyName = $trusted.FriendlyName; "
        "notBefore = $trusted.NotBefore.ToString('yyyy-MM-dd HH:mm:ss'); "
        "notAfter = $trusted.NotAfter.ToString('yyyy-MM-dd HH:mm:ss') "
        "} | ConvertTo-Json -Depth 4"
    )
    return ["powershell", "-NoProfile", "-Command", script]


def _build_windows_ca_delete_command(store_path: str, thumbprint: str) -> Sequence[str]:
    safe_store_path = str(store_path).replace("'", "''")
    safe_thumbprint = str(thumbprint).upper()
    script = f"Remove-Item -LiteralPath '{safe_store_path}\\{safe_thumbprint}' -Force"
    return ["powershell", "-NoProfile", "-Command", script]


def _parse_certificate_list_output(output: str) -> list[dict]:
    text = str(output or "").strip()
    if not text:
        return []

    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return []

    raw_items = loaded if isinstance(loaded, list) else [loaded]
    certificates: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        certificate = {
            "storePath": str(raw_item.get("storePath") or ""),
            "thumbprint": str(raw_item.get("thumbprint") or "").upper(),
            "subject": str(raw_item.get("subject") or ""),
            "issuer": str(raw_item.get("issuer") or ""),
            "friendlyName": str(raw_item.get("friendlyName") or ""),
            "notBefore": str(raw_item.get("notBefore") or ""),
            "notAfter": str(raw_item.get("notAfter") or ""),
        }
        if not certificate["storePath"] or not THUMBPRINT_PATTERN.fullmatch(certificate["thumbprint"]):
            continue
        dedupe_key = (certificate["storePath"], certificate["thumbprint"])
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        certificates.append(certificate)
    return certificates


def _normalize_thumbprints(thumbprints: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    for item in thumbprints or []:
        value = str(item or "").strip().upper()
        if not THUMBPRINT_PATTERN.fullmatch(value) or value in result:
            continue
        result.append(value)
    return result


def _certificate_operation_failed(message: str, *, status: str) -> dict:
    return {
        "ok": False,
        "status": status,
        "count": 0,
        "certificates": [],
        "message": message,
    }


def _install_failed_result(message: str, current_ca_path: Path) -> dict:
    return {
        "ok": False,
        "status": "install-failed",
        "installed": False,
        "label": "安装失败",
        "message": message,
        "currentCaPath": str(current_ca_path),
    }


def _build_delete_message(deleted_count: int, skipped_count: int) -> str:
    if deleted_count and not skipped_count:
        return f"已删除 {deleted_count} 张 MITM 证书。"
    if deleted_count and skipped_count:
        return f"已删除 {deleted_count} 张 MITM 证书，{skipped_count} 张未删除。"
    if skipped_count:
        return f"未删除 MITM 证书，{skipped_count} 张被跳过。"
    return "未删除 MITM 证书。"


def _unknown_result(message: str) -> dict:
    return {
        "ok": False,
        "status": "unknown",
        "installed": False,
        "label": "无法检测",
        "message": message,
    }
