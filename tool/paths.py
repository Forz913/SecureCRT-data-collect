"""路径工具：兼容 PyInstaller 冻结环境。"""
from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """程序数据目录：冻结时为 exe 所在目录，开发时为项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def resource_path(rel: str) -> str:
    """只读资源路径：冻结时在 PyInstaller 解包目录，开发时为项目根目录。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))
    return str(base / rel)
