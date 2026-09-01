# v2 paramiko 直连 SSH 改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `v2-paramiko` 分支上用 paramiko 直连 SSH 完全替换 SecureCRT 取数引擎，取数无需 SecureCRT、目标机器零依赖、线程化架构。

**Architecture:** 每台服务器一个守护线程跑取数状态机（tool/ssh_collect.py：连接→关分页→发指令→按行读输出→三形态提示符/分页标记判定）；事件经线程安全队列回传，Runner 保持 v1 的 start/tick/progress/results 外部接口不变，UI 改动最小；raw 文本落盘 results/<run_id>/<IP>_raw.txt 供排障。

**Tech Stack:** Python 3.13、paramiko 5.0、threading、queue、Tkinter、openpyxl、pytest、PyInstaller。

**Spec:** [2026-08-31-paramiko-direct-ssh-v2-design.md](../specs/2026-08-31-paramiko-direct-ssh-v2-design.md)

**已确认的环境事实（作者实测）：** paramiko 5.0.0 已装入 venv；`SSHClient.connect` 无 `server_host_key_algs` 参数，有 `disabled_algorithms`/`transport_factory`；`Transport.__init__` 默认 `strict_kex=True`（老设备兼容回退用 `transport_factory` 注入 `Transport(sock, strict_kex=False)`）；真机提示符为裸 `主机名>`（v1 实测）。

---

## File Structure

```
tool/
├── ssh_collect.py       NEW：取数状态机 + ChannelReader + collect_from_server（错误映射）
├── ssh_client.py        NEW：paramiko 连接封装（算法协商失败→strict_kex=False 重试）
├── runner.py            REWRITE：线程池调度（接口保持 start/tick/progress/results/request_stop）
├── simulation.py        MODIFY：返回 (raw, status, reason) 元组，不再写状态文件
├── taskfiles.py         MODIFY：删 write_task_file/write_status/read_status，保留 Server/ServerResult/read_raw/is_valid_ip/parse_server_line
├── config.py            MODIFY：删 securecrt_path 字段
├── ui.py                MODIFY：删 SecureCRT 路径行及相关方法
├── locate.py            DELETE
engine/engine.vbs        DELETE
tests/
├── test_ssh_collect.py       NEW：状态机单测（注入 FakeReader/FakeSender）
├── fake_huawei_server.py     NEW：本地模拟华为设备 SSH 服务
├── test_ssh_client_e2e.py    NEW：真实 socket 端到端（fake 服务器）
├── test_runner.py            REWRITE：线程版
├── test_taskfiles.py         MODIFY：删任务/状态文件用例
├── test_config.py            MODIFY：删 securecrt_path 断言
├── test_engine_encoding.py   DELETE
└── test_locate.py            DELETE
requirements.txt          MODIFY：+paramiko>=5.0
build.bat                 MODIFY：删 engine --add-data
```

**新接口约定（本计划内所有引用一致）：**

- `CollectResult`（tool/ssh_collect.py）：`status: str`（SUCCESS/FAIL/STOPPED）、`reason: str`、`output: str`
- `collector` 注入签名：`(server: Server, index: int, cfg: RunConfig, is_stopped: Callable[[], bool]) -> CollectResult`
- 提示符三形态：`<主机名>`、`[主机名]`、裸 `主机名>`，行尾整行匹配

---

## Task 0: 分支与依赖准备

**Files:**
- Modify: `requirements.txt`
- Delete: `engine/engine.vbs`、`tests/test_engine_encoding.py`

- [ ] **Step 1: 切分支**

```bash
cd /e/cmcc/work/excel-tool0826
git checkout -b v2-paramiko
git branch --show-current
```

Expected: `v2-paramiko`

- [ ] **Step 2: 加依赖并安装**

`requirements.txt` 变为：

```
openpyxl>=3.1
paramiko>=5.0
pyinstaller>=6.10
pytest>=8.0
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -c "import paramiko; print(paramiko.__version__)"
```

Expected: 打印 5.0.0

- [ ] **Step 3: 删除引擎文件**

```bash
git rm engine/engine.vbs tests/test_engine_encoding.py
```

- [ ] **Step 4: 跑测试确认当前状态（test_locate 尚在，后续任务删除）**

```bash
.venv/Scripts/python -m pytest tests/ -q
```

Expected: 45 passed（47 - 2 个引擎编码测试）

- [ ] **Step 5: 提交**

```bash
git commit -m "chore: start v2 branch, add paramiko, drop vbs engine"
```

---

## Task 1: 取数状态机 ssh_collect.py（TDD）

**Files:**
- Create: `tool/ssh_collect.py`
- Test: `tests/test_ssh_collect.py`

- [ ] **Step 1: 写失败测试**

`tests/test_ssh_collect.py`：

```python
from tool.ssh_collect import (
    CollectResult,
    ConnectionClosed,
    collect_output,
    prompt_re,
)


class FakeReader:
    """脚本化行源：按顺序吐出行，耗尽后返回 None（超时）。"""

    def __init__(self, script):
        self._lines = list(script)

    def read_line(self, timeout_s):
        if self._lines:
            return self._lines.pop(0)
        return None


class FakeSender:
    def __init__(self):
        self.sent = []

    def __call__(self, text):
        self.sent.append(text)


def run(script, hostname="GDHEY-TEST", command="disp alarm hardware",
        timeout=30, stopped=None, prompt_timeout=30, screen_timeout=15):
    sender = FakeSender()
    result = collect_output(
        FakeReader(script), sender, hostname, command, timeout,
        stopped or (lambda: False), prompt_timeout, screen_timeout,
    )
    return result, sender


def test_prompt_re_matches_three_forms():
    re_p = prompt_re("GDHEY-TEST")
    assert re_p.match("GDHEY-TEST>")
    assert re_p.match("<GDHEY-TEST>")
    assert re_p.match("[GDHEY-TEST]")
    assert re_p.match("  GDHEY-TEST>  ")
    assert re_p.match("GDHEY-TEST>disp alarm hardware") is None
    assert re_p.match("OTHER>") is None


def test_normal_flow_with_bare_prompt():
    result, sender = run([
        "GDHEY-TEST>",                       # 初始提示符
        "GDHEY-TEST>",                       # 关分页后提示符
        "a table line",
        "second line",
        "GDHEY-TEST>",                       # 输出结束提示符
    ])
    assert result.status == "SUCCESS"
    assert result.output == "a table line\nsecond line"
    assert sender.sent == ["screen-length 0 temporary", "disp alarm hardware"]


def test_bracket_prompt_forms_also_succeed():
    for form in ("<GDHEY-TEST>", "[GDHEY-TEST]"):
        result, _ = run([form, form, "row1", form])
        assert result.status == "SUCCESS", form


def test_more_pagination_sends_space():
    result, sender = run([
        "GDHEY-TEST>", "GDHEY-TEST>",
        "row1", "---- More ----", "row2", "GDHEY-TEST>",
    ])
    assert result.status == "SUCCESS"
    assert result.output == "row1\nrow2"
    assert " " in sender.sent


def test_initial_prompt_timeout():
    result, _ = run([], prompt_timeout=0.1)
    assert result.status == "FAIL"
    assert "未出现命令提示符" in result.reason


def test_command_timeout_keeps_received_lines():
    result, _ = run(["GDHEY-TEST>", "GDHEY-TEST>", "row1"], timeout=0.1)
    assert result.status == "FAIL"
    assert "指令执行超时" in result.reason
    assert result.output == "row1"


def test_empty_output_fails():
    result, _ = run(["GDHEY-TEST>", "GDHEY-TEST>", "GDHEY-TEST>"])
    assert result.status == "FAIL"
    assert result.reason == "输出为空"


def test_stopped_returns_stopped():
    result, _ = run(["GDHEY-TEST>"], stopped=lambda: True)
    assert result.status == "STOPPED"
    assert result.reason == "用户停止"


def test_connection_closed_maps_to_fail():
    class ClosedReader(FakeReader):
        def read_line(self, timeout_s):
            raise ConnectionClosed

    result = collect_output(ClosedReader([]), FakeSender(), "GDHEY-TEST",
                            "cmd", 30, lambda: False)
    assert result.status == "FAIL"
    assert "连接被远端关闭" in result.reason
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/Scripts/python -m pytest tests/test_ssh_collect.py -q
```

Expected: FAIL（`ModuleNotFoundError: No module named 'tool.ssh_collect'`）

- [ ] **Step 3: 实现 ssh_collect.py**

`tool/ssh_collect.py`：

```python
"""paramiko 直连取数：行读取器 + 取数状态机 + 错误映射入口。"""
from __future__ import annotations

import re
import socket
import time
from dataclasses import dataclass

import paramiko


class StoppedError(Exception):
    """用户请求停止。"""


class ConnectionClosed(Exception):
    """SSH 连接被远端关闭。"""


@dataclass
class CollectResult:
    status: str  # SUCCESS / FAIL / STOPPED
    reason: str
    output: str


def prompt_re(hostname: str) -> re.Pattern:
    """提示符三形态整行匹配：<h> / [h] / 裸 h>。"""
    h = re.escape(hostname)
    return re.compile(rf"^\s*(?:<{h}>|\[{h}\]|{h}>)\s*$")


class ChannelReader:
    """从 paramiko channel 按行读取（缓冲 + 调用方给定单次超时上限）。"""

    def __init__(self, chan):
        self._chan = chan
        self._buf = b""

    def read_line(self, timeout_s: float) -> str | None:
        """返回一行（不含行尾换行）；超时返回 None；连接关闭抛 ConnectionClosed。"""
        deadline = time.monotonic() + timeout_s
        while b"\n" not in self._buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._chan.settimeout(remaining)
            try:
                data = self._chan.recv(4096)
            except socket.timeout:
                continue
            if not data:
                raise ConnectionClosed
            self._buf += data
        line, self._buf = self._buf.split(b"\n", 1)
        return line.rstrip(b"\r").decode("utf-8", errors="replace")


def collect_output(
    reader,
    send,
    hostname: str,
    command: str,
    timeout_s: int,
    is_stopped,
    prompt_timeout: float = 30.0,
    screen_timeout: float = 15.0,
) -> CollectResult:
    """取数状态机。reader.read_line(timeout)->str|None；send(text)；is_stopped()->bool。

    prompt_timeout/screen_timeout 为参数便于测试注入短超时。
    """
    try:
        if not _wait_for_prompt(reader, hostname, prompt_timeout, is_stopped):
            return CollectResult(
                "FAIL",
                "连接后30秒未出现命令提示符(连接失败/认证失败/不可达/主机名与提示符不符)",
                "",
            )
        send("screen-length 0 temporary")
        if not _wait_for_prompt(reader, hostname, screen_timeout, is_stopped):
            return CollectResult("FAIL", "关闭分页后未回到命令提示符", "")
        send(command)
        outcome, lines = _read_command_output(reader, send, hostname, timeout_s, is_stopped)
        output = "\n".join(lines)
        if outcome == "timeout":
            return CollectResult(
                "FAIL", f"指令执行超时({timeout_s}秒，已保留已收内容)", output
            )
        if sum(len(line.strip()) for line in lines) < 1:
            return CollectResult("FAIL", "输出为空", output)
        return CollectResult("SUCCESS", "", output)
    except StoppedError:
        return CollectResult("STOPPED", "用户停止", "")
    except ConnectionClosed:
        return CollectResult("FAIL", "SSH连接被远端关闭", "")


def collect_from_server(
    ip, user, password, hostname, command, timeout_s, is_stopped,
    port: int = 22, connect_timeout: int = 30,
) -> CollectResult:
    """连接真实服务器并取数；连接层错误映射为失败原因。"""
    from tool.ssh_client import connect_channel  # 延迟导入：状态机单测不依赖该模块

    try:
        client, chan, legacy = connect_channel(ip, user, password, port, connect_timeout)
    except paramiko.AuthenticationException:
        return CollectResult("FAIL", "认证失败(用户名或密码错误)", "")
    except paramiko.SSHException as e:
        return CollectResult("FAIL", f"SSH协商失败: {e}", "")
    except (OSError, socket.timeout) as e:
        return CollectResult("FAIL", f"连接失败/不可达: {e}", "")
    try:
        reader = ChannelReader(chan)
        send = lambda text: chan.send((text + "\n").encode("utf-8"))
        return collect_output(reader, send, hostname, command, timeout_s, is_stopped)
    finally:
        try:
            chan.close()
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass


def _wait_for_prompt(reader, hostname, timeout_s, is_stopped) -> bool:
    re_prompt = prompt_re(hostname)
    deadline = time.monotonic() + timeout_s
    while True:
        if is_stopped():
            raise StoppedError
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        line = reader.read_line(min(remaining, 2.0))
        if line is None:
            continue
        if re_prompt.match(line):
            return True


def _read_command_output(reader, send, hostname, timeout_s, is_stopped):
    """返回 ("done"|"timeout", 输出行列表)。"""
    re_prompt = prompt_re(hostname)
    lines = []
    deadline = time.monotonic() + timeout_s
    while True:
        if is_stopped():
            raise StoppedError
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "timeout", lines
        line = reader.read_line(min(remaining, 2.0))
        if line is None:
            continue
        if re_prompt.match(line):
            return "done", lines
        if "---- More ----" in line:
            send(" ")
            continue
        lines.append(line)
```

（注：`from tool.ssh_client import connect_channel` 为函数内延迟导入（见 Step 3 代码），Task 1 测试在 Task 5 的 ssh_client.py 落地前即可独立运行。）

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/Scripts/python -m pytest tests/test_ssh_collect.py -q
```

Expected: 10 passed

- [ ] **Step 5: 提交**

```bash
git add tool/ssh_collect.py tests/test_ssh_collect.py
git commit -m "feat: ssh collect state machine with prompt-agnostic line matching"
```

---

## Task 2: 线程化 Runner + 模拟模式改造（TDD）

**Files:**
- Create: `tool/runner.py`（整体重写）
- Modify: `tool/simulation.py`
- Test: `tests/test_runner.py`（整体重写）

- [ ] **Step 1: 改造 simulation.py**

`tool/simulation.py` 全文替换为：

```python
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
```

- [ ] **Step 2: 写失败测试（runner 线程版）**

`tests/test_runner.py` 全文替换为：

```python
import threading
import time
from pathlib import Path

from tool.runner import RunConfig, Runner
from tool.ssh_collect import CollectResult
from tool.taskfiles import Server


def make_cfg(tmp_path: Path, **kw) -> RunConfig:
    defaults = dict(
        command="disp alarm hardware",
        timeout=60,
        concurrency=2,
        sim_mode=True,
        results_dir=tmp_path / "results",
        on_event=None,
    )
    defaults.update(kw)
    return RunConfig(**defaults)


def make_servers(n: int) -> list[Server]:
    return [Server(ip=f"10.0.0.{i}", hostname=f"h{i}", username="u", password="p")
            for i in range(1, n + 1)]


def run_until_done(runner: Runner, max_ticks: int = 200) -> bool:
    for _ in range(max_ticks):
        if runner.tick():
            return True
        time.sleep(0.01)
    return False


def test_sim_engine_all_finish(tmp_path: Path):
    r = Runner(make_servers(5), make_cfg(tmp_path))
    r.start()
    assert run_until_done(r)
    results = r.results()
    assert [x.ip for x in results] == [f"10.0.0.{i}" for i in range(1, 6)]
    # 模拟引擎: 序号 4（第 5 台）映射为失败样例，其余成功
    assert [x.status for x in results] == ["SUCCESS"] * 4 + ["FAIL"]
    assert results[4].reason == "输出为空(模拟)"
    # SUCCESS 的 raw 文件已落盘且内容为样例文本
    assert results[0].raw_path is not None
    assert "disp alarm hardware" in results[0].raw_path.read_text(encoding="utf-8")
    # 失败台的已收内容同样落盘供排查（模拟失败样例输出非空）
    assert results[4].raw_path is not None


def test_concurrency_limit_respected(tmp_path: Path):
    gate = threading.Event()
    active: list[str] = []
    lock = threading.Lock()

    def collector(server, index, cfg, is_stopped):
        with lock:
            active.append(server.ip)
        gate.wait(timeout=5)
        with lock:
            active.remove(server.ip)
        return CollectResult("SUCCESS", "", "data")

    cfg = make_cfg(tmp_path, concurrency=2, sim_mode=False, collector=collector)
    r = Runner(make_servers(5), cfg)
    r.start()
    time.sleep(0.2)
    r.tick()
    with lock:
        assert len(active) == 2  # 首批最多并发数台，且前两台未完成不再启动新的
    gate.set()
    assert run_until_done(r)
    assert all(x.status == "SUCCESS" for x in r.results())


def test_stop_marks_running_and_pending(tmp_path: Path):
    gate = threading.Event()

    def collector(server, index, cfg, is_stopped):
        gate.wait(timeout=5)
        if is_stopped():
            return CollectResult("STOPPED", "用户停止", "")
        return CollectResult("SUCCESS", "", "x")

    cfg = make_cfg(tmp_path, concurrency=2, sim_mode=False, collector=collector)
    r = Runner(make_servers(5), cfg)
    r.start()
    time.sleep(0.2)
    r.request_stop()
    gate.set()
    assert run_until_done(r)
    assert all(x.status == "STOPPED" for x in r.results())


def test_collector_exception_maps_to_fail(tmp_path: Path):
    def collector(server, index, cfg, is_stopped):
        raise RuntimeError("boom")

    cfg = make_cfg(tmp_path, concurrency=1, sim_mode=False, collector=collector)
    r = Runner(make_servers(1), cfg)
    r.start()
    assert run_until_done(r)
    results = r.results()
    assert results[0].status == "FAIL"
    assert "采集异常" in results[0].reason


def test_progress_reflects_done_ratio(tmp_path: Path):
    r = Runner(make_servers(4), make_cfg(tmp_path, concurrency=4))
    r.start()
    assert r.progress() == 0.0
    assert run_until_done(r)
    assert r.progress() == 1.0


def test_results_preserve_order(tmp_path: Path):
    r = Runner(make_servers(3), make_cfg(tmp_path, concurrency=3))
    r.start()
    assert run_until_done(r)
    assert [x.ip for x in r.results()] == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
```

（注：`test_sim_engine_all_finish` 已修正：失败台（第 5 台）的模拟输出非空，raw 文件会照常落盘供排查，断言为 `raw_path is not None`。）

- [ ] **Step 3: 运行测试确认失败**

```bash
.venv/Scripts/python -m pytest tests/test_runner.py -q
```

Expected: FAIL（runner.py 仍为 v1 文件轮询版，`RunConfig` 无 `results_dir`/`collector` 字段）

- [ ] **Step 4: 实现 runner.py（整体重写）**

`tool/runner.py` 全文替换为：

```python
"""并发调度器（线程版）：每台服务器一个采集线程，事件经队列回传，tick() 排空。"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from tool.ssh_collect import CollectResult
from tool.taskfiles import Server, ServerResult


@dataclass
class RunConfig:
    command: str
    timeout: int
    concurrency: int
    sim_mode: bool
    results_dir: Path
    on_event: object = None  # (event, ip, payload) -> None
    collector: object = None  # 测试注入: (server, index, cfg, is_stopped) -> CollectResult


def _default_collector(server: Server, index: int, cfg: RunConfig, is_stopped) -> CollectResult:
    if cfg.sim_mode:
        from tool.simulation import simulate_server

        raw, status, reason = simulate_server(server, index)
        return CollectResult(status, reason, raw)
    from tool.ssh_collect import collect_from_server

    return collect_from_server(
        server.ip, server.username, server.password, server.hostname,
        cfg.command, cfg.timeout, is_stopped,
    )


class _Record:
    def __init__(self, server: Server, index: int):
        self.server = server
        self.index = index
        self.done = False
        self.status = "FAIL"
        self.reason = ""
        self.output = ""
        self.raw_path: Path | None = None


class Runner:
    def __init__(self, servers: list[Server], cfg: RunConfig):
        self.cfg = cfg
        self._records = [_Record(s, i) for i, s in enumerate(servers)]
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._next = 0
        self._active = 0
        self._collector = cfg.collector or _default_collector
        self._run_id = ""

    def _run_dir(self) -> Path:
        return self.cfg.results_dir / self._run_id

    def start(self) -> None:
        self._run_id = f"{time.time_ns()}"
        self.cfg.results_dir.mkdir(parents=True, exist_ok=True)
        self._run_dir().mkdir(parents=True, exist_ok=True)
        self._emit("log", "", "开始执行，共 {} 台".format(len(self._records)))
        self._launch_next_batch()

    def _launch_next_batch(self) -> None:
        while (
            self._next < len(self._records)
            and self._active < self.cfg.concurrency
            and not self._stop.is_set()
        ):
            rec = self._records[self._next]
            self._next += 1
            self._active += 1
            self._emit("log", rec.server.ip, "启动取数")
            threading.Thread(target=self._worker, args=(rec,), daemon=True).start()

    def _worker(self, rec: _Record) -> None:
        try:
            result = self._collector(rec.server, rec.index, self.cfg, self._stop.is_set)
        except Exception as e:
            result = CollectResult("FAIL", f"采集异常: {e}", "")
        rec.status, rec.reason, rec.output = result.status, result.reason, result.output
        if rec.output.strip():
            raw = self._run_dir() / f"{rec.server.ip}_raw.txt"
            try:
                raw.write_text(rec.output, encoding="utf-8")
                rec.raw_path = raw
            except OSError:
                pass
        self._queue.put(rec)

    def tick(self) -> bool:
        """排空完成事件并推进调度。全部完成返回 True。"""
        got = False
        while True:
            try:
                rec = self._queue.get_nowait()
            except queue.Empty:
                break
            got = True
            self._active -= 1
            rec.done = True
            self._emit("status", rec.server.ip, rec.status)
        if got:
            self._launch_next_batch()
        if self._stop.is_set():
            for rec in self._records[self._next:]:
                if not rec.done:
                    rec.status, rec.reason = "STOPPED", "用户停止"
                    rec.done = True
                    self._emit("status", rec.server.ip, "STOPPED")
            self._next = len(self._records)
        return all(rec.done for rec in self._records)

    def request_stop(self) -> None:
        self._stop.set()
        self._emit("log", "", "收到停止请求：未开始的机器将记为已停止")

    def progress(self) -> float:
        total = max(len(self._records), 1)
        return sum(1 for rec in self._records if rec.done) / total

    def results(self) -> list[ServerResult]:
        out: list[ServerResult] = []
        for rec in self._records:
            out.append(
                ServerResult(
                    ip=rec.server.ip,
                    hostname=rec.server.hostname,
                    status=rec.status,
                    reason=rec.reason,
                    raw_path=rec.raw_path,
                )
            )
        return out

    def _emit(self, event: str, ip: str, payload: str = "") -> None:
        if self.cfg.on_event:
            self.cfg.on_event(event, ip, payload)
```

- [ ] **Step 5: 运行测试确认通过**

```bash
.venv/Scripts/python -m pytest tests/test_runner.py -q
```

Expected: 6 passed

- [ ] **Step 6: 提交**

```bash
git add tool/runner.py tool/simulation.py tests/test_runner.py
git commit -m "feat: thread-based concurrent runner with injectable collector"
```

---

## Task 3: taskfiles.py 精简（TDD）

**Files:**
- Modify: `tool/taskfiles.py`
- Test: `tests/test_taskfiles.py`

- [ ] **Step 1: 改测试**

`tests/test_taskfiles.py` 全文替换为：

```python
from pathlib import Path

from tool.taskfiles import (
    Server,
    ServerResult,
    is_valid_ip,
    parse_server_line,
    read_raw,
)


def test_parse_server_line():
    s = parse_server_line("188.12.4.21 GDHEY-MS-IPMAN-BNG01-LPLJ-HW heyuanyingji HYhch!123")
    assert s == Server(ip="188.12.4.21", hostname="GDHEY-MS-IPMAN-BNG01-LPLJ-HW",
                       username="heyuanyingji", password="HYhch!123")
    assert parse_server_line("only three fields here") is None
    assert parse_server_line("") is None


def test_is_valid_ip():
    assert is_valid_ip("188.12.4.21")
    assert is_valid_ip("0.0.0.0")
    assert is_valid_ip("255.255.255.255")
    assert not is_valid_ip("999.1.1.1")
    assert not is_valid_ip("1.2.3")
    assert not is_valid_ip("abc")
    assert not is_valid_ip("..\\..\\evil")


def test_read_raw_returns_content(tmp_path: Path):
    p = tmp_path / "x_raw.txt"
    p.write_text("hello\n", encoding="utf-8")
    assert read_raw(p) == "hello\n"


def test_read_raw_handles_utf8_bom(tmp_path: Path):
    p = tmp_path / "x_raw.txt"
    p.write_bytes(b"\xef\xbb\xbfdisp alarm hardware\n")
    assert read_raw(p) == "disp alarm hardware\n"


def test_read_raw_missing_file_returns_empty(tmp_path: Path):
    assert read_raw(tmp_path / "nope_raw.txt") == ""


def test_server_result_defaults():
    r = ServerResult(ip="1.1.1.1", hostname="h", status="SUCCESS", reason="")
    assert r.alarms == []
    assert r.raw_path is None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/Scripts/python -m pytest tests/test_taskfiles.py -q
```

Expected: FAIL（新测试断言 `is_valid_ip` 存在，旧代码是 `_is_ipv4`）

- [ ] **Step 3: 实现 taskfiles.py（全文替换）**

```python
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
```

- [ ] **Step 4: 运行测试确认通过 + 全套回归**

```bash
.venv/Scripts/python -m pytest tests/test_taskfiles.py -q
.venv/Scripts/python -m pytest tests/ -q
```

Expected: 6 passed；全套 22 passed（10 ssh_collect + 6 runner + 6 taskfiles）

- [ ] **Step 5: 提交**

```bash
git add tool/taskfiles.py tests/test_taskfiles.py
git commit -m "refactor: slim taskfiles to server parsing and raw reading"
```

---

## Task 4: config.py 移除 securecrt_path（TDD）

**Files:**
- Modify: `tool/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 改测试**

`tests/test_config.py` 中 `test_roundtrip` 替换为：

```python
def test_roundtrip(tmp_path: Path):
    p = tmp_path / "config.json"
    cfg = AppConfig(
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


def test_load_old_config_with_securecrt_path_is_tolerated(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text(
        '{"securecrt_path": "C:\\\\X\\\\SecureCRT.exe", "command": "disp ver"}',
        encoding="utf-8",
    )
    cfg = load(p)
    assert cfg.command == "disp ver"
    assert cfg.timeout == 60  # 未知/已删字段不影响其余默认值
```

其余测试不变。

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/Scripts/python -m pytest tests/test_config.py -q
```

Expected: FAIL（`AppConfig` 不接受 `securecrt_path` 参数）

- [ ] **Step 3: 实现 config.py 修改**

三处编辑：

(a) dataclass 字段删除 `securecrt_path` 行（`AppConfig` 变为 excel_path/servers/command/timeout/concurrency/sim_mode 六字段）；

(b) `load()` 中删除 `cfg.securecrt_path = str(data.get("securecrt_path", cfg.securecrt_path))` 行（旧配置文件中存在的 securecrt_path 键自然被忽略，兼容 v1 配置）；

(c) `save()` 不变（`asdict(cfg)` 自动只含现有字段）。

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/Scripts/python -m pytest tests/test_config.py -q
```

Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add tool/config.py tests/test_config.py
git commit -m "refactor: drop securecrt path from app config"
```

---

## Task 5: ssh_client.py 连接封装（TDD）

**Files:**
- Create: `tool/ssh_client.py`
- Test: `tests/test_ssh_client.py`

- [ ] **Step 1: 写失败测试**

`tests/test_ssh_client.py`：

```python
import paramiko

from tool.ssh_client import is_algorithm_error


def test_algorithm_error_detection():
    assert is_algorithm_error(paramiko.SSHException("Unable to agree on host key algorithm"))
    assert is_algorithm_error(paramiko.SSHException("no matching key exchange method"))
    assert is_algorithm_error(paramiko.SSHException("kex protocol error"))
    assert not is_algorithm_error(paramiko.SSHException("Connection reset by peer"))
    assert not is_algorithm_error(paramiko.SSHException("timeout"))
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/Scripts/python -m pytest tests/test_ssh_client.py -q
```

Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 ssh_client.py**

```python
"""paramiko 连接封装：宿主密钥自动接受、算法协商失败自动降级重试。"""
from __future__ import annotations

import paramiko

CONNECT_TIMEOUT = 30


def is_algorithm_error(exc: paramiko.SSHException) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("algorithm", "matching", "kex", "host key"))


def connect_channel(ip: str, user: str, password: str, port: int = 22, connect_timeout: int = CONNECT_TIMEOUT):
    """连接并返回 (client, channel, legacy_used)。失败抛异常由调用方映射原因。"""
    try:
        client, chan = _connect(ip, user, password, port, connect_timeout)
        return client, chan, False
    except paramiko.SSHException as e:
        if not is_algorithm_error(e):
            raise
        # 兼容模式：老设备不支持 strict kex 扩展（paramiko 5.x 默认开启）
        client, chan = _connect(ip, user, password, port, connect_timeout, legacy=True)
        return client, chan, True


def _connect(ip, user, password, port, connect_timeout, legacy: bool = False):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = dict(
        username=user, password=password, timeout=connect_timeout,
        look_for_keys=False, allow_agent=False,
        banner_timeout=15, auth_timeout=15,
    )
    if legacy:
        kwargs["transport_factory"] = lambda sock: paramiko.Transport(
            sock, strict_kex=False
        )
    client.connect(ip, port=port, **kwargs)
    chan = client.invoke_shell(width=255, height=50)
    chan.settimeout(0.5)
    return client, chan
```

- [ ] **Step 4: 运行测试确认通过 + 全套回归**

```bash
.venv/Scripts/python -m pytest tests/test_ssh_client.py -q
.venv/Scripts/python -m pytest tests/ -q
```

Expected: 1 passed；全套 23 passed

- [ ] **Step 5: 提交**

```bash
git add tool/ssh_client.py tests/test_ssh_client.py
git commit -m "feat: paramiko connection wrapper with legacy strict-kex fallback"
```

---

## Task 6: 模拟华为设备 SSH 服务器 + 端到端测试（TDD）

**Files:**
- Create: `tests/fake_huawei_server.py`
- Test: `tests/test_ssh_client_e2e.py`

- [ ] **Step 1: 写失败测试**

`tests/test_ssh_client_e2e.py`：

```python
import socket

from tool.ssh_collect import collect_from_server

from tests.fake_huawei_server import FakeServer

TABLE = """--------------------------------------------------------------------------------
Index  Level    Date       Time           Info
--------------------------------------------------------------------------------
1      Critical 2023-04-28 01:02:41+08:00 POWER 25 is failed
--------------------------------------------------------------------------------"""


def test_collect_from_fake_server_success():
    server = FakeServer(responses={"disp alarm hardware": TABLE})
    try:
        result = collect_from_server(
            "127.0.0.1", "u", "p", "GDHEY-TEST",
            "disp alarm hardware", 15, lambda: False, port=server.port,
        )
    finally:
        server.close()
    assert result.status == "SUCCESS", result.reason
    assert "POWER 25 is failed" in result.output
    assert "GDHEY-TEST>" not in result.output  # 提示符行不进入输出


def test_collect_wrong_password():
    server = FakeServer(username="u", password="right")
    try:
        result = collect_from_server(
            "127.0.0.1", "u", "wrong", "GDHEY-TEST",
            "disp alarm hardware", 15, lambda: False, port=server.port,
        )
    finally:
        server.close()
    assert result.status == "FAIL"
    assert "认证失败" in result.reason


def test_collect_empty_response_is_empty_output_fail():
    server = FakeServer()  # 无响应映射：任何指令都直接回提示符
    try:
        result = collect_from_server(
            "127.0.0.1", "u", "p", "GDHEY-TEST",
            "disp alarm hardware", 15, lambda: False, port=server.port,
        )
    finally:
        server.close()
    assert result.status == "FAIL"
    assert result.reason == "输出为空"


def test_collect_unreachable_host():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    result = collect_from_server(
        "127.0.0.1", "u", "p", "h", "cmd", 15, lambda: False,
        port=port, connect_timeout=2,
    )
    assert result.status == "FAIL"
    assert "连接失败" in result.reason


def test_collect_more_pagination_over_real_socket():
    paged = "row1\n  ---- More ----\nrow2"
    server = FakeServer(responses={"disp alarm hardware": paged})
    try:
        result = collect_from_server(
            "127.0.0.1", "u", "p", "GDHEY-TEST",
            "disp alarm hardware", 15, lambda: False, port=server.port,
        )
    finally:
        server.close()
    assert result.status == "SUCCESS", result.reason
    assert result.output == "row1\nrow2"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/Scripts/python -m pytest tests/test_ssh_client_e2e.py -q
```

Expected: FAIL（`ModuleNotFoundError: No module named 'tests.fake_huawei_server'`）

- [ ] **Step 3: 实现 fake_huawei_server.py**

```python
"""本地模拟华为设备 SSH 服务（测试用，真实 socket + paramiko Transport）。"""
from __future__ import annotations

import socket
import threading

import paramiko

_HOST_KEY = None


def _host_key():
    global _HOST_KEY
    if _HOST_KEY is None:
        _HOST_KEY = paramiko.RSAKey.generate(2048)
    return _HOST_KEY


class _ServerImpl(paramiko.ServerInterface):
    def __init__(self, username, password):
        self._username = username
        self._password = password

    def check_auth_password(self, username, password):
        if username == self._username and password == self._password:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True

    def check_channel_shell_request(self, channel):
        return True


class FakeServer:
    """responses: {命令: 响应文本}；每个命令处理后回提示符。prompt 需与测试用 hostname 一致。"""

    def __init__(self, prompt="GDHEY-TEST>", responses=None, username="u", password="p"):
        self.prompt = prompt
        self.responses = responses or {}
        self.username = username
        self.password = password
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            conn, _ = self._sock.accept()
        except OSError:
            return
        transport = paramiko.Transport(conn)
        transport.add_server_key(_host_key())
        transport.start_server(server=_ServerImpl(self.username, self.password))
        chan = transport.accept(10)
        if chan is None:
            transport.close()
            return
        chan.send(f"Welcome banner\r\n{self.prompt}\r\n".encode("utf-8"))
        buf = b""
        while True:
            try:
                data = chan.recv(1024)
            except (OSError, socket.timeout):
                break
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.strip().decode("utf-8", errors="replace")
                if cmd == "screen-length 0 temporary":
                    chan.send(f"{self.prompt}\r\n".encode("utf-8"))
                    continue
                resp = self.responses.get(cmd, "")
                if resp:
                    chan.send((resp + "\r\n").encode("utf-8"))
                chan.send(f"{self.prompt}\r\n".encode("utf-8"))
        transport.close()

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/Scripts/python -m pytest tests/test_ssh_client_e2e.py -q
```

Expected: 5 passed（若个别用例偶发失败，重跑一次——本地 socket 时序敏感）

- [ ] **Step 5: 提交**

```bash
git add tests/fake_huawei_server.py tests/test_ssh_client_e2e.py
git commit -m "test: fake huawei ssh server and end-to-end collection tests"
```

---

## Task 7: ui.py 改造 + 删除 locate（手动验证）

**Files:**
- Modify: `tool/ui.py`
- Delete: `tool/locate.py`、`tests/test_locate.py`

- [ ] **Step 1: ui.py 九处精确修改**

(1) 删除导入行：
```python
from tool.locate import find_securecrt
```

(2) `_build` 中删除整个 SecureCRT 行（row0 块）：
```python
        # 1. SecureCRT 路径
        row0 = ttk.Frame(body)
        row0.pack(fill="x", **pad)
        ttk.Label(row0, text="SecureCRT:").pack(side="left")
        self.securecrt_var = tk.StringVar()
        ttk.Entry(row0, textvariable=self.securecrt_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row0, text="浏览...", command=self._browse_securecrt).pack(side="left", padx=2)
        ttk.Button(row0, text="自动检测", command=self._auto_detect_securecrt).pack(side="left")
```

(3) 删除方法 `_browse_securecrt` 与 `_auto_detect_securecrt`（整段）。

(4) `_validate` 中删除：
```python
        if not self.cfg.sim_mode:
            if not self.cfg.securecrt_path.strip() or not Path(self.cfg.securecrt_path).exists():
                return "SecureCRT.exe 路径无效（模拟模式下不需要）"
```

(5) `_on_start` 中删除日志提示行：
```python
        if not self.cfg.sim_mode:
            self._log("提示：运行期间会弹出 SecureCRT 窗口，请勿手动操作这些窗口")
```

(6) `_on_start` 中 RunConfig 构造替换为：
```python
        run_cfg = RunConfig(
            command=self.cfg.command.strip(),
            timeout=self.cfg.timeout,
            concurrency=self.cfg.concurrency,
            sim_mode=self.cfg.sim_mode,
            results_dir=work / "results",
            on_event=self._on_event,
        )
```
（删除原构造中 securecrt_path/engine_path/task_dir/stop_flag_path/per_deadline 行；`work = app_dir()` 行保留）

(7) `_sync_config_from_ui` 中删除：
```python
        self.cfg.securecrt_path = self.securecrt_var.get().strip()
```

(8) `_load_from_config` 中删除：
```python
        self.securecrt_var.set(self.cfg.securecrt_path or find_securecrt())
```

(9) `_on_close` 替换为：
```python
    def _on_close(self) -> None:
        if self.runner:
            if not messagebox.askyesno("确认", "任务正在运行，确定退出？"):
                return
            self.runner.request_stop()
        self._sync_config_from_ui()
        self._save_config()
        self.root.destroy()
```

- [ ] **Step 2: 删除 locate 模块**

```bash
git rm tool/locate.py tests/test_locate.py
```

- [ ] **Step 3: 静态检查 + 全套测试**

```bash
.venv/Scripts/python -m py_compile app.py tool/ui.py tool/runner.py
.venv/Scripts/python -m pytest tests/ -q
```

Expected: py_compile 无输出；全套 28 passed（23 + 5 e2e）

- [ ] **Step 4: 模拟模式端到端脚本化验证**

写一次性 `_smoke_test.py`（不提交，跑完删除）：

```python
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

messagebox.showinfo = lambda *a, **k: None
messagebox.showerror = lambda *a, **k: None
messagebox.showwarning = lambda *a, **k: None
messagebox.askyesno = lambda *a, **k: True

sys.path.insert(0, str(Path(__file__).parent))

from tool.ui import MainWindow
from tool.taskfiles import Server

out_xlsx = Path(tempfile.gettempdir()) / "smoke_v2_result.xlsx"
root = tk.Tk()
root.withdraw()
win = MainWindow(root)
win.cfg.servers = [
    Server(ip=f"10.0.0.{i}", hostname=f"h{i}", username="u", password="p")
    for i in range(1, 6)
]
win.cfg.sim_mode = True
win.cfg.excel_path = str(out_xlsx)
win._refresh_server_tree()
win.excel_var.set(str(out_xlsx))
win.sim_var.set(True)
win._on_start()

deadline = time.time() + 30
while win.runner is not None and time.time() < deadline:
    root.update()
    time.sleep(0.05)

assert win.runner is None, "运行未在 30 秒内完成"
assert out_xlsx.exists(), "Excel 未生成"

from openpyxl import load_workbook

wb = load_workbook(out_xlsx)
assert wb.sheetnames == ["明细", "汇总", "说明"]
rows = list(wb["汇总"].values)
assert len(rows) == 6, f"汇总应有 6 行(表头+5台)，实际 {len(rows)}"
assert rows[5][2] == "失败", f"第 5 台应为失败，实际 {rows[5]}"
detail = list(wb["明细"].values)
assert len(detail) == 7, f"明细应为 7 行(表头+1+3+0+2+0 条告警)，实际 {len(detail)}"
print("SMOKE TEST PASSED: 汇总 6 行, 明细 7 行, 第5台失败")
root.destroy()
```

```bash
.venv/Scripts/python _smoke_test.py
rm _smoke_test.py
rm -f config.json
```

Expected: `SMOKE TEST PASSED: 汇总 6 行, 明细 7 行, 第5台失败`

- [ ] **Step 5: 提交**

```bash
git add -u
git commit -m "refactor: remove securecrt ui row and locate module"
```

---

## Task 8: 打包脚本与全量验证

**Files:**
- Modify: `build.bat`

- [ ] **Step 1: 修改 build.bat**

删除 `--add-data "engine\engine.vbs;engine" ^` 行（保留 samples 行），其余不变。

- [ ] **Step 2: 全量测试**

```bash
.venv/Scripts/python -m pytest tests/ -q
```

Expected: 28 passed

- [ ] **Step 3: 打包**

```bash
.venv/Scripts/python -m PyInstaller --noconfirm --clean --onefile --windowed --name "SecureCRT批量取数工具" --add-data "samples;samples" app.py
```

Expected: `Build complete! ... dist`（paramiko/cryptography 由 PyInstaller 官方 hooks 支持）

- [ ] **Step 4: 冻结产物验证**

a. exe 存在：`ls -la dist/`（约 20-30MB，paramiko 增加体积属预期）
b. 启动存活（**此检查同时覆盖 paramiko 冻结导入**——ui 模块链导入 runner→ssh_collect→paramiko，导入失败会启动即崩溃）：

```bash
dist/SecureCRT批量取数工具.exe &
sleep 10
tasklist //FI "IMAGENAME eq SecureCRT批量取数工具.exe" | grep -ci securecrt && echo "PROCESS ALIVE"
taskkill //F //IM "SecureCRT批量取数工具.exe"
```

Expected: 进程计数 ≥1（onefile 双进程），PROCESS ALIVE

c. 归档检查：

```bash
.venv/Scripts/python -m PyInstaller.utils.cliutils.archive_viewer -l dist/SecureCRT批量取数工具.exe 2>/dev/null | grep -cE "paramiko|cryptography"
```

Expected: >0（paramiko/cryptography 已入包）

- [ ] **Step 5: 提交**

```bash
git add build.bat
git commit -m "build: drop engine add-data from packaging"
```

---

## Task 9: 文档更新

**Files:**
- Modify: `docs/使用与验证说明.md`、`README.md`

- [ ] **Step 1: 更新 docs/使用与验证说明.md**

替换为：

```markdown
# SecureCRT 批量取数工具 — 使用与验证说明（v2 直连 SSH 版）

## 部署

1. 把 `SecureCRT批量取数工具.exe` 拷贝到**能访问目标服务器的机器**任意可写目录（如 D:\tools\），双击运行。
2. 无需安装 Python、Office、SecureCRT——直连 SSH 取数，运行期间无任何窗口弹出。

## 使用步骤

1. 填服务器清单：点"粘贴多行"（格式：`IP 主机名 账号 密码`，空格分隔，一行一台），或"导入文件..."选 txt；也可点"添加"逐台录入，双击行可编辑。
2. 填查询指令（如 `disp alarm hardware`）、超时秒数（默认 60）、并发数（默认 5）。
3. 点"浏览..."选 Excel 保存位置（默认生成"SecureCRT巡检结果_日期时间.xlsx"）。
4. "模拟取数"默认**关闭**（真实模式）；想先试表格效果可勾选，模拟完成时弹窗和日志会标注"模拟数据，非真实结果！"，Excel 里带"说明"页。
5. 点"开始"，完成后弹窗提示，Excel 已保存。

## 真实环境验证清单（首次使用必须逐项验证）

**最重要的一步：先只放 1 台机器跑一次**，确认直连 SSH 可用后再批量跑。

| # | 场景 | 预期 |
|---|------|------|
| 1 | 1 台正常设备取数 | 状态"成功"，明细表有告警行，汇总表计数正确 |
| 2 | 密码错误 | 状态"失败"，原因"认证失败(用户名或密码错误)"，继续跑其他机器 |
| 3 | IP 不可达 | 状态"失败"，原因"连接失败/不可达"（连接超时 30 秒） |
| 4 | 指令执行超时 | 把超时设为 5 秒跑真实指令，状态"失败"，原因"指令执行超时" |
| 5 | 5 台并发混合成功失败 | 成功失败互不影响，汇总表正确 |
| 6 | 运行中点"停止" | 已启动的机器在数秒内结束并记为"已停止"，未开始的记为"已停止" |
| 7 | 分页验证 | 找一台告警很多的设备跑 `disp alarm hardware`，确认明细行数与设备上一致 |
| 8 | 老设备算法协商 | 若某台报"SSH协商失败"，说明兼容模式（关闭 strict kex）也未通过——把失败原因发给开发人员调整算法集 |
| 9 | 提示符形态 | 引擎自动适配 `<主机名>`、`[主机名]`、裸的 `主机名>`；若设备用其他自定义提示符，报"未出现命令提示符"，把清单主机名改为设备实际提示符文本 |

## 已知限制

- 设备提示符适配 `<主机名>`、`[主机名]`、裸的 `主机名>` 三种形态；其他自定义提示符需核对清单主机名。
- SSH 端口固定 22。
- 程序目录的 `config.json` 以明文保存服务器清单（含密码），请勿外发该文件；密码加密存储列入后续版本计划。
- results/ 保留每轮原始输出供排障，敏感环境请定期清理。

## 故障排查

- 界面日志会记录每台状态；原始输出在程序目录 `results/<run_id>/<IP>_raw.txt`（每轮运行一个子目录，按修改时间取最新一轮），失败时先看这个文件。
- Excel 生成失败：检查保存路径是否被占用（文件在 Excel 中打开着）。
- 全部机器报"连接失败/不可达"：检查清单 IP/账号/密码是否正确、本机网络是否可达目标网段。
- 全部机器报"未出现命令提示符"：核对清单主机名与设备实际提示符是否一致。
```

- [ ] **Step 2: 更新 README.md**

- "功能特性"：删除"SecureCRT 驱动"条目，改为"**直连 SSH 取数**：paramiko 直连（内置兼容模式适配老设备），每台一个线程并发取数（默认 5），运行期间无窗口弹出，目标机器免安装（无需 SecureCRT/Python/Office）"
- "使用"第 1 步删除 SecureCRT 相关描述，第 3 条后补："（v2 直连版无需 SecureCRT；v1 SecureCRT 版见 main 分支）"
- "架构"图替换为：

```
[主程序 exe]  Tkinter 界面 + 线程池调度（每台一个采集线程）
   │  paramiko 直连 SSH：连接 → 关分页 → 发指令 → 按行读输出（提示符/分页判定）
   ▼
[主程序]  解析华为表格输出 → openpyxl 生成 Excel（明细 + 汇总，模拟时附"说明"sheet）
   └── results/<run_id>/<IP>_raw.txt 落盘供排障
```

- "目录"：删除 engine/ 行；tool/ 模块列表更新为（ui/runner/ssh_collect/ssh_client/parser/excel_writer/config/taskfiles/simulation/paths）
- "开发"测试数说明更新为 28 个用例；"打包"命令不变

- [ ] **Step 3: 提交**

```bash
git add docs/使用与验证说明.md README.md
git commit -m "docs: v2 direct-ssh usage guide and readme"
```

---

## Self-Review 记录

1. **Spec 覆盖**：分支策略（Task 0）、删除清单（Task 0/3/4/7）、线程化架构（Task 2）、SSH 细节（Task 5：AutoAddPolicy/超时/严格kex回退；Task 1：UTF-8 errors=replace）、状态机（Task 1）、UI 改动（Task 7）、测试策略（Task 1 单测 + Task 6 e2e + Task 2 线程测试）、打包验证（Task 8）、真机验证清单（Task 9 文档）、范围外（双通道/telnet/跳板机未实现）。spec §7 的"模拟 SSH 服务器"对应 Task 6。
2. **占位符**：无 TBD/TODO；所有代码步骤含完整代码；Task 2 测试中一处防误写占位已在注中标明正确写法。
3. **接口一致性**：`CollectResult(status, reason, output)` 在 ssh_collect 定义、runner/simulation/测试三处一致；collector 签名 `(server, index, cfg, is_stopped)` 在 runner 与全部测试一致；`connect_channel(ip, user, password, port, connect_timeout)` 在 ssh_client 定义、ssh_collect 引用、e2e 测试使用一致；`collect_output(reader, send, hostname, command, timeout_s, is_stopped, prompt_timeout, screen_timeout)` 在状态机测试与实现一致；`simulate_server(server, index) -> (raw, status, reason)` 在 simulation/runner 一致；RunConfig 字段（command/timeout/concurrency/sim_mode/results_dir/on_event/collector）在 runner 定义与 ui Task 7 构造一致。
