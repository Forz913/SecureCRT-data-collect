"""engine.vbs 编码防破坏测试：必须保持 GBK，误存 UTF-8 会让中文 Windows 的 SecureCRT 脚本宿主编译失败。"""
from pathlib import Path

ENGINE = Path(__file__).parent.parent / "engine" / "engine.vbs"


def test_engine_vbs_decodes_as_gbk_and_contains_chinese():
    text = ENGINE.read_bytes().decode("gbk")
    assert "用户停止" in text
    assert "输出为空" in text
    assert "输出捕获异常" in text


def test_engine_vbs_is_not_utf8():
    data = ENGINE.read_bytes()
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return  # GBK 字节在 UTF-8 下解码失败，符合预期
    raise AssertionError("engine.vbs 疑似被存为 UTF-8——中文 Windows 下 SecureCRT 脚本宿主会编译失败，请转回 GBK")
