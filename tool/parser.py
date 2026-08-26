"""华为 VRP 表格输出解析（固定格式：disp alarm hardware）。"""
from __future__ import annotations

import re

LEVELS = ("Critical", "Major", "Minor", "Warning")

ALARM_RE = re.compile(
    r"^\s*(\d+)\s+(Critical|Major|Minor|Warning)\s+"
    r"(\d{4}-\d{2}-\d{2})\s+"
    r"(\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2})?)\s*(.*)$"
)
# 折行对齐 Info 列（样例为 42 空格）；阈值 20 排除表尾轻缩进的脚注行
CONTINUATION_RE = re.compile(r"^ {20,}(\S.*)$")
SEPARATOR_RE = re.compile(r"^[-= ]+$")
HEADER_RE = re.compile(r"^Index\b")


def normalize(raw: str) -> str:
    return raw.replace("\r\n", "\n").replace("\r", "\n")


def parse_output(raw: str) -> list[dict]:
    """把原始屏幕输出解析为告警列表。

    每条: {"index": str, "level": str, "date": str, "time": str, "info": str}
    折行规则: 以空白开头的行拼接到上一条告警的 info；
    命令回显/提示符等无格式行直接忽略。
    """
    alarms: list[dict] = []
    for line in normalize(raw).splitlines():
        if not line.strip() or "---- More ----" in line:
            continue
        if HEADER_RE.match(line) or SEPARATOR_RE.match(line):
            continue
        m = ALARM_RE.match(line)
        if m:
            alarms.append(
                {
                    "index": m.group(1),
                    "level": m.group(2),
                    "date": m.group(3),
                    "time": m.group(4),
                    "info": m.group(5).strip(),
                }
            )
            continue
        c = CONTINUATION_RE.match(line)
        if c and alarms:
            alarms[-1]["info"] += c.group(1).strip()
    return alarms
