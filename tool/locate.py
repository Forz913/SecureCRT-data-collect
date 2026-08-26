"""查找 SecureCRT.exe：常见安装路径 + 注册表。"""
from __future__ import annotations

import os

CANDIDATES = [
    r"C:\Program Files\VanDyke Software\Clients\SecureCRT.exe",
    r"C:\Program Files (x86)\VanDyke Software\Clients\SecureCRT.exe",
]


def find_securecrt(exists=os.path.exists, registry_lookup=None) -> str:
    if registry_lookup is None:
        registry_lookup = _registry_lookup
    for c in CANDIDATES:
        if exists(c):
            return c
    base = registry_lookup()
    if base:
        p = os.path.join(base, "SecureCRT.exe")
        if exists(p):
            return p
    return ""


def _registry_lookup() -> str:
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\VanDyke Software\Clients\SecureCRT") as k:
                    for name in ("Install Path", "Path", ""):
                        try:
                            val, _ = winreg.QueryValueEx(k, name)
                            if val:
                                return str(val)
                        except OSError:
                            continue
            except OSError:
                continue
    except Exception:
        pass
    return ""
