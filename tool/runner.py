"""并发调度器（线程版）：每台服务器一个采集线程，事件经队列回传。

线程契约（UI 侧必须遵守）：
- start()/tick()/request_stop() 只能由同一线程（UI 线程）调用，不可并发；
- tick() 负责排空队列并推进调度，UI 需周期调用（如 after(400)）；
- results()/progress() 应在 tick() 返回 True（全部完成）后调用，此时所有记录已通过队列完成内存同步；
- worker 线程只写自身记录并 put 队列，不触碰调度状态（_next/_active）。
"""
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
    """默认采集器：模拟模式走 simulation，真实模式走 SSH 直连。

    延迟导入：两个模块互不依赖对方才能加载的组件（真实连接/模拟数据）。
    """
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
    """单台服务器的调度状态，由 worker 线程写入、UI 线程经 tick 读取。"""

    def __init__(self, server: Server, index: int):
        self.server = server
        self.index = index
        self.done = False  # 完成（成功/失败/已停止）才置 True
        self.status = "FAIL"
        self.reason = ""
        self.output = ""
        self.raw_path: Path | None = None


class Runner:
    def __init__(self, servers: list[Server], cfg: RunConfig):
        self.cfg = cfg
        self._records = [_Record(s, i) for i, s in enumerate(servers)]
        self._queue: queue.Queue = queue.Queue()  # worker → UI 线程的结果通道
        self._stop = threading.Event()  # 停止标志，采集器轮询此标志响应停止
        self._next = 0  # 下一台待启动服务器的下标（调度游标）
        self._active = 0  # 当前在跑的 worker 数，上限 concurrency
        self._collector = cfg.collector or _default_collector
        self._run_id = ""  # start() 时赋 time_ns 值

    def _run_dir(self) -> Path:
        return self.cfg.results_dir / self._run_id

    def start(self) -> None:
        """启动调度：为本次运行分配独立目录并发射首批 worker。

        每次运行一个 time_ns 目录：即使上次运行关闭时仍有旧线程在跑，
        它们只会写入旧目录，不会污染本次运行的结果文件。
        """
        self._run_id = f"{time.time_ns()}"
        self.cfg.results_dir.mkdir(parents=True, exist_ok=True)
        self._run_dir().mkdir(parents=True, exist_ok=True)
        self._emit("log", "", "开始执行，共 {} 台".format(len(self._records)))
        self._launch_next_batch()

    def _launch_next_batch(self) -> None:
        """按并发上限启动下一批 worker；停止标志置位后不再启动新的。"""
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
        """单台采集线程：任何异常兜底为 FAIL，结果必定经队列回传。

        全路径 try/except + finally put 保证调度器不会因采集器抛异常而卡死。
        """
        result = CollectResult("FAIL", "采集异常: 未知错误", "")
        try:
            try:
                result = self._collector(rec.server, rec.index, self.cfg, self._stop.is_set)
            except Exception as e:
                result = CollectResult("FAIL", f"采集异常: {e}", "")
            rec.status, rec.reason, rec.output = result.status, result.reason, result.output
            if rec.output.strip():
                # 原始输出落盘到本次运行目录，供 UI 解析与排障
                raw = self._run_dir() / f"{rec.server.ip}_raw.txt"
                try:
                    raw.write_text(rec.output, encoding="utf-8")
                    rec.raw_path = raw
                except OSError:
                    pass
        except Exception:
            rec.status, rec.reason = "FAIL", "采集异常: 结果处理失败"
        finally:
            # 注：BaseException（如 KeyboardInterrupt）会绕过此处，属进程级终止，可接受
            self._queue.put(rec)

    def tick(self) -> bool:
        """排空完成事件并推进调度。全部完成返回 True。

        队列排空后才补发下一批（先收账再放新任务）；停止标志置位时，
        尚未开始的机器就地记为 STOPPED。results()/progress() 应在
        本方法返回 True 后调用——那时所有 worker 已完成并经队列同步。
        """
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
        """请求停止：置停止标志，在跑的 worker 由采集器轮询感知后自行结束。"""
        self._stop.set()
        self._emit("log", "", "收到停止请求：未开始的机器将记为已停止")

    def progress(self) -> float:
        """完成比例（0.0-1.0），供进度条显示。"""
        total = max(len(self._records), 1)
        return sum(1 for rec in self._records if rec.done) / total

    def results(self) -> list[ServerResult]:
        """导出全部结果；须在 tick() 返回 True 后调用（见模块级线程契约）。"""
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
        """向 on_event 回调转发事件；回调在 UI 线程上下文执行（见线程契约）。"""
        if self.cfg.on_event:
            self.cfg.on_event(event, ip, payload)
