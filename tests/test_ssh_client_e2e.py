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
