"""生成 Excel：明细表 + 汇总表。"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from tool.parser import LEVELS
from tool.taskfiles import ServerResult

DETAIL_HEADERS = ["IP", "主机名", "告警序号", "级别", "日期", "时间", "告警内容"]
SUMMARY_HEADERS = ["IP", "主机名", "状态", "失败原因", "告警总数"] + list(LEVELS)
STATUS_CN = {"SUCCESS": "成功", "FAIL": "失败", "STOPPED": "已停止"}


def write_workbook(path: Path, results: list[ServerResult], sim_mode: bool = False) -> None:
    wb = Workbook()

    ws_detail = wb.active
    ws_detail.title = "明细"
    ws_detail.append(DETAIL_HEADERS)
    for r in results:
        for a in r.alarms:
            ws_detail.append(
                [r.ip, r.hostname, a["index"], a["level"], a["date"], a["time"], a["info"]]
            )
    _style_header(ws_detail)
    _auto_width(ws_detail)

    ws_summary = wb.create_sheet("汇总")
    ws_summary.append(SUMMARY_HEADERS)
    for r in results:
        counts = Counter(a["level"] for a in r.alarms)
        ws_summary.append(
            [r.ip, r.hostname, STATUS_CN.get(r.status, r.status), r.reason, len(r.alarms)]
            + [counts.get(lv, 0) for lv in LEVELS]
        )
    _style_header(ws_summary)
    _auto_width(ws_summary)

    if sim_mode:
        ws_note = wb.create_sheet("说明")
        ws_note.append(["注意：本文件为模拟数据（测试用），非真实设备结果。"])
        ws_note.column_dimensions["A"].width = 60

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _style_header(ws) -> None:
    fill = PatternFill("solid", fgColor="D9E1F2")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = fill


def _auto_width(ws) -> None:
    for col in ws.columns:
        width = max(_display_width(c.value) for c in col if c.value is not None)
        ws.column_dimensions[col[0].column_letter].width = min(width + 4, 60)


def _display_width(value) -> int:
    # CJK 字符在 Excel 中约占 2 个宽度单位
    return sum(2 if ord(ch) > 127 else 1 for ch in str(value))
