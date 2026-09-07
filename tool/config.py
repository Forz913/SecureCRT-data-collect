"""config.json 读写：界面状态持久化。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tool.taskfiles import Server

@dataclass
class AppConfig:
    """界面状态配置。含服务器口令（明文落盘为已知取舍，见 save 注释）。"""
    excel_path: str = ""
    servers: list[Server] = field(default_factory=list)
    command: str = "disp alarm hardware"
    timeout: int = 60
    concurrency: int = 5
    sim_mode: bool = False  # 默认真实模式，开发机测试需手动勾选模拟


def _get_str(data: dict, key: str, default: str) -> str:
    """按 key 取字符串字段，任何异常（缺键/类型错）都退回默认值。"""
    try:
        return str(data.get(key, default))
    except Exception:
        return default


def _get_int(data: dict, key: str, default: int) -> int:
    """按 key 取整数字段，非数字值退回默认值（如手工改坏的配置）。"""
    try:
        return int(data.get(key, default))
    except (TypeError, ValueError):
        return default


def _get_bool(data: dict, key: str, default: bool) -> bool:
    """按 key 取布尔字段。

    兼容两种写法：JSON 真布尔，或字符串 "true"/"false"（不区分大小写）。
    其他任何类型（数字、空串、None）一律退回默认值，避免误判。
    """
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return default


def load(path: Path) -> AppConfig:
    """加载配置；任何环节失败都整体退回默认配置，绝不抛出。

    容错策略（手改 config.json 是常见场景）：
    - 文件不存在 → 默认配置
    - JSON 损坏 / 非 dict → 默认配置
    - 逐字段独立容错：单字段类型错只影响该字段
    - servers 只保留形如 [str, str, str, str] 的 4 元素列表，其余条目丢弃
    """
    try:
        if not path.exists():
            return AppConfig()
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return AppConfig()
    if not isinstance(data, dict):
        return AppConfig()
    cfg = AppConfig()
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
    """序列化配置为 UTF-8 JSON（indent=2 便于手工查看/修改）。

    servers 写为嵌套 list 而非 dict：保留字段顺序，与手工编辑习惯一致。
    口令明文落盘为已知取舍（规格确认过），使用说明已提示勿外发 config.json。
    """
    data = asdict(cfg)
    data["servers"] = [[s.ip, s.hostname, s.username, s.password] for s in cfg.servers]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
