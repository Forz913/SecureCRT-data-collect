"""本地模拟华为设备 SSH 服务（测试用，真实 socket + paramiko Transport）。"""
from __future__ import annotations

import socket
import threading

import paramiko

_HOST_KEY = None


def _host_key():
    global _HOST_KEY
    if _HOST_KEY is None:
        _HOST_KEY = paramiko.RSAKey.generate(2048)
    return _HOST_KEY


class _ServerImpl(paramiko.ServerInterface):
    def __init__(self, username, password):
        self._username = username
        self._password = password

    def check_auth_password(self, username, password):
        if username == self._username and password == self._password:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True

    def check_channel_shell_request(self, channel):
        return True


class FakeServer:
    """responses: {命令: 响应文本}；每个命令处理后回提示符。prompt 需与测试用 hostname 一致。"""

    def __init__(self, prompt="GDHEY-TEST>", responses=None, username="u", password="p"):
        self.prompt = prompt
        self.responses = responses or {}
        self.username = username
        self.password = password
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            conn, _ = self._sock.accept()
        except OSError:
            return
        transport = paramiko.Transport(conn)
        transport.add_server_key(_host_key())
        transport.start_server(server=_ServerImpl(self.username, self.password))
        chan = transport.accept(10)
        if chan is None:
            transport.close()
            return
        chan.send(f"Welcome banner\r\n{self.prompt}\r\n".encode("utf-8"))
        buf = b""
        while True:
            try:
                data = chan.recv(1024)
            except (OSError, socket.timeout):
                break
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.strip().decode("utf-8", errors="replace")
                if cmd == "screen-length 0 temporary":
                    chan.send(f"\r\n{self.prompt}\r\n".encode("utf-8"))
                    continue
                resp = self.responses.get(cmd, "")
                if resp:
                    chan.send(resp.encode("utf-8"))
                chan.send(f"\r\n{self.prompt}\r\n".encode("utf-8"))
        transport.close()

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass
