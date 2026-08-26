"""模拟模式：按服务器序号映射样例输出，直接写结果文件（不走 SecureCRT）。"""
from __future__ import annotations

from pathlib import Path

from tool.paths import resource_path
from tool.taskfiles import Server, write_status

SAMPLES = [
    "sample_1_normal.txt",
    "sample_2_multiple.txt",
    "sample_3_empty.txt",
    "sample_4_more.txt",
]


def simulate_server(server: Server, index: int, status_path: Path, raw_path: Path) -> None:
    """index % 5 == 4 映射为失败样例，其余映射为成功样例。"""
    status_path.parent.mkdir(parents=True, exist_ok=True)
    if index % 5 == 4:
        raw_path.write_text("<host>\r\n", encoding="utf-8")
        write_status(status_path, server.ip, "FAIL", "输出为空(模拟)")
        return
    sample = Path(resource_path("samples")) / SAMPLES[index % 4]
    raw_path.write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
    write_status(status_path, server.ip, "SUCCESS", "")
