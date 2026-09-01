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
