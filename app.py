import tkinter as tk

from tool.ui import MainWindow


def main() -> None:
    root = tk.Tk()
    root.title("SecureCRT 批量取数工具")
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
