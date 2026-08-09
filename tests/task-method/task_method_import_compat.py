from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TASK_METHOD_DIR = Path(__file__).resolve().parent
for candidate in (PROJECT_ROOT, TASK_METHOD_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def import_task_method_module(file_name: str) -> ModuleType:
    """加载 tests/task-method 下的脚本；目录名带连字符，不能直接包导入。"""
    module_path = TASK_METHOD_DIR / file_name
    module_name = f"task_method_{module_path.stem}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载任务脚本：{module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
