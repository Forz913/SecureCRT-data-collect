"""config.json 读写：界面状态持久化。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tool.taskfiles import Server

@dataclass
class AppConfig:
    securecrt_path: str = ""
    excel_path: str = ""
    servers: list[Server] = field(default_factory=list)
    command: str = "disp alarm hardware"
    timeout: int = 60
    concurrency: int = 5
    sim_mode: bool = False  # 默认真实模式，开发机测试需手动勾选模拟


def _get_str(data: dict, key: str, default: str) -> str:
    try:
        return str(data.get(key, default))
    except Exception:
        return default


def _get_int(data: dict, key: str, default: int) -> int:
    try:
        return int(data.get(key, default))
    except (TypeError, ValueError):
        return default


def _get_bool(data: dict, key: str, default: bool) -> bool:
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return default


def load(path: Path) -> AppConfig:
    try:
        if not path.exists():
            return AppConfig()
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return AppConfig()
    if not isinstance(data, dict):
        return AppConfig()
    cfg = AppConfig()
    cfg.securecrt_path = _get_str(data, "securecrt_path", cfg.securecrt_path)
    cfg.excel_path = _get_str(data, "excel_path", cfg.excel_path)
    cfg.command = _get_str(data, "command", cfg.command)
    cfg.timeout = _get_int(data, "timeout", cfg.timeout)
    cfg.concurrency = _get_int(data, "concurrency", cfg.concurrency)
    cfg.sim_mode = _get_bool(data, "sim_mode", cfg.sim_mode)
    cfg.servers = [
        Server(s[0], s[1], s[2], s[3])
        for s in data.get("servers", [])
        if isinstance(s, list) and len(s) == 4 and all(isinstance(x, str) for x in s)
    ]
    return cfg


def save(path: Path, cfg: AppConfig) -> None:
    data = asdict(cfg)
    data["servers"] = [[s.ip, s.hostname, s.username, s.password] for s in cfg.servers]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
