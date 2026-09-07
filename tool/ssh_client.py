"""paramiko 连接封装：宿主密钥自动接受、算法协商失败自动降级重试。"""
from __future__ import annotations

import paramiko

CONNECT_TIMEOUT = 30  # 默认 TCP 连接超时（秒）


def is_algorithm_error(exc: paramiko.SSHException) -> bool:
    """判断异常是否属于算法协商类（可降级重试），而非认证失败等（重试无意义）。"""
    msg = str(exc).lower()
    return any(k in msg for k in ("algorithm", "matching", "kex", "host key"))


def connect_channel(ip: str, user: str, password: str, port: int = 22, connect_timeout: int = CONNECT_TIMEOUT):
    """连接并返回 (client, channel, legacy_used)。

    legacy_used 表示是否走了兼容模式（第二次连接）；目前调用方未消费该标志（预留）。
    失败抛异常由调用方映射为中文原因（认证失败/协商失败/不可达等）。
    """
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
    """执行单次连接并打开交互 shell 通道。

    关闭密钥文件/agent 探测（look_for_keys/allow_agent=False）：本工具只用
    密码认证，避免探测过程拖慢连接或误选本机私钥。
    """
    client = paramiko.SSHClient()
    # 自动接受任意主机密钥：等价 v1 的 /ACCEPTHOSTKEYS，规格确认过的取舍。
    # 注意：不防中间人，生产网使用存在设备仿冒风险（已知限制）。
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
        # width=255：终端极宽，避免设备按窄终端折行插入换行干扰提示符/表格解析
        chan = client.invoke_shell(width=255, height=50)
    except Exception:
        client.close()
        raise
    chan.settimeout(0.5)  # 读取循环用，配合采集器的剩余时间切片逻辑
    return client, chan
