"""服务器清单解析与结果文件读取。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class Server:
    """一台目标设备的连接信息，是全项目共享的数据对象。"""
    ip: str
    hostname: str  # 清单中标注的主机名，用于提示符匹配与结果展示
    username: str
    password: str

@dataclass
class ServerResult:
    """一台设备的采集结果，由采集器产出、经调度器汇总、UI 负责展示与写 Excel。"""
    ip: str
    hostname: str
    status: str  # SUCCESS / FAIL / STOPPED
    reason: str  # FAIL 时的中文原因，如 "指令执行超时(60秒)"
    raw_path: Path | None = None  # SUCCESS 时原始输出落盘路径，供 UI 解析
    alarms: list[dict] = field(default_factory=list)  # parse_output 的解析结果


def read_raw(path: Path) -> str:
    """读取原始输出文件；文件缺失返回空串（调用方会转 FAIL）。

    用 utf-8-sig 是历史兼容：v1 引擎经 ADODB 写出的文件带 UTF-8 BOM，
    该编码对无 BOM 的当前 v2 文件同样正常。
    """
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig")


def is_valid_ip(value: str) -> bool:
    """校验 IPv4 格式（四段 0-255 数字）。

    除格式校验外还承担安全职责：IP 会被拼进 results/ 目录下的文件名，
    拒绝含分隔符的字符串可防止路径穿越写出目录外。
    """
    octets = value.split(".")
    return (
        len(octets) == 4
        and all(o.isdigit() and 0 <= int(o) <= 255 for o in octets)
    )


def parse_server_line(line: str) -> Server | None:
    """解析清单行 'IP 主机名 账号 密码'（空白分隔）；首字段须为 IPv4 地址。

    不合格式返回 None（调用方跳过该行并提示），不抛异常。
    """
    parts = line.split()
    if len(parts) != 4 or not is_valid_ip(parts[0]):
        return None
    return Server(ip=parts[0], hostname=parts[1], username=parts[2], password=parts[3])
