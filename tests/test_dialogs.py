# -*- coding: utf-8 -*-
"""弹窗链路测试：确认框、对比方式选择框、运行日志折叠、运行结果常驻、
地址反查、日志文件、认证、证书、theme.CheckBox 文字复选框、登录凭据窗口
（列出/确认后删除）。

所有弹窗都是阻塞式（wait_window），必须用 after 时间线驱动：
opener 回调里打开弹窗（阻塞在嵌套事件循环），auto-driver 回调在同一
嵌套循环里找到弹窗并操作，全部断言在驱动结束后回到主流程执行。"""
import os, sys, time, shutil, subprocess, faulthandler
from _testtmp import TMP  # noqa: E402
import tkinter as tk
from tkinter import messagebox, ttk

faulthandler.dump_traceback_later(60, exit=True)

HOME = TMP + "/fakehome_dialogs"
shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME)
os.environ["HOME"] = HOME
os.environ["SVNWB_CONFIG_DIR"] = os.path.join(HOME, "cfg")
os.environ["SVNWB_LEGACY_SETTINGS"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/no_such_legacy_settings.json"   # 迁移源指向不存在的路径，不搬真实配置
os.environ["SVNWB_LOG_DIR"] = os.path.join(HOME, "logs")
os.environ["PATH"] = TMP + "/bin:" + os.environ["PATH"]

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import SVNWorkBench as m

PASSED = []
def ok(name, cond, extra=""):
    PASSED.append(name)
    print("%s %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        sys.exit(1)

INFOS = []
messagebox.showerror = lambda *a, **k: None
messagebox.showinfo = lambda *a, **k: INFOS.append(a)
messagebox.showwarning = lambda *a, **k: None

store = m.ConfigStore(m.CONFIG_DIR)
store.load()
hub = m.Hub(store)
app = m.App(store, hub)
app.root.update()

OBS = {}


def walk(parent):
    out = []
    for w in parent.winfo_children():
        out.append(w)
        out.extend(walk(w))
    return out


def dialogs():
    return [w for w in app.root.winfo_children()
            if isinstance(w, tk.Toplevel) and w.winfo_exists()]


def buttons(win):
    return [w for w in walk(win)
            if isinstance(w, tk.Button) or w.winfo_class() == "TButton"]


def click(win, text):
    for b in buttons(win):
        if (b.cget("text") or "") == text:
            b.invoke()
            return True
    return False


def entries(win):
    # 输入框统一用 ttk.Entry（与按钮同高 32px，见 theme.TEntry 样式）
    return [w for w in walk(win)
            if isinstance(w, (tk.Entry, ttk.Entry))]


def set_entry(e, s):
    e.delete(0, "end")
    e.insert(0, s)


def texts(win):
    return [w for w in walk(win) if isinstance(w, tk.Text)]


def checkbuttons(win):
    # 复选框统一用 theme.CheckBox（☑/☐ 大字形，见 theme.py）；
    # tk.Checkbutton 的小方框放大不了、clam 的 ttk 指示符是个“叉”，都不能用
    return [w for w in walk(win) if isinstance(w, m.theme.CheckBox)]


def drive(label, opener, steps):
    """opener: 无参可调用（打开阻塞弹窗）；steps: 依序对弹窗操作的函数。

    step 返回 None 表示“弹窗未就绪/不属于本步”（下一拍重试），
    返回其他值表示已执行操作；某步操作的弹窗真正消失后才进入下一步。
    这样可以容忍 event_generate 异步事件偶尔丢失的情况。
    """
    st = {"i": 0, "done": False, "res": None, "fail": False,
          "miss": 0, "cur": None, "err": None, "stop": False,
          "deadline": time.time() + 12}

    def close_all():
        for w in dialogs():
            try:
                w.destroy()
            except tk.TclError:
                pass

    def give_up(err):
        st["fail"] = True
        st["err"] = st["err"] or err
        st["stop"] = True
        close_all()

    def open_it():
        try:
            st["res"] = opener()
        except Exception as e:
            give_up("opener: %r" % e)
        finally:
            st["done"] = True

    def tick():
        if st["done"] or st["stop"]:
            return
        try:
            if time.time() > st["deadline"]:
                give_up(u"超时未完成")
                return
            moved = False
            if st["i"] < len(steps):
                cur = st["cur"]
                if cur is not None and not cur.winfo_exists():
                    # 上一步操作的弹窗已关闭 → 完成本步
                    st["i"] += 1
                    st["cur"] = None
                    moved = True
                else:
                    if cur is None:
                        dlgs = dialogs()
                        if dlgs:
                            cur = dlgs[-1]
                            st["cur"] = cur
                    if cur is not None:
                        if steps[st["i"]](cur) is not None:
                            moved = True
                        if not cur.winfo_exists():
                            st["i"] += 1
                            st["cur"] = None
            if moved:
                st["miss"] = 0
            else:
                st["miss"] += 1
            if st["miss"] > 60:      # ~3 秒无进展，放弃并强关弹窗
                st["fail"] = True
                st["err"] = u"驱动无进展"
                st["stop"] = True
                close_all()
                return
        except Exception as e:       # 步骤异常不能静默弄死驱动
            st["fail"] = True
            st["err"] = "%r" % e
            st["stop"] = True
            close_all()
            return
        app.root.after(50, tick)

    app.root.after(30, open_it)
    app.root.after(80, tick)
    end = time.time() + 15
    while not st["done"] and time.time() < end:
        app.root.after(30)
        app.root.update()
    complete = st["done"] and not st["fail"] and st["i"] >= len(steps)
    ok(label, complete,
       "steps=%d/%d fail=%s done=%s err=%s"
       % (st["i"], len(steps), st["fail"], st["done"], st["err"]))
    return st


# ---------- 1. ask_confirm：取消→False ----------
def confirm_cancel(d):
    OBS["t1"] = d.title()
    d.update_idletasks()
    OBS.setdefault("dlg_widths", []).append((d.title(), d.winfo_width()))
    return click(d, u"取消") or None

st = drive(u"确认框打开并可取消",
           lambda: m.ask_confirm(app.root, u"标题", u"第一行\n第二行\n第三行"),
           [confirm_cancel])
ok("确认框标题与取消结果",
   OBS.get("t1") == u"标题" and st["res"] is False,
   "%r / %r" % (OBS.get("t1"), st["res"]))

# ---------- 2. ask_confirm：自定义按钮→True ----------
st = drive(u"确认框自定义按钮可用",
           lambda: m.ask_confirm(app.root, u"标题", u"内容", u"开始下载"),
           [lambda d: click(d, u"开始下载") or None])
ok("确认框确定返回 True", st["res"] is True, str(st["res"]))


# ---------- 2a. 模态窗口最小化防护：dialog 类型 + 自动还原 ----------
def guard_step(d):
    if "guard_type" not in OBS:
        OBS["guard_type"] = str(d.attributes("-type"))
        OBS["guard_calls"] = []
        OBS["guard_grab"] = (d.grab_current() is d)
        # 模拟“被最小化”后的 Unmap；真实 wm iconify 对 transient 会被 Tk
        # 直接拒绝，所以这里替换 state/deiconify/lift 锁行为本身
        d.state = lambda: "iconic"
        d.deiconify = lambda: OBS["guard_calls"].append("deiconify")
        d.lift = lambda: OBS["guard_calls"].append("lift")
        d.event_generate("<Unmap>")
        return True
    if "deiconify" not in OBS["guard_calls"]:
        return None                 # 等 after_idle 的还原回调
    return click(d, u"取消") or None


st = drive(u"模态窗口最小化自动还原",
           lambda: m.ask_confirm(app.root, u"标题", u"内容"), [guard_step])
ok("模态窗口标为 dialog，被最小化时自动还原且保留抓取",
   "dialog" in OBS.get("guard_type", "")
   and OBS.get("guard_grab") is True
   and OBS.get("guard_calls") == ["deiconify", "lift"],
   "%r / %r / %r" % (OBS.get("guard_type"), OBS.get("guard_grab"),
                     OBS.get("guard_calls")))

# ---------- 2b. 对比方式选择框：取消 / 选内置并记住 ----------
def diff_cancel(d):
    OBS["diff_title"] = d.title()
    d.update_idletasks()
    OBS.setdefault("dlg_widths", []).append((d.title(), d.winfo_width()))
    if not buttons(d):
        return None
    return click(d, u"取消") or None

st = drive(u"对比方式弹窗可取消",
           lambda: m.dialogs.ask_diff_mode(app.root), [diff_cancel])
ok("对比方式弹窗标题与取消结果",
   OBS.get("diff_title") == u"选择对比方式" and st["res"] is None,
   "%r / %r" % (OBS.get("diff_title"), st["res"]))


def diff_builtin_remember(d):
    if "diff_btns" not in OBS:
        OBS["diff_btns"] = [b.cget("text") for b in buttons(d)]
    boxes = checkbuttons(d)
    if not boxes:
        return None
    if not boxes[0].get():
        boxes[0].invoke()
    OBS["diff_remember"] = boxes[0].get()
    return click(d, u"内置窗口") or None

st = drive(u"对比方式弹窗选内置并记住",
           lambda: m.dialogs.ask_diff_mode(app.root),
           [diff_builtin_remember])
ok("对比方式弹窗按钮、返回值与记住勾选",
   set(OBS.get("diff_btns") or []) >= {u"meld 对比", u"内置窗口", u"取消"}
   and st["res"] == {"mode": "builtin", "remember": True}
   and OBS.get("diff_remember") is True,
   "%r / %r / %r" % (OBS.get("diff_btns"), st["res"],
                     OBS.get("diff_remember")))

# ---------- 3. 运行日志：默认折叠 + 任务运行也不自动展开 ----------
app.root.update()
ok("日志默认折叠", app.log_expanded is False and not app.log.winfo_ismapped())
app._set_busy(True, "download")
app.root.update()
app._set_busy(False, None)
ok("任务运行前后都不自动展开日志",
   app.log_expanded is False and not app.log.winfo_ismapped())

app._toggle_log()
app.root.update()
expanded_ok = (app.log_expanded is True and app.log.winfo_ismapped()
               and u"\u25be" in app.log_toggle.cget("text"))
app._set_busy(True, "download")
app._set_busy(False, None)
still_ok = app.log_expanded is True
app._toggle_log()
app.root.update()
collapsed_ok = (app.log_expanded is False and not app.log.winfo_ismapped()
                and u"\u25b8" in app.log_toggle.cget("text"))
ok("日志标题展开/收起、箭头与用户状态保持",
   expanded_ok and still_ok and collapsed_ok,
   "%s/%s/%s" % (expanded_ok, still_ok, collapsed_ok))

# ---------- 3b. 运行结果常驻状态栏：不自动消失，下一条覆盖上一条 ----------
app._toast(u"下载完成", "ok")
for _ in range(10):
    app.root.update()
    time.sleep(0.02)
ok("toast 常驻且成功用绿色",
   app.toast_text.cget("text") == u"下载完成"
   and app.toast_text.cget("foreground") == "#15803d",
   "%s / %s" % (app.toast_text.cget("text"),
                app.toast_text.cget("foreground")))
app._toast(u"提交失败", "err")
ok("下一条结果覆盖上一条且失败用红色",
   app.toast_text.cget("text") == u"提交失败"
   and app.toast_text.cget("foreground") == "#dc2626",
   "%s / %s" % (app.toast_text.cget("text"),
                app.toast_text.cget("foreground")))

# ---------- 3c. 通知类失败不弹模态消息框 ----------
_dlg_before = len(dialogs())
_notify_ok = app._run_start("commit", {"message": "", "paths": []}) is False
app.root.update()
ok("通知类失败只更新状态栏/日志，不弹阻塞式消息框",
   _notify_ok
   and app.toast_text.cget("text") == u"请填写提交说明"
   and app.toast_text.cget("foreground") == m.core.LOG_COLORS["warn"]
   and u"请填写提交说明" in app.log.get("1.0", "end-1c")
   and len(dialogs()) == _dlg_before,
   "%r / %r / %r" % (app.toast_text.cget("text"),
                     app.toast_text.cget("foreground"), len(dialogs())))

# ---------- 4. 按工作副本反查 SVN 地址 ----------
def wait_probe(target_app=None):
    # 只等“当前这一次”反查的结果：worker 线程可能比上一次入队慢半拍，
    # 队列里先出现旧的 seq 时不能立刻收工（否则当前结果还没到，断言就
    # 读到上一条 toast——测试在本机偶发过这个竞态）。
    # 超时给足 30s：测试进程里第一次 fork/exec svn 可能要几秒（本机实测
    # 冷启动 4s 左右），原来 3s 会偶发失败。
    target_app = target_app or app
    target = target_app.probe_seq
    got = []
    for _ in range(600):
        while not target_app.probe_q.empty():
            got.append(target_app.probe_q.get_nowait())
        if any(item[0] >= target for item in got):
            break
        time.sleep(0.05)
    for item in got:
        target_app._probe_done(*item)
    target_app._drain_probe()
    target_app.root.update()


def set_wc(path, url=u""):
    app.wc_path.delete(0, "end")
    app.wc_path.insert(0, path)
    app.url_entry.delete(0, "end")
    app.url_entry.insert(0, url)


REFRESH_CALLS = []
orig_refresh_status = app._refresh_status
app._refresh_status = lambda quiet=False: REFRESH_CALLS.append(quiet)


def reset_calls():
    del REFRESH_CALLS[:]


set_wc(TMP + "/no_such_wc_dir")
reset_calls()
store.update_fields("", "", [])
app._probe_url(True)
wait_probe()
ok("目录不存在时提示且不改动地址/配置、不刷新列表",
   u"目录不存在" in app.toast_text.cget("text")
   and app.url_entry.get() == ""
   and store.settings["dst"] == ""
   and store.settings["svn_url"] == ""
   and REFRESH_CALLS == [],
   "%s / %r / %r" % (app.toast_text.cget("text"), app.url_entry.get(),
                     REFRESH_CALLS))

set_wc("/tmp")
reset_calls()
app._probe_url(True)
wait_probe()
ok("非工作副本时给出提示且不刷新列表",
   u"不是 SVN 工作副本" in app.toast_text.cget("text")
   and REFRESH_CALLS == [],
   "%s / %r" % (app.toast_text.cget("text"), REFRESH_CALLS))

# 真实工作副本 -> 反查地址并写回配置
REPO = TMP + "/dlg_repo"
WC = TMP + "/dlg_wc"
shutil.rmtree(REPO, ignore_errors=True)
shutil.rmtree(WC, ignore_errors=True)
subprocess.check_call(["svnadmin", "create", REPO])
subprocess.check_call(["svn", "checkout", "-q", "file://" + REPO, WC])
reset_calls()
set_wc(WC)
app._probe_url(True)
wait_probe()
ok("工作副本地址回填、记为自动地址并写回配置，成功后刷新列表",
   app.url_entry.get().startswith("file://")
   and app.url_auto == app.url_entry.get()
   and store.settings["svn_url"] == app.url_entry.get()
   and store.settings["dst"] == WC
   and REFRESH_CALLS == [False]
   and u"读取 SVN 地址" in app.toast_text.cget("text"),
   "%r / %r / %r / %r" % (app.url_entry.get(), app.url_auto,
                          store.settings.get("dst"), REFRESH_CALLS))

# 手改过的地址不被反查结果覆盖（地址有效时仍刷新列表）
reset_calls()
set_wc(WC, u"https://svn.example.com/hand-edited")
app._probe_url(True)
wait_probe()
ok("手改地址不被覆盖并给出说明",
   app.url_entry.get() == u"https://svn.example.com/hand-edited"
   and u"已保留你填写的地址" in app.toast_text.cget("text")
   and REFRESH_CALLS == [False],
   "%r / %r / %r" % (app.url_entry.get(), app.toast_text.cget("text"),
                     REFRESH_CALLS))

# 自动反查（离开输入框）：非法路径不写配置、不刷新
reset_calls()
store.update_fields("", "", [])
set_wc(TMP + "/no_such_wc_dir2")
app._wc_blur()
wait_probe()
ok("自动反查失败时非法工作副本不写配置、不刷新列表",
   store.settings["dst"] == "" and store.settings["svn_url"] == ""
   and REFRESH_CALLS == [],
   "%r / %r" % (store.settings, REFRESH_CALLS))

# 自动反查（工作副本变化）：成功写回配置并静默刷新列表
reset_calls()
set_wc(WC)
app.url_auto = None
app._wc_ok_path = None
app._wc_blur()
wait_probe()
ok("工作副本变化后自动反查成功并静默刷新列表",
   app.url_entry.get().startswith("file://")
   and store.settings["dst"] == WC
   and store.settings["svn_url"] == app.url_entry.get()
   and REFRESH_CALLS == [True],
   "%r / %r / %r" % (app.url_entry.get(), store.settings.get("dst"),
                     REFRESH_CALLS))

app._refresh_status = orig_refresh_status

# 纯函数：直接读 svn info 解析
url, err = m.probe_wc_url(WC)
url2, err2 = m.probe_wc_url("/tmp")
url3, err3 = m.probe_wc_url(TMP + "/no_such_dir")
ok("probe_wc_url 解析成功并拒绝非工作副本/不存在目录",
   url.startswith("file://") and url2 == u"" and bool(err2)
   and url3 == u"" and bool(err3),
   "%r / %r / %r" % (url, url2, url3))

# 浏览按钮 -> 选目录后自动反查（目录选择被 stub 成“取消”）
m.App._zenity_dir = staticmethod(lambda initial: "")
m.filedialog.askdirectory = lambda **kw: ""
app._browse_wc()
app.root.update()
ok("取消目录选择不改动工作副本", app.wc_path.get() == WC, app.wc_path.get())

# 工作副本是唯一标识：新窗口启动时反查地址，成功后才刷新列表
set_wc(WC)
app._save_form()
st2 = m.ConfigStore(m.CONFIG_DIR)
st2.load()
app2 = m.App(st2, m.Hub(st2))
app2.root.update()
STARTUP_CALLS = []
app2._refresh_status = lambda quiet=False: STARTUP_CALLS.append(quiet)
app2._startup_refresh()
wait_probe(app2)
ok("启动时自动反查地址并静默刷新改动列表",
   app2.url_entry.get().startswith("file://")
   and STARTUP_CALLS == [True],
   "%r / %r" % (app2.url_entry.get(), STARTUP_CALLS))
app2.root.destroy()

# 启动时配置里的非法路径：目录不存在直接清掉；存在但不是工作副本时
# 由启动反查失败清掉（界面与配置都不再显示，下次启动也干净）
st3 = m.ConfigStore(m.CONFIG_DIR)
st3.load()
st3.update_fields("https://svn.example.com/stale", "/tmp", [])
app3 = m.App(st3, m.Hub(st3))
app3.root.update()
STARTUP3 = []
app3._refresh_status = lambda quiet=False: STARTUP3.append(quiet)
app3._startup_refresh()
wait_probe(app3)
ok("启动时非工作副本路径及残留地址被清除",
   app3.wc_path.get() == "" and app3.url_entry.get() == ""
   and st3.settings["dst"] == "" and st3.settings["svn_url"] == ""
   and STARTUP3 == [],
   "%r / %r / %r" % (app3.wc_path.get(), app3.url_entry.get(),
                     st3.settings))
st3.update_fields("https://svn.example.com/stale2",
                  TMP + "/no_such_wc", [])
app3._load_settings()
st3_disk = m.ConfigStore(m.CONFIG_DIR).load()
ok("重启不显示非法工作副本路径与残留地址",
   app3.wc_path.get() == "" and app3.url_entry.get() == ""
   and st3_disk.settings["dst"] == ""
   and st3_disk.settings["svn_url"] == "",
   "%r / %r / %r" % (app3.wc_path.get(), app3.url_entry.get(),
                     st3_disk.settings))
app3.root.destroy()


# ---------- 5. 日志文件窗口 ----------
def logs_step(d):
    OBS["log_title"] = d.title()
    OBS["log_tree"] = any(w.winfo_class() == "Treeview" for w in walk(d))
    d.update_idletasks()
    OBS.setdefault("dlg_widths", []).append((d.title(), d.winfo_width()))
    if "log_notice" not in OBS:
        # 未选文件点“打开所选文件”：窗口内提示，不弹系统消息框
        for tree in [w for w in walk(d) if w.winfo_class() == "Treeview"]:
            tree.selection_remove(tree.selection())
        click(d, u"打开所选文件")
        OBS["log_notice"] = u" | ".join(
            (w.cget("text") or "") for w in walk(d)
            if isinstance(w, tk.Label)
            and u"请先选中" in (w.cget("text") or ""))
        return True
    d.event_generate("<Escape>")
    return True

st = drive(u"日志窗口可打开关闭", app._show_logs, [logs_step])
ok("日志窗口标题与文件列表",
   OBS.get("log_title") == u"运行日志文件" and OBS.get("log_tree") is True,
   "%r / %r" % (OBS.get("log_title"), OBS.get("log_tree")))
ok("日志窗口未选文件时窗口内提示（不弹模态消息框）",
   u"请先选中" in OBS.get("log_notice", ""),
   repr(OBS.get("log_notice")))

# ---------- 6. 认证弹窗：填写并连接 ----------
def auth_fill(d):
    if d.title() != u"需要 SVN 身份验证":
        return None
    ents = entries(d)
    OBS["auth_ents"] = len(ents)
    d.update_idletasks()
    OBS.setdefault("dlg_widths", []).append((d.title(), d.winfo_width()))
    if len(ents) != 2:
        return None
    OBS["auth_mask"] = ents[1].cget("show")
    OBS["auth_cbs"] = len(checkbuttons(d))
    if not OBS.get("auth_filled"):
        set_entry(ents[0], "alice")
        set_entry(ents[1], "secret")
        OBS["auth_filled"] = True
    if not OBS.get("auth_cb_on"):
        for cb in checkbuttons(d):
            cb.invoke()
            OBS["auth_cb_on"] = True
    return click(d, u"连接") or None

st = drive(u"认证弹窗填写并连接",
           lambda: m.ask_auth(app.root,
                              "svn: E170001: Authentication failed\nrealm: example"),
           [auth_fill])
v = st["res"] or {}
ok("认证弹窗输入框/密码打码/记住密码与返回凭据",
   OBS.get("auth_ents") == 2 and OBS.get("auth_mask") == "*"
   and OBS.get("auth_cbs") == 1 and v.get("ok") is True
   and v.get("username") == "alice" and v.get("password") == "secret"
   and v.get("remember") is True,
   "%r / %r" % (OBS.get("auth_ents"), v))

# ---------- 7. 证书弹窗 ----------
def cert_fill(d):
    if d.title() != u"服务器证书验证失败":
        return None
    OBS["cert_cbs"] = len(checkbuttons(d))
    d.update_idletasks()
    OBS.setdefault("dlg_widths", []).append((d.title(), d.winfo_width()))
    if not OBS.get("cert_cb_on"):
        for cb in checkbuttons(d):
            cb.invoke()
            OBS["cert_cb_on"] = True
    return click(d, u"信任并重试") or None

st = drive(u"证书弹窗信任并重试",
           lambda: m.ask_cert(app.root, "svn: E230001: Certificate verification failed"),
           [cert_fill])
ok("证书弹窗记住选择并返回 remember",
   OBS.get("cert_cbs") == 1
   and (st["res"] or {}).get("remember") is True,
   "%r / %r" % (OBS.get("cert_cbs"), st["res"]))

# ---------- 8. 认证弹窗取消路径 ----------
def auth_cancel(d):
    if d.title() != u"需要 SVN 身份验证":
        return None
    return click(d, u"取消本次操作") or None

st = drive(u"认证弹窗可取消",
           lambda: m.ask_auth(app.root, "auth required"),
           [auth_cancel])
ok("取消返回 ok=False", (st["res"] or {}).get("ok") is False, str(st["res"]))

# ---------- 9. theme.CheckBox：与改动列表一致的文字复选框 ----------
v = tk.BooleanVar(value=False)
cb = m.theme.CheckBox(app.root, text=u"测试勾选", variable=v)   # 不 pack：断言不依赖显示
initial_ok = (cb.glyph.cget("text") == m.CHECK_OFF
              and int(cb._glyph_font.cget("size")) ==
              m.theme.base_size() + m.UP_CHECK_DELTA
              and cb._glyph_font.cget("weight") == "bold")
cb.invoke()
ok("CheckBox 初始字形、字号与 invoke 翻转",
   initial_ok and v.get() is True and cb.glyph.cget("text") == m.CHECK_ON,
   "%r / %r" % (cb.glyph.cget("text"), v.get()))
cb.configure(state="disabled")
cb.invoke()
cb.configure(text=u"新文字")
ok("CheckBox 禁用后点击无效且文字可改",
   v.get() is True and cb.label.cget("text") == u"新文字",
   "%r / %r" % (v.get(), cb.label.cget("text")))
cb.destroy()

# ---------- 10. 登录凭据窗口：列出缓存凭据 ----------
SUB = TMP + "/fake_subversion"
shutil.rmtree(SUB, ignore_errors=True)
AUTH = os.path.join(SUB, "auth", "svn.simple")
os.makedirs(AUTH)
os.environ["SVNWB_SUBVERSION_DIR"] = SUB     # 测试不碰真实 ~/.subversion
ok("凭据目录可用环境变量覆盖",
   os.path.normpath(str(m.subversion_auth_dir())) == AUTH,
   str(m.subversion_auth_dir()))


def write_cred(fname, realm, user):
    p = os.path.join(AUTH, fname)
    with open(p, "w") as f:
        f.write("K 8\nsvn:realmstring\nV %d\n%s\nK 8\nusername\nV %d\n%s\n"
                % (len(realm), realm, len(user), user))
    return p


REALM_A = "https://svn.example.com:443 SVN realm alice"
REALM_B = "<file://" + TMP + "/credsrepo> alice"
FILE_A = write_cred("aaaa", REALM_A, "alice")
FILE_B = write_cred("bbbb", REALM_B, "bob")

creds = m.list_credentials()
ok("list_credentials 列出名称、用户名与缓存文件",
   len(creds) == 2
   and creds[0]["name"] == REALM_A and creds[1]["name"] == REALM_B
   and creds[0]["username"] == "alice" and creds[1]["username"] == "bob"
   and creds[0]["file"] == "aaaa",
   str(creds))

# ---------- 11. 登录凭据窗口：展示名称，确认后删除 ----------
OBS["cred_body"] = None
OBS["cred_title"] = None


def confirm_yes(parent, title, body, *a, **k):
    OBS["cred_title"] = title
    OBS["cred_body"] = body
    return True


m.dialogs.ask_confirm = confirm_yes


def creds_del(d):
    trees_ = [w for w in walk(d) if w.winfo_class() == "Treeview"]
    if not trees_:
        return None
    tree = trees_[0]
    OBS["cred_dlg_title"] = d.title()
    d.update_idletasks()
    OBS.setdefault("dlg_widths", []).append((d.title(), d.winfo_width()))
    if "rows0" not in OBS:
        OBS["rows0"] = list(tree.get_children())
        OBS["vals0"] = [tree.item(i, "values") for i in OBS["rows0"]]
    if "deleted" not in OBS:
        # 布局回归：窗口高度不够时 pack 曾把按钮条挤出可视区（只剩 1x1
        # 像素），用户“根本看不到删除按钮”-> 看不出、删不掉（20261015）。
        # 这里锁住“按钮真实占据可视区域”。
        d.update_idletasks()
        OBS["btn_vis"] = dict(
            ((b.cget("text") or ""), (b.winfo_width(), b.winfo_height()))
            for b in buttons(d))
        tree.selection_set(OBS["rows0"][0])
        click(d, u"删除所选…")
        OBS["deleted"] = True
        OBS["rows1"] = list(tree.get_children())
        return True
    if "center_gap" not in OBS:
        # 弹窗基于父窗口居中（用户要求），不偏左上角。首次进来时 WM
        # 装饰偏移的异步标定可能还没落地，等标定完成再量（本机 KWin
        # 把请求位置当框架左上角，客户区偏 (1, 41)，见 theme._calibrate）
        end = time.time() + 2
        while m.theme._DECOR is None and time.time() < end:
            d.update()
            time.sleep(0.02)
        OBS["center_gap"] = (
            d.winfo_rootx() + d.winfo_width() // 2
            - app.root.winfo_rootx() - app.root.winfo_width() // 2,
            d.winfo_rooty() + d.winfo_height() // 2
            - app.root.winfo_rooty() - app.root.winfo_height() // 2)
        OBS["transient"] = str(d.transient())
    return click(d, u"关闭") or None


st = drive(u"登录凭据窗口列出并删除", app._show_credentials, [creds_del])
vals0 = OBS.get("vals0") or []
ok("凭据窗口标题、行数与行内容",
   OBS.get("cred_dlg_title") == u"SVN 登录凭据"
   and len(OBS.get("rows0") or []) == 2
   and vals0 and vals0[0][0] == "alice" and vals0[0][1] == REALM_A
   and vals0[0][2] == "aaaa",
   "%r / %r" % (OBS.get("cred_dlg_title"), vals0))
ok("删除前确认并刷新列表，未选中的凭据保留",
   OBS.get("cred_title") == u"删除登录凭据"
   and REALM_A in (OBS.get("cred_body") or u"")
   and not os.path.exists(FILE_A) and os.path.exists(FILE_B)
   and OBS.get("rows1") == ["c0"],
   "%r / %r" % (OBS.get("cred_title"), OBS.get("rows1")))
VIS = OBS.get("btn_vis") or {}
ok("删除/刷新/关闭按钮在可视区内（不被布局挤出）",
   u"删除所选…" in VIS and u"刷新" in VIS and u"关闭" in VIS
   and all(w > 20 and h > 10 for w, h in VIS.values()), str(VIS))
GAP = OBS.get("center_gap") or (999, 999)
ok("凭据窗口居中并登记为父窗 transient",
   abs(GAP[0]) <= 5 and abs(GAP[1]) <= 5
   and OBS.get("transient") == str(app.root.winfo_toplevel()),
   "%r / %r" % (GAP, OBS.get("transient")))

# ---------- 12. 登录凭据窗口：未选中提示 / 取消不删除 ----------
INFOS[:] = []
OBS["no_sel_body"] = None


def confirm_must_not_run(parent, title, body, *a, **k):
    OBS["no_sel_body"] = body
    return True


m.dialogs.ask_confirm = confirm_must_not_run


def creds_no_sel(d):
    trees_ = [w for w in walk(d) if w.winfo_class() == "Treeview"]
    if not trees_:
        return None
    if "clicked" not in OBS:
        click(d, u"删除所选…")
        OBS["clicked"] = True
        OBS["no_sel_notice"] = u" | ".join(
            (w.cget("text") or "") for w in walk(d)
            if isinstance(w, tk.Label)
            and u"请先选中" in (w.cget("text") or ""))
        return True
    return click(d, u"关闭") or None


st = drive(u"登录凭据窗口未选中时提示", app._show_credentials, [creds_no_sel])
ok("未选中时窗口内提示先选凭据且不弹确认框",
   OBS.get("no_sel_body") is None
   and u"请先选中" in OBS.get("no_sel_notice", "")
   and not INFOS,
   "%r / %r / %r" % (OBS.get("no_sel_body"), OBS.get("no_sel_notice"),
                     INFOS[-1:]))

OBS["cancel_body"] = None
OBS["cancel_clicked"] = False


def confirm_no(parent, title, body, *a, **k):
    OBS["cancel_body"] = body
    return False


m.dialogs.ask_confirm = confirm_no


def creds_cancel(d):
    trees_ = [w for w in walk(d) if w.winfo_class() == "Treeview"]
    if not trees_:
        return None
    tree = trees_[0]
    if not OBS["cancel_clicked"]:
        rows = list(tree.get_children())
        if not rows:
            return None
        tree.selection_set(rows[0])
        click(d, u"删除所选…")
        OBS["cancel_clicked"] = True
        return True
    return click(d, u"关闭") or None


st = drive(u"登录凭据窗口取消不删除", app._show_credentials, [creds_cancel])
ok("取消删除时已展示凭据名称且文件保留",
   REALM_B in (OBS.get("cancel_body") or u"")
   and os.path.exists(FILE_B),
   repr(OBS.get("cancel_body")))

# 统一宽度回归：弹窗不再按内容自适应（确认框短内容时曾缩成 200 多像素），
# 所有模态弹窗都撑到 theme.DIALOG_W；检出对话框在 test_repo_browser 里锁
WIDTHS = OBS.get("dlg_widths") or []
ok("所有模态弹窗宽度统一为 DIALOG_W",
   len(WIDTHS) >= 6 and len(set(w for _t, w in WIDTHS)) == 1
   and all(w == m.theme.DIALOG_W for _t, w in WIDTHS),
   "%r / DIALOG_W=%d" % (WIDTHS, m.theme.DIALOG_W))

print("dialogs: ALL PASS (%d)" % len(PASSED))
