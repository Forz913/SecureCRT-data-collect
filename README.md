# SecureCRT 批量取数 Excel 汇总工具

批量登录华为服务器执行查询指令，把各台设备的输出解析汇总成 Excel 表格（明细表 + 汇总表）。

## 功能特性

- **图形界面**：批量录入/粘贴/导入服务器清单（`IP 主机名 账号 密码`），配置查询指令、超时、并发数（默认 5）、Excel 保存位置
- **直连 SSH 取数**：paramiko 直连（内置兼容模式适配老设备），每台一个线程并发取数（默认 5），运行期间无窗口弹出，目标机器免安装（无需 SecureCRT/Python/Office）
- **失败隔离**：连接失败/密码错误/超时单台记录原因后继续，不影响其他机器
- **Excel 汇总**：明细表（IP/主机名/级别/日期/时间/告警内容）+ 汇总表（状态/失败原因/各级告警计数），无需安装 Office
- **模拟模式**：内置样例数据走通全流程，便于无网络环境试用与验证

## 使用

1. 把 `dist/SecureCRT批量取数工具.exe` 拷贝到能访问目标服务器的机器任意可写目录，双击运行（免安装）
2. 填服务器清单、查询指令（如 `disp alarm hardware`）、Excel 保存位置，点"开始"（默认文件名每次运行自动刷新为当前时间）

> （v2 直连版无需 SecureCRT；v1 SecureCRT 版见 main 分支）

详细说明与真实环境验证清单见 [docs/使用与验证说明.md](docs/使用与验证说明.md)。

> 目标设备需为华为 VRP 设备（提示符适配 `<主机名>` / `[主机名]` / 裸 `主机名>` 三种形态，匹配忽略大小写）。

## 开发

```bash
# 环境（开发机 Windows，Python 3.13）
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt

# 测试（57 个用例；模拟模式覆盖全流程，无需 SecureCRT/网络）
.venv/Scripts/python -m pytest tests/ -q

# 运行（开发模式）
.venv/Scripts/python app.py

# 打包
cmd //c build.bat   # 产物: dist/SecureCRT批量取数工具.exe
```

## 架构

```
[主程序 exe]  Tkinter 界面 + 线程池调度（每台一个采集线程）
   │  paramiko 直连 SSH：连接 → 关分页 → 发指令 → 按行读输出（提示符/分页判定）
   ▼
[主程序]  解析华为表格输出 → openpyxl 生成 Excel（明细 + 汇总，模拟时附"说明"sheet）
   └── results/<run_id>/<IP>_raw.txt 落盘供排障
```

## 目录

```
app.py              入口
tool/               主程序模块（ui/runner/ssh_collect/ssh_client/parser/excel_writer/config/taskfiles/simulation/paths）
samples/            模拟模式样例输出
tests/              57 个 pytest 用例（含模拟华为设备 SSH 服务器端到端）
docs/               使用说明、验证清单、设计文档、实现计划
build.bat           PyInstaller 打包脚本
```

## 文档

- [使用与验证说明](docs/使用与验证说明.md)
- [设计文档](docs/superpowers/specs/2026-08-26-securecrt-batch-excel-tool-design.md)
- [实现计划](docs/superpowers/plans/2026-08-26-securecrt-batch-excel-tool.md)
