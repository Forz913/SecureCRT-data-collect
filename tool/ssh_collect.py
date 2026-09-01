"""paramiko 直连取数：行读取器 + 取数状态机 + 错误映射入口。"""
from __future__ import annotations

import re
import socket
import time
from dataclasses import dataclass

import paramiko


class StoppedError(Exception):
    """用户请求停止。"""


class ConnectionClosed(Exception):
    """SSH 连接被远端关闭。"""


@dataclass
class CollectResult:
    status: str  # SUCCESS / FAIL / STOPPED
    reason: str
    output: str


def prompt_re(hostname: str) -> re.Pattern:
    """提示符三形态整行匹配：<h> / [h] / 裸 h>。"""
    h = re.escape(hostname)
    return re.compile(rf"^\s*(?:<{h}>|\[{h}\]|{h}>)\s*$")


class ChannelReader:
    """从 paramiko channel 按行读取（缓冲 + 调用方给定单次超时上限）。"""

    def __init__(self, chan):
        self._chan = chan
        self._buf = b""

    def read_line(self, timeout_s: float) -> str | None:
        """返回一行（不含行尾换行）；超时返回 None；连接关闭抛 ConnectionClosed。"""
        deadline = time.monotonic() + timeout_s
        while b"\n" not in self._buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._chan.settimeout(remaining)
            try:
                data = self._chan.recv(4096)
            except socket.timeout:
                continue
            if not data:
                raise ConnectionClosed
            self._buf += data
        line, self._buf = self._buf.split(b"\n", 1)
        return line.rstrip(b"\r").decode("utf-8", errors="replace")


def collect_output(
    reader,
    send,
    hostname: str,
    command: str,
    timeout_s: int,
    is_stopped,
    prompt_timeout: float = 30.0,
    screen_timeout: float = 15.0,
) -> CollectResult:
    """取数状态机。reader.read_line(timeout)->str|None；send(text)；is_stopped()->bool。

    prompt_timeout/screen_timeout 为参数便于测试注入短超时。
    """
    try:
        if not _wait_for_prompt(reader, hostname, prompt_timeout, is_stopped):
            return CollectResult(
                "FAIL",
                "连接后30秒未出现命令提示符(连接失败/认证失败/不可达/主机名与提示符不符)",
                "",
            )
        send("screen-length 0 temporary")
        if not _wait_for_prompt(reader, hostname, screen_timeout, is_stopped):
            return CollectResult("FAIL", "关闭分页后未回到命令提示符", "")
        send(command)
        outcome, lines = _read_command_output(reader, send, hostname, timeout_s, is_stopped)
        output = "\n".join(lines)
        if outcome == "timeout":
            return CollectResult(
                "FAIL", f"指令执行超时({timeout_s}秒，已保留已收内容)", output
            )
        if sum(len(line.strip()) for line in lines) < 1:
            return CollectResult("FAIL", "输出为空", output)
        return CollectResult("SUCCESS", "", output)
    except StoppedError:
        return CollectResult("STOPPED", "用户停止", "")
    except ConnectionClosed:
        return CollectResult("FAIL", "SSH连接被远端关闭", "")


def collect_from_server(
    ip, user, password, hostname, command, timeout_s, is_stopped,
    port: int = 22, connect_timeout: int = 30,
) -> CollectResult:
    """连接真实服务器并取数；连接层错误映射为失败原因。"""
    from tool.ssh_client import connect_channel  # 延迟导入：状态机单测不依赖该模块

    try:
        client, chan, legacy = connect_channel(ip, user, password, port, connect_timeout)
    except paramiko.AuthenticationException:
        return CollectResult("FAIL", "认证失败(用户名或密码错误)", "")
    except paramiko.SSHException as e:
        return CollectResult("FAIL", f"SSH协商失败: {e}", "")
    except (OSError, socket.timeout) as e:
        return CollectResult("FAIL", f"连接失败/不可达: {e}", "")
    try:
        reader = ChannelReader(chan)
        send = lambda text: chan.send((text + "\n").encode("utf-8"))
        return collect_output(reader, send, hostname, command, timeout_s, is_stopped)
    finally:
        try:
            chan.close()
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass


def _wait_for_prompt(reader, hostname, timeout_s, is_stopped) -> bool:
    re_prompt = prompt_re(hostname)
    deadline = time.monotonic() + timeout_s
    while True:
        if is_stopped():
            raise StoppedError
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        line = reader.read_line(min(remaining, 2.0))
        if line is None:
            continue
        if re_prompt.match(line):
            return True


def _read_command_output(reader, send, hostname, timeout_s, is_stopped):
    """返回 ("done"|"timeout", 输出行列表)。"""
    re_prompt = prompt_re(hostname)
    lines = []
    deadline = time.monotonic() + timeout_s
    while True:
        if is_stopped():
            raise StoppedError
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "timeout", lines
        line = reader.read_line(min(remaining, 2.0))
        if line is None:
            continue
        if re_prompt.match(line):
            return "done", lines
        if "---- More ----" in line:
            send(" ")
            continue
        lines.append(line)
