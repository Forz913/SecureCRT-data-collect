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


def write_workbook(path: Path, results: list[ServerResult]) -> None:
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

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _style_header(ws) -> None:
    fill = PatternFill("solid", fgColor="D9E1F2")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = fill


def _auto_width(ws) -> None:
    for col in ws.columns:
        width = max(len(str(c.value)) for c in col if c.value is not None)
        ws.column_dimensions[col[0].column_letter].width = min(width + 4, 60)
