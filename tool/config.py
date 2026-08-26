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
    sim_mode: bool = True  # 默认模拟模式：开发机/无 SecureCRT 环境首次打开即可试用


def load(path: Path) -> AppConfig:
    try:
        if not path.exists():
            return AppConfig()
        data = json.loads(path.read_text(encoding="utf-8"))
        cfg = AppConfig()
        cfg.securecrt_path = str(data.get("securecrt_path", cfg.securecrt_path))
        cfg.excel_path = str(data.get("excel_path", cfg.excel_path))
        cfg.command = str(data.get("command", cfg.command))
        cfg.timeout = int(data.get("timeout", cfg.timeout))
        cfg.concurrency = int(data.get("concurrency", cfg.concurrency))
        cfg.sim_mode = bool(data.get("sim_mode", cfg.sim_mode))
        cfg.servers = [
            Server(s[0], s[1], s[2], s[3])
            for s in data.get("servers", [])
            if isinstance(s, list) and len(s) == 4
        ]
        return cfg
    except Exception:
        return AppConfig()


def save(path: Path, cfg: AppConfig) -> None:
    data = asdict(cfg)
    data["servers"] = [[s.ip, s.hostname, s.username, s.password] for s in cfg.servers]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
