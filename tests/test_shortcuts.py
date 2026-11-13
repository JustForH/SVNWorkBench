# -*- coding: utf-8 -*-
"""输入控件快捷键测试：Ctrl+A 全选（Entry/TEntry/Text），Ctrl+C 复制。

键事件需要控件持有焦点，先 focus_force 再 event_generate；
复制/剪切/粘贴是 Tk 原生绑定，这里一并验证可用。
桌面随时可能把焦点抢到别的窗口（Tk 的 Entry 一失焦就清掉选中、
键事件也可能被丢弃），因此按下键后用 check 判定预期结果，不满足
就重来——绑定真正缺失时重试多少次都不会通过，最终断言照常失败。"""
import os
import sys
from _testtmp import TMP  # noqa: E402
import shutil

HOME = TMP + "/fakehome_shortcuts"
shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME)
os.environ["HOME"] = HOME
os.environ["SVNWB_CONFIG_DIR"] = os.path.join(HOME, "cfg")
os.environ["SVNWB_LEGACY_SETTINGS"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/no_such_legacy_settings.json"   # 迁移源指向不存在的路径，不搬真实配置
os.environ["SVNWB_LOG_DIR"] = os.path.join(HOME, "logs")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import SVNWorkBench as m   # noqa: E402
import tkinter as tk   # noqa: E402
from tkinter import ttk   # noqa: E402

PASSED = []
def ok(name, cond, extra=""):
    PASSED.append(name)
    print("%s %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        sys.exit(1)

store = m.ConfigStore(m.CONFIG_DIR)
store.load()
hub = m.Hub(store)
app = m.App(store, hub)
app.root.update()


def clipboard():
    try:
        return app.root.clipboard_get()
    except tk.TclError:
        return None


def entry_sel(w):
    try:
        a, b = w.index("sel.first"), w.index("sel.last")
    except tk.TclError:
        return None
    return w.get()[a:b]


def text_sel(w):
    sel = w.tag_ranges("sel")
    if not sel:
        return None
    return w.get(sel[0], sel[1])


def sel_entry(w, text):
    """把 Entry 置为 text 并选中（复制/剪切测试的前置状态）。"""
    w.delete(0, "end")
    w.insert(0, text)
    w.select_range(0, "end")
    w.icursor("end")


def press(w, key, check=None, prepare=None, tries=4):
    """生成一次键事件；check 是预期结果的判定，不满足就重试。

    焦点被抢走时键事件会被丢弃、Entry 的选中也会被 FocusOut 清掉，
    所以每次都 focus_force 抢回焦点再敲。
    """
    for _ in range(tries):
        w.focus_force()
        app.root.update()
        if prepare is not None:
            prepare()
        if key in ("<Control-c>", "<Control-x>"):
            app.root.clipboard_clear()
        w.event_generate(key)
        app.root.update()
        if check is None or check():
            return


# ---- 0. 展开运行日志（折叠时控件未映射，拿不到键事件） ----
app._set_log_expanded(True)
app.root.update()

# ---- 1. 工作副本输入框（真实 Entry） ----
wc = TMP + "/TestTJSB"
app.wc_path.delete(0, "end")
app.wc_path.insert(0, wc)
press(app.wc_path, "<Control-a>", lambda: entry_sel(app.wc_path) == wc)
ok("工作副本输入框 Ctrl+A 全选", entry_sel(app.wc_path) == wc,
   repr(entry_sel(app.wc_path)))
press(app.wc_path, "<Control-c>", lambda: clipboard() == wc,
      lambda: sel_entry(app.wc_path, wc))
ok("工作副本输入框 Ctrl+C 复制", clipboard() == wc, repr(clipboard()))

# ---- 2. 大写情形（Shift 或 CapsLock 下的键序） ----
url = u"https://svn.example.com/repo/国产化/测试"
app.url_entry.delete(0, "end")
app.url_entry.insert(0, url)
press(app.url_entry, "<Control-A>", lambda: entry_sel(app.url_entry) == url,
      lambda: sel_entry(app.url_entry, url))
ok("SVN 地址框 Ctrl+Shift+A 全选", entry_sel(app.url_entry) == url,
   repr(entry_sel(app.url_entry)))

# ---- 3. 输入框 Ctrl+A + Ctrl+X 剪切 ----
app.root.update()
app.wc_path.delete(0, "end")
app.wc_path.insert(0, wc)
press(app.wc_path, "<Control-a>", lambda: entry_sel(app.wc_path) == wc)
press(app.wc_path, "<Control-x>",
      lambda: app.wc_path.get() == "" and clipboard() == wc,
      lambda: sel_entry(app.wc_path, wc))
ok("工作副本框 Ctrl+X 剪切", app.wc_path.get() == "" and clipboard() == wc,
   "entry=%r clip=%r" % (app.wc_path.get(), clipboard()))

# ---- 4. 粘贴（Ctrl+V 原生） ----
def put_clip():
    app.root.clipboard_clear()
    app.root.clipboard_append(u"../SP_PISA2_0")


press(app.wc_path, "<Control-v>",
      lambda: app.wc_path.get() == u"../SP_PISA2_0", put_clip)
ok("工作副本框 Ctrl+V 粘贴", app.wc_path.get() == u"../SP_PISA2_0",
   repr(app.wc_path.get()))

# ---- 5. 日志区（禁用态 Text，有内容）：全选 + 复制 ----
log_text = app.log.get("1.0", "end-1c")
press(app.log, "<Control-a>", lambda: text_sel(app.log) == log_text)
ok("日志区（禁用 Text）Ctrl+A 全选", text_sel(app.log) == log_text)
press(app.log, "<Control-c>", lambda: clipboard() == log_text,
      lambda: app.log.tag_add("sel", "1.0", "end-1c"))
ok("日志区 Ctrl+C 复制全部日志", clipboard() == log_text,
   repr((clipboard() or "")[:40]))

# ---- 6/7. ttk.Entry 与弹窗（Toplevel）里的输入框同样生效 ----
# 根窗口用的是 grid，临时控件放独立 Toplevel 里
win = tk.Toplevel(app.root)
te = ttk.Entry(win)
te.insert(0, u"ttk 输入框内容")
te.pack()
dlg_ent = tk.Entry(win)
dlg_ent.insert(0, u"弹窗输入框内容")
dlg_ent.pack()
combo = ttk.Combobox(win, values=[u"https://svn.example.com/repo"])
combo.insert(0, u"https://svn.example.com/repo")
combo.pack()
app.root.update()
press(te, "<Control-a>", lambda: entry_sel(te) == u"ttk 输入框内容")
te_sel = entry_sel(te)          # Entry 失焦会清掉选中，取值必须在按完立刻取
press(dlg_ent, "<Control-a>",
      lambda: entry_sel(dlg_ent) == u"弹窗输入框内容")
dlg_sel = entry_sel(dlg_ent)
ok("TEntry / 弹窗输入框 Ctrl+A 全选",
   te_sel == u"ttk 输入框内容" and dlg_sel == u"弹窗输入框内容",
   "%r / %r" % (te_sel, dlg_sel))
press(combo, "<Control-a>",
      lambda: entry_sel(combo) == u"https://svn.example.com/repo")
combo_sel = entry_sel(combo)
ok("TCombobox 地址框 Ctrl+A 全选",
   combo_sel == u"https://svn.example.com/repo", repr(combo_sel))
win.destroy()

print("shortcuts: ALL PASS (%d)" % len(PASSED))
