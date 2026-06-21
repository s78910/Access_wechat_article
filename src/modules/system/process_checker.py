from __future__ import annotations

import subprocess


def get_process_command_line(pid: int) -> str:
    """读取指定 Windows 进程命令行；读取失败时返回空字符串。"""
    try:
        safe_pid = int(pid)
    except (TypeError, ValueError):
        return ""
    if safe_pid <= 0:
        return ""

    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter \"ProcessId={safe_pid}\").CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except Exception:
        return ""

    return (completed.stdout or "").strip()


__all__ = ["get_process_command_line"]
