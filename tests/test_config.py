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
