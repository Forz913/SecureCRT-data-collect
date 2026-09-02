import socket

import pytest

from tool.ssh_collect import (
    ChannelReader,
    CollectResult,
    ConnectionClosed,
    collect_output,
    prompt_re,
    prompt_tail_re,
)


class FakeReader:
    """脚本化行源：按顺序吐出行，耗尽后返回 None（超时）。"""

    def __init__(self, script):
        self._lines = list(script)

    def read_line(self, timeout_s):
        if self._lines:
            return self._lines.pop(0)
        return None

    def tail_prompt(self, re_prompt):
        return False

    def clear(self):
        pass


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


class FakeChan:
    """伪造 paramiko channel：按脚本吐字节块，耗尽后模拟 socket 超时。"""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.timeout = None

    def settimeout(self, t):
        self.timeout = t

    def recv(self, n):
        if self._chunks:
            return self._chunks.pop(0)
        raise socket.timeout


def test_channel_reader_assembles_lines_across_chunks():
    r = ChannelReader(FakeChan([b"hel", b"lo\r\nwor", b"ld\r\n"]))
    assert r.read_line(1.0) == "hello"
    assert r.read_line(1.0) == "world"


def test_channel_reader_strips_crlf():
    r = ChannelReader(FakeChan([b"a\r\n"]))
    assert r.read_line(1.0) == "a"


def test_channel_reader_replaces_bad_utf8():
    r = ChannelReader(FakeChan([b"\xff\xfe\r\n"]))
    line = r.read_line(1.0)
    assert line is not None
    assert "\r" not in line


def test_channel_reader_raises_connection_closed_on_eof():
    class EofChan(FakeChan):
        def recv(self, n):
            return b""

    r = ChannelReader(EofChan([]))
    with pytest.raises(ConnectionClosed):
        r.read_line(1.0)


def test_screen_length_timeout_branch():
    # 初始提示符出现，关分页后不再出现提示符
    result, _ = run(["GDHEY-TEST>"], screen_timeout=0.1)
    assert result.status == "FAIL"
    assert "关闭分页后未回到命令提示符" in result.reason


def test_prompt_tail_re_matches_buffer_without_newline():
    re_tail = prompt_tail_re("GDHEY-TEST")
    assert re_tail.search("some banner\nGDHEY-TEST>") is not None
    assert re_tail.search("GDHEY-TEST>\r") is not None
    assert re_tail.search("xGDHEY-TEST>") is None  # 非行首
    assert re_tail.search("GDHEY-TEST> ") is not None
    assert re_tail.search("partial") is None


def test_prompt_re_is_case_insensitive():
    assert prompt_re("GDHEY-TEST").match("gdhey-test>")


def test_channel_reader_tail_prompt_and_clear():
    class ChunkChan:
        def __init__(self, chunks):
            self._chunks = list(chunks)

        def settimeout(self, t):
            pass

        def recv(self, n):
            if self._chunks:
                return self._chunks.pop(0)
            raise socket.timeout

    r = ChannelReader(ChunkChan([b"banner\r\nGDHEY-TEST>"]))
    assert r.read_line(0.1) == "banner"
    assert r.tail_prompt(prompt_tail_re("GDHEY-TEST"))
    r.clear()
    assert not r.tail_prompt(prompt_tail_re("GDHEY-TEST"))


def test_initial_timeout_preserves_seen_content():
    # 提示符超时失败时，output 携带已收到的横幅内容（供落盘排障）
    result, _ = run(["Welcome banner", "second line"], prompt_timeout=0.1)
    assert result.status == "FAIL"
    assert result.output == "Welcome banner\nsecond line"
