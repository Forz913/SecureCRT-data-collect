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
    reason: str  # FAIL 时的中文原因；SUCCESS 为空串
    output: str  # 已收屏幕文本；SUCCESS 为完整输出，FAIL 保留已收内容便于排障


def prompt_re(hostname: str) -> re.Pattern:
    """提示符三形态整行匹配：<h> / [h] / 裸 h>。"""
    h = re.escape(hostname)
    return re.compile(rf"^\s*(?:<{h}>|\[{h}\]|{h}>)\s*$", re.IGNORECASE)


def prompt_tail_re(hostname: str) -> re.Pattern:
    """缓冲尾部提示符匹配：真机提示符常无行尾换行（游标停在 > 后）。

    前置 (?:\n|^) 约束保证提示符必须是独立一段的开头，
    避免把命令回显行（如 "GDHEY-TEST>disp xxx"）误判为提示符。
    """
    h = re.escape(hostname)
    return re.compile(rf"(?:\n|^)[ \t]*(?:<{h}>|\[{h}\]|{h}>)[ \t\r]*\Z", re.IGNORECASE)


class ChannelReader:
    """从 paramiko channel 收数据的缓冲读取器。

    接口：fill（阻塞收数据）/ read_line_available（非阻塞取整行）/
    tail_prompt（缓冲尾部提示符检测，提示符可无行尾换行）/ clear。
    """

    def __init__(self, chan):
        self._chan = chan
        self._buf = b""

    def fill(self, timeout_s: float) -> bool:
        """阻塞接收数据填入缓冲；超时返回 False；连接关闭抛 ConnectionClosed。"""
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._chan.settimeout(remaining)
            try:
                data = self._chan.recv(4096)
            except socket.timeout:
                continue
            if not data:
                raise ConnectionClosed
            self._buf += data
            return True

    def read_line_available(self) -> str | None:
        """缓冲中已有完整行则取出一行（不阻塞）；否则返回 None。"""
        if b"\n" not in self._buf:
            return None
        line, self._buf = self._buf.split(b"\n", 1)
        return line.rstrip(b"\r").decode("utf-8", errors="replace")

    def tail_prompt(self, re_prompt) -> bool:
        """缓冲尾部（可无行尾换行）是否以提示符结尾。"""
        text = self._buf.decode("utf-8", errors="replace")
        return re_prompt.search(text) is not None

    def clear(self) -> None:
        self._buf = b""


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
    """取数状态机。reader 需实现 fill/read_line_available/tail_prompt/clear；send(text)；is_stopped()->bool。

    prompt_timeout/screen_timeout 为参数便于测试注入短超时。
    """
    try:
        ok, seen = _wait_for_prompt(reader, hostname, prompt_timeout, is_stopped)
        if not ok:
            return CollectResult(
                "FAIL",
                "连接后30秒未出现命令提示符(连接失败/认证失败/不可达/主机名与提示符不符)",
                seen,
            )
        # 先关分页再发指令：避免输出被 ---- More ---- 分页打断；
        # 关分页失败的老设备由 _read_command_output 里的发空格翻页兜底
        send("screen-length 0 temporary")
        ok, seen = _wait_for_prompt(reader, hostname, screen_timeout, is_stopped)
        if not ok:
            return CollectResult("FAIL", "关闭分页后未回到命令提示符", seen)
        send(command)
        outcome, lines = _read_command_output(reader, send, hostname, timeout_s, is_stopped)
        output = "\n".join(lines)
        if outcome == "timeout":
            return CollectResult(
                "FAIL", f"指令执行超时({timeout_s}秒，已保留已收内容)", output
            )
        if sum(len(line.strip()) for line in lines) < 1:
            # 空输出判定：全部行去空白后无任何内容才算空；
            # 无告警但正常回显表头的设备不会误判（表头+分隔线远不止 1 字符）
            return CollectResult("FAIL", "输出为空", output)
        return CollectResult("SUCCESS", "", output)
    except StoppedError:
        return CollectResult("STOPPED", "用户停止", "")
    except ConnectionClosed:
        # 注意：连接中断时已收内容当前不保留（与超时路径的"已保留已收内容"不同），
        # 设备重启/网络抖动导致输出半截时 raw 不落盘
        return CollectResult("FAIL", "SSH连接被远端关闭", "")


def collect_from_server(
    ip, user, password, hostname, command, timeout_s, is_stopped,
    port: int = 22, connect_timeout: int = 30,
) -> CollectResult:
    """连接真实服务器并取数；连接层错误映射为失败原因。"""
    from tool.ssh_client import connect_channel  # 延迟导入：状态机单测不依赖该模块

    try:
        # legacy 标志（兼容模式是否启用）当前未消费，预留
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


def _wait_for_prompt(reader, hostname, timeout_s, is_stopped):
    """等待提示符。返回 (是否出现, 等待期间收到的文本)。

    事件式检测：每次收到数据立即检查完整行与缓冲尾部，提示符可无行尾换行。
    """
    re_line = prompt_re(hostname)
    re_tail = prompt_tail_re(hostname)
    seen = []
    deadline = time.monotonic() + timeout_s
    while True:
        if is_stopped():
            raise StoppedError
        line = reader.read_line_available()
        if line is not None:
            if re_line.match(line):
                return True, "\n".join(seen)
            seen.append(line)
            continue
        if reader.tail_prompt(re_tail):
            reader.clear()
            return True, "\n".join(seen)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, "\n".join(seen)
        # 0.2 秒切片：即使期间无数据也定期返回循环顶，保证 is_stopped
        # 及时响应；数据一到达就立即检查尾部，慢速输出也不会漏判提示符
        reader.fill(min(remaining, 0.2))


def _read_command_output(reader, send, hostname, timeout_s, is_stopped):
    """返回 ("done"|"timeout", 输出行列表)。事件式检测。"""
    re_line = prompt_re(hostname)
    re_tail = prompt_tail_re(hostname)
    lines = []
    deadline = time.monotonic() + timeout_s
    while True:
        if is_stopped():
            raise StoppedError
        line = reader.read_line_available()
        if line is not None:
            if re_line.match(line):
                return "done", lines
            if "---- More ----" in line:
                # 关分页失败的老设备仍会分页：发空格翻下一页，
                # More 标记行本身不入输出（parser 侧同样忽略）
                send(" ")
                continue
            lines.append(line)
            continue
        if reader.tail_prompt(re_tail):
            reader.clear()
            return "done", lines
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "timeout", lines
        reader.fill(min(remaining, 0.2))  # 同上：0.2 秒切片兼顾停止响应与不漏判
