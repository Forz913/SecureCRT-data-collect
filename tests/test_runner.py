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
    # 完成后清理 stop.flag
    assert not tmp_path.joinpath("stop.flag").exists()


def test_concurrency_limit_respected(tmp_path: Path):
    servers = make_servers(5)
    launched: list[str] = []

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


def test_launcher_failure_marks_record_fail(tmp_path: Path):
    servers = make_servers(1)
    cfg = make_cfg(tmp_path, concurrency=1)

    def bad_launcher(runner, rec):
        raise OSError("模拟启动异常")

    cfg.launcher = bad_launcher
    r = Runner(servers, cfg)
    r.start()
    assert run_until_done(r)
    results = r.results()
    assert results[0].status == "FAIL"
    assert "启动失败" in results[0].reason


def test_success_without_raw_file_becomes_fail(tmp_path: Path):
    servers = make_servers(1)
    cfg = make_cfg(tmp_path, concurrency=1)
    cfg.launcher = lambda runner, rec: write_status(
        tmp_path / "results" / f"{rec.server.ip}_status.txt", rec.server.ip, "SUCCESS", ""
    )
    r = Runner(servers, cfg)
    r.start()
    assert run_until_done(r)
    results = r.results()
    assert results[0].status == "FAIL"
    assert results[0].reason == "原始输出文件缺失"


def test_progress_reflects_done_ratio(tmp_path: Path):
    servers = make_servers(4)
    cfg = make_cfg(tmp_path, concurrency=4)
    r = Runner(servers, cfg)
    r.start()
    assert r.progress() == 0.0
    assert run_until_done(r)
    assert r.progress() == 1.0


def test_cleanup_removes_task_files(tmp_path: Path):
    servers = make_servers(2)
    cfg = make_cfg(tmp_path, concurrency=2)
    # 预置两个任务文件模拟真实模式
    for s in servers:
        task = tmp_path / "task" / f"{s.ip}.txt"
        task.parent.mkdir(parents=True, exist_ok=True)
        task.write_text("x", encoding="utf-8")
    r = Runner(servers, cfg)
    r.start()
    assert run_until_done(r)
    for s in servers:
        assert not (tmp_path / "task" / f"{s.ip}.txt").exists()


def test_stale_run_id_status_is_ignored(tmp_path: Path):
    servers = make_servers(1)
    cfg = make_cfg(tmp_path, concurrency=1, per_deadline=300.0)
    cfg.launcher = lambda runner, rec: None  # 引擎不自动完成
    r = Runner(servers, cfg)
    r.start()
    rid = r._run_id
    write_status(tmp_path / "results" / "10.0.0.1_status.txt",
                 "10.0.0.1", "SUCCESS", "在途", "stale-rid")
    r.tick()
    assert not r._records[0].done  # run_id 不匹配，忽略
    write_status(tmp_path / "results" / "10.0.0.1_status.txt",
                 "10.0.0.1", "SUCCESS", "", rid)
    # 补写原始输出文件：results() 对 SUCCESS 但缺 raw 的记录会降级为 FAIL（见
    # test_success_without_raw_file_becomes_fail），本测试聚焦 run_id 过滤不关心该降级
    (tmp_path / "results" / "10.0.0.1_raw.txt").write_text("ok\n", encoding="utf-8")
    assert run_until_done(r)
    assert r.results()[0].status == "SUCCESS"


def test_real_mode_launcher_writes_task_and_spawns_securecrt(tmp_path: Path):
    import subprocess
    from unittest import mock

    from tool.runner import Runner, _default_launcher

    cfg = make_cfg(tmp_path, sim_mode=False,
                   securecrt_path=r"C:\fake\SecureCRT.exe",
                   engine_path=r"C:\fake\engine.vbs")
    r = Runner(make_servers(1), cfg)
    rec = r._records[0]
    r.start()
    with mock.patch("subprocess.Popen") as popen:
        _default_launcher(r, rec)
    task = tmp_path / "task" / "10.0.0.1.txt"
    assert task.exists()
    assert task.read_text(encoding="utf-8").splitlines()[8] == r._run_id
    args = popen.call_args[0][0]
    assert args[0] == r"C:\fake\SecureCRT.exe"
    assert args[1] == "/SCRIPT"
    assert args[2] == r"C:\fake\engine.vbs"
    assert args[3] == "/ARG"
    assert args[4] == str(task)
    assert popen.call_args[1]["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
