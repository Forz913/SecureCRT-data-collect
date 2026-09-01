"""paramiko 连接封装：宿主密钥自动接受、算法协商失败自动降级重试。"""
from __future__ import annotations

import paramiko

CONNECT_TIMEOUT = 30


def is_algorithm_error(exc: paramiko.SSHException) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("algorithm", "matching", "kex", "host key"))


def connect_channel(ip: str, user: str, password: str, port: int = 22, connect_timeout: int = CONNECT_TIMEOUT):
    """连接并返回 (client, channel, legacy_used)。失败抛异常由调用方映射原因。"""
    try:
        client, chan = _connect(ip, user, password, port, connect_timeout)
        return client, chan, False
    except paramiko.SSHException as e:
        if not is_algorithm_error(e):
            raise
        # 兼容模式：老设备不支持 strict kex 扩展（paramiko 5.x 默认开启）
        client, chan = _connect(ip, user, password, port, connect_timeout, legacy=True)
        return client, chan, True


def _connect(ip, user, password, port, connect_timeout, legacy: bool = False):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = dict(
        username=user, password=password, timeout=connect_timeout,
        look_for_keys=False, allow_agent=False,
        banner_timeout=15, auth_timeout=15,
    )
    if legacy:
        kwargs["transport_factory"] = lambda sock: paramiko.Transport(
            sock, strict_kex=False
        )
    client.connect(ip, port=port, **kwargs)
    try:
        chan = client.invoke_shell(width=255, height=50)
    except Exception:
        client.close()
        raise
    chan.settimeout(0.5)
    return client, chan
