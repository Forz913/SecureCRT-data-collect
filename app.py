"""程序入口：创建主窗口并进入 Tk 事件循环。"""
import tkinter as tk

from tool.ui import MainWindow


def main() -> None:
    """创建根窗口并挂载主界面，阻塞于事件循环直至窗口关闭。"""
    root = tk.Tk()
    root.title("SecureCRT 批量取数工具")
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
