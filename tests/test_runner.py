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
