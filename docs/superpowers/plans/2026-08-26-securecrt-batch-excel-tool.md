# SecureCRT 批量取数 Excel 汇总工具 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个免安装 exe 工具，在装有 SecureCRT 的机器上并发批量登录华为服务器执行查询指令，解析输出并汇总生成 Excel（明细表+汇总表）。

**Architecture:** Python/Tkinter 主程序（PyInstaller 打包）负责界面、任务分发、结果汇总和 Excel 生成；engine.vbs 在 SecureCRT 脚本宿主内运行，每进程处理一台服务器（SSH2 连接 → 关分页 → 发指令 → 捕获输出）；主程序与引擎通过 task/、results/ 目录下的 UTF-8 文件交互。开发机无法访问服务器，全流程用内置样例的"模拟模式"验证。

**Tech Stack:** Python 3.13、Tkinter、openpyxl、pytest、PyInstaller、VBScript（SecureCRT 脚本接口）。

**Spec:** [2026-08-26-securecrt-batch-excel-tool-design.md](../specs/2026-08-26-securecrt-batch-excel-tool-design.md)

**开发机环境（已确认）：** `python` = 3.13.9（anaconda）；shell 为 bash。以下命令按 bash 语法书写。

---

## File Structure

```
excel-tool0826/
├── app.py                     # 入口：tk.Tk + MainWindow + mainloop
├── tool/
│   ├── __init__.py
│   ├── paths.py               # app_dir()/resource_path()（兼容 PyInstaller 冻结）
│   ├── taskfiles.py           # Server/ServerResult 数据类；task/结果文件读写；清单行解析
│   ├── parser.py              # 华为 disp 表格输出解析（纯函数）
│   ├── excel_writer.py        # openpyxl 生成明细+汇总双 sheet
│   ├── config.py              # config.json 读写
│   ├── locate.py              # SecureCRT.exe 查找（常见路径+注册表）
│   ├── runner.py              # 并发调度器（状态文件轮询、停止标志、单台超时）
│   ├── simulation.py          # 模拟模式样例数据提供
│   └── ui.py                  # Tkinter 主窗口
├── engine/
│   └── engine.vbs             # SecureCRT 取数引擎（每进程一台）
├── samples/                   # 模拟模式 + 解析测试样例
│   ├── sample_1_normal.txt    # iplist.txt 原始样例（1 条告警+折行）
│   ├── sample_2_multiple.txt  # 3 条不同级别告警+折行
│   ├── sample_3_empty.txt     # 只有表头无告警
│   └── sample_4_more.txt      # 含 ---- More ---- 分页标记
├── tests/
│   ├── test_parser.py
│   ├── test_taskfiles.py
│   ├── test_excel_writer.py
│   ├── test_config.py
│   ├── test_locate.py
│   └── test_runner.py
├── requirements.txt
├── build.bat                  # PyInstaller 打包脚本
├── docs/
│   ├── superpowers/specs/...  # 已有设计文档
│   └── 使用与验证说明.md        # 用户使用说明 + 真实环境验证清单
└── .gitignore
```

任务文件约定（engine.vbs 与 runner.py 之间的接口，两侧代码必须一致）：

- `task/<IP>.txt`：UTF-8、每行一个字段、共 8 行：`IP / 主机名 / 账号 / 密码 / 超时秒数 / 查询指令 / 结果文件前缀(绝对路径不含扩展名) / 停止标志文件(绝对路径)`
- `results/<IP>_raw.txt`：原始屏幕输出（UTF-8）
- `results/<IP>_status.txt`：`IP<TAB>状态<TAB>原因`，状态取值 `SUCCESS / FAIL / STOPPED`
- `stop.flag`：存在即表示用户请求停止

---

## Task 0: 项目初始化

**Files:**
- Create: `.gitignore`、`requirements.txt`、`tool/__init__.py`、`tests/__init__.py`

- [ ] **Step 1: 初始化 git 仓库并创建基础文件**

```bash
cd /e/cmcc/work/excel-tool0826
git init
mkdir -p tool engine samples tests
```

`.gitignore` 内容：

```gitignore
.venv/
__pycache__/
*.pyc
build/
dist/
*.spec
task/
results/
config.json
stop.flag
*.xlsx
```

`requirements.txt` 内容：

```
openpyxl>=3.1
pyinstaller>=6.10
pytest>=8.0
```

`tool/__init__.py` 与 `tests/__init__.py`：空文件。

- [ ] **Step 2: 创建虚拟环境并安装依赖**

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

- [ ] **Step 3: 验证环境**

```bash
.venv/Scripts/python -c "import openpyxl, tkinter; print(openpyxl.__version__)"
```

Expected: 打印 openpyxl 版本号，无报错。

- [ ] **Step 4: 提交**

```bash
git add .gitignore requirements.txt tool/__init__.py tests/__init__.py
git commit -m "chore: project skeleton with gitignore and requirements"
```

---

## Task 1: 样例数据 + 输出解析器 parser.py（TDD）

**Files:**
- Create: `samples/sample_1_normal.txt`、`samples/sample_2_multiple.txt`、`samples/sample_3_empty.txt`、`samples/sample_4_more.txt`
- Create: `tool/parser.py`
- Test: `tests/test_parser.py`

- [ ] **Step 1: 创建样例文件**

`samples/sample_1_normal.txt`（源自 iplist.txt 样例，含命令回显和结尾提示符，模拟引擎捕获的真实形态）：

```
disp alarm hardware
--------------------------------------------------------------------------------
Index  Level    Date       Time           Info                                  
--------------------------------------------------------------------------------
1      Critical 2023-04-28 01:02:41+08:00 PM7 POWER 25 is failed, the B plane po
                                          wer supply became faulty[OID:1.3.6.1.4
                                          .1.2011.5.25.219.2.5.5,EntCode:136961]
<GDHEY-MS-IPMAN-BNG01-LPLJ-HW>
```

`samples/sample_2_multiple.txt`：

```
disp alarm hardware
--------------------------------------------------------------------------------
Index  Level    Date       Time           Info                                  
--------------------------------------------------------------------------------
1      Critical 2023-04-28 01:02:41+08:00 PM7 POWER 25 is failed, the B plane po
                                          wer supply became faulty[OID:1.3.6.1.4
                                          .1.2011.5.25.219.2.5.5,EntCode:136961]
2      Major    2023-05-02 08:15:03+08:00 Board 3 temperature is too high, the t
                                          emperature has exceeded the upper limit
3      Warning  2023-05-10 12:30:00+08:00 Interface GE1/0/1 is down
<GDHEY-MS-IPMAN-BNG01-LPXD-HW>
```

`samples/sample_3_empty.txt`：

```
disp alarm hardware
--------------------------------------------------------------------------------
Index  Level    Date       Time           Info                                  
--------------------------------------------------------------------------------
<GDHEY-MS-IPMAN-BNG01-LPLJ-HW>
```

`samples/sample_4_more.txt`（含分页标记）：

```
disp alarm hardware
--------------------------------------------------------------------------------
Index  Level    Date       Time           Info                                  
--------------------------------------------------------------------------------
1      Critical 2023-04-28 01:02:41+08:00 PM7 POWER 25 is failed
  ---- More ----
2      Minor    2023-04-29 09:00:00+08:00 Fan 1 speed is abnormal
<GDHEY-MS-IPMAN-BNG01-LPLJ-HW>
```

- [ ] **Step 2: 写失败测试**

`tests/test_parser.py`：

```python
from pathlib import Path

from tool.parser import parse_output

SAMPLES = Path(__file__).parent.parent / "samples"


def read_sample(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


def test_parses_single_alarm_with_wrapped_info():
    alarms = parse_output(read_sample("sample_1_normal.txt"))
    assert len(alarms) == 1
    a = alarms[0]
    assert a["index"] == "1"
    assert a["level"] == "Critical"
    assert a["date"] == "2023-04-28"
    assert a["time"] == "01:02:41+08:00"
    assert a["info"].startswith("PM7 POWER 25 is failed")
    assert "power supply became faulty" in a["info"]
    assert "OID:1.3.6.1.4" in a["info"]


def test_parses_multiple_alarms_with_levels():
    alarms = parse_output(read_sample("sample_2_multiple.txt"))
    assert [a["level"] for a in alarms] == ["Critical", "Major", "Warning"]
    assert len(alarms) == 3
    assert "exceeded the upper limit" in alarms[1]["info"]


def test_empty_table_returns_empty_list():
    assert parse_output(read_sample("sample_3_empty.txt")) == []


def test_more_markers_are_removed():
    alarms = parse_output(read_sample("sample_4_more.txt"))
    assert len(alarms) == 2
    assert alarms[1]["level"] == "Minor"
    assert "---- More ----" not in alarms[0]["info"]


def test_garbage_text_is_ignored():
    raw = "hello\nsome random text\n<host>\n"
    assert parse_output(raw) == []
```

- [ ] **Step 3: 运行测试确认失败**

```bash
.venv/Scripts/python -m pytest tests/test_parser.py -q
```

Expected: FAIL（`ModuleNotFoundError: No module named 'tool.parser'`）

- [ ] **Step 4: 实现 parser.py**

`tool/parser.py`：

```python
"""华为 VRP 表格输出解析（固定格式：disp alarm hardware）。"""
from __future__ import annotations

import re

LEVELS = ("Critical", "Major", "Minor", "Warning")

ALARM_RE = re.compile(
    r"^\s*(\d+)\s+(Critical|Major|Minor|Warning)\s+"
    r"(\d{4}-\d{2}-\d{2})\s+"
    r"(\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2})?)\s*(.*)$"
)
CONTINUATION_RE = re.compile(r"^ +(\S.*)$")
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
            # 直接拼接不加空格：80 列硬折行会词中断行（"po"+"wer"→"power"），
            # 词边界折行时行尾已带空格，拼接后自然保留
            alarms[-1]["info"] += c.group(1).strip()
    return alarms
```

- [ ] **Step 5: 运行测试确认通过**

```bash
.venv/Scripts/python -m pytest tests/test_parser.py -q
```

Expected: 5 passed

- [ ] **Step 6: 提交**

```bash
git add samples/ tool/parser.py tests/test_parser.py
git commit -m "feat: parse Huawei disp alarm output with line-wrap handling"
```

---

## Task 2: 任务/结果文件读写 taskfiles.py（TDD）

**Files:**
- Create: `tool/taskfiles.py`
- Test: `tests/test_taskfiles.py`

- [ ] **Step 1: 写失败测试**

`tests/test_taskfiles.py`：

```python
from pathlib import Path

from tool.taskfiles import (
    Server,
    parse_server_line,
    read_raw,
    read_status,
    write_status,
    write_task_file,
)


def test_task_file_roundtrip_with_chinese_and_special_chars(tmp_path: Path):
    server = Server(ip="188.12.4.21", hostname="GDHEY-BNG01", username="heyuanyingji", password="HYhch!123")
    task = tmp_path / "task" / f"{server.ip}.txt"
    write_task_file(
        task, server, command="disp alarm hardware", timeout=60,
        result_prefix=str(tmp_path / "results" / server.ip),
        stop_flag_path=str(tmp_path / "stop.flag"),
    )
    lines = task.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "188.12.4.21"
    assert lines[1] == "GDHEY-BNG01"
    assert lines[2] == "heyuanyingji"
    assert lines[3] == "HYhch!123"
    assert lines[4] == "60"
    assert lines[5] == "disp alarm hardware"
    assert lines[6] == str(tmp_path / "results" / "188.12.4.21")
    assert lines[7] == str(tmp_path / "stop.flag")


def test_status_write_read_roundtrip(tmp_path: Path):
    p = tmp_path / "results" / "1.2.3.4_status.txt"
    write_status(p, "1.2.3.4", "SUCCESS", "")
    assert read_status(p) == ("SUCCESS", "")
    write_status(p, "1.2.3.4", "FAIL", "超时")
    assert read_status(p) == ("FAIL", "超时")


def test_read_status_missing_file_returns_none(tmp_path: Path):
    assert read_status(tmp_path / "nope.txt") is None


def test_read_raw_missing_file_returns_empty(tmp_path: Path):
    assert read_raw(tmp_path / "nope_raw.txt") == ""


def test_parse_server_line():
    s = parse_server_line("188.12.4.21 GDHEY-MS-IPMAN-BNG01-LPLJ-HW heyuanyingji HYhch!123")
    assert s == Server(ip="188.12.4.21", hostname="GDHEY-MS-IPMAN-BNG01-LPLJ-HW",
                       username="heyuanyingji", password="HYhch!123")
    assert parse_server_line("only three fields here") is None
    assert parse_server_line("") is None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/Scripts/python -m pytest tests/test_taskfiles.py -q
```

Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 taskfiles.py**

`tool/taskfiles.py`：

```python
"""任务文件与结果文件读写，以及服务器清单行解析。

task/<IP>.txt: UTF-8，每行一个字段，共 8 行:
  IP / 主机名 / 账号 / 密码 / 超时秒数 / 查询指令 / 结果前缀(绝对路径) / 停止标志文件(绝对路径)
results/<IP>_status.txt: IP<TAB>状态<TAB>原因（SUCCESS / FAIL / STOPPED）
results/<IP>_raw.txt: 原始屏幕输出（UTF-8）
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
    parts = path.read_text(encoding="utf-8").rstrip("\n").split("\t")
    if len(parts) < 3:
        return None
    return parts[1], parts[2]


def read_raw(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/Scripts/python -m pytest tests/test_taskfiles.py -q
```

Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add tool/taskfiles.py tests/test_taskfiles.py
git commit -m "feat: task/result file IO with server list line parsing"
```

---

## Task 3: Excel 生成 excel_writer.py（TDD）

**Files:**
- Create: `tool/excel_writer.py`
- Test: `tests/test_excel_writer.py`

- [ ] **Step 1: 写失败测试**

`tests/test_excel_writer.py`：

```python
from pathlib import Path

from openpyxl import load_workbook

from tool.excel_writer import write_workbook
from tool.taskfiles import ServerResult


def make_result(ip: str, status: str, reason: str, alarms: list[dict]) -> ServerResult:
    return ServerResult(ip=ip, hostname=f"host-{ip}", status=status,
                        reason=reason, raw_path=None, alarms=alarms)


def test_workbook_has_two_sheets_with_correct_rows(tmp_path: Path):
    results = [
        make_result("1.1.1.1", "SUCCESS", "", [
            {"index": "1", "level": "Critical", "date": "2023-04-28",
             "time": "01:02:41+08:00", "info": "POWER failed"},
            {"index": "2", "level": "Minor", "date": "2023-04-29",
             "time": "09:00:00+08:00", "info": "Fan speed abnormal"},
        ]),
        make_result("2.2.2.2", "FAIL", "连接失败", []),
    ]
    out = tmp_path / "结果.xlsx"
    write_workbook(out, results)

    wb = load_workbook(out)
    assert wb.sheetnames == ["明细", "汇总"]

    ws = wb["明细"]
    rows = list(ws.values)
    assert rows[0] == ("IP", "主机名", "告警序号", "级别", "日期", "时间", "告警内容")
    assert len(rows) == 3  # 表头 + 2 条告警
    assert rows[1][0] == "1.1.1.1" and rows[1][3] == "Critical"
    assert rows[2][6] == "Fan speed abnormal"

    ws2 = wb["汇总"]
    rows2 = list(ws2.values)
    assert rows2[0] == ("IP", "主机名", "状态", "失败原因", "告警总数",
                        "Critical", "Major", "Minor", "Warning")
    assert len(rows2) == 3  # 表头 + 2 台
    # 注：openpyxl 保存时丢弃空字符串，空单元格读回为 None
    assert rows2[1][:5] == ("1.1.1.1", "host-1.1.1.1", "成功", None, 2)
    assert rows2[1][5] == 1 and rows2[1][7] == 1  # Critical 1、Minor 1（列 5-8 为四级计数）
    assert rows2[2][:4] == ("2.2.2.2", "host-2.2.2.2", "失败", "连接失败")


def test_stopped_status_shown_in_summary(tmp_path: Path):
    results = [make_result("3.3.3.3", "STOPPED", "用户停止", [])]
    out = tmp_path / "停止.xlsx"
    write_workbook(out, results)
    wb = load_workbook(out)
    ws = wb["汇总"]
    rows = list(ws.values)
    assert rows[1][2] == "已停止"
```

（注：`rows2[1][5] == 1 and rows2[1][8] == 1` 中第二段改为 `rows2[1][7] == 1`——级别列顺序为 Critical(5)/Major(6)/Minor(7)/Warning(8)，样例告警是 Critical+Minor。若执行时断言失败，按此修正断言后重跑。）

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/Scripts/python -m pytest tests/test_excel_writer.py -q
```

Expected: FAIL（`ModuleNotFoundError: No module named 'tool.excel_writer'`）

- [ ] **Step 3: 实现 excel_writer.py**

`tool/excel_writer.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/Scripts/python -m pytest tests/test_excel_writer.py -q
```

Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add tool/excel_writer.py tests/test_excel_writer.py
git commit -m "feat: excel writer with detail and summary sheets"
```

---

## Task 4: 配置持久化 config.py（TDD）

**Files:**
- Create: `tool/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**

`tests/test_config.py`：

```python
import json
from pathlib import Path

from tool.config import AppConfig, load, save
from tool.taskfiles import Server


def test_roundtrip(tmp_path: Path):
    p = tmp_path / "config.json"
    cfg = AppConfig(
        securecrt_path=r"C:\X\SecureCRT.exe",
        excel_path=r"C:\Y\out.xlsx",
        servers=[Server("1.1.1.1", "h1", "u1", "p1!")],
        command="disp alarm hardware",
        timeout=90,
        concurrency=3,
        sim_mode=False,
    )
    save(p, cfg)
    loaded = load(p)
    assert loaded == cfg


def test_load_missing_file_returns_defaults(tmp_path: Path):
    cfg = load(tmp_path / "nope.json")
    assert cfg.servers == []
    assert cfg.command == "disp alarm hardware"
    assert cfg.timeout == 60
    assert cfg.concurrency == 5
    assert cfg.sim_mode is True


def test_load_corrupted_json_returns_defaults(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    cfg = load(p)
    assert cfg.command == "disp alarm hardware"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/Scripts/python -m pytest tests/test_config.py -q
```

Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 config.py**

`tool/config.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/Scripts/python -m pytest tests/test_config.py -q
```

Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add tool/config.py tests/test_config.py
git commit -m "feat: config persistence with tolerant loading"
```

---

## Task 5: SecureCRT 路径查找 locate.py（TDD）

**Files:**
- Create: `tool/locate.py`
- Test: `tests/test_locate.py`

- [ ] **Step 1: 写失败测试**

`tests/test_locate.py`：

```python
from tool.locate import find_securecrt


def test_returns_second_candidate_when_first_missing():
    def fake_exists(p: str) -> bool:
        return p == r"C:\Program Files (x86)\VanDyke Software\Clients\SecureCRT.exe"
    found = find_securecrt(exists=fake_exists, registry_lookup=lambda: "")
    assert found == r"C:\Program Files (x86)\VanDyke Software\Clients\SecureCRT.exe"


def test_uses_registry_path_when_no_candidate_exists():
    def fake_exists(p: str) -> bool:
        return p == r"D:\Apps\SecureCRT\SecureCRT.exe"
    found = find_securecrt(exists=fake_exists,
                           registry_lookup=lambda: r"D:\Apps\SecureCRT")
    assert found == r"D:\Apps\SecureCRT\SecureCRT.exe"


def test_returns_empty_when_not_found():
    found = find_securecrt(exists=lambda p: False, registry_lookup=lambda: "")
    assert found == ""
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/Scripts/python -m pytest tests/test_locate.py -q
```

Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 locate.py**

`tool/locate.py`：

```python
"""查找 SecureCRT.exe：常见安装路径 + 注册表。"""
from __future__ import annotations

import os

CANDIDATES = [
    r"C:\Program Files\VanDyke Software\Clients\SecureCRT.exe",
    r"C:\Program Files (x86)\VanDyke Software\Clients\SecureCRT.exe",
]


def find_securecrt(exists=os.path.exists, registry_lookup=None) -> str:
    if registry_lookup is None:
        registry_lookup = _registry_lookup
    for c in CANDIDATES:
        if exists(c):
            return c
    base = registry_lookup()
    if base:
        p = os.path.join(base, "SecureCRT.exe")
        if exists(p):
            return p
    return ""


def _registry_lookup() -> str:
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\VanDyke Software\Clients\SecureCRT") as k:
                    for name in ("Install Path", "Path", ""):
                        try:
                            val, _ = winreg.QueryValueEx(k, name)
                            if val:
                                return str(val)
                        except OSError:
                            continue
            except OSError:
                continue
    except Exception:
        pass
    return ""
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/Scripts/python -m pytest tests/test_locate.py -q
```

Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add tool/locate.py tests/test_locate.py
git commit -m "feat: securecrt executable discovery via common paths and registry"
```

---

## Task 6: 并发调度器 runner.py（TDD，模拟引擎下测试，不依赖 SecureCRT）

**Files:**
- Create: `tool/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: 写失败测试**

`tests/test_runner.py`：

```python
from pathlib import Path

from tool.runner import RunConfig, Runner
from tool.taskfiles import Server, write_status


def make_cfg(tmp_path: Path, **kw) -> RunConfig:
    defaults = dict(
        command="disp alarm hardware",
        timeout=60,
        concurrency=2,
        sim_mode=True,
        securecrt_path="",
        engine_path="",
        task_dir=tmp_path / "task",
        results_dir=tmp_path / "results",
        stop_flag_path=tmp_path / "stop.flag",
        per_deadline=300.0,
        on_event=None,
    )
    defaults.update(kw)
    return RunConfig(**defaults)


def make_servers(n: int) -> list[Server]:
    return [Server(ip=f"10.0.0.{i}", hostname=f"h{i}", username="u", password="p") for i in range(1, n + 1)]


def run_until_done(runner: Runner, max_ticks: int = 50) -> bool:
    for _ in range(max_ticks):
        if runner.tick():
            return True
    return False


def test_all_servers_finish_with_sim_engine(tmp_path: Path):
    servers = make_servers(5)
    r = Runner(servers, make_cfg(tmp_path))
    r.start()
    assert run_until_done(r)
    results = r.results()
    assert [x.ip for x in results] == [s.ip for s in servers]
    # 模拟引擎: 序号 4（第 5 台）映射为失败样例，其余成功
    assert [x.status for x in results] == ["SUCCESS"] * 4 + ["FAIL"]
    assert results[4].reason == "输出为空(模拟)"
    # 完成后清理 stop.flag 和 task 目录
    assert not tmp_path.joinpath("stop.flag").exists()


def test_concurrency_limit_respected(tmp_path: Path):
    servers = make_servers(5)
    launched: list[str] = []
    status_written: list[str] = []

    def fake_launch(runner, rec):
        launched.append(rec.server.ip)
        # 不写状态文件：模拟仍在运行的引擎

    cfg = make_cfg(tmp_path, concurrency=2, per_deadline=300.0)
    cfg.launcher = fake_launch
    r = Runner(servers, cfg)
    r.start()
    r.tick()
    assert launched == ["10.0.0.1", "10.0.0.2"]  # 第一批最多并发数台
    r.tick()
    assert launched == ["10.0.0.1", "10.0.0.2"]  # 未完成前不再启动新的

    # 手动写入状态模拟两台完成
    for ip in ["10.0.0.1", "10.0.0.2"]:
        write_status(tmp_path / "results" / f"{ip}_status.txt", ip, "SUCCESS", "")
    r.tick()  # 标记完成
    r.tick()  # 启动下一批
    assert launched == ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"]


def test_stop_marks_pending_as_stopped(tmp_path: Path):
    servers = make_servers(5)
    cfg = make_cfg(tmp_path, concurrency=2, per_deadline=300.0)
    cfg.launcher = lambda runner, rec: None  # 引擎永远不完成
    r = Runner(servers, cfg)
    r.start()
    r.tick()  # 启动 2 台
    assert tmp_path.joinpath("stop.flag").exists() is False
    r.request_stop()
    assert tmp_path.joinpath("stop.flag").exists()
    r.tick()
    # 未启动的 3 台立即记为已停止；已启动的 2 台等自然结束
    results = r.results()
    stopped = [x for x in results if x.status == "STOPPED"]
    assert len(stopped) == 3


def test_per_server_deadline_marks_fail(tmp_path: Path):
    servers = make_servers(2)
    cfg = make_cfg(tmp_path, concurrency=2, per_deadline=0.0)  # 立即超时
    cfg.launcher = lambda runner, rec: None
    r = Runner(servers, cfg)
    r.start()
    r.tick()
    r.tick()
    results = r.results()
    assert all(x.status == "FAIL" and x.reason == "超时未返回" for x in results)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/Scripts/python -m pytest tests/test_runner.py -q
```

Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 runner.py**

`tool/runner.py`：

```python
"""并发调度器：按并发数分批启动取数引擎，轮询状态文件汇总结果。

完成判定以各台状态文件为准（SecureCRT 单实例复用导致进程退出不代表任务完成）。
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from tool.taskfiles import (
    Server,
    ServerResult,
    read_status,
    write_task_file,
)

@dataclass
class RunConfig:
    command: str
    timeout: int
    concurrency: int
    sim_mode: bool
    securecrt_path: str
    engine_path: str
    task_dir: Path
    results_dir: Path
    stop_flag_path: Path
    per_deadline: float  # 每台从启动到完成的最长秒数
    on_event: object = None  # (event, ip, payload) -> None
    launcher: object = None  # 测试注入用: (runner, rec) -> None


def _default_launcher(runner, rec) -> None:
    if runner.cfg.sim_mode:
        from tool.simulation import simulate_server

        simulate_server(rec.server, rec.index, runner._status_path(rec), runner._raw_path(rec))
    else:
        task_path = runner.cfg.task_dir / f"{rec.server.ip}.txt"
        write_task_file(
            task_path,
            rec.server,
            runner.cfg.command,
            runner.cfg.timeout,
            result_prefix=str(runner._result_prefix(rec)),
            stop_flag_path=str(runner.cfg.stop_flag_path),
        )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [runner.cfg.securecrt_path, "/SCRIPT", runner.cfg.engine_path, "/ARG", str(task_path)],
            creationflags=flags,
        )
        # 不等待进程：完成以状态文件为准


class _Record:
    def __init__(self, server: Server, index: int):
        self.server = server
        self.index = index
        self.launch_time: float | None = None
        self.done = False
        self.status = "FAIL"
        self.reason = ""


class Runner:
    def __init__(self, servers: list[Server], cfg: RunConfig):
        self.cfg = cfg
        self._records = [_Record(s, i) for i, s in enumerate(servers)]
        self._running = 0
        self._stopped = False
        self._launcher = cfg.launcher or _default_launcher

    def _status_path(self, rec: _Record) -> Path:
        return self.cfg.results_dir / f"{rec.server.ip}_status.txt"

    def _raw_path(self, rec: _Record) -> Path:
        return self.cfg.results_dir / f"{rec.server.ip}_raw.txt"

    def _result_prefix(self, rec: _Record) -> Path:
        return self.cfg.results_dir / rec.server.ip

    def _emit(self, event: str, ip: str, payload: str = "") -> None:
        if self.cfg.on_event:
            self.cfg.on_event(event, ip, payload)

    def start(self) -> None:
        self.cfg.task_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.results_dir.mkdir(parents=True, exist_ok=True)
        if self.cfg.stop_flag_path.exists():
            self.cfg.stop_flag_path.unlink()
        for rec in self._records:
            for p in (self._status_path(rec), self._raw_path(rec)):
                if p.exists():
                    p.unlink()
        self._emit("log", "", "开始执行，共 {} 台".format(len(self._records)))

    def request_stop(self) -> None:
        self._stopped = True
        self.cfg.stop_flag_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.stop_flag_path.write_text("stop", encoding="utf-8")
        self._emit("log", "", "收到停止请求：未开始的机器将记为已停止")

    def tick(self) -> bool:
        """推进一步调度。全部完成返回 True。"""
        now = time.monotonic()
        for rec in self._records:
            if rec.done:
                continue
            st = read_status(self._status_path(rec))
            if st is not None:
                rec.status, rec.reason = st
                rec.done = True
                self._running -= 1
                self._emit("status", rec.server.ip, rec.status)
                continue
            if rec.launch_time is not None and now - rec.launch_time > self.cfg.per_deadline:
                rec.status, rec.reason = "FAIL", "超时未返回"
                rec.done = True
                self._running -= 1
                self._emit("status", rec.server.ip, "FAIL")
                continue
            if rec.launch_time is None and not self._stopped and self._running < self.cfg.concurrency:
                rec.launch_time = now
                self._running += 1
                self._emit("log", rec.server.ip, "启动取数")
                self._launcher(self, rec)
                continue
            if rec.launch_time is None and self._stopped:
                rec.status, rec.reason = "STOPPED", "用户停止"
                rec.done = True
                self._emit("status", rec.server.ip, "STOPPED")
        if all(rec.done for rec in self._records):
            self._cleanup()
            return True
        return False

    def _cleanup(self) -> None:
        if self.cfg.stop_flag_path.exists():
            self.cfg.stop_flag_path.unlink()

    def results(self) -> list[ServerResult]:
        out: list[ServerResult] = []
        for rec in self._records:
            raw_path = self._raw_path(rec)
            if rec.status == "SUCCESS" and not raw_path.exists():
                rec.status, rec.reason = "FAIL", "原始输出文件缺失"
            out.append(
                ServerResult(
                    ip=rec.server.ip,
                    hostname=rec.server.hostname,
                    status=rec.status,
                    reason=rec.reason,
                    raw_path=raw_path if raw_path.exists() else None,
                )
            )
        return out
```

- [ ] **Step 4: 实现 simulation.py（runner 的模拟引擎依赖）**

`tool/simulation.py`：

```python
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
```

- [ ] **Step 5: 实现 paths.py（simulation.py 依赖）**

`tool/paths.py`：

```python
"""路径工具：兼容 PyInstaller 冻结环境。"""
from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """程序数据目录：冻结时为 exe 所在目录，开发时为项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def resource_path(rel: str) -> str:
    """只读资源路径：冻结时在 PyInstaller 解包目录，开发时为项目根目录。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))
    return str(base / rel)
```

- [ ] **Step 6: 运行测试确认通过**

```bash
.venv/Scripts/python -m pytest tests/test_runner.py -q
```

Expected: 4 passed

- [ ] **Step 7: 提交**

```bash
git add tool/runner.py tool/simulation.py tool/paths.py tests/test_runner.py
git commit -m "feat: concurrent runner with status polling, stop flag and sim engine"
```

---

## Task 7: SecureCRT 取数引擎 engine.vbs（无自动化测试，附评审清单）

**Files:**
- Create: `engine/engine.vbs`

- [ ] **Step 1: 创建 engine.vbs**

完整内容（**文件编码必须是 ANSI/GBK**：SecureCRT 脚本宿主在中文 Windows 上按 ANSI 读取 .vbs，本脚本含中文注释和原因字符串，UTF-8 编码会在 GBK 解码下编译失败——"未结束的字符串常量"，已用 cscript 实测验证，GBK 下编译通过。若用 Write 工具（UTF-8）创建，需转码：`p.write_bytes(text.encode("gbk"))`。另注意 Python 侧 write_task_file 在 Windows 上实际写出 CRLF 行尾，引擎里的 vbCrLf/vbCr→vbLf 归一化是必需的）：

```vbs
' engine.vbs - SecureCRT 批量取数引擎（每进程一台服务器）
' 用法: SecureCRT.exe /SCRIPT engine.vbs /ARG <任务文件绝对路径>
' 任务文件: UTF-8，每行一个字段，共 8 行:
'   IP / 主机名 / 账号 / 密码 / 超时秒数 / 查询指令 / 结果文件前缀(绝对路径) / 停止标志文件(绝对路径)
' 输出: <前缀>_raw.txt（原始屏幕输出）、<前缀>_status.txt（IP<TAB>状态<TAB>原因）
' 状态: SUCCESS / FAIL / STOPPED
' 注意: 不使用 crt.Quit —— SecureCRT 单实例，Quit 会关掉用户自己的窗口
Option Explicit

Dim g_fso
Set g_fso = CreateObject("Scripting.FileSystemObject")

Function ReadFileUtf8(strPath)
    If Not g_fso.FileExists(strPath) Then
        ReadFileUtf8 = ""
        Exit Function
    End If
    Dim st
    Set st = CreateObject("ADODB.Stream")
    st.Type = 2
    st.Charset = "utf-8"
    st.Open
    st.LoadFromFile strPath
    ReadFileUtf8 = st.ReadText
    st.Close
End Function

Sub WriteFileUtf8(strPath, strContent)
    Dim st
    Set st = CreateObject("ADODB.Stream")
    st.Type = 2
    st.Charset = "utf-8"
    st.Open
    st.WriteText strContent
    st.SaveToFile strPath, 2
    st.Close
End Sub

Sub WriteStatus(strPrefix, strIp, strStatus, strReason)
    WriteFileUtf8 strPrefix & "_status.txt", strIp & vbTab & strStatus & vbTab & strReason
End Sub

Sub DisconnectQuietly()
    On Error Resume Next
    crt.Session.Disconnect
    On Error GoTo 0
End Sub

Sub Main()
    Dim taskPath, content, lines
    Dim ip, hostname, user, passwd
    Dim timeoutSec, command, prefix, stopFlagPath
    Dim n, rawOut

    If crt.Arguments.Count < 1 Then
        Exit Sub
    End If
    taskPath = crt.Arguments.GetArg(0)

    content = ReadFileUtf8(taskPath)
    If content = "" Then
        Exit Sub
    End If
    content = Replace(content, vbCrLf, vbLf)
    content = Replace(content, vbCr, vbLf)
    lines = Split(content, vbLf)
    If UBound(lines) < 7 Then
        Exit Sub
    End If

    ip = Trim(lines(0))
    hostname = Trim(lines(1))
    user = Trim(lines(2))
    passwd = lines(3)
    timeoutSec = CLng(Trim(lines(4)))
    command = Trim(lines(5))
    prefix = Trim(lines(6))
    stopFlagPath = Trim(lines(7))

    If g_fso.FileExists(stopFlagPath) Then
        WriteStatus prefix, ip, "STOPPED", "用户停止"
        Exit Sub
    End If

    ' 全程容错：脚本运行时错误降级为失败状态，由主程序状态轮询收敛
    On Error Resume Next
    crt.Session.Connect "/SSH2 /ACCEPTHOSTKEYS /L " & user & " /PASSWORD """ & passwd & """ " & ip
    If Err.Number <> 0 Then
        WriteStatus prefix, ip, "FAIL", "连接异常: " & Err.Description
        DisconnectQuietly
        Exit Sub
    End If

    n = crt.Screen.WaitForString("<", 30)
    If Not n Then
        WriteStatus prefix, ip, "FAIL", "连接后30秒未出现命令提示符(连接失败/认证失败/不可达)"
        DisconnectQuietly
        Exit Sub
    End If

    crt.Screen.Send "screen-length 0 temporary" & vbCr
    n = crt.Screen.WaitForString("<", 15)
    If Not n Then
        WriteStatus prefix, ip, "FAIL", "关闭分页后未回到命令提示符"
        DisconnectQuietly
        Exit Sub
    End If

    crt.Screen.Send command & vbCr
    ' 字面量提示符 <主机名>（取任务文件主机名字段），避免输出中的 <> 内容提前截断捕获
    rawOut = crt.Screen.ReadString("<" & hostname & ">", timeoutSec)

    If rawOut = "" Then
        n = crt.Screen.WaitForString("<", 2)
        If n Then
            WriteStatus prefix, ip, "FAIL", "输出捕获异常"
        Else
            WriteStatus prefix, ip, "FAIL", "指令执行超时(" & timeoutSec & "秒)"
        End If
        DisconnectQuietly
        Exit Sub
    End If

    WriteFileUtf8 prefix & "_raw.txt", rawOut

    If Len(Trim(Replace(rawOut, command, ""))) < 10 Then
        WriteStatus prefix, ip, "FAIL", "输出为空"
        DisconnectQuietly
        Exit Sub
    End If

    WriteStatus prefix, ip, "SUCCESS", ""
    DisconnectQuietly
End Sub

Main
```

- [ ] **Step 2: 人工评审清单（开发机无法运行 SecureCRT，逐项核对）**

逐项检查并确认：

1. `crt.Arguments.GetArg(0)` 为 0 基下标，取第一个 /ARG 参数（SecureCRT 脚本接口标准用法）。
2. 任务文件 UTF-8 读写使用 ADODB.Stream，与 Python 侧 `write_task_file` 的 UTF-8 编码一致；Step 1 代码已把 `vbCrLf`/`vbCr` 统一替换为 `vbLf` 后再 Split，兼容 Windows/Unix 换行（Python 侧写 `\n`）。
3. `crt.Screen.ReadString("<" & hostname & ">", timeoutSec)` 使用字面量提示符（取自任务文件主机名字段，华为 VRP 用户视图提示符为 `<主机名>`）——若提示符与清单主机名不符（大小写/改名），捕获超时并记 FAIL"输出捕获异常(提示符与清单主机名可能不符)"，可在汇总表中发现并修正清单。
4. 提示符假设为华为 VRP 用户视图 `<主机名>`（含 `<`）。若登录后落在系统视图 `[主机名]` 或自定义提示符，`WaitForString("<", 30)` 会超时失败——华为 BNG 默认登录后即用户视图，风险低；验证清单含此项。
5. `WaitForString("<", 30)` 若登录横幅含 `<` 会提前匹配，随后发送的指令会在登录完成后由设备执行，第 2 次 `WaitForString("<", 15)` 仍会等到真实提示符——无害。
6. 密码含双引号 `"` 时 `/PASSWORD """ & passwd & """` 会解析错误；华为运维密码通常不含双引号，验证清单注明限制。
7. 引擎不调用 `crt.Quit`，结束只断开连接，空标签页留在 SecureCRT 中由用户手动关闭。
8. `timeoutSec` 由主程序校验为正整数后才写入任务文件，`CLng` 不会抛错。
9. 所有失败路径都写状态文件，保证主程序轮询一定能收敛（最坏情况由 per_deadline 兜底）。

- [ ] **Step 3: 提交**

```bash
git add engine/engine.vbs
git commit -m "feat: securecrt vbs engine for per-server data collection"
```

---

## Task 8: Tkinter 主界面 ui.py + 入口 app.py（手动验证）

**Files:**
- Create: `tool/ui.py`、`app.py`

- [ ] **Step 1: 创建 app.py**

```python
import tkinter as tk

from tool.ui import MainWindow


def main() -> None:
    root = tk.Tk()
    root.title("SecureCRT 批量取数工具")
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 创建 ui.py**

```python
"""Tkinter 主界面。"""
from __future__ import annotations

import datetime
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from tool.config import AppConfig, load as cfg_load, save as cfg_save
from tool.excel_writer import write_workbook
from tool.locate import find_securecrt
from tool.parser import parse_output
from tool.paths import app_dir, resource_path
from tool.runner import RunConfig, Runner
from tool.taskfiles import Server, parse_server_line, read_raw


def default_excel_name() -> str:
    return "SecureCRT巡检结果_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".xlsx"


class MainWindow:
    POLL_MS = 400

    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg_path = app_dir() / "config.json"
        self.cfg: AppConfig = cfg_load(self.cfg_path)
        self.runner: Runner | None = None
        self._build()
        self._load_from_config()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 界面搭建 ----------

    def _build(self) -> None:
        self.root.geometry("980x680")
        self.root.minsize(860, 560)
        pad = {"padx": 6, "pady": 3}
        body = ttk.Frame(self.root, padding=8)
        body.pack(fill="both", expand=True)

        # 1. SecureCRT 路径
        row0 = ttk.Frame(body)
        row0.pack(fill="x", **pad)
        ttk.Label(row0, text="SecureCRT:").pack(side="left")
        self.securecrt_var = tk.StringVar()
        ttk.Entry(row0, textvariable=self.securecrt_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row0, text="浏览...", command=self._browse_securecrt).pack(side="left", padx=2)
        ttk.Button(row0, text="自动检测", command=self._auto_detect_securecrt).pack(side="left")

        # 2. Excel 保存位置
        row1 = ttk.Frame(body)
        row1.pack(fill="x", **pad)
        ttk.Label(row1, text="保存到:").pack(side="left")
        self.excel_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.excel_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row1, text="浏览...", command=self._browse_excel).pack(side="left")

        # 3. 指令 + 超时
        row2 = ttk.Frame(body)
        row2.pack(fill="x", **pad)
        ttk.Label(row2, text="查询指令:").pack(side="left")
        self.command_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.command_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Label(row2, text="超时(秒):").pack(side="left")
        self.timeout_var = tk.IntVar(value=60)
        ttk.Spinbox(row2, from_=10, to=600, textvariable=self.timeout_var, width=6).pack(side="left", padx=4)

        # 4. 并发 + 模拟模式
        row3 = ttk.Frame(body)
        row3.pack(fill="x", **pad)
        ttk.Label(row3, text="并发数:").pack(side="left")
        self.concurrency_var = tk.IntVar(value=5)
        ttk.Spinbox(row3, from_=1, to=10, textvariable=self.concurrency_var, width=4).pack(side="left", padx=4)
        self.sim_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row3, text="模拟取数（测试用，不连真实服务器）", variable=self.sim_var).pack(side="left", padx=12)

        # 5. 服务器清单
        row4 = ttk.Frame(body)
        row4.pack(fill="x", **pad)
        ttk.Label(row4, text="服务器清单:").pack(side="left")
        ttk.Button(row4, text="添加", command=self._add_server).pack(side="left", padx=2)
        ttk.Button(row4, text="粘贴多行", command=self._paste_servers).pack(side="left", padx=2)
        ttk.Button(row4, text="导入文件...", command=self._import_servers).pack(side="left", padx=2)
        ttk.Button(row4, text="删除选中", command=self._delete_selected).pack(side="left", padx=2)
        ttk.Button(row4, text="清空", command=self._clear_servers).pack(side="left", padx=2)

        table_frame = ttk.Frame(body)
        table_frame.pack(fill="both", expand=True, **pad)
        cols = ("ip", "hostname", "username", "password")
        self.server_tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=8)
        for cid, text in zip(cols, ("IP", "主机名", "账号", "密码")):
            self.server_tree.heading(cid, text=text)
            self.server_tree.column(cid, width=170, anchor="w")
        ysb = ttk.Scrollbar(table_frame, orient="vertical", command=self.server_tree.yview)
        self.server_tree.configure(yscrollcommand=ysb.set)
        self.server_tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.server_tree.bind("<Double-1>", self._edit_server)

        # 6. 运行控制
        row6 = ttk.Frame(body)
        row6.pack(fill="x", **pad)
        self.start_btn = ttk.Button(row6, text="开始", command=self._on_start)
        self.start_btn.pack(side="left", padx=2)
        self.stop_btn = ttk.Button(row6, text="停止", command=self._on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=2)
        self.progress = ttk.Progressbar(row6, maximum=100)
        self.progress.pack(side="left", fill="x", expand=True, padx=8)

        # 7. 状态列表 + 日志
        status_frame = ttk.Frame(body)
        status_frame.pack(fill="x", **pad)
        self.status_tree = ttk.Treeview(status_frame, columns=("ip", "hostname", "status"), show="headings", height=5)
        for cid, text in zip(("ip", "hostname", "status"), ("IP", "主机名", "状态")):
            self.status_tree.heading(cid, text=text)
            self.status_tree.column(cid, width=170, anchor="w")
        self.status_tree.pack(fill="x")

        log_frame = ttk.LabelFrame(body, text="运行日志", padding=4)
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=8, state="disabled")
        self.log_text.pack(fill="both", expand=True)

    # ---------- 清单操作 ----------

    def _servers_from_tree(self) -> list[Server]:
        servers = []
        for iid in self.server_tree.get_children():
            values = self.server_tree.item(iid, "values")
            servers.append(Server(ip=values[0], hostname=values[1],
                                  username=values[2], password=values[3]))
        return servers

    def _refresh_server_tree(self) -> None:
        self.server_tree.delete(*self.server_tree.get_children())
        for s in self.cfg.servers:
            self.server_tree.insert("", "end", values=(s.ip, s.hostname, s.username, s.password))

    def _add_server(self) -> None:
        self._open_server_dialog(None)

    def _edit_server(self, _event=None) -> None:
        sel = self.server_tree.selection()
        if sel:
            self._open_server_dialog(sel[0])

    def _open_server_dialog(self, iid: str | None) -> None:
        dlg = tk.Toplevel(self.root)
        dlg.title("编辑服务器" if iid else "添加服务器")
        dlg.transient(self.root)
        dlg.grab_set()
        fields = {}
        if iid:
            cur = self.server_tree.item(iid, "values")
        else:
            cur = ["", "", "", ""]
        for r, (label, key) in enumerate(zip(("IP", "主机名", "账号", "密码"), ("ip", "hostname", "username", "password"))):
            ttk.Label(dlg, text=label + ":").grid(row=r, column=0, sticky="e", padx=6, pady=4)
            var = tk.StringVar(value=cur[r])
            ttk.Entry(dlg, textvariable=var, width=32).grid(row=r, column=1, padx=6, pady=4)
            fields[key] = var

        def on_ok() -> None:
            server = Server(ip=fields["ip"].get().strip(), hostname=fields["hostname"].get().strip(),
                            username=fields["username"].get().strip(), password=fields["password"].get())
            if not server.ip or not server.username or not server.password:
                messagebox.showwarning("提示", "IP、账号、密码不能为空", parent=dlg)
                return
            if iid:
                self.cfg.servers[self.server_tree.index(iid)] = server
            else:
                self.cfg.servers.append(server)
            self._refresh_server_tree()
            dlg.destroy()

        ttk.Button(dlg, text="确定", command=on_ok).grid(row=4, column=0, pady=8)
        ttk.Button(dlg, text="取消", command=dlg.destroy).grid(row=4, column=1, pady=8)

    def _paste_servers(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("提示", "剪贴板为空")
            return
        added = 0
        for line in text.splitlines():
            s = parse_server_line(line)
            if s:
                self.cfg.servers.append(s)
                added += 1
        self._refresh_server_tree()
        self._log(f"粘贴完成：新增 {added} 台")

    def _import_servers(self) -> None:
        path = filedialog.askopenfilename(
            title="选择服务器清单文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        added = 0
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            s = parse_server_line(line)
            if s:
                self.cfg.servers.append(s)
                added += 1
        self._refresh_server_tree()
        self._log(f"导入完成：{path} 新增 {added} 台")

    def _delete_selected(self) -> None:
        sel = self.server_tree.selection()
        if not sel:
            return
        for iid in sel:
            del self.cfg.servers[self.server_tree.index(iid)]
        self._refresh_server_tree()

    def _clear_servers(self) -> None:
        if messagebox.askyesno("确认", "清空所有服务器？"):
            self.cfg.servers.clear()
            self._refresh_server_tree()

    # ---------- 路径选择 ----------

    def _browse_securecrt(self) -> None:
        path = filedialog.askopenfilename(title="选择 SecureCRT.exe",
                                          filetypes=[("SecureCRT", "SecureCRT.exe"), ("所有文件", "*.*")])
        if path:
            self.securecrt_var.set(path)

    def _auto_detect_securecrt(self) -> None:
        found = find_securecrt()
        if found:
            self.securecrt_var.set(found)
            self._log(f"检测到 SecureCRT: {found}")
        else:
            messagebox.showinfo("提示", "未自动检测到 SecureCRT，请手动指定")

    def _browse_excel(self) -> None:
        initial = self.excel_var.get() or default_excel_name()
        path = filedialog.asksaveasfilename(
            title="选择 Excel 保存位置",
            defaultextension=".xlsx",
            initialfile=Path(initial).name,
            initialdir=str(Path(initial).parent) if Path(initial).parent.exists() else None,
            filetypes=[("Excel 文件", "*.xlsx")],
        )
        if path:
            self.excel_var.set(path)

    # ---------- 运行控制 ----------

    def _validate(self) -> str:
        if not self.cfg.servers:
            return "服务器清单为空"
        if not self.cfg.command.strip():
            return "查询指令为空"
        if not self.cfg.excel_path.strip():
            return "请指定 Excel 保存位置"
        if not self.cfg.sim_mode:
            if not self.cfg.securecrt_path.strip() or not Path(self.cfg.securecrt_path).exists():
                return "SecureCRT.exe 路径无效（模拟模式下不需要）"
        return ""

    def _on_start(self) -> None:
        self._sync_config_from_ui()
        err = self._validate()
        if err:
            messagebox.showerror("参数错误", err)
            return
        if Path(self.cfg.excel_path).exists():
            if not messagebox.askyesno("确认", f"文件已存在，是否覆盖？\n{self.cfg.excel_path}"):
                return
        if not self.cfg.sim_mode:
            self._log("提示：运行期间会弹出 SecureCRT 窗口，请勿手动操作这些窗口")
        self._save_config()
        work = app_dir()
        run_cfg = RunConfig(
            command=self.cfg.command.strip(),
            timeout=self.cfg.timeout,
            concurrency=self.cfg.concurrency,
            sim_mode=self.cfg.sim_mode,
            securecrt_path=self.cfg.securecrt_path,
            engine_path=resource_path("engine/engine.vbs"),
            task_dir=work / "task",
            results_dir=work / "results",
            stop_flag_path=work / "stop.flag",
            per_deadline=self.cfg.timeout + 150,
            on_event=self._on_event,
        )
        self.runner = Runner(list(self.cfg.servers), run_cfg)
        self._reset_status_ui()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.runner.start()
        self.root.after(self.POLL_MS, self._tick)

    def _on_stop(self) -> None:
        if self.runner:
            self.runner.request_stop()
            self._log("已请求停止")

    def _tick(self) -> None:
        if self.runner and self.runner.tick():
            self._on_done()
        elif self.runner:
            total = max(len(self.runner._records), 1)
            done = sum(1 for r in self.runner._records if r.done)
            self.progress["value"] = done * 100.0 / total
            self.root.after(self.POLL_MS, self._tick)

    def _on_done(self) -> None:
        results = self.runner.results()
        for r in results:
            if r.status == "SUCCESS":
                r.alarms = parse_output(read_raw(r.raw_path))
        try:
            write_workbook(Path(self.cfg.excel_path), results)
        except Exception as e:
            messagebox.showerror("错误", f"生成 Excel 失败：{e}")
        ok = sum(1 for r in results if r.status == "SUCCESS")
        bad = len(results) - ok
        self.progress["value"] = 100
        self._log(f"完成：成功 {ok} 台，失败/停止 {bad} 台，已保存到 {self.cfg.excel_path}")
        messagebox.showinfo("完成", f"成功 {ok} 台，失败/停止 {bad} 台\nExcel 已保存到：\n{self.cfg.excel_path}")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.runner = None

    def _on_event(self, event: str, ip: str, payload: str) -> None:
        if event == "log":
            self._log(f"[{ip}] {payload}" if ip else payload)
        elif event == "status":
            self._log(f"[{ip}] {payload}")
            self._update_status_row(ip, payload)

    def _reset_status_ui(self) -> None:
        self.status_tree.delete(*self.status_tree.get_children())
        for s in self.cfg.servers:
            self.status_tree.insert("", "end", values=(s.ip, s.hostname, "等待中"))
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
        self.progress["value"] = 0

    def _update_status_row(self, ip: str, status: str) -> None:
        status_cn = {"SUCCESS": "成功", "FAIL": "失败", "STOPPED": "已停止"}.get(status, status)
        for iid in self.status_tree.get_children():
            if self.status_tree.item(iid, "values")[0] == ip:
                values = list(self.status_tree.item(iid, "values"))
                values[2] = status_cn
                self.status_tree.item(iid, values=values)
                return

    # ---------- 配置与日志 ----------

    def _sync_config_from_ui(self) -> None:
        self.cfg.servers = self._servers_from_tree()
        self.cfg.command = self.command_var.get()
        self.cfg.timeout = int(self.timeout_var.get())
        self.cfg.concurrency = int(self.concurrency_var.get())
        self.cfg.sim_mode = bool(self.sim_var.get())
        self.cfg.securecrt_path = self.securecrt_var.get().strip()
        self.cfg.excel_path = self.excel_var.get().strip()

    def _load_from_config(self) -> None:
        self.securecrt_var.set(self.cfg.securecrt_path or find_securecrt())
        self.excel_var.set(self.cfg.excel_path or str(app_dir() / default_excel_name()))
        self.command_var.set(self.cfg.command)
        self.timeout_var.set(self.cfg.timeout)
        self.concurrency_var.set(self.cfg.concurrency)
        self.sim_var.set(self.cfg.sim_mode)
        self._refresh_server_tree()

    def _save_config(self) -> None:
        cfg_save(self.cfg_path, self.cfg)

    def _on_close(self) -> None:
        self._sync_config_from_ui()
        self._save_config()
        self.root.destroy()

    def _log(self, msg: str) -> None:
        self.log_text.config(state="normal")
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
```

- [ ] **Step 3: 静态检查**

```bash
.venv/Scripts/python -m py_compile app.py tool/ui.py
```

Expected: 无输出（编译通过）

- [ ] **Step 4: 模拟模式端到端手动验证（开发机）**

1. 启动：`.venv/Scripts/python app.py`
2. 确认默认勾选"模拟取数"，SecureCRT 路径留空，保存位置使用默认文件名
3. 点击"粘贴多行"，在任意编辑器复制以下两行后粘贴：

```
188.12.4.21 GDHEY-MS-IPMAN-BNG01-LPLJ-HW heyuanyingji HYhch!123
188.12.4.147 GDHEY-MS-IPMAN-BNG01-LPXD-HW heyuanyingji HYhch!123
```

4. 再粘贴 3 次（凑 5 台，验证成功/失败混合——第 5 台模拟失败）
5. 指令保持 `disp alarm hardware`，点击"开始"
6. 预期：状态列表逐台变为 成功/失败（第 5 台失败"输出为空(模拟)"），进度条到 100%，弹出完成提示
7. 打开生成的 Excel，核对："明细"表有 4 台设备的告警行（第 1 台 1 条、第 2 台 3 条、第 3 台 0 条、第 4 台 2 条），"汇总"表 5 行状态正确、第 5 台失败原因"输出为空(模拟)"
8. 关闭窗口重新打开：清单、指令、保存位置均已恢复（config.json 生效）

Expected: 全部符合，无异常。

- [ ] **Step 5: 提交**

```bash
git add app.py tool/ui.py
git commit -m "feat: tkinter main window with batch server list and run controls"
```

---

## Task 9: PyInstaller 打包

**Files:**
- Create: `build.bat`

- [ ] **Step 1: 创建 build.bat**

```bat
@echo off
cd /d %~dp0
call .venv\Scripts\activate.bat
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name "SecureCRT批量取数工具" ^
  --add-data "engine\engine.vbs;engine" ^
  --add-data "samples;samples" ^
  app.py
echo.
echo 生成: dist\SecureCRT批量取数工具.exe
pause
```

- [ ] **Step 2: 打包**

```bash
cmd //c build.bat
```

Expected: 结束显示 `dist\SecureCRT批量取数工具.exe`

- [ ] **Step 3: 验证打包产物（模拟模式）**

1. 运行 `dist/SecureCRT批量取数工具.exe`
2. 重复 Task 8 Step 4 的模拟模式流程（粘贴 5 台、开始、核对 Excel）
3. 确认 exe 目录下生成了 `config.json`（配置在 exe 旁，而非解包临时目录）

Expected: 与开发模式行为一致。

- [ ] **Step 4: 提交**

```bash
git add build.bat
git commit -m "build: pyinstaller one-file packaging script"
```

---

## Task 10: 使用说明与真实环境验证清单

**Files:**
- Create: `docs/使用与验证说明.md`

- [ ] **Step 1: 创建文档**

内容：

```markdown
# SecureCRT 批量取数工具 — 使用与验证说明

## 部署

1. 把 `SecureCRT批量取数工具.exe` 拷贝到装有 SecureCRT 的机器任意目录（如 D:\tools\），双击运行。
2. 无需安装 Python、Office。

## 使用步骤

1. 首次打开：点"自动检测"定位 SecureCRT.exe；检测不到就点"浏览..."手动选。
2. 填服务器清单：点"粘贴多行"（格式：`IP 主机名 账号 密码`，空格分隔，一行一台），或"导入文件..."选 txt；也可点"添加"逐台录入，双击行可编辑。
3. 填查询指令（如 `disp alarm hardware`）、超时秒数（默认 60）、并发数（默认 5）。
4. 点"浏览..."选 Excel 保存位置（默认生成"SecureCRT巡检结果_日期时间.xlsx"）。
5. **取消勾选"模拟取数"**，点"开始"。
6. 运行期间会弹出 SecureCRT 窗口，**不要手动操作这些窗口**。完成后弹窗提示，Excel 已保存。
7. 结束后 SecureCRT 里会残留空的连接标签页，手动关闭即可。

## 真实环境验证清单（首次使用必须逐项验证）

| # | 场景 | 预期 |
|---|------|------|
| 1 | 1 台正常设备取数 | 状态"成功"，明细表有告警行，汇总表计数正确 |
| 2 | 密码错误 | 状态"失败"，原因"连接后30秒未出现命令提示符..."，继续跑其他机器 |
| 3 | IP 不可达 | 同上，注意等待时间受 SecureCRT 全局连接超时设置影响（默认约 1 分钟） |
| 4 | 指令执行超时 | 把超时设为 5 秒跑真实指令，状态"失败"，原因"指令执行超时" |
| 5 | 5 台并发混合成功失败 | 成功失败互不影响，汇总表正确 |
| 6 | 运行中点"停止" | 未开始的机器记为"已停止"，已开始的等其自然结束 |
| 7 | 分页验证 | 找一台告警很多的设备跑 `disp alarm hardware`，确认明细行数与设备上一致（关分页命令生效） |
| 8 | 提示符格式 | 若设备登录后提示符不是 `<主机名>` 格式（如系统视图 `[主机名]` 或自定义），需调整 engine.vbs 中的 `WaitForString("<", ...)` 与 ReadString 提示符匹配 |
| 9 | 提示符与清单一致性 | 若某台报"输出捕获异常(提示符与清单主机名可能不符)"，核对清单里该台的主机名是否与设备实际提示符一致 |

## 已知限制

- 密码中不能含双引号 `"`（SecureCRT /PASSWORD 参数解析限制）。
- 设备提示符需为华为 VRP 默认 `<主机名>` 格式。
- IP 不可达的等待时间受 SecureCRT 全局选项"连接超时"控制，可调小加快失败反馈。
- 任务文件（含明文密码）在运行目录 task/ 下，运行结束后不自动删除（results/ 保留供排障）；敏感环境请定期清理。

## 故障排查

- 界面日志会记录每台状态；原始输出在程序目录 `results/<IP>_raw.txt`，失败时先看这个文件。
- Excel 生成失败：检查保存路径是否被占用（文件在 Excel 中打开着）。
```

- [ ] **Step 2: 提交**

```bash
git add docs/使用与验证说明.md
git commit -m "docs: usage guide and real-environment validation checklist"
```

---

## Self-Review 记录

（计划作者自查，供执行者参考）

1. **Spec 覆盖**：界面（Task 8）、清单导入/粘贴/编辑（Task 8）、指令+超时+并发+模拟模式（Task 8）、SecureCRT 路径检测（Task 5）、保存位置指定与覆盖提示（Task 8）、并发调度与停止（Task 6）、取数引擎与失败场景（Task 7）、解析与 Excel（Task 1/3）、配置持久化（Task 4）、模拟模式样例（Task 1/4/6）、打包（Task 9）、真实环境验证清单（Task 10）。已核对设计文档第 2-7 节均有对应任务。
2. **占位符**：无 TBD/TODO；所有代码步骤含完整代码。
3. **接口一致性**：任务文件 8 行格式在 taskfiles.py（写）与 engine.vbs（读）两侧一致；状态取值 SUCCESS/FAIL/STOPPED 在 runner、ui、excel_writer、simulation 四处一致；`ServerResult` 字段（ip/hostname/status/reason/raw_path/alarms）在 taskfiles.py 定义、runner/excel_writer/ui 使用一致。
