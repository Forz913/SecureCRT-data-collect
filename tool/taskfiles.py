"""服务器清单解析与结果文件读取。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class Server:
    ip: str
    hostname: str
    username: str
    password: str

@dataclass
class ServerResult:
    ip: str
    hostname: str
    status: str  # SUCCESS / FAIL / STOPPED
    reason: str
    raw_path: Path | None = None
    alarms: list[dict] = field(default_factory=list)


def read_raw(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig")


def is_valid_ip(value: str) -> bool:
    octets = value.split(".")
    return (
        len(octets) == 4
        and all(o.isdigit() and 0 <= int(o) <= 255 for o in octets)
    )


def parse_server_line(line: str) -> Server | None:
    """解析清单行 'IP 主机名 账号 密码'（空白分隔）；首字段须为 IPv4 地址。"""
    parts = line.split()
    if len(parts) != 4 or not is_valid_ip(parts[0]):
        return None
    return Server(ip=parts[0], hostname=parts[1], username=parts[2], password=parts[3])
