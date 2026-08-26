"""任务文件与结果文件读写，以及服务器清单行解析。

task/<IP>.txt: UTF-8，每行一个字段，共 8 行:
  IP / 主机名 / 账号 / 密码 / 超时秒数 / 查询指令 / 结果前缀(绝对路径) / 停止标志文件(绝对路径)
results/<IP>_status.txt: IP<TAB>状态<TAB>原因（SUCCESS / FAIL / STOPPED）
results/<IP>_raw.txt: 原始屏幕输出（引擎写入的 UTF-8 含 BOM，读取时用 utf-8-sig 剥离）
"""
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


def write_task_file(
    path: Path,
    server: Server,
    command: str,
    timeout: int,
    result_prefix: str,
    stop_flag_path: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                server.ip,
                server.hostname,
                server.username,
                server.password,
                str(timeout),
                command,
                result_prefix,
                stop_flag_path,
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_status(path: Path, ip: str, status: str, reason: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{ip}\t{status}\t{reason}", encoding="utf-8")


def read_status(path: Path) -> tuple[str, str] | None:
    """返回 (状态, 原因)；文件不存在或格式不对返回 None。"""
    if not path.exists():
        return None
    parts = path.read_text(encoding="utf-8-sig").rstrip("\n").split("\t")
    if len(parts) < 3:
        return None
    return parts[1], parts[2]


def read_raw(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig")


def _is_ipv4(value: str) -> bool:
    octets = value.split(".")
    return (
        len(octets) == 4
        and all(o.isdigit() and 0 <= int(o) <= 255 for o in octets)
    )


def parse_server_line(line: str) -> Server | None:
    """解析清单行 'IP 主机名 账号 密码'（空白分隔）；首字段须为 IPv4 地址。"""
    parts = line.split()
    if len(parts) != 4 or not _is_ipv4(parts[0]):
        return None
    return Server(ip=parts[0], hostname=parts[1], username=parts[2], password=parts[3])
