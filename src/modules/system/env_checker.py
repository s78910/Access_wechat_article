from __future__ import annotations

import os
import platform
import sys
from importlib import metadata
from pathlib import Path

from src.app.pywebview_app.config import APP_NAME
from src.config.runtime_config import load_runtime_config


def _read_package_version(package_name: str) -> str:
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return "未安装"
    except Exception:
        return "未知"


def _build_system_label(system_name: str, system_release: str, machine: str = "") -> str:
    """Build the short OS label shown in the runtime environment card."""
    return " ".join(part for part in (system_name, system_release) if part).strip()


def get_system_status() -> dict:
    """Return lightweight local runtime status for diagnostics."""
    system_name = platform.system()
    system_release = platform.release()
    machine = platform.machine()
    runtime_config = load_runtime_config()

    return {
        "platform": platform.platform(),
        "system": system_name,
        "release": system_release,
        "systemLabel": _build_system_label(system_name, system_release, machine),
        "pythonVersion": platform.python_version(),
        "pythonExecutable": sys.executable,
        "appName": APP_NAME,
        "appVersion": runtime_config.app.version,
        "mitmproxyVersion": _read_package_version("mitmproxy"),
        "playwrightVersion": _read_package_version("playwright"),
        "pywebviewVersion": _read_package_version("pywebview"),
        "cwd": str(Path.cwd()),
        "pid": os.getpid(),
    }
