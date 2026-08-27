# SecureCRT 批量取数 Excel 汇总工具

在装有 SecureCRT 的机器上批量登录华为服务器执行查询指令，把各台设备的输出解析汇总成 Excel 表格（明细表 + 汇总表）。

## 功能特性

- **图形界面**：批量录入/粘贴/导入服务器清单（`IP 主机名 账号 密码`），配置查询指令、超时、并发数（默认 5）、Excel 保存位置
- **SecureCRT 驱动**：通过 SecureCRT 脚本接口并发登录取数（每台一个引擎进程，互不阻塞），自动关闭分页、捕获完整输出
- **失败隔离**：连接失败/密码错误/超时单台记录原因后继续，不影响其他机器
- **Excel 汇总**：明细表（IP/主机名/级别/日期/时间/告警内容）+ 汇总表（状态/失败原因/各级告警计数），无需安装 Office
- **模拟模式**：内置样例数据走通全流程，便于无网络环境试用与验证

## 使用

1. 把 `dist/SecureCRT批量取数工具.exe` 拷贝到装有 SecureCRT 的机器任意可写目录，双击运行（免安装，无需 Python/Office）
2. 首次打开点"自动检测"定位 SecureCRT.exe
3. 填服务器清单、查询指令（如 `disp alarm hardware`）、Excel 保存位置，点"开始"

详细说明与真实环境验证清单见 [docs/使用与验证说明.md](docs/使用与验证说明.md)。

> 目标设备需为华为 VRP 设备（默认提示符 `<主机名>`）；密码不能含双引号 `"`。

## 开发

```bash
# 环境（开发机 Windows，Python 3.13）
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt

# 测试（47 个用例；模拟模式覆盖全流程，无需 SecureCRT/网络）
.venv/Scripts/python -m pytest tests/ -q

# 运行（开发模式）
.venv/Scripts/python app.py

# 打包
cmd //c build.bat   # 产物: dist/SecureCRT批量取数工具.exe
```

## 架构

```
[主程序 exe]  Tkinter 界面 + 并发调度（按并发数分批启动引擎、状态文件轮询）
   │  任务文件 task/<IP>.txt（9 字段，含 run_id）
   ▼
[engine.vbs]  在 SecureCRT 脚本宿主内运行，每进程一台：连接 → 关分页 → 发指令 → 捕获
   │  结果 results/<run_id>/<IP>_{status,raw}.txt（每轮独立目录，防跨轮污染）
   ▼
[主程序 exe]  解析华为表格输出 → openpyxl 生成 Excel（明细 + 汇总，模拟时附"说明"sheet）
```

## 目录

```
app.py              入口
tool/               主程序模块（ui/runner/parser/excel_writer/config/locate/taskfiles/simulation/paths）
engine/engine.vbs   取数引擎（GBK 编码，勿用 UTF-8 保存）
samples/            模拟模式样例输出
tests/              47 个 pytest 用例
docs/               使用说明、验证清单、设计文档、实现计划
build.bat           PyInstaller 打包脚本
```

## 文档

- [使用与验证说明](docs/使用与验证说明.md)
- [设计文档](docs/superpowers/specs/2026-08-26-securecrt-batch-excel-tool-design.md)
- [实现计划](docs/superpowers/plans/2026-08-26-securecrt-batch-excel-tool.md)
