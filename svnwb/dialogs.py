# -*- coding: utf-8 -*-
"""通用弹窗与界面辅助。

_dialog              模态对话框骨架（依附父窗、置前、Esc 关闭）
ask_confirm          多行内容确认框
ask_auth / ask_cert  SVN 凭据与自定义证书弹窗（答复经 Hub.respond 回传）
open_with_system / show_logs  用系统编辑器查看落盘日志
show_credentials     svn 缓存登录凭据列表（确认后删除）
install_edit_shortcuts        输入框 Ctrl+A 全选与复制粘贴

调用方一律写成 dialogs.ask_xxx(...)（模块属性晚绑定），
测试才好 monkeypatch 成静默实现。
"""

import os
import subprocess
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from tkinter import ttk

from . import core, theme
from .core import (list_credentials, log_dir, subversion_auth_dir, tail_msg)


def _info_box(parent, text, wraplength):
    """弹窗里的说明块：白色面板 + 1px 细边框（不用 Tk 默认的立体凹陷）。"""
    lbl = tk.Label(parent, text=text, justify="left", anchor="w",
                   wraplength=wraplength, bg=core.SURFACE, fg=core.TEXT,
                   relief="flat", bd=0, padx=10, pady=8,
                   highlightthickness=1, highlightbackground=core.BORDER)
    lbl.pack(padx=18, pady=(14, 8), anchor="w")
    return lbl


def _dialog(parent, title):
    """创建模态对话框骨架：依附父窗、置前、Esc 关闭。

    位置由调用方在内容全部建好后、grab_set 之前调
    theme.center_on_parent(win, parent) 居中——这里建时还量不到尺寸，
    不预设位置（见 theme.center_on_parent）。
    """
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=core.APP_BG)   # 与主窗口同一套平面底色
    win.transient(parent)
    win.resizable(False, False)
    # 模态窗禁止/自动恢复最小化：被最小化后 grab 仍生效，主窗口会像卡死
    theme.install_modal_guard(win)
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    win.bind("<Escape>", lambda e: win.destroy())
    return win


def ask_confirm(parent, title, body, ok_text=u"确定"):
    """多行内容确认框；返回 True 表示用户确认。

    内容区限高并可滚动：提交清单/提交说明很长时，窗口不能跟着无限变高，
    否则底部的确认按钮会被顶到屏幕外，用户根本点不到（用户反馈）。
    按钮条先按窗口底部 pack，内容再多也优先保证按钮可见。
    """
    win = _dialog(parent, title)
    text = str(body).rstrip("\n")
    lines = text.split("\n")

    # 按钮条先占住底部，内容区只拿剩下的空间
    bar = tk.Frame(win)
    bar.pack(side="bottom", fill="x", padx=18, pady=(4, 16))

    # 视口高度按屏幕高度收紧（小屏/大字号时也不能把按钮挤出去）
    font = tkfont.nametofont("TkDefaultFont")
    line_h = font.metrics("linespace") or 20
    max_lines = max(4, min(12, (win.winfo_screenheight() - 260) // line_h))
    # 宽度按内容最长行估算，但不超过原来的 520px 换行宽度
    max_px = max([font.measure(line) for line in lines] or [0])
    char_w = font.measure(u"0") or 7
    width = max(24, min(76, int(min(520, max_px) / char_w) + 2))
    visible = min(max_lines, max(1, len(lines)))
    if max_px > 520:
        visible = min(max_lines, max(visible, 3))

    box = tk.Frame(win)
    box.pack(fill="both", expand=True, padx=18, pady=(16, 8))
    txt = theme.surface(tk.Text(box, height=visible, width=width,
                                wrap="word", state="normal", undo=False))
    txt.insert("1.0", text)
    txt.configure(state="disabled")
    txt.pack(side="left", fill="both", expand=True)
    if len(lines) > visible or max_px > width * char_w:
        ysb = ttk.Scrollbar(box, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")

    result = {"ok": False}

    def yes():
        result["ok"] = True
        win.destroy()

    # 同一排两个按钮同宽：按文案长度取标准宽/长名宽，右边缘对齐
    bw = theme.BTN_W if len(ok_text) <= 4 else theme.BTN_W_LONG
    ttk.Button(bar, text=u"取消", command=win.destroy,
               width=bw).pack(side="right", padx=(8, 0))
    ttk.Button(bar, text=ok_text, command=yes, width=bw,
               style=theme.ACCENT_STYLE).pack(side="right")
    theme.center_on_parent(win, parent)
    win.grab_set()
    win.wait_window()
    return result["ok"]


def ask_diff_mode(parent):
    """选择本次对比方式；返回 {"mode": "meld"/"builtin", "remember": bool}，
    取消返回 None。

    只在装了 meld、且条目适合外部对比（非目录）时由调用方打开；用户勾选
    “记住”后由调用方把结果写进配置，下次不再询问。
    """
    win = _dialog(parent, u"选择对比方式")
    tk.Label(win, text=u"本次对比使用：").pack(
        anchor="w", padx=18, pady=(16, 0))
    _info_box(win,
              u"meld：在外部程序中左右对比两版原始内容，适合逐行细看。\n"
              u"内置窗口：在程序内显示彩色统一差异，不启动外部进程。\n"
              u"勾选“记住”后，可从顶栏“对比方式”或改动列表右键菜单改回来。",
              480)
    remember = tk.BooleanVar(value=False)
    theme.CheckBox(win, text=u"记住我的选择，以后不再询问",
                   variable=remember).pack(anchor="w", padx=16, pady=(2, 0))
    result = {"value": None}

    def choose(mode):
        result["value"] = {"mode": mode, "remember": bool(remember.get())}
        win.destroy()

    bar = tk.Frame(win)
    bar.pack(fill="x", padx=18, pady=(12, 16))
    # “meld 对比”混排后比 4 个汉字略宽，同排三个按钮统一用长名宽度
    ttk.Button(bar, text=u"取消", command=win.destroy,
               width=theme.BTN_W_LONG).pack(side="right", padx=(8, 0))
    ttk.Button(bar, text=u"内置窗口", command=lambda: choose("builtin"),
               width=theme.BTN_W_LONG).pack(side="right", padx=(8, 0))
    ttk.Button(bar, text=u"meld 对比", command=lambda: choose("meld"),
               width=theme.BTN_W_LONG,
               style=theme.ACCENT_STYLE).pack(side="right")
    theme.center_on_parent(win, parent)
    win.grab_set()
    win.wait_window()
    return result["value"]


def ask_auth(parent, message):
    """SVN 身份验证弹窗；返回 {"ok":True,"username","password","remember"} 或 {"ok":False}。"""
    win = _dialog(parent, u"需要 SVN 身份验证")
    _info_box(win, tail_msg(message), 460)
    result = {"ok": False}
    user = tk.StringVar()
    pwd = tk.StringVar()
    remember = tk.BooleanVar(value=False)
    tk.Label(win, text=u"用户名").pack(anchor="w", padx=18)
    e_user = ttk.Entry(win, textvariable=user, width=34)
    e_user.pack(fill="x", padx=18, pady=(2, 6))
    tk.Label(win, text=u"密码").pack(anchor="w", padx=18)
    ttk.Entry(win, textvariable=pwd, show="*", width=34).pack(
        fill="x", padx=18, pady=(2, 6))
    theme.CheckBox(win, text=u"让 svn 记住密码（明文保存在 ~/.subversion）",
                   variable=remember).pack(anchor="w", padx=16, pady=(4, 0))

    def ok():
        result.update({"ok": True, "username": user.get().strip(),
                       "password": pwd.get(), "remember": bool(remember.get())})
        win.destroy()

    bar = tk.Frame(win)
    bar.pack(fill="x", padx=18, pady=(12, 16))
    ttk.Button(bar, text=u"取消本次操作", command=win.destroy,
               width=theme.BTN_W_LONG).pack(side="right", padx=(8, 0))
    ttk.Button(bar, text=u"连接", command=ok, width=theme.BTN_W_LONG,
               style=theme.ACCENT_STYLE).pack(side="right")
    theme.center_on_parent(win, parent)
    win.grab_set()
    win.after(30, e_user.focus_set)
    win.wait_window()
    return result


def ask_cert(parent, message):
    """服务器证书弹窗；返回 {"ok":True,"remember"} 或 {"ok":False}。"""
    win = _dialog(parent, u"服务器证书验证失败")
    _info_box(win, tail_msg(message), 480)
    result = {"ok": False}
    remember = tk.BooleanVar(value=False)
    theme.CheckBox(win, text=u"记住此选择（写入配置，之后自动信任）",
                   variable=remember).pack(anchor="w", padx=16, pady=(2, 0))

    def ok():
        result.update({"ok": True, "remember": bool(remember.get())})
        win.destroy()

    bar = tk.Frame(win)
    bar.pack(fill="x", padx=18, pady=(12, 16))
    ttk.Button(bar, text=u"取消本次操作", command=win.destroy,
               width=theme.BTN_W_LONG).pack(side="right", padx=(8, 0))
    ttk.Button(bar, text=u"信任并重试", command=ok,
               width=theme.BTN_W_LONG,
               style=theme.ACCENT_STYLE).pack(side="right")
    theme.center_on_parent(win, parent)
    win.grab_set()
    win.wait_window()
    return result


def open_with_system(path):
    """用系统默认程序打开文件/目录；失败返回 False。"""
    try:
        subprocess.Popen(["xdg-open", str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


def show_logs(parent):
    """运行日志文件列表：可打开所选日志或所在文件夹。"""
    win = _dialog(parent, u"运行日志文件")
    d = log_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        files = sorted(d.glob("*.log"),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:200]
    except OSError:
        files = []
    tk.Label(win, text=str(d), fg=core.MUTED, anchor="w").pack(
        fill="x", padx=16, pady=(12, 6))
    box = tk.Frame(win)
    box.pack(fill="both", expand=True, padx=16)
    tree = ttk.Treeview(box, columns=("name", "size", "mtime"), show="headings",
                        height=14, selectmode="browse")
    tree.heading("name", text=u"文件名")
    tree.heading("size", text=u"大小")
    tree.heading("mtime", text=u"修改时间")
    tree.column("name", width=340, anchor="w")
    tree.column("size", width=90, anchor="e")
    tree.column("mtime", width=160, anchor="w")
    sb = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    count = 0
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        count += 1
        tree.insert("", "end", values=(
            f.name, "%.1f KB" % (st.st_size / 1024.0),
            datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")))

    # 通知写在窗口内（不弹系统 messagebox：模态消息框被最小化后 grab
    # 仍生效，主窗口会像卡死；用户反馈）
    notice = tk.Label(win, text="", fg=core.MUTED, anchor="w")
    notice.pack(fill="x", padx=16, pady=(6, 0))

    def say(msg, kind="warn"):
        notice.configure(text=msg, fg=core.LOG_COLORS.get(kind, core.MUTED))

    def sel_file():
        sel = tree.selection()
        if not sel:
            return None
        return d / str(tree.item(sel[0], "values")[0])

    def open_sel():
        f = sel_file()
        if f is None:
            say(u"请先选中一个日志文件")
            return
        if not open_with_system(f):
            say(u"无法打开日志文件（系统缺少 xdg-open？）", "err")

    def open_dir():
        if not open_with_system(d):
            say(u"无法打开文件夹（系统缺少 xdg-open？）", "err")

    tree.bind("<Double-Button-1>", lambda e: open_sel())
    bar = tk.Frame(win)
    bar.pack(fill="x", padx=16, pady=(10, 16))
    ttk.Button(bar, text=u"打开所在文件夹", command=open_dir).pack(side="left")
    ttk.Button(bar, text=u"关闭", command=win.destroy,
               width=theme.BTN_W_LONG).pack(side="right", padx=(8, 0))
    ttk.Button(bar, text=u"打开所选文件", command=open_sel,
               width=theme.BTN_W_LONG).pack(side="right")
    if not count:
        tk.Label(win, text=u"（还没有日志）", fg=core.MUTED).pack(anchor="w", padx=16)
    theme.center_on_parent(win, parent)
    win.grab_set()
    win.wait_window()


def show_credentials(parent):
    """svn 登录凭据窗口：列出缓存的凭据，确认后删除（用户要求）。

    svn 把“记住密码”的凭据缓存在 ~/.subversion/auth/svn.simple 下
    （每个文件一条，见 core.list_credentials）。删除文件 = svn 忘掉该
    凭据，下次连接重新询问用户名/密码；删除前必须展示凭据名称让用户确认
    （用户要求），删除后列表立即刷新。

    布局必须用 grid（只有列表行带 weight）：pack 在窗口高度不够时会把
    最后排的按钮条整体挤出可视区，只剩 1x1 像素——用户实测“凭据窗口
    里根本没有删除按钮，无法删除”（20261015）。别再改回 pack。
    """
    win = _dialog(parent, u"SVN 登录凭据")
    win.resizable(True, True)
    win.geometry("720x460")
    win.rowconfigure(2, weight=1)      # 只让列表行伸缩，按钮条固定可见
    win.columnconfigure(0, weight=1)
    tk.Label(win, text=u"缓存目录: %s" % subversion_auth_dir(), fg=core.MUTED,
             anchor="w").grid(row=0, column=0, sticky="ew", padx=16,
                              pady=(12, 2))
    tk.Label(win, text=u"选中后点“删除所选…”；删除后 svn 下次连接会重新询问"
                       u"用户名/密码", fg=core.MUTED, anchor="w").grid(
        row=1, column=0, sticky="ew", padx=16, pady=(0, 6))
    box = tk.Frame(win)
    box.grid(row=2, column=0, sticky="nsew", padx=16)
    box.rowconfigure(0, weight=1)
    box.columnconfigure(0, weight=1)
    tree = ttk.Treeview(box, columns=("user", "name", "file"),
                        show="headings", height=10, selectmode="extended")
    tree.heading("user", text=u"用户名")
    tree.heading("name", text=u"凭据名称")
    tree.heading("file", text=u"缓存文件")
    tree.column("user", width=140, anchor="w")
    tree.column("name", width=400, anchor="w")
    tree.column("file", width=140, anchor="w")
    sb = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="ns")
    empty = tk.Label(win, text="", fg=core.MUTED)
    empty.grid(row=3, column=0, sticky="w", padx=16)
    # 通知写在窗口内（系统 messagebox 是 Tk 内部模态窗，最小化后会攥着
    # grab 让主窗口像卡死；这里统一用窗口内提示）
    notice = tk.Label(win, text="", fg=core.MUTED, anchor="w",
                      justify="left", wraplength=660)
    notice.grid(row=4, column=0, sticky="ew", padx=16)
    state = {"items": []}

    def say(msg, kind="warn"):
        notice.configure(text=msg, fg=core.LOG_COLORS.get(kind, core.MUTED))

    def refresh():
        for iid in tree.get_children():
            tree.delete(iid)
        state["items"] = list_credentials()
        for i, it in enumerate(state["items"]):
            tree.insert("", "end", iid="c%d" % i, values=(
                it.get("username") or u"（未记录）",
                it.get("name") or it.get("file") or "",
                it.get("file") or ""))
        empty.configure(
            text=u"" if state["items"] else u"（没有缓存的登录凭据）")

    def del_sel():
        chosen = []
        for iid in tree.selection():
            try:
                i = int(str(iid)[1:])
            except ValueError:
                continue
            if 0 <= i < len(state["items"]):
                chosen.append(state["items"][i])
        if not chosen:
            say(u"请先选中要删除的凭据")
            return
        names = "\n".join(it.get("name") or it.get("file") or u""
                          for it in chosen)
        body = (u"将删除以下 %d 条缓存的登录凭据：\n%s\n\n"
                u"删除后 svn 下次连接会重新询问用户名/密码。" % (len(chosen),
                                                                names))
        ok = ask_confirm(win, u"删除登录凭据", body, u"确认删除")
        try:
            if win.winfo_exists():
                win.grab_set()    # 确认框关闭后把模态抓取还给本窗口
        except tk.TclError:
            return
        if not ok:
            return
        failed = []
        for it in chosen:
            try:
                os.remove(it["path"])
            except OSError as e:
                failed.append(u"%s（%s）" % (it.get("name") or it.get("file"),
                                             e))
        refresh()
        if failed:
            say(u"以下凭据删除失败：\n%s" % "\n".join(failed), "err")

    bar = tk.Frame(win)
    bar.grid(row=5, column=0, sticky="ew", padx=16, pady=(10, 16))
    ttk.Button(bar, text=u"删除所选…", command=del_sel,
               width=theme.BTN_W_LONG).pack(side="left")
    ttk.Button(bar, text=u"关闭", command=win.destroy,
               width=theme.BTN_W).pack(side="right", padx=(8, 0))
    ttk.Button(bar, text=u"刷新", command=refresh,
               width=theme.BTN_W).pack(side="right")
    refresh()
    theme.center_on_parent(win, parent)
    win.grab_set()
    win.wait_window()


def install_edit_shortcuts(root):
    """输入控件通用快捷键：Ctrl+A 全选（覆盖 Shift/CapsLock 的大写情形）。

    复制/剪切/粘贴（Ctrl+C/X/V）Tk 对 Entry/Combobox/Text 已有原生绑定
    （tk.tcl 的 <<Copy>> 等虚拟事件），这里只补 Tk 缺失的"全选"。
    类级绑定对之后创建的 Toplevel 弹窗里的控件同样生效。
    """

    def select_all(event):
        w = event.widget
        try:
            if w.winfo_class() == "Text":
                w.tag_add("sel", "1.0", "end-1c")
            else:
                w.select_range(0, "end")
                w.icursor("end")
        except tk.TclError:
            return None
        return "break"

    for cls in ("Entry", "TEntry", "TCombobox", "Text"):
        root.bind_class(cls, "<Control-a>", select_all)
        root.bind_class(cls, "<Control-A>", select_all)


def install_text_copy(text, parent, menu_attr=None):
    """给只读 Text 装复制链路：点击聚焦 + Ctrl+A/Ctrl+C + 右键菜单。

    禁用态 Text 被鼠标点击时 Tk **不会**自动把焦点给它，不补 focus_set
    的话快捷键会落到父窗口，看起来像"全选/复制不支持"（查看内容窗口与
    内置差异窗口都踩过）。菜单提供 复制（无选区时禁用）/ 复制全部内容 /
    全选。menu_attr 非空时把菜单挂到 parent 上，调用方保持引用。
    """
    menu = theme.make_menu(parent)

    def focus_text(event=None):
        try:
            text.focus_set()
        except tk.TclError:
            pass
        return None

    def select_all(event=None):
        try:
            text.tag_add("sel", "1.0", "end-1c")
            text.mark_set("insert", "1.0")
            text.see("1.0")
            text.focus_set()
        except tk.TclError:
            return None
        return "break"

    def copy_text(value):
        if not value:
            return None
        try:
            text.clipboard_clear()
            text.clipboard_append(value)
        except tk.TclError:
            return None
        return "break"

    def copy_sel(event=None):
        try:
            value = text.get("sel.first", "sel.last")
        except tk.TclError:
            return None
        return copy_text(value)

    def copy_all(event=None):
        return copy_text(text.get("1.0", "end-1c"))

    def on_menu(event):
        focus_text()
        selected = bool(text.tag_ranges("sel"))
        try:
            menu.entryconfigure(
                0, state="normal" if selected else "disabled")
            menu.tk_popup(event.x_root, event.y_root)
        except tk.TclError:
            for fn in (menu.unpost, menu.grab_release):
                try:
                    fn()
                except tk.TclError:
                    pass

    menu.add_command(label=u"复制", command=copy_sel)
    menu.add_command(label=u"复制全部内容", command=copy_all)
    menu.add_command(label=u"全选", command=select_all)
    text.bind("<Button-1>", focus_text)
    text.bind("<Button-3>", on_menu)
    text.bind("<Control-a>", select_all)
    text.bind("<Control-A>", select_all)
    text.bind("<Control-c>", copy_sel)
    text.bind("<Control-C>", copy_sel)
    if menu_attr:
        setattr(parent, menu_attr, menu)
    return menu


def show_diff_win(parent, path, res, font_bold=None, win=None):
    """差异对比窗口（非模态）：双击改动列表时弹出。

    复用已有窗口——再次调用只刷新内容，不重复开窗。
    res: {"lines": [...], "stats": (新增行, 删除行, 变更块)}；返回窗口对象，
    调用方把它存下来，下次传回 win 即可复用。
    """
    alive = False
    if win is not None:
        try:
            alive = bool(win.winfo_exists())
        except tk.TclError:
            alive = False
    if alive:
        win.deiconify()
        win.lift()
    else:
        win = tk.Toplevel(parent)
        win.title(u"差异对比")
        win.configure(bg=core.APP_BG)
        win.geometry("940x560")
        win.minsize(560, 320)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.bind("<Escape>", lambda _e: win.destroy())
        head = tk.Frame(win)
        head.pack(fill="x", padx=12, pady=(10, 6))
        win.path_lbl = tk.Label(head, anchor="w", font=font_bold)
        win.path_lbl.pack(side="left")
        win.stats_lbl = tk.Label(head, fg=core.MUTED)
        win.stats_lbl.pack(side="right")
        body = tk.Frame(win)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        txt = theme.surface(tk.Text(body, state="disabled", wrap="none",
                                    undo=False), mono=True)
        ysb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
        xsb = ttk.Scrollbar(body, orient="horizontal", command=txt.xview)
        txt.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        txt.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        txt.tag_configure("add", foreground=core.TREE_COLORS["add"])
        txt.tag_configure("del", foreground=core.TREE_COLORS["del"])
        txt.tag_configure("hunk", foreground=core.LOG_COLORS["cmd"],
                          font=font_bold)
        txt.tag_configure("file", foreground=core.MUTED, font=font_bold)
        txt.tag_configure("empty", foreground=core.MUTED)
        win.diff_text = txt
        # 只读差异内容同一套复制链路：点击聚焦、Ctrl+A/Ctrl+C、右键复制
        win.diff_menu = install_text_copy(txt, win)
        theme.center_on_parent(win, parent)   # 新窗口首次出现时摆到父窗正中

    lines = res.get("lines") or []
    stats = res.get("stats") or (0, 0, 0)
    add, rem, hunk = stats
    win.path_lbl.configure(text=path or u"全部改动")
    win.title(u"差异对比 · %s" % (path or u"全部改动"))
    win.stats_lbl.configure(
        text=(u"新增 %d 行 · 删除 %d 行 · %d 个变更块" % (add, rem, hunk))
        if lines else u"没有差异")
    txt = win.diff_text
    txt.configure(state="normal")
    txt.delete("1.0", "end")
    if not lines:
        txt.insert("end", u"（没有差异）", "empty")
    for ln in lines:
        if ln.startswith(("+++", "---", "Index:", "=====")):
            tag = "file"
        elif ln.startswith("@@"):
            tag = "hunk"
        elif ln.startswith("+"):
            tag = "add"
        elif ln.startswith("-"):
            tag = "del"
        else:
            tag = None
        if tag:
            txt.insert("end", ln + "\n", tag)
        else:
            txt.insert("end", ln + "\n")
    txt.configure(state="disabled")
    txt.see("1.0")
    try:
        txt.focus_set()                 # 打开/刷新差异窗口后快捷键立即可用
    except tk.TclError:
        pass
    return win
