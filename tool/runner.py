"""并发调度器：按并发数分批启动取数引擎，轮询状态文件汇总结果。

完成判定以各台状态文件为准（SecureCRT 单实例复用导致进程退出不代表任务完成）。
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from tool.taskfiles import (
    Server,
    ServerResult,
    read_status,
    write_status,
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
                if rec.launch_time is not None:
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
                try:
                    self._launcher(self, rec)
                except Exception as e:
                    # 启动异常不中断整个批次：记为失败，由状态轮询收敛
                    write_status(self._status_path(rec), rec.server.ip, "FAIL", f"启动失败: {e}")
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
        for rec in self._records:
            p = self.cfg.task_dir / f"{rec.server.ip}.txt"
            if p.exists():
                p.unlink()

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

    def progress(self) -> float:
        """完成比例 0.0-1.0。"""
        total = max(len(self._records), 1)
        return sum(1 for rec in self._records if rec.done) / total
