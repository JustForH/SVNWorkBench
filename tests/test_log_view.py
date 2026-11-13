# -*- coding: utf-8 -*-
"""提交历史窗口回归测试（log_view.py）。

覆盖：core.parse_log_xml / repo_path_to_url 纯函数、
窗口懒加载与复用、经 Hub 的真实 svn log 读取（修订列表 + 每个版本改动的
文件列表）、双击修订与双击文件的差异对比（**对比语义 -c N = 本次提交 vs
上一版本，不含本地未提交改动**）、**单文件按地址对比（工作副本没有该
节点——本版本新增/删除——时仍成立，E155010 回归锁）**、**meld 两版
模式（cat rN-1 与 rN 临时文件左右对比；整版本不走 meld——3.20 命令行
开不了补丁视图）**、**超大差异截断防卡死**、地址目标（仓库浏览器右键
“查看提交记录”带来 url，不依赖工作副本）、任务繁忙时按钮禁用、
关闭窗口时按钮从 _need_idle 摘干净。

不进入 mainloop：用 after 时间线 + root.update() 泵事件。配置与临时
数据全部指向 /tmp，不碰真实配置。
"""
import os
import sys
from _testtmp import TMP  # noqa: E402
import time
import shutil
import subprocess

try:
    import faulthandler
    faulthandler.dump_traceback_later(180, exit=True)
except ImportError:
    pass

HOME = TMP + "/fakehome_log"
shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME)
os.environ["HOME"] = HOME
os.environ["SVNWB_CONFIG_DIR"] = TMP + "/cfg_log"
os.environ["SVNWB_LEGACY_SETTINGS"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/no_such_legacy_settings.json"   # 迁移源指向不存在的路径，不搬真实配置
os.environ["SVNWB_LOG_DIR"] = TMP + "/logs_log"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import SVNWorkBench as m   # noqa: E402

REPO = TMP + "/svnrepo_log"
WC = TMP + "/dl_log_wc"

FAILS = []
PASSED = [0]


def check(cond, msg, extra=""):
    if cond:
        PASSED[0] += 1
        print("PASS: %s" % msg)
    else:
        FAILS.append(msg)
        print("FAIL: %s %s" % (msg, extra))


# ---- 静默化所有弹窗 ----
m.messagebox.showerror = lambda *a, **k: None
m.messagebox.showwarning = lambda *a, **k: None
m.messagebox.showinfo = lambda *a, **k: None
m.dialogs.ask_auth = lambda parent, message: {"ok": False}
m.dialogs.ask_cert = lambda parent, message: {"ok": False}
m.dialogs.ask_confirm = lambda *a, **k: True

# “选择对比方式”弹窗：替换成固定答复，测试里按需改 value（None = 取消）
DIFF_ANSWER = {"value": {"mode": "meld", "remember": False}}
ASK_CALLS = [0]
ASK_PARENTS = []


def _ask_diff_mode(parent):
    ASK_CALLS[0] += 1
    ASK_PARENTS.append(parent)
    return DIFF_ANSWER["value"]


m.dialogs.ask_diff_mode = _ask_diff_mode

# ============================================================
# 1. 纯函数：parse_log_xml / repo_path_to_url
# ============================================================
XML = (u'<?xml version="1.0" encoding="UTF-8"?>\n'
       u'<log>\n'
       u'<logentry revision="3">\n'
       u'  <author>zhangsan</author>\n'
       u'  <date>2026-10-10T08:30:00.000000Z</date>\n'
       u'  <paths>\n'
       u'    <path action="M" kind="file">/trunk/b.txt</path>\n'
       u'    <path action="A" kind="file">/trunk/a.txt</path>\n'
       u'  </paths>\n'
       u'  <msg>第一行说明\n第二行说明</msg>\n'
       u'</logentry>\n'
       u'<logentry revision="2">\n'
       u'  <author></author>\n'
       u'  <date>2026-10-09T09:00:00.000000Z</date>\n'
       u'  <paths></paths>\n'
       u'  <msg>只有一行</msg>\n'
       u'</logentry>\n'
       u'</log>')
entries = m.parse_log_xml(XML)
e3 = entries[0] if entries else {}
check(len(entries) == 2
      and e3.get("rev") == "3" and e3.get("author") == "zhangsan"
      and e3.get("msg", u"").startswith(u"第一行说明")
      and [p["path"] for p in e3.get("paths", [])] ==
      ["/trunk/a.txt", "/trunk/b.txt"]
      and e3["paths"][0]["action"] == "A"
      and entries[1]["author"] == u"" and entries[1]["paths"] == [],
      "parse_log_xml 解析版本/作者/多行说明/文件与空值", repr(entries))
check(m.parse_log_xml("这不是 XML") == [] and m.parse_log_xml("") == [],
      "parse_log_xml 非 XML/空输入返回空列表")

check(
    m.repo_path_to_url("https://h/svn/repo", "/trunk/a.c")
    == "https://h/svn/repo/trunk/a.c"
    and m.repo_path_to_url("https://h/svn/repo/", "/trunk/a.c")
    == "https://h/svn/repo/trunk/a.c"
    and m.repo_path_to_url("https://h/svn/%E5%9B%BD", "/trunk/中.c")
    == "https://h/svn/国/trunk/中.c"
    and m.repo_path_to_url("", "/trunk/a.c") == u""
    and m.repo_path_to_url("https://h/svn/repo", "") == u"",
    "repo_path_to_url 拼接/尾斜杠/编码/空参数")

# ============================================================
# 2. 建本地仓库：r1 加两个文件，r2 改 a.txt 并新增 c.txt
# ============================================================
shutil.rmtree(REPO, ignore_errors=True)
shutil.rmtree(WC, ignore_errors=True)
subprocess.check_call(["svnadmin", "create", REPO])
subprocess.check_call(["svn", "checkout", "-q", "file://" + REPO, WC])
with open(os.path.join(WC, "a.txt"), "w") as f:
    f.write("line1\n")
with open(os.path.join(WC, "b.txt"), "w") as f:
    f.write("b1\n")
subprocess.check_call(["svn", "add", "-q", "a.txt", "b.txt"], cwd=WC)
subprocess.check_call(["svn", "commit", "-q", "-m", "r1 说明"], cwd=WC)
with open(os.path.join(WC, "a.txt"), "w") as f:
    f.write("line1\nline2\n")
with open(os.path.join(WC, "c.txt"), "w") as f:
    f.write("c1\n")
subprocess.check_call(["svn", "add", "-q", "c.txt"], cwd=WC)
# r2 故意用一段较长的多行说明：列表“说明”列放不下，用来验证提交说明
# 显示区能显示完整内容（用户反馈长描述看不全）
MSG_R2 = (u"r2 改 a 新增 c\n"
          u"\n"
          u"第二行说明：这里故意写一段比较长的提交描述，用来验证提交历史\n"
          u"窗口能显示完整的提交说明，而不是只看到第一行。\n"
          u"最后一行结尾。")
subprocess.check_call(["svn", "commit", "-q", "-m", MSG_R2], cwd=WC)

store = m.ConfigStore(m.CONFIG_DIR)
store.load()
hub = m.Hub(store)
app = m.App(store, hub)
app.root.update()
check(store.settings.get("diff_tool") == "ask",
      "对比方式默认每次询问", repr(store.settings.get("diff_tool")))


def pump_idle(timeout=60):
    """泵事件直到界面侧忙碌结束。

    不能只看 hub.busy()：runner 线程退出到 done 事件投递之间有一小段
    空窗，期间 hub.busy() 已是 False 但界面还没消费 done。
    """
    t0 = time.time()
    while app.busy and time.time() - t0 < timeout:
        app.root.update()
        time.sleep(0.05)
    for _ in range(5):                 # 事件消费后再泵两拍，稳一点
        app.root.update()
        time.sleep(0.02)


# ============================================================
# 3. 窗口：懒加载、复用、按钮登记
# ============================================================
app._open_log_view()
lv = app._log_view
check(lv is not None and lv.winfo_exists()
      and lv.winfo_toplevel() is lv
      and lv._repo_root == u""
      and str(lv.transient()) == str(app.root.winfo_toplevel()),
      "提交历史窗口打开、未覆盖 Tk _root、登记为父窗 transient",
      repr(lv))
app._open_log_view()
check(app._log_view is lv, "重复打开复用同一窗口（不重建）")
# 布局回归（20261016 用户反馈）：提交说明区仅 3 行高——原来 6 行把下面的
# 改动列表挤出可视区，只有全屏才看得见；两个列表的 height 只给保底请求
# 值、实际高度交给 expand，默认窗口尺寸下两个列表都必须真实可见
for _ in range(6):                 # 泵几拍，等几何布局落地
    app.root.update()
    time.sleep(0.02)
check(int(lv.msg_text.cget("height")) == 3
      and lv.tree.winfo_height() >= 100 and lv.ftree.winfo_height() >= 100,
      "默认尺寸下说明区 3 行且两个列表都可见",
      "msg=%s tree=%d ftree=%d" % (lv.msg_text.cget("height"),
                                   lv.tree.winfo_height(),
                                   lv.ftree.winfo_height()))

# ============================================================
# 4. 读取提交历史（经 Hub 的真实 svn log -v）
# ============================================================
app.wc_path.delete(0, "end")
app.wc_path.insert(0, WC)
lv.limit_var.set("10")
lv.refresh()
check(app.busy and lv.btn_refresh.instate(["disabled"])
      and lv.btn_diff.instate(["disabled"]),
      "读取历史时界面忙碌且刷新/对比按钮禁用")
pump_idle()
revs = lv.tree.get_children()
check(len(revs) == 2
      and list(lv.tree.item(revs[0], "values"))[0] == "r2"
      and u"共 2 条" in lv.status.cget("text")
      and u"选中某个版本" in lv.msg_text.get("1.0", "end"),
      "修订列表两条、最新在上、状态与未选中提示正确",
      "%s / %s" % (revs, lv.status.cget("text")))

lv.tree.selection_set(revs[0])
lv._on_select()
mvals = list(lv.tree.item(revs[0], "values"))
paths0 = [str(lv.ftree.item(i, "values")[1]) for i in lv.ftree.get_children()]
check(str(lv.msg_text.cget("state")) == "disabled"
      and str(lv.msg_text.cget("wrap")) == "word"
      and mvals[3] == u"r2 改 a 新增 c …"
      and lv.msg_text.get("1.0", "end").strip() == MSG_R2,
      "说明区只读/按词换行，列表首行省略，完整说明可见",
      "%r / %r" % (mvals[3] if len(mvals) > 3 else None,
                   lv.msg_text.get("1.0", "end")[:60]))
check(len(paths0) == 2
      and any(p.endswith("a.txt") for p in paths0)
      and any(p.endswith("c.txt") for p in paths0)
      and any("A 添加" in str(lv.ftree.item(i, "values")[0])
              for i in lv.ftree.get_children()),
      "r2 文件列表为 a.txt/c.txt 并显示改动类型", str(paths0))

lv.tree.selection_set(revs[1])
lv._on_select()
paths1 = [str(lv.ftree.item(i, "values")[1]) for i in lv.ftree.get_children()]
check(lv.msg_text.get("1.0", "end").strip() == u"r1 说明"
      and len(paths1) == 2,
      "切换版本后说明区与文件列表同步更新", str(paths1))

# ============================================================
# 5. 双击修订 -> 差异（内置窗口 / meld 两条路）
# ============================================================
orig_find = m.App.find_meld
try:
    m.App.find_meld = staticmethod(lambda: None)
    # 本地未提交改动：双击对比的是“本次提交 vs 上一版本”（-c N = N-1→N），
    # 既不掺本地修改，也不含更早版本的内容
    with open(os.path.join(WC, "a.txt"), "w") as f:
        f.write("local-edit\nline1\nline2\n")
    lv.tree.selection_set(revs[0])
    lv._on_select()
    lv._on_rev_dbl()
    pump_idle()
    txt = app.diff_win.diff_text.get("1.0", "end") if app.diff_win else ""
    check(app.diff_win is not None
          and "a.txt" in txt and "line2" in txt
          and "local-edit" not in txt and "b1" not in txt
          and u"相比上一版本 r1" in lv.status.cget("text")
          and u"相比上一版本 r1" in app.diff_win.path_lbl.cget("text")
          and bool(app.diff_win.stats_lbl.cget("text"))
          and u"已用内置差异窗口" in lv.status.cget("text")
          and not app.meld_procs,
          "整版本内置差异：只含 r2 改动、写明上一版本、不启动 meld",
          txt[:120].replace("\n", "|"))
    app.diff_win.destroy()
    app.diff_win = None
    subprocess.check_call(["svn", "revert", "-q", "a.txt"], cwd=WC)

    # 双击文件行：只对比该文件
    iid = [i for i in lv.ftree.get_children()
           if "c.txt" in str(lv.ftree.item(i, "values"))][0]
    lv.ftree.selection_set(iid)
    lv.ftree.focus(iid)
    lv._on_file_dbl()
    pump_idle()
    txt = app.diff_win.diff_text.get("1.0", "end") if app.diff_win else ""
    check(app.diff_win is not None and "c.txt" in txt and "a.txt" not in txt,
          "单文件差异只含该文件", txt[:120].replace("\n", "|"))
    app.diff_win.destroy()
    app.diff_win = None

    # 有 meld：整版本统一差异仍进内置窗口——meld 3.20 的命令行打不开
    # 补丁视图，把 .diff 丢给它只会拿 diff 文件和它自己对比（“文件完全
    # 相同”，用户实测反馈）
    m.App.find_meld = staticmethod(lambda: "/bin/true")
    lv.tree.selection_set(revs[0])
    lv._on_rev_dbl()
    pump_idle()
    check(app.diff_win is not None
          and u"已用内置差异窗口" in lv.status.cget("text")
          and not app.meld_procs,
          "装了 meld 整版本对比仍用内置窗口且不启动 meld",
          str(app.meld_procs))
    app.diff_win.destroy()
    app.diff_win = None

    # 单文件 + meld：cat 出 r1/r2 两版原始内容，meld 左右两版对比
    iid = [i for i in lv.ftree.get_children()
           if "a.txt" in str(lv.ftree.item(i, "values"))][0]
    lv.ftree.selection_set(iid)
    lv.ftree.focus(iid)
    lv._on_file_dbl()
    pump_idle()
    check(u"已用 meld" in lv.status.cget("text")
          and bool(ASK_PARENTS) and ASK_PARENTS[-1] is lv,
          "单文件走 meld 两版对比，弹窗以提交历史为父窗",
          lv.status.cget("text"))
    # 不断言 meld_procs：/bin/true 启动即退出，泵事件时已被 _reap_meld
    # 回收；状态栏走到“已用 meld”就说明 Popen 成功（失败会是“启动失败”）
    prev_files = [f for f in os.listdir(app._tmp_dir())
                  if f.startswith("svnwb_prev_")]
    cur_files = [f for f in os.listdir(app._tmp_dir())
                 if f.startswith("svnwb_cur_")]
    left = right = None
    if prev_files and cur_files:
        with open(os.path.join(app._tmp_dir(), prev_files[-1])) as f:
            left = f.read()
        with open(os.path.join(app._tmp_dir(), cur_files[-1])) as f:
            right = f.read()
    check(left == "line1\n" and right == "line1\nline2\n",
          "两版临时文件内容为 r1 与 r2", "%r / %r" % (left, right))

    # 选“内置窗口”：单文件 + 装了 meld 也不设 pair，按地址跑统一差异
    DIFF_ANSWER["value"] = {"mode": "builtin", "remember": False}
    n_before = len([f for f in os.listdir(app._tmp_dir())
                    if f.startswith("svnwb_prev_")
                    or f.startswith("svnwb_cur_")])
    n_ask = ASK_CALLS[0]
    lv._on_file_dbl()
    pump_idle()
    txt = app.diff_win.diff_text.get("1.0", "end") if app.diff_win else ""
    n_after = len([f for f in os.listdir(app._tmp_dir())
                   if f.startswith("svnwb_prev_")
                   or f.startswith("svnwb_cur_")])
    check(ASK_CALLS[0] == n_ask + 1 and app.diff_win is not None
          and "a.txt" in txt and "line2" in txt
          and n_after == n_before,
          "单文件选内置时弹窗询问、显示文件改动、不生成两版临时文件",
          "%d/%d / %s" % (n_before, n_after,
                          txt[:80].replace("\n", "|")))
    if app.diff_win is not None:
        app.diff_win.destroy()
        app.diff_win = None

    # 弹窗取消：不启动任务、不弹差异窗口
    DIFF_ANSWER["value"] = None
    lv._on_file_dbl()
    check(u"已取消对比" in lv.status.cget("text")
          and not app.hub.busy() and app.diff_win is None,
          "取消对比：有提示、不启动任务、不弹差异窗口",
          lv.status.cget("text"))

    # 勾“记住”：写配置；下一次不再询问
    DIFF_ANSWER["value"] = {"mode": "builtin", "remember": True}
    app.store.set_option("diff_tool", "ask")
    n_ask = ASK_CALLS[0]
    lv._on_file_dbl()
    pump_idle()
    check(ASK_CALLS[0] == n_ask + 1
          and app.store.settings.get("diff_tool") == "builtin",
          "ask 模式弹窗询问，勾记住后写入配置",
          "%d / %r" % (ASK_CALLS[0],
                       app.store.settings.get("diff_tool")))
    if app.diff_win is not None:
        app.diff_win.destroy()
        app.diff_win = None
    n_ask = ASK_CALLS[0]
    lv._on_file_dbl()
    pump_idle()
    check(ASK_CALLS[0] == n_ask and app.diff_win is not None,
          "记住后不再弹窗，直接按保存的方式对比",
          str(ASK_CALLS[0]))
    if app.diff_win is not None:
        app.diff_win.destroy()
        app.diff_win = None
    app.store.set_option("diff_tool", "ask")     # 还原，后续用例仍会询问
    DIFF_ANSWER["value"] = {"mode": "meld", "remember": False}

    # 本版本新增的文件、工作副本停在上一版本 → 本地没有这个节点
    #（旧实现按工作副本相对路径对比报 E155010“找不到节点”，20261013
    # 用户日志实测），单文件按地址对比必须仍能成立
    m.App.find_meld = staticmethod(lambda: None)
    subprocess.check_call(["svn", "update", "-q", "-r", "1"], cwd=WC)
    iid = [i for i in lv.ftree.get_children()
           if "c.txt" in str(lv.ftree.item(i, "values"))][0]
    lv.ftree.selection_set(iid)
    lv.ftree.focus(iid)
    lv._on_file_dbl()
    pump_idle()
    check(app.diff_win is not None
          and "c.txt" in app.diff_win.diff_text.get("1.0", "end")
          and "+c1" in app.diff_win.diff_text.get("1.0", "end"),
          "本地无节点的新增文件仍能按地址对比（E155010 回归）",
          lv.status.cget("text"))
    if app.diff_win is not None:
        app.diff_win.destroy()
        app.diff_win = None
    subprocess.check_call(["svn", "update", "-q"], cwd=WC)   # 恢复到最新

    # 超大差异截断：防止整版本差异把内置窗口卡死（用户反馈“卡死”）
    big = ["+x%d" % i for i in range(m.DIFF_MAX_LINES + 300)]
    lv.open_diff({"rev": "2", "title": u"", "lines": big,
                  "stats": (0, 0, 0)})
    txt = app.diff_win.diff_text.get("1.0", "end") if app.diff_win else ""
    check(app.diff_win is not None
          and len(txt.splitlines()) <= m.DIFF_MAX_LINES + 10
          and u"已截断" in txt,
          "超大差异弹内置窗口、截断并写明原因",
          str(len(txt.splitlines())))
    if app.diff_win is not None:
        app.diff_win.destroy()
        app.diff_win = None
finally:
    m.App.find_meld = staticmethod(orig_find)

# ============================================================
# 6. 边界：没选版本点对比 / 空工作副本刷新
# ============================================================
for iid in lv.tree.selection():
    lv.tree.selection_remove(iid)
lv.diff_rev()
no_sel = lv.status.cget("text")
saved_wc = app.wc_path.get()
app.wc_path.delete(0, "end")
lv.refresh()
no_wc = lv.status.cget("text")
app.wc_path.insert(0, saved_wc)
check(u"请先选中一个版本" in no_sel
      and u"请先在主界面填写工作副本路径" in no_wc,
      "未选版本/未填工作副本时给出提示", "%r / %r" % (no_sel, no_wc))

# ============================================================
# 7. 地址目标（仓库浏览器右键“查看提交记录”带来 url）
# ============================================================
try:
    m.App.find_meld = staticmethod(lambda: None)   # 确保走内置差异窗口
    app._open_log_view(url="file://" + REPO)
    pump_idle()
    revs_url = lv.tree.get_children()
    check(app._log_view is lv and lv.url == "file://" + REPO
          and len(revs_url) == 2 and lv.title().endswith(REPO),
          "地址目标复用窗口、切换目标并读到提交", lv.title())

    # 双击修订：地址目标整版本对比，语义仍是“本次提交 vs 上一版本”
    lv.tree.selection_set(revs_url[0])
    lv._on_select()
    lv._on_rev_dbl()
    pump_idle()
    txt_rev = app.diff_win.diff_text.get("1.0", "end") if app.diff_win else ""
    rev_status = lv.status.cget("text")
    app.diff_win.destroy()
    app.diff_win = None

    # 双击文件：按仓库根拼出文件地址，只对比该文件
    iid = [i for i in lv.ftree.get_children()
           if "c.txt" in str(lv.ftree.item(i, "values"))][0]
    lv.ftree.selection_set(iid)
    lv.ftree.focus(iid)
    lv._on_file_dbl()
    pump_idle()
    txt_file = app.diff_win.diff_text.get("1.0", "end") if app.diff_win else ""
    check("line2" in txt_rev and u"相比上一版本 r1" in rev_status
          and "c.txt" in txt_file and "a.txt" not in txt_file,
          "地址目标整版本对比语义正确，单文件只含该文件",
          "%r / %r" % (rev_status, txt_file[:80].replace("\n", "|")))
    app.diff_win.destroy()
    app.diff_win = None
finally:
    m.App.find_meld = staticmethod(orig_find)

# 主界面按钮（不带 url）-> 切回工作副本目标并重读
app._open_log_view()
pump_idle()
check(lv.url == u"" and len(lv.tree.get_children()) == 2,
      "主界面按钮切回工作副本目标并重读",
      "%r / %s" % (lv.url, lv.tree.get_children()))

# ============================================================
# 8. 本版本删除的文件：HEAD 已无此路径，单文件对比仍要成立
#    （E155010 回归锁）；meld 两版模式右侧为空文件
# ============================================================
subprocess.check_call(["svn", "delete", "-q", "b.txt"], cwd=WC)
subprocess.check_call(["svn", "commit", "-q", "-m", "r3 删除 b"], cwd=WC)
lv.refresh()
pump_idle()
revs3 = lv.tree.get_children()
lv.tree.selection_set(revs3[0])          # r3 在最上面
lv._on_select()
b_rows = [i for i in lv.ftree.get_children()
          if "b.txt" in str(lv.ftree.item(i, "values"))]
check(len(revs3) == 3 and bool(b_rows),
      "删除提交后读到三条且 r3 文件行含 b.txt",
      str([str(lv.ftree.item(i, "values"))
           for i in lv.ftree.get_children()]))

try:
    # 没装 meld：按地址统一差异，HEAD 已无该路径也要成功
    m.App.find_meld = staticmethod(lambda: None)
    lv.ftree.selection_set(b_rows[0])
    lv.ftree.focus(b_rows[0])
    lv._on_file_dbl()
    pump_idle()
    txt = app.diff_win.diff_text.get("1.0", "end") if app.diff_win else ""
    check(app.diff_win is not None and "b.txt" in txt and "b1" in txt,
          "已删除文件的单文件对比成功（按地址，E155010 回归）",
          "%r / %s" % (lv.status.cget("text"),
                       txt[:100].replace("\n", "|")))
    if app.diff_win is not None:
        app.diff_win.destroy()
        app.diff_win = None

    # 有 meld：左 = 上一版本内容，右 = 空文件（本版本已删除）
    m.App.find_meld = staticmethod(lambda: "/bin/true")
    before = set(os.listdir(app._tmp_dir()))
    lv.ftree.selection_set(b_rows[0])
    lv.ftree.focus(b_rows[0])
    lv._on_file_dbl()
    pump_idle()
    new_files = set(os.listdir(app._tmp_dir())) - before
    prev_new = [f for f in new_files if "svnwb_prev_" in f]
    cur_new = [f for f in new_files if "svnwb_cur_" in f]
    left = right = None
    if prev_new and cur_new:
        with open(os.path.join(app._tmp_dir(), sorted(prev_new)[0])) as f:
            left = f.read()
        with open(os.path.join(app._tmp_dir(), sorted(cur_new)[0])) as f:
            right = f.read()
    check(u"已用 meld" in lv.status.cget("text")
          and left is not None and "b1" in left and right == u"",
          "删除文件走 meld 两版：左为上一版本内容，右为空文件",
          "%r / %r" % (left, right))
finally:
    m.App.find_meld = staticmethod(orig_find)

# ============================================================
# 9. 关闭窗口：引用清空、按钮摘干净
# ============================================================
lv.destroy()
app.root.update()
closed_ok = app._log_view is None
app._open_log_view()
check(closed_ok and app._log_view is not None and app._log_view is not lv,
      "关闭后引用清空，可再次打开新窗口")
app._log_view.destroy()
app.root.update()

app._on_close()

print("-" * 46)
if FAILS:
    print("通过 %d 项，失败 %d 项" % (PASSED[0], len(FAILS)))
    for f in FAILS:
        print("  FAIL: %s" % f)
    sys.exit(1)
print("log_view: ALL PASS (%d)" % PASSED[0])
sys.exit(0)
