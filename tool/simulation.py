"""模拟模式：按服务器序号映射样例输出（不走网络）。"""
from __future__ import annotations

from pathlib import Path

from tool.paths import resource_path
from tool.taskfiles import Server

SAMPLES = [
    "sample_1_normal.txt",
    "sample_2_multiple.txt",
    "sample_3_empty.txt",
    "sample_4_more.txt",
]


def simulate_server(server: Server, index: int) -> tuple[str, str, str]:
    """返回 (raw_text, status, reason)；index % 5 == 4 映射为失败样例。"""
    if index % 5 == 4:
        return "<host>\r\n", "FAIL", "输出为空(模拟)"
    sample = Path(resource_path("samples")) / SAMPLES[index % 4]
    return sample.read_text(encoding="utf-8"), "SUCCESS", ""
