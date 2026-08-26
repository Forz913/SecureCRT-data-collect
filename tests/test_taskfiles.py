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


def test_status_file_exact_bytes(tmp_path: Path):
    p = tmp_path / "results" / "1.2.3.4_status.txt"
    write_status(p, "1.2.3.4", "FAIL", "连接失败")
    data = p.read_bytes()
    assert data == "1.2.3.4\tFAIL\t连接失败".encode("utf-8")
    assert not data.endswith(b"\n")


def test_read_status_handles_utf8_bom(tmp_path: Path):
    p = tmp_path / "results" / "1.2.3.4_status.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\xef\xbb\xbf" + "1.2.3.4\tFAIL\t超时".encode("utf-8"))
    assert read_status(p) == ("FAIL", "超时")


def test_read_raw_handles_utf8_bom(tmp_path: Path):
    p = tmp_path / "results" / "1.2.3.4_raw.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\xef\xbb\xbfdisp alarm hardware\n")
    assert read_raw(p) == "disp alarm hardware\n"


def test_read_raw_returns_content(tmp_path: Path):
    p = tmp_path / "results" / "1.2.3.4_raw.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("hello\n", encoding="utf-8")
    assert read_raw(p) == "hello\n"


def test_read_status_empty_file_returns_none(tmp_path: Path):
    p = tmp_path / "results" / "x_status.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("", encoding="utf-8")
    assert read_status(p) is None
