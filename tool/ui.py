"""Tkinter 主界面。"""
from __future__ import annotations

import datetime
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from tool.config import AppConfig, load as cfg_load, save as cfg_save
from tool.excel_writer import write_workbook
from tool.locate import find_securecrt
from tool.parser import parse_output
from tool.paths import app_dir, resource_path
from tool.runner import RunConfig, Runner
from tool.taskfiles import Server, parse_server_line, read_raw


def default_excel_name() -> str:
    return "SecureCRT巡检结果_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".xlsx"


class MainWindow:
    POLL_MS = 400

    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg_path = app_dir() / "config.json"
        self.cfg: AppConfig = cfg_load(self.cfg_path)
        self.runner: Runner | None = None
        self._build()
        self._load_from_config()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 界面搭建 ----------

    def _build(self) -> None:
        self.root.geometry("980x680")
        self.root.minsize(860, 560)
        pad = {"padx": 6, "pady": 3}
        body = ttk.Frame(self.root, padding=8)
        body.pack(fill="both", expand=True)

        # 1. SecureCRT 路径
        row0 = ttk.Frame(body)
        row0.pack(fill="x", **pad)
        ttk.Label(row0, text="SecureCRT:").pack(side="left")
        self.securecrt_var = tk.StringVar()
        ttk.Entry(row0, textvariable=self.securecrt_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row0, text="浏览...", command=self._browse_securecrt).pack(side="left", padx=2)
        ttk.Button(row0, text="自动检测", command=self._auto_detect_securecrt).pack(side="left")

        # 2. Excel 保存位置
        row1 = ttk.Frame(body)
        row1.pack(fill="x", **pad)
        ttk.Label(row1, text="保存到:").pack(side="left")
        self.excel_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.excel_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row1, text="浏览...", command=self._browse_excel).pack(side="left")

        # 3. 指令 + 超时
        row2 = ttk.Frame(body)
        row2.pack(fill="x", **pad)
        ttk.Label(row2, text="查询指令:").pack(side="left")
        self.command_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.command_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Label(row2, text="超时(秒):").pack(side="left")
        self.timeout_var = tk.IntVar(value=60)
        ttk.Spinbox(row2, from_=10, to=600, textvariable=self.timeout_var, width=6).pack(side="left", padx=4)

        # 4. 并发 + 模拟模式
        row3 = ttk.Frame(body)
        row3.pack(fill="x", **pad)
        ttk.Label(row3, text="并发数:").pack(side="left")
        self.concurrency_var = tk.IntVar(value=5)
        ttk.Spinbox(row3, from_=1, to=10, textvariable=self.concurrency_var, width=4).pack(side="left", padx=4)
        self.sim_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row3, text="模拟取数（测试用，不连真实服务器）", variable=self.sim_var).pack(side="left", padx=12)

        # 5. 服务器清单
        row4 = ttk.Frame(body)
        row4.pack(fill="x", **pad)
        ttk.Label(row4, text="服务器清单:").pack(side="left")
        ttk.Button(row4, text="添加", command=self._add_server).pack(side="left", padx=2)
        ttk.Button(row4, text="粘贴多行", command=self._paste_servers).pack(side="left", padx=2)
        ttk.Button(row4, text="导入文件...", command=self._import_servers).pack(side="left", padx=2)
        ttk.Button(row4, text="删除选中", command=self._delete_selected).pack(side="left", padx=2)
        ttk.Button(row4, text="清空", command=self._clear_servers).pack(side="left", padx=2)

        table_frame = ttk.Frame(body)
        table_frame.pack(fill="both", expand=True, **pad)
        cols = ("ip", "hostname", "username", "password")
        self.server_tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=8)
        for cid, text in zip(cols, ("IP", "主机名", "账号", "密码")):
            self.server_tree.heading(cid, text=text)
            self.server_tree.column(cid, width=170, anchor="w")
        ysb = ttk.Scrollbar(table_frame, orient="vertical", command=self.server_tree.yview)
        self.server_tree.configure(yscrollcommand=ysb.set)
        self.server_tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.server_tree.bind("<Double-1>", self._edit_server)

        # 6. 运行控制
        row6 = ttk.Frame(body)
        row6.pack(fill="x", **pad)
        self.start_btn = ttk.Button(row6, text="开始", command=self._on_start)
        self.start_btn.pack(side="left", padx=2)
        self.stop_btn = ttk.Button(row6, text="停止", command=self._on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=2)
        self.progress = ttk.Progressbar(row6, maximum=100)
        self.progress.pack(side="left", fill="x", expand=True, padx=8)

        # 7. 状态列表 + 日志
        status_frame = ttk.Frame(body)
        status_frame.pack(fill="x", **pad)
        self.status_tree = ttk.Treeview(status_frame, columns=("ip", "hostname", "status"), show="headings", height=5)
        for cid, text in zip(("ip", "hostname", "status"), ("IP", "主机名", "状态")):
            self.status_tree.heading(cid, text=text)
            self.status_tree.column(cid, width=170, anchor="w")
        self.status_tree.pack(fill="x")

        log_frame = ttk.LabelFrame(body, text="运行日志", padding=4)
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=8, state="disabled")
        self.log_text.pack(fill="both", expand=True)

    # ---------- 清单操作 ----------

    def _servers_from_tree(self) -> list[Server]:
        servers = []
        for iid in self.server_tree.get_children():
            values = self.server_tree.item(iid, "values")
            servers.append(Server(ip=values[0], hostname=values[1],
                                  username=values[2], password=values[3]))
        return servers

    def _refresh_server_tree(self) -> None:
        self.server_tree.delete(*self.server_tree.get_children())
        for s in self.cfg.servers:
            self.server_tree.insert("", "end", values=(s.ip, s.hostname, s.username, s.password))

    def _add_server(self) -> None:
        self._open_server_dialog(None)

    def _edit_server(self, _event=None) -> None:
        sel = self.server_tree.selection()
        if sel:
            self._open_server_dialog(sel[0])

    def _open_server_dialog(self, iid: str | None) -> None:
        dlg = tk.Toplevel(self.root)
        dlg.title("编辑服务器" if iid else "添加服务器")
        dlg.transient(self.root)
        dlg.grab_set()
        fields = {}
        if iid:
            cur = self.server_tree.item(iid, "values")
        else:
            cur = ["", "", "", ""]
        for r, (label, key) in enumerate(zip(("IP", "主机名", "账号", "密码"), ("ip", "hostname", "username", "password"))):
            ttk.Label(dlg, text=label + ":").grid(row=r, column=0, sticky="e", padx=6, pady=4)
            var = tk.StringVar(value=cur[r])
            ttk.Entry(dlg, textvariable=var, width=32).grid(row=r, column=1, padx=6, pady=4)
            fields[key] = var

        def on_ok() -> None:
            server = Server(ip=fields["ip"].get().strip(), hostname=fields["hostname"].get().strip(),
                            username=fields["username"].get().strip(), password=fields["password"].get())
            if not server.ip or not server.username or not server.password:
                messagebox.showwarning("提示", "IP、账号、密码不能为空", parent=dlg)
                return
            if iid:
                self.cfg.servers[self.server_tree.index(iid)] = server
            else:
                self.cfg.servers.append(server)
            self._refresh_server_tree()
            dlg.destroy()

        ttk.Button(dlg, text="确定", command=on_ok).grid(row=4, column=0, pady=8)
        ttk.Button(dlg, text="取消", command=dlg.destroy).grid(row=4, column=1, pady=8)

    def _paste_servers(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("提示", "剪贴板为空")
            return
        added = 0
        for line in text.splitlines():
            s = parse_server_line(line)
            if s:
                self.cfg.servers.append(s)
                added += 1
        self._refresh_server_tree()
        self._log(f"粘贴完成：新增 {added} 台")

    def _import_servers(self) -> None:
        path = filedialog.askopenfilename(
            title="选择服务器清单文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        added = 0
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            s = parse_server_line(line)
            if s:
                self.cfg.servers.append(s)
                added += 1
        self._refresh_server_tree()
        self._log(f"导入完成：{path} 新增 {added} 台")

    def _delete_selected(self) -> None:
        sel = self.server_tree.selection()
        if not sel:
            return
        for iid in sel:
            del self.cfg.servers[self.server_tree.index(iid)]
        self._refresh_server_tree()

    def _clear_servers(self) -> None:
        if messagebox.askyesno("确认", "清空所有服务器？"):
            self.cfg.servers.clear()
            self._refresh_server_tree()

    # ---------- 路径选择 ----------

    def _browse_securecrt(self) -> None:
        path = filedialog.askopenfilename(title="选择 SecureCRT.exe",
                                          filetypes=[("SecureCRT", "SecureCRT.exe"), ("所有文件", "*.*")])
        if path:
            self.securecrt_var.set(path)

    def _auto_detect_securecrt(self) -> None:
        found = find_securecrt()
        if found:
            self.securecrt_var.set(found)
            self._log(f"检测到 SecureCRT: {found}")
        else:
            messagebox.showinfo("提示", "未自动检测到 SecureCRT，请手动指定")

    def _browse_excel(self) -> None:
        initial = self.excel_var.get() or default_excel_name()
        path = filedialog.asksaveasfilename(
            title="选择 Excel 保存位置",
            defaultextension=".xlsx",
            initialfile=Path(initial).name,
            initialdir=str(Path(initial).parent) if Path(initial).parent.exists() else None,
            filetypes=[("Excel 文件", "*.xlsx")],
        )
        if path:
            self.excel_var.set(path)

    # ---------- 运行控制 ----------

    def _validate(self) -> str:
        if not self.cfg.servers:
            return "服务器清单为空"
        if not self.cfg.command.strip():
            return "查询指令为空"
        if not self.cfg.excel_path.strip():
            return "请指定 Excel 保存位置"
        if not self.cfg.sim_mode:
            if not self.cfg.securecrt_path.strip() or not Path(self.cfg.securecrt_path).exists():
                return "SecureCRT.exe 路径无效（模拟模式下不需要）"
        return ""

    def _on_start(self) -> None:
        self._sync_config_from_ui()
        err = self._validate()
        if err:
            messagebox.showerror("参数错误", err)
            return
        if Path(self.cfg.excel_path).exists():
            if not messagebox.askyesno("确认", f"文件已存在，是否覆盖？\n{self.cfg.excel_path}"):
                return
        if not self.cfg.sim_mode:
            self._log("提示：运行期间会弹出 SecureCRT 窗口，请勿手动操作这些窗口")
        self._save_config()
        work = app_dir()
        run_cfg = RunConfig(
            command=self.cfg.command.strip(),
            timeout=self.cfg.timeout,
            concurrency=self.cfg.concurrency,
            sim_mode=self.cfg.sim_mode,
            securecrt_path=self.cfg.securecrt_path,
            engine_path=resource_path("engine/engine.vbs"),
            task_dir=work / "task",
            results_dir=work / "results",
            stop_flag_path=work / "stop.flag",
            per_deadline=self.cfg.timeout + 150,
            on_event=self._on_event,
        )
        self.runner = Runner(list(self.cfg.servers), run_cfg)
        self._reset_status_ui()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.runner.start()
        self.root.after(self.POLL_MS, self._tick)

    def _on_stop(self) -> None:
        if self.runner:
            self.runner.request_stop()
            self._log("已请求停止")

    def _tick(self) -> None:
        if self.runner and self.runner.tick():
            self._on_done()
        elif self.runner:
            self.progress["value"] = self.runner.progress() * 100.0
            self.root.after(self.POLL_MS, self._tick)

    def _on_done(self) -> None:
        results = self.runner.results()
        for r in results:
            if r.status == "SUCCESS":
                r.alarms = parse_output(read_raw(r.raw_path))
        try:
            write_workbook(Path(self.cfg.excel_path), results)
        except Exception as e:
            messagebox.showerror("错误", f"生成 Excel 失败：{e}")
            self._log(f"生成 Excel 失败：{e}")
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.runner = None
            return
        ok = sum(1 for r in results if r.status == "SUCCESS")
        bad = len(results) - ok
        self.progress["value"] = 100
        self._log(f"完成：成功 {ok} 台，失败/停止 {bad} 台，已保存到 {self.cfg.excel_path}")
        messagebox.showinfo("完成", f"成功 {ok} 台，失败/停止 {bad} 台\nExcel 已保存到：\n{self.cfg.excel_path}")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.runner = None

    def _on_event(self, event: str, ip: str, payload: str) -> None:
        if event == "log":
            self._log(f"[{ip}] {payload}" if ip else payload)
        elif event == "status":
            self._log(f"[{ip}] {payload}")
            self._update_status_row(ip, payload)

    def _reset_status_ui(self) -> None:
        self.status_tree.delete(*self.status_tree.get_children())
        for s in self.cfg.servers:
            self.status_tree.insert("", "end", values=(s.ip, s.hostname, "等待中"))
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
        self.progress["value"] = 0

    def _update_status_row(self, ip: str, status: str) -> None:
        status_cn = {"SUCCESS": "成功", "FAIL": "失败", "STOPPED": "已停止"}.get(status, status)
        for iid in self.status_tree.get_children():
            if self.status_tree.item(iid, "values")[0] == ip:
                values = list(self.status_tree.item(iid, "values"))
                values[2] = status_cn
                self.status_tree.item(iid, values=values)
                return

    # ---------- 配置与日志 ----------

    def _sync_config_from_ui(self) -> None:
        self.cfg.servers = self._servers_from_tree()
        self.cfg.command = self.command_var.get()
        try:
            self.cfg.timeout = int(self.timeout_var.get())
        except (ValueError, tk.TclError):
            self.cfg.timeout = 60
        self.cfg.timeout = max(10, min(600, self.cfg.timeout))
        try:
            self.cfg.concurrency = int(self.concurrency_var.get())
        except (ValueError, tk.TclError):
            self.cfg.concurrency = 5
        self.cfg.concurrency = max(1, min(10, self.cfg.concurrency))
        self.cfg.sim_mode = bool(self.sim_var.get())
        self.cfg.securecrt_path = self.securecrt_var.get().strip()
        self.cfg.excel_path = self.excel_var.get().strip()

    def _load_from_config(self) -> None:
        self.securecrt_var.set(self.cfg.securecrt_path or find_securecrt())
        self.excel_var.set(self.cfg.excel_path or str(app_dir() / default_excel_name()))
        self.command_var.set(self.cfg.command)
        self.timeout_var.set(self.cfg.timeout)
        self.concurrency_var.set(self.cfg.concurrency)
        self.sim_var.set(self.cfg.sim_mode)
        self._refresh_server_tree()

    def _save_config(self) -> None:
        cfg_save(self.cfg_path, self.cfg)

    def _on_close(self) -> None:
        self._sync_config_from_ui()
        self._save_config()
        self.root.destroy()

    def _log(self, msg: str) -> None:
        self.log_text.config(state="normal")
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
