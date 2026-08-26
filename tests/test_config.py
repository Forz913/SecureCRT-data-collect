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


def test_string_false_is_parsed_as_false(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text('{"sim_mode": "false"}', encoding="utf-8")
    assert load(p).sim_mode is False
    p.write_text('{"sim_mode": "true"}', encoding="utf-8")
    assert load(p).sim_mode is True


def test_bad_field_does_not_discard_servers(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text(
        '{"timeout": "abc", "servers": [["1.1.1.1", "h1", "u1", "p1"]]}',
        encoding="utf-8",
    )
    cfg = load(p)
    assert cfg.timeout == 60  # 坏字段回退默认值
    assert len(cfg.servers) == 1  # 服务器清单保留


def test_wrong_length_server_entry_filtered(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text(
        '{"servers": [["1.1.1.1", "h1", "u1", "p1"], ["2.2.2.2", "h2"]]}',
        encoding="utf-8",
    )
    cfg = load(p)
    assert [s.ip for s in cfg.servers] == ["1.1.1.1"]
