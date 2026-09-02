# v2 改造：paramiko 直连 SSH 通道 — 设计文档

日期：2026-08-31
状态：已与用户逐节确认

## 1. 背景与目标

v1（SecureCRT 脚本驱动）已在目标机器（SecureCRT 8.x）真机验证通过。但该方案存在固有代价：运行期间弹出 SecureCRT 窗口、目标机器必须安装 SecureCRT、进程+文件交换架构复杂。

v2 目标：**用 paramiko 直连 SSH 完全替换 SecureCRT 引擎**，取数时不打开 SecureCRT、目标机器零依赖、架构简化为进程内线程池。

**分支策略（用户指定）**：从当前 main 切出 `v2-paramiko` 分支开发，v1 完整保留在 main 作兜底。v2 真机验证通过后合并回 main；失败则弃分支，v1 exe 继续使用。

**真机经验（v1 实测，直接内置于 v2）**：
- 真实设备提示符是**裸的 `主机名>`**（无尖括号），非样例中的 `<主机名>`；需同时适配 `<主机名>`（用户视图）、`[主机名]`（系统视图）、裸 `主机名>` 三种形态
- 分页标记 `---- More ----` 需兜底处理（即使发了 `screen-length 0 temporary`）

## 2. 删除与保留（v2 分支上）

**删除**：
- `engine/engine.vbs`、`tool/locate.py`
- task/ 文件交换整套：`write_task_file`、run_id 状态文件机制（线程方案内存传递，无跨进程竞态）
- runner 的 subprocess 启动、状态文件轮询、per_deadline 兜底
- `tests/test_engine_encoding.py` 及依赖文件交换的 runner 测试（重写）

**保留**：
- 解析器（parser.py）、Excel 生成（excel_writer.py）、配置（config.py，删 securecrt_path 字段）、模拟模式（simulation.py + samples/）、UI 结构
- `results/<run_id>/<IP>_raw.txt` 仍落盘供排障（仅 raw，无 status 文件）
- `ServerResult` 数据类、状态语义（SUCCESS/FAIL/STOPPED）、汇总/明细输出格式——Excel 输出完全不变

## 3. 新架构（线程化）

```
[主程序 exe]  UI 不变（start/tick/progress/results/on_event 接口照旧）
   │  线程池（默认 5），每台一个采集线程
   ▼
[tool/ssh_collect.py]  paramiko 直连：TCP 连接→SSH 协商→关分页→发指令→流式读输出→检测提示符/分页符
   │  事件经线程安全队列回传（Tk 非线程安全，UI 仍靠 after() 轮询排空队列）
   ▼
[主程序]  内存结果直接进 Excel；raw 文本另存 results/<run_id>/<IP>_raw.txt
```

- Runner 对外接口保持 v1 不变：`start() / tick() / request_stop() / progress() / results() / on_event`，UI 改动最小
- worker 线程只往 queue 放事件（log/status/完成），tick() 排空队列更新记录状态
- 停止：设置停止事件；worker 在读取循环间隙检查并断开连接；未启动的记 STOPPED"用户停止"

## 4. SSH 连接细节

| 项 | 设计 |
|---|---|
| 库与打包 | `paramiko>=3.5`（支持 Python 3.13），随 exe 打包（含 cryptography 依赖），目标机器仍免安装 |
| 宿主密钥 | AutoAddPolicy 自动接受（等价 v1 的 /ACCEPTHOSTKEYS） |
| 超时 | 连接+登录超时 30 秒；指令读取超时用界面配置值 |
| 编码 | 输出按 UTF-8 解码，errors=replace |
| 老设备算法兼容 | 首次协商失败（SSHException：无共同 kex/cipher）→ 自动以兼容模式重试：启用旧算法集（diffie-hellman-group14-sha1、3des-cbc 等），日志注明已切换兼容模式 |

## 5. 取数状态机（ssh_collect.py，每台一个线程）

1. 连接 → `invoke_shell()` 开交互式会话
2. 读流等提示符：**行尾**匹配提示符三形态（`<h>` / `[h]` / 裸 `h>`，忽略大小写），超时 30 秒 → FAIL"未出现命令提示符(连接失败/认证失败/不可达/主机名与提示符不符)"。行尾匹配天然避免命中"提示符+指令回显"同一行（v1 的回显陷阱）

> **真机实测补充（2026-09-02）**：VRP 提示符不带行尾换行（光标停在 `>` 后等待输入），行式读取永远收不到提示符行——已增加**缓冲尾部匹配**双检测（完整行 + 缓冲区尾部 `\Z` 锚定），模拟服务器同步改为真机行为并作为回归测试；提示符超时失败时已收到的横幅内容会写入 raw 文件供排障
3. 发送 `screen-length 0 temporary`，再等提示符
4. 发送查询指令
5. 循环读行：
   - 行尾匹配提示符三形态 → 输出结束，SUCCESS
   - 行含 `---- More ----` → 发空格翻页继续（关分页失效时的兜底）
   - 其他行 → 追加到输出缓冲
   - 累计超时（界面配置值）→ FAIL"指令执行超时"，已收内容照写 raw 文件
6. 空输出检查（去掉提示符行后 <10 字符）→ FAIL"输出为空"；否则 SUCCESS
7. 断开连接，事件入队

失败语义与 v1 完全一致：单台失败记原因继续，汇总表不变。

## 6. UI 改动

- 删除"SecureCRT 路径"行（浏览/自动检测按钮随之消失）
- config.json 移除 `securecrt_path` 字段（现有 tolerant load 对旧配置缺字段天然兼容）
- 其余不变：清单、指令、超时、并发、模拟模式、保存路径、进度/日志/状态列表

## 7. 测试策略（开发机全可做）

- **状态机单元测试**：流式读取抽象为可注入的行源，用样例文本驱动全部路径：三形态提示符、More 翻页、超时、空输出、连接失败、停止中断
- **模拟 SSH 服务器**：paramiko.ServerInterface 模拟华为设备（登录后输出提示符、回应指令、分页行为），端到端测 ssh_collect 的真实 socket 路径
- 保留 parser/excel/config/taskfiles 现有测试；runner 测试重写为线程版；删除引擎编码测试
- **打包验证**：PyInstaller 打包后运行模拟模式 + 本地 SSH 服务器模式，确认 paramiko/cryptography 在冻结环境正常

## 8. 真机验证清单（用户执行，先 1 台）

1. 单台取数：成功、明细正确
2. 密码错误 / IP 不可达：失败原因正确
3. 5 台并发混合成功失败
4. 停止按钮行为
5. 算法协商：若某台报"算法协商失败"，确认日志自动切兼容模式后成功

## 9. 风险与回退

| 风险 | 对策 |
|------|------|
| 老设备算法协商不过（最大未知项） | 自动兼容模式重试；仍失败则明细记原因，可切回 main 分支的 v1 exe |
| 冻结环境 cryptography 异常（PyInstaller 已知偶发） | 打包后本地 SSH 服务器模式验证覆盖此路径 |
| 线程 bug | 状态机单测 + 模拟 SSH 服务器端到端测试全覆盖 |
| v1 回归 | v1 完整留在 main，随时切回 |

## 10. 范围外（YAGNI）

- 双通道并存（v1 完整留在 main 即兜底，无需同包双通道）
- telnet 协议
- 跳板机链/SSH 代理
- 结果文件的 run_id 隔离语义变化（保留目录结构，仅无 status 文件）
