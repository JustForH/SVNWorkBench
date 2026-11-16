# -*- coding: utf-8 -*-
"""SVNWorkBench 桌面版端到端回归测试（本地 file:// SVN 仓库）。

不进入 mainloop：用与界面相同的事件处理函数手动泵事件，
覆盖 检出/增量更新/排除的恢复与收紧/状态（含忽略文件与排序）/键盘选择/
添加/提交/删除/对比/差异/异源拒绝/运行日志默认折叠。
"""
import os
import re
import sys
from _testtmp import TMP  # noqa: E402
import time
import shutil
import subprocess
import tempfile
import queue as _queue

os.environ["SVNWB_CONFIG_DIR"] = TMP + "/cfg"
os.environ["SVNWB_LEGACY_SETTINGS"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/no_such_legacy_settings.json"   # 迁移源指向不存在的路径，不搬真实配置
os.environ["SVNWB_LOG_DIR"] = TMP + "/logs"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

import SVNWorkBench as m   # noqa: E402

URL = "file://" + TMP + "/svnrepo/trunk"
DST = TMP + "/dl_target"
EXCLUDES = ["lib/Mips", "lib/Win"]

FAILS = []
PASSED = [0]


def check(cond, msg, extra=""):
    if cond:
        PASSED[0] += 1
        print("PASS: %s" % msg)
    else:
        FAILS.append(msg)
        print("FAIL: %s %s" % (msg, extra))


# ---- 静默化所有弹窗：打印而不是阻塞等待点击 ----
def _silent(kind):
    def f(title, msg, parent=None, **kw):
        print("[MSG-%s] %s: %s" % (kind, title, str(msg).replace("\n", " | ")))
        return "ok"
    return f


m.messagebox.showerror = _silent("ERROR")
m.messagebox.showwarning = _silent("WARN")
m.messagebox.showinfo = _silent("INFO")
m.dialogs.ask_auth = lambda parent, message: (print("[ASK_AUTH] " + m.tail_msg(message)),
                                      {"ok": False})[-1]
m.dialogs.ask_cert = lambda parent, message: (print("[ASK_CERT] " + m.tail_msg(message)),
                                      {"ok": False})[-1]
m.dialogs.ask_confirm = lambda *a, **k: True
m.dialogs.show_logs = lambda *a, **k: None
# “选择对比方式”弹窗：测试里替换成固定答复（None = 取消），按需修改
DIFF_ANSWER = {"value": {"mode": "meld", "remember": False}}
ASK_CALLS = [0]


def _ask_diff_mode(parent):
    ASK_CALLS[0] += 1
    return DIFF_ANSWER["value"]


m.dialogs.ask_diff_mode = _ask_diff_mode
m.filedialog.askdirectory = lambda **kw: ""


def pump_task(app, mode, timeout=120):
    """泵主界面事件直到指定模式任务的 done（任务须已由别处启动）。"""
    end = time.time() + timeout
    got = None
    while time.time() < end:
        try:
            ev = app.hub.events.get_nowait()
        except _queue.Empty:
            time.sleep(0.02)
            continue
        app._handle_event(ev)
        if ev.get("type") == "done" and ev.get("mode") == mode:
            got = ev
            break
    if got is None:
        raise RuntimeError("等待任务超时: %s" % mode)
    # 泵完自动刷新等后续任务
    idle = 0.0
    end = time.time() + 60
    while time.time() < end:
        try:
            ev = app.hub.events.get_nowait()
        except _queue.Empty:
            if not app.hub.busy():
                idle += 0.05
                if idle >= 0.3:
                    break
            time.sleep(0.05)
            continue
        idle = 0.0
        app._handle_event(ev)
    return got


def run_task(app, mode, params, timeout=120):
    """启动任务、等待其 done，再把自动触发的后续任务泵完。"""
    if not app._run_start(mode, params):
        raise RuntimeError("_run_start 被拒绝: %s" % mode)
    return pump_task(app, mode, timeout)


def wait_probe(app, timeout=60):
    """等当前地址反查结果并交给主线程处理（与界面 _poll 同一条链路）。"""
    target = app.probe_seq
    got = []
    end = time.time() + timeout
    while time.time() < end:
        while not app.probe_q.empty():
            got.append(app.probe_q.get_nowait())
        if any(item[0] >= target for item in got):
            break
        time.sleep(0.02)
    for item in got:
        app._probe_done(*item)
    app._drain_probe()
    try:
        app.root.update()
    except Exception:
        pass


def log_since(app, idx):
    return app.log.get(idx, "end")


def list_lines(app):
    """改动列表（tk.Text）当前渲染出来的行文本。"""
    return [app.up_text.get("%d.0" % n, "%d.end" % n)
            for n in range(1, len(app.up_items) + 1)]


class Click(object):
    """模拟鼠标事件：列表的点击处理只用到 x/y/state（右键菜单还要根坐标）。"""
    def __init__(self, x, y, x_root=0, y_root=0, state=0):
        self.x, self.y = x, y
        self.x_root, self.y_root = x_root, y_root
        self.state = state


def click_line(app, n, x, state=0):
    """在第 n 行（1 起）的 x 位置模拟一次单击；state=1 表示按住 Shift。"""
    app.up_text.update_idletasks()     # 让 Tk 先排好行布局，dlineinfo 才有值
    info = app.up_text.dlineinfo("%d.0" % n)
    app._up_click(Click(x, info[1] + info[3] // 2, state=state))


def check_x(app, n):
    """第 n 行（1 起）☑/☐ 字形中心的 x 像素（只有点这里才切勾选）。"""
    app.up_text.update_idletasks()
    box = app.up_text.bbox("%d.0" % n)
    return box[0] + box[2] // 2


def dblclick_line(app, n, x):
    """在第 n 行（1 起）的 x 位置模拟一次双击（含随后的第二次 release）。"""
    app.up_text.update_idletasks()     # 见 click_line：先排好行布局
    info = app.up_text.dlineinfo("%d.0" % n)
    y = info[1] + info[3] // 2
    app._up_dblclick(Click(x, y))
    app._up_click(Click(x, y))       # 双击的第二次 release 应被忽略
    app._skip_release = False        # 复位，避免影响后续单击用例
    return y


def setup_repo():
    """重建本地 file:// 测试仓库。

    测试过程中会向仓库提交（加入版本控制/提交阶段），仓库状态会变化，
    因此每次运行都从零重建，保证用例可重复执行。
    """
    repo = TMP + "/svnrepo"
    setup = TMP + "/wc_setup"
    for p in (repo, setup):
        shutil.rmtree(p, ignore_errors=True)
    subprocess.check_call(["svnadmin", "create", repo])
    os.makedirs(setup)
    subprocess.check_call(["svn", "checkout", "-q", "file://" + repo,
                           os.path.join(setup, "wc")])
    wc = os.path.join(setup, "wc")
    files = ["trunk/src/a.c", "trunk/doc/readme.txt", "trunk/sub/deep/d.txt",
             "trunk/lib/Keep/k.txt", "trunk/lib/Mips/m.bin",
             "trunk/lib/Win/w.bin"]
    for rel in files:
        p = os.path.join(wc, rel)
        d = os.path.dirname(p)
        if not os.path.isdir(d):
            os.makedirs(d)
        with open(p, "w") as f:
            f.write("content of %s\n" % rel)
    subprocess.check_call(["svn", "add", "-q", "--parents"] + files, cwd=wc)
    subprocess.check_call(["svn", "commit", "-q", "-m", "init"], cwd=wc)


def main():
    setup_repo()
    shutil.rmtree(TMP + "/cfg", ignore_errors=True)
    shutil.rmtree(DST, ignore_errors=True)

    store = m.ConfigStore(m.CONFIG_DIR)
    store.load()
    store.update_fields(URL, DST, EXCLUDES)
    hub = m.Hub(store)
    app = m.App(store, hub)
    check(store.settings.get("diff_tool") == "ask"
          and app._diff_tool() == "ask"
          and app.btn_diff_mode.cget("text") == u"对比方式"
          and bool(app.up_text.bind("<Button-3>")),
          "对比方式默认询问且顶栏/右键入口存在")
    app._set_diff_mode("builtin")
    store2 = m.ConfigStore(m.CONFIG_DIR).load()
    check(store.settings.get("diff_tool") == "builtin"
          and app._diff_mode_var.get() == "builtin"
          and store2.settings.get("diff_tool") == "builtin",
          "对比方式写入配置、菜单同步且重载保留")
    app._set_diff_mode("ask")

    # ---- 阶段 0: 凭据命令行参数（--config-option 三段式语法回归） ----
    # 旧代码写成 servers:选项 两段式，svn 直接以 E205000 拒绝，
    # 导致勾选"记住密码"后的下载必失败
    r = m.Runner("download", _queue.Queue(), TMP + "/unit_check.log")
    r.creds = ("alice", "pw", True)
    opt = " ".join(r._decorate(["svn", "ls", URL]))
    check("servers:global:store-plaintext-passwords=yes" in opt
          and "servers:store-plaintext-passwords" not in opt,
          "记住密码使用三段式 --config-option: %s" % opt)
    pr = subprocess.Popen(
        ["svn", "--non-interactive", "--config-option",
         "servers:global:store-plaintext-passwords=yes", "ls", URL],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _so, se = pr.communicate(timeout=60)
    r2 = m.Runner("download", _queue.Queue(), TMP + "/unit_check.log")
    r2.creds = ("alice", "pw", False)
    opt2 = " ".join(r2._decorate(["svn", "ls", URL]))
    check(pr.returncode == 0
          and "--no-auth-cache" in opt2 and "config-option" not in opt2,
          "svn 接受三段式参数；不记住密码只加 --no-auth-cache: %s"
          % se.decode("utf-8", "replace").strip())

    # ---- 阶段 0b: 配置与日志的默认落点（都离开程序目录） ----
    env_log_ok = str(m.log_dir()) == os.environ.get("SVNWB_LOG_DIR")
    saved_log = os.environ.pop("SVNWB_LOG_DIR", None)
    default_log = m.log_dir()
    if saved_log is not None:
        os.environ["SVNWB_LOG_DIR"] = saved_log
    check(env_log_ok
          and str(default_log).startswith(tempfile.gettempdir() + os.sep)
          and "SVNWorkBench-" in str(default_log)
          and default_log.name == "logs",
          "日志目录环境变量覆盖/默认 = /tmp/SVNWorkBench-<用户>/logs: %s"
          % default_log)
    saved_xdg = os.environ.pop("XDG_CONFIG_HOME", None)
    default_cfg = m.core.default_config_dir()
    os.environ["XDG_CONFIG_HOME"] = TMP + "/xdg"
    try:
        xdg_ok = (str(m.core.default_config_dir())
                  == TMP + "/xdg/SVNWorkBench")
    finally:
        if saved_xdg is not None:
            os.environ["XDG_CONFIG_HOME"] = saved_xdg
        else:
            os.environ.pop("XDG_CONFIG_HOME", None)
    check(str(default_cfg).endswith(os.path.join(".config", "SVNWorkBench"))
          and xdg_ok and str(m.CONFIG_DIR) == TMP + "/cfg",
          "默认配置目录/XDG 覆盖/SVNWB_CONFIG_DIR 均正确: %s" % default_cfg)

    # ---- 阶段 0c: 旧版（程序同级 configs/_settings.json）一次性迁移 ----
    old_cfg = TMP + "/cfg_new_loc"
    legacy = TMP + "/legacy_settings.json"
    shutil.rmtree(old_cfg, ignore_errors=True)
    os.makedirs(old_cfg)
    m.Path(legacy).write_text(
        json.dumps({"svn_url": URL, "dst": DST, "excludes": ["doc"],
                      "trust_server_cert": True}), encoding="utf-8")
    old_legacy = m.config_store.LEGACY_SETTINGS
    m.config_store.LEGACY_SETTINGS = m.Path(legacy)
    try:
        st2 = m.ConfigStore(old_cfg)
        st2.load()
        check(st2.settings["svn_url"] == URL
              and st2.settings["dst"] == DST
              and st2.settings["excludes"] == ["doc"]
              and st2.settings["trust_server_cert"] is True
              and st2.settings.get("migrated") is True
              and m.Path(legacy).exists(),
              "旧配置字段迁入、打 migrated、旧文件保留")
        st2.update_fields("", "", [])        # 用户清空后重启，不能又搬回来
        st3 = m.ConfigStore(old_cfg)
        st3.load()
        check(st3.settings["svn_url"] == "",
              "迁移只做一次，不再回填: %s" % st3.settings["svn_url"])
        # 没有旧配置时也照常打标记（新装用户）
        m.config_store.LEGACY_SETTINGS = m.Path(TMP + "/no_legacy.json")
        st4 = m.ConfigStore(TMP + "/cfg_fresh")
        st4.load()
        check(st4.settings.get("migrated") is True
              and st4.settings["svn_url"] == "",
              "新装也打 migrated 标记且配置为空")
    finally:
        m.config_store.LEGACY_SETTINGS = old_legacy

    # ---- 阶段 0d: 启动参数（工作副本路径） ----
    old_wc = app.wc_path.get()
    old_url = store.settings.get("svn_url") or u""
    old_dst = store.settings.get("dst") or u""
    refresh_calls = []
    orig_refresh = app._refresh_status
    app._refresh_status = lambda quiet=False: refresh_calls.append(quiet)
    store.update_fields("", "", [])

    # 非法路径：只填到输入框，不写配置、不刷新列表（下次启动不显示）
    app.open_wc(TMP + "/nested_wc")
    wait_probe(app)
    check(app.wc_path.get() == TMP + "/nested_wc"
          and m.resolve_dst(str(app.wc_path.get())).is_absolute()
          and store.settings["dst"] == ""
          and store.settings["svn_url"] == ""
          and refresh_calls == [],
          "非法启动参数不写配置、不刷新改动列表")

    # 合法工作副本：反查成功后写回配置并刷新列表
    setup_wc = TMP + "/wc_setup/wc"     # setup_repo() 建的原始工作副本
    app.open_wc(setup_wc)
    wait_probe(app)
    check(app.wc_path.get() == setup_wc
          and app.url_entry.get().startswith("file://")
          and store.settings["dst"] == setup_wc
          and store.settings["svn_url"] == app.url_entry.get()
          and refresh_calls == [False],
          "启动参数为合法工作副本时反查并写回配置、刷新改动列表",
          "%r / %r" % (app.url_entry.get(), store.settings))
    app._refresh_status = orig_refresh

    # 还原表单/配置，后续阶段按原流程走
    app.wc_path.delete(0, "end")
    if old_wc:
        app.wc_path.insert(0, old_wc)
    app.url_entry.delete(0, "end")
    if old_url:
        app.url_entry.insert(0, old_url)
    app.url_auto = old_url or None
    app._wc_ok_path = str(m.resolve_dst(old_wc)) if old_wc else None
    store.update_fields(old_url, old_dst, [])

    # ---- 阶段 0e: 配置里的非法工作副本/残留地址在启动时被清掉 ----
    store.update_fields("https://svn.example.com/stale",
                        TMP + "/no_such_wc", [])
    app._load_settings()
    st_disk = m.ConfigStore(m.CONFIG_DIR).load()
    check(app.wc_path.get() == "" and app.url_entry.get() == ""
          and store.settings["dst"] == ""
          and store.settings["svn_url"] == ""
          and st_disk.settings["dst"] == ""
          and st_disk.settings["svn_url"] == "",
          "启动时不显示非法工作副本路径与残留地址，并从配置清除",
          "%r / %r / %r" % (app.wc_path.get(), app.url_entry.get(),
                            st_disk.settings))
    store.update_fields(old_url, old_dst, [])

    # ---- 阶段 1: 首次下载（走仓库浏览器的检出桥接） ----
    store.update_fields("", "", [])      # 先清空，验证检出后回写配置
    idx = app.log.index("end-1c")
    started = app._checkout_from_browser(URL, DST, EXCLUDES)
    ev = pump_task(app, "download")
    check(started is True and ev.get("ok") is True
          and app.log_expanded is False
          and app.toast_text.cget("text") == u"下载完成",
          "检出桥接启动并完成下载，日志保持折叠，状态栏显示结果")
    p = m.resolve_dst(DST)
    check((p / "src/a.c").is_file()
          and (p / "doc/readme.txt").is_file()
          and (p / "sub/deep/d.txt").is_file()
          and (p / "lib/Keep/k.txt").is_file()
          and not (p / "lib/Mips/m.bin").exists()
          and not (p / "lib/Win/w.bin").exists(),
          "下载内容正确且排除清单生效")
    check("下载完成" in log_since(app, idx)
          and store.settings["svn_url"] == URL
          and store.settings["dst"] == DST
          and store.settings["excludes"] == EXCLUDES
          and any(f.endswith(".log") for f in os.listdir(m.log_dir()))
          and not (m.CONFIG_DIR / "logs").exists(),
          "下载日志与配置（地址/目录/排除）均正确回写")

    # ---- 阶段 1b: 工作副本变化 -> 自动反查地址并刷新改动列表 ----
    setup_wc = TMP + "/wc_setup/wc"
    with open(os.path.join(setup_wc, "auto_probe.txt"), "w") as f:
        f.write("auto\n")
    app.wc_path.delete(0, "end")
    app.wc_path.insert(0, setup_wc)
    app.url_entry.delete(0, "end")
    app.url_auto = None
    app._wc_blur()                 # 自动（非手动）触发反查
    wait_probe(app)
    ev = pump_task(app, "status")
    names = [i["path"] for i in app.up_items]
    check(ev.get("ok") is True
          and "auto_probe.txt" in names
          and app.url_entry.get().startswith("file://")
          and store.settings["dst"] == setup_wc
          and app.toast_text.cget("text") == u"下载完成",
          "工作副本变化后自动反查地址并刷新列表（自动刷新不覆盖结果提示）",
          "%r / %r / %r" % (names, app.url_entry.get(),
                            store.settings.get("dst")))
    os.remove(os.path.join(setup_wc, "auto_probe.txt"))
    app._set_form(URL, DST, save=True)      # 还原到下载目标工作副本
    app.up_items = []

    # ---- 阶段 2: 上传状态列表 ----
    # 先做忽略规则（要提交的属性改动别把 a.c 的修改一起带上去）
    with open(str(p / "src/libz.so"), "w") as f:
        f.write("elf\n")
    subprocess.check_call(["svn", "propset", "svn:ignore", "*.so",
                           os.path.join(str(p), "src")])
    subprocess.check_call(["svn", "commit", "-q", "-m", "ignore *.so",
                           "src"], cwd=str(p))
    with open(str(p / "src/a.c"), "a") as f:
        f.write("\n// changed\n")
    with open(str(p / "src/new.c"), "w") as f:
        f.write("int n;\n")
    ev = run_task(app, "status", {"wc": str(p)})
    names = dict((i["path"], i["item"]) for i in app.up_items)
    check(ev.get("ok") is True
          and names.get("src/a.c") == "modified"
          and names.get("src/new.c") == "unversioned"
          and names.get("src/libz.so") == "ignored",
          "状态读取正确：修改/未版本控制/忽略文件都列出",
          str(names))
    order = [i["path"] for i in app.up_items]
    lines = list_lines(app)
    check(order == ["src/a.c", "src/libz.so", "src/new.c"]
          and m.status_sort_key({"item": "unversioned", "path": "a"}) >
          m.status_sort_key({"item": "modified", "path": "zz"})
          and u"M 修改" in lines[0] and u"I 忽略" in lines[1]
          and u"? 未版本控制" in lines[2],
          "未版本控制/忽略排最后且状态文字正确: %s" % order)
    check(app.up_count.cget("text") == u"已勾选 0 / %d" % len(app.up_items)
          and not hasattr(app, "range_var")
          and len(list_lines(app)) == len(app.up_items),
          "默认全不勾选、无列表范围单选、行数与数据一致")
    check(bool(app.up_text.tag_ranges("mod"))
          and bool(app.up_text.tag_cget("mod", "background"))
          and bool(app.up_text.tag_cget("gray", "background")),
          "改动列表状态行按标签着色")

    app._up_all()
    all_ok = len(app._checked_paths()) == len(app.up_items)
    app._up_none()
    none_ok = app._checked_paths() == []
    check(all_ok and none_ok,
          "全选/全不选两种勾选操作正确")
    # 勾选切换（模拟点击第 1 行的勾选框区域）
    app._up_all()
    first = app.up_items[0]["path"]
    click_line(app, 1, check_x(app, 1))
    off_ok = (first not in app._checked_paths()
              and m.CHECK_OFF in list_lines(app)[0])
    click_line(app, 1, check_x(app, 1))
    on_ok = (first in app._checked_paths()
             and m.CHECK_ON in list_lines(app)[0])
    check(off_ok and on_ok, "点击勾选框可取消/恢复勾选且字形同步")

    # 资源管理器式高亮选择（用户要求）：Ctrl/Shift 只改变行高亮，
    # ☑/☐ 只在点勾选框或按空格时改变；先全部勾上，验证选择始终不动勾选
    app._up_none()
    app.up_sel_lines = set()
    app.up_sel_line = None
    app.up_anchor_line = None
    app._up_all()
    checked_snapshot = set(app.up_checked)
    click_line(app, 2, 300)              # 普通单击正文：只高亮第 2 行
    plain_ok = (app.up_sel_lines == set([1])
                and app.up_sel_line == 1
                and app.up_anchor_line == 1
                and app.up_checked == checked_snapshot
                and m.CHECK_ON in list_lines(app)[1])
    click_line(app, 3, 300, state=4)     # Ctrl 单击第 3 行：追加高亮
    ctrl_add_ok = (app.up_sel_lines == set([1, 2])
                   and app.up_anchor_line == 2
                   and app.up_checked == checked_snapshot)
    click_line(app, 2, 300, state=4)     # Ctrl 单击第 2 行：取消该行高亮
    ctrl_del_ok = (app.up_sel_lines == set([2])
                   and app.up_anchor_line == 1
                   and app.up_checked == checked_snapshot)
    click_line(app, 1, 300, state=1)     # Shift 第 1 行：高亮 1-2，清空段外
    shift_ok = (app.up_sel_lines == set([0, 1])
                and app.up_sel_line == 0 and app.up_anchor_line == 1
                and app.up_checked == checked_snapshot)
    click_line(app, 3, 300, state=5)     # Ctrl+Shift 第 3 行：追加 2-3
    ctrl_shift_ok = (app.up_sel_lines == set([0, 1, 2])
                     and app.up_sel_line == 2 and app.up_anchor_line == 1
                     and app.up_checked == checked_snapshot)
    # 只有点 ☑/☐ 字形才改勾选：点状态文字不算（用户反馈）
    app.up_text.update_idletasks()
    _st = app.up_text.bbox("2.2")        # 第 2 行状态文字首字符
    click_line(app, 2, _st[0] + _st[2] // 2)
    status_ok = (app.up_checked == checked_snapshot
                 and app.up_sel_lines == set([1]))   # 只是普通选中该行
    app._up_key_select_all()             # 重新把三行都高亮
    # 多行高亮时点选区内任一勾选框：整个选区同步成同一状态
    click_line(app, 2, check_x(app, 2))
    sync_off_ok = (app.up_checked
                   == checked_snapshot - set(app.up_items[i]["path"]
                                             for i in (0, 1, 2))
                   and app.up_sel_lines == set([0, 1, 2])
                   and app.up_sel_line == 1 and app.up_anchor_line == 1
                   and all("cur" in app.up_text.tag_names("%d.0" % (i + 1))
                           for i in range(3)))
    click_line(app, 3, check_x(app, 3))
    sync_on_ok = (app.up_checked == checked_snapshot
                  and app.up_sel_lines == set([0, 1, 2]))
    click_line(app, 2, check_x(app, 2), state=1)   # Shift 点方框也同步选区
    box_mod_ok = (app.up_checked
                  == checked_snapshot - set(app.up_items[i]["path"]
                                            for i in (0, 1, 2))
                  and app.up_sel_lines == set([0, 1, 2]))
    click_line(app, 2, check_x(app, 2))   # 恢复全勾
    # 未高亮的行点勾选框：只改它自己，不把选区扩成多行
    app._up_select_line(0)
    click_line(app, 2, check_x(app, 2))
    single_ok = (app.up_checked
                 == checked_snapshot - set([app.up_items[1]["path"]])
                 and app.up_sel_lines == set([0]))
    click_line(app, 2, check_x(app, 2))   # 恢复全勾
    app._up_key_select_all()             # Ctrl+A：全选高亮，不改勾选
    ctrl_a_ok = (app.up_sel_lines == set(range(len(app.up_items)))
                 and app.up_checked == checked_snapshot)
    app.up_text.update_idletasks()
    _last = app.up_text.dlineinfo("%d.0" % len(app.up_items))
    app._up_click(Click(300, _last[1] + _last[3] + 4))   # 点最后一行下方空白
    blank_ok = (not app.up_sel_lines and app.up_sel_line is None
                and app.up_checked == checked_snapshot)
    check(plain_ok and ctrl_add_ok and ctrl_del_ok and shift_ok
          and ctrl_shift_ok and ctrl_a_ok and blank_ok,
          "高亮选择与勾选分离：单选/追加/取消/整段/追加整段/"
          "Ctrl+A/空白清空选择",
          "%r / %r / %r" % (sorted(app.up_sel_lines), app.up_sel_line,
                            app.up_anchor_line))
    check(status_ok and sync_off_ok and sync_on_ok and box_mod_ok and single_ok,
          "只有点 ☑/☐ 才改勾选；多行高亮时整个选区联动，未选中行只改自己",
          "%r / %r" % (sorted(app.up_checked), sorted(app.up_sel_lines)))
    app._up_none()
    app.up_sel_lines = set()
    app._up_mark_current()

    # ---- 阶段 2b: 键盘操作（↑/↓ 移动，Shift+方向扩展，空格批量勾选） ----
    bindings_ok = (bool(app.up_text.bind("<Up>"))
                   and bool(app.up_text.bind("<Down>"))
                   and bool(app.up_text.bind("<Shift-Up>"))
                   and bool(app.up_text.bind("<Shift-Down>"))
                   and bool(app.up_text.bind("<Shift-Prior>"))
                   and bool(app.up_text.bind("<Shift-Next>"))
                   and bool(app.up_text.bind("<Shift-Home>"))
                   and bool(app.up_text.bind("<Shift-End>"))
                   and bool(app.up_text.bind("<space>")))
    app._up_none()
    app.up_sel_line = None
    app.up_sel_lines = set()
    app.up_selected = None
    moves = []
    app._up_move(1)
    moves.append(app.up_selected == app.up_items[0]["path"])
    app._up_move(1)
    moves.append(app.up_selected == app.up_items[1]["path"])
    app._up_move(-1)
    moves.append(app.up_selected == app.up_items[0]["path"])
    app._up_move(-1)
    moves.append(app.up_selected == app.up_items[0]["path"])
    app._up_move(1, last=True)
    moves.append(app.up_selected == app.up_items[-1]["path"])
    app._up_move(1)
    moves.append(app.up_selected == app.up_items[-1]["path"])
    # Shift+↓ 从锚点 0 扩展到 0-1、0-2；Shift+↑ 缩回 0，锚点不动
    app._up_move(1, first=True)
    app._up_move(1, extend=True)
    shift_down = (app.up_sel_lines == set([0, 1])
                  and app.up_sel_line == 1
                  and app.up_anchor_line == 0
                  and not app.up_checked)
    app._up_move(1, extend=True)
    shift_more = (app.up_sel_lines == set([0, 1, 2])
                  and app.up_anchor_line == 0)
    app._up_move(-2, extend=True)
    shift_up = (app.up_sel_lines == set([0])
                and app.up_sel_line == 0
                and app.up_anchor_line == 0)
    check(bindings_ok and all(moves) and shift_down and shift_more and shift_up
          and bool(app.up_text.tag_ranges("cur")),
          "键盘 ↑/↓/End 移动，Shift+↑/↓ 扩展/收缩选区且锚点不动")
    # 单行：空格切换当前行；多行：空格批量全勾/全取消（混合 -> 全勾）
    app._up_move(1, last=True)
    app._up_toggle_current()
    last_path = app.up_items[-1]["path"]
    on_ok = (last_path in app._checked_paths()
             and m.CHECK_ON in list_lines(app)[-1])
    app._up_toggle_current()
    off_ok = last_path not in app._checked_paths()
    app.up_sel_lines = set([0, 1, 2])
    app.up_sel_line = 1
    app._up_toggle_current()
    batch_on = (len(app._checked_paths()) == 3
                and all(app.up_items[i]["path"] in app.up_checked
                        for i in (0, 1, 2)))
    app._up_toggle_current()
    batch_off = not app.up_checked
    app.up_sel_line = None
    app.up_sel_lines = set()
    app._up_toggle_current()
    empty_ok = app._checked_paths() == []
    check(on_ok and off_ok and batch_on and batch_off and empty_ok,
          "空格批量勾选/取消高亮选区，无选区时切换当前行")
    app._up_none()

    # ---- 阶段 3: 添加 + 提交 ----
    ev_add = run_task(app, "add", {"wc": str(p), "paths": ["src/new.c"]})
    app.up_msg.delete("1.0", "end")
    app.up_msg.insert("1.0", u"e2e 测试提交")
    ev = run_task(app, "commit",
                  {"wc": str(p), "message": u"e2e 测试提交",
                   "paths": ["src/a.c", "src/new.c"]})
    check(ev_add.get("ok") is True and ev.get("ok") is True
          and ev.get("result")
          and app.up_msg.get("1.0", "end").strip() == "",
          "添加并提交成功，提交说明已清空")

    # ---- 阶段 3b: 默认不勾选时“提交”被拦截 ----
    app._up_none()
    app.up_msg.delete("1.0", "end")
    app.up_msg.insert("1.0", u"不该提交出去")
    app._commit()
    check(not app.hub.busy()
          and app.toast_text.cget("text") == u"请先勾选要提交的条目",
          "未勾选任何条目时提交被拦截并提示")

    # ---- 阶段 3c: 未版本控制目录添加后可用“还原”完整取消（E155038 回归） ----
    ndir = p / "newtree" / "sub"
    ndir.mkdir(parents=True)
    with open(str(ndir / "n.txt"), "w") as f:
        f.write("n\n")
    run_task(app, "status", {"wc": str(p)})
    tree_rows = [i for i in app.up_items
                 if i["path"] == "newtree"
                 or i["path"].startswith("newtree/")]
    check([(i["path"], i["item"]) for i in tree_rows]
          == [("newtree", "unversioned")],
          "未版本控制目录在列表里按顶层目录展示", str(tree_rows))
    app.up_checked = set([i["path"] for i in tree_rows])
    app._up_add()
    ev_add = pump_task(app, "add")
    names = dict((i["path"], i["item"]) for i in app.up_items)
    check(ev_add.get("ok") is True
          and names.get("newtree") == "added"
          and names.get("newtree/sub/n.txt") == "added",
          "添加未版本控制目录：连带子目录与文件一起加入")
    app.up_checked = set(i["path"] for i in app.up_items
                         if i["path"] == "newtree"
                         or i["path"].startswith("newtree/"))
    app._up_revert()
    ev_rev = pump_task(app, "revert")
    names = dict((i["path"], i["item"]) for i in app.up_items)
    check(ev_rev.get("ok") is True
          and names.get("newtree") == "unversioned"
          and "newtree/sub" not in names
          and (ndir / "n.txt").is_file(),
          "还原新增目录：整棵子树取消添加且本地文件保留")
    shutil.rmtree(str(p / "newtree"))
    run_task(app, "status", {"wc": str(p)})

    # ---- 阶段 3d: 删除目录后“还原”恢复整棵子树（同 E155038 回归） ----
    run_task(app, "delete", {"wc": str(p), "paths": ["sub/deep"]})
    names = dict((i["path"], i["item"]) for i in app.up_items)
    check(names.get("sub/deep") == "deleted" and not (p / "sub/deep").exists(),
          "删除目录：标记删除并移除本地目录")
    app.up_checked = set(["sub/deep"])
    app._up_revert()
    ev_rev = pump_task(app, "revert")
    names = dict((i["path"], i["item"]) for i in app.up_items)
    check(ev_rev.get("ok") is True and "sub/deep" not in names
          and (p / "sub/deep/d.txt").is_file(),
          "还原删除的目录：整棵子树一起恢复")

    # ---- 阶段 4: 双击对比（内置差异窗口） ----
    with open(str(p / "src/a.c"), "a") as f:
        f.write("// diff-me\n")
    ev = run_task(app, "status", {"wc": str(p)})
    tabs = re.findall(r"\d+", str(app.up_text.cget("tabs")))
    check(ev.get("ok") is True and len(app.up_items) >= 1
          and len(list_lines(app)) == len(app.up_items)
          and not app.up_checked
          and m.CHECK_OFF in list_lines(app)[0]
          and len(tabs) == 2
          and not any(i.get("repos_item") for i in app.up_items)
          and bool(app.up_text.bind("<Double-Button-1>"))
          and app.diff_win is None,
          "改动列表三列、默认全不勾选、无仓库更新数据，双击已绑定")

    click_line(app, 1, 300)
    check(app.up_selected == "src/a.c"
          and bool(app.up_text.tag_ranges("cur"))
          and app.diff_win is None,
          "单击只选中并高亮，不弹差异窗口")

    # ---- 样式：放大勾选框 + 鼠标悬停高亮 ----
    app.up_text.update_idletasks()
    _cb = app.up_text.bbox("1.0")      # 勾选框字符格
    _tb = app.up_text.bbox("1.2")      # 正文首字符格
    _dc = abs((_cb[1] + _cb[3] / 2.0) - (_tb[1] + _tb[3] / 2.0))
    check(app.font_chk.cget("size") > app.font_up.cget("size")
          and bool(app.up_text.tag_cget("chk", "font"))
          and app.up_text.tag_cget("txt", "offset") == str(m.UP_TEXT_OFFSET)
          and "txt" in app.up_text.tag_names("1.2")
          and "txt" not in app.up_text.tag_names("1.0")
          and _dc <= 2,
          "勾选框放大、正文垂直居中（中心差 %.1f px）" % _dc)
    hn = 2 if len(app.up_items) > 1 else 1   # 悬停第 2 行（只有 1 项时退到第 1 行）
    app.up_text.update_idletasks()          # 先排好行布局，dlineinfo 才有值
    info = app.up_text.dlineinfo("%d.0" % hn)
    y = info[1] + info[3] // 2
    app._up_motion(Click(300, y))
    hover_ok = (bool(app.up_text.tag_ranges("hover"))
                and app.up_hover_line == hn - 1
                and app.up_text.cget("cursor") == "arrow")
    app._up_leave(Click(300, 0))
    leave_ok = not app.up_text.tag_ranges("hover")
    app._up_motion(Click(300, y))
    app._up_render(list(app.up_items))      # 重绘会抹掉标签，鼠标还在原行
    redraw_ok = bool(app.up_text.tag_ranges("hover"))
    app._up_leave(Click(300, 0))
    check(hover_ok and leave_ok and redraw_ok,
          "悬停高亮进入/移出/重绘补回且不改光标")

    app._up_all()
    n_chk = len(app._checked_paths())
    dblclick_line(app, 1, check_x(app, 1))        # 双击勾选框区域
    check(len(app._checked_paths()) == n_chk and app.diff_win is None,
          "双击勾选区不改变勾选状态且不弹差异窗口")
    app._up_none()

    # 没装 meld -> 内置彩色差异窗口
    orig_find = m.App.find_meld
    m.App.find_meld = staticmethod(lambda: None)
    try:
        n_ask = ASK_CALLS[0]
        dblclick_line(app, 1, 300)
        ev = pump_task(app, "diff")
        diff = app.diff_win.diff_text.get("1.0", "end") if app.diff_win else ""
        check(ev.get("ok") is True and ASK_CALLS[0] == n_ask
              and "diff-me" in diff
              and app.diff_win is not None
              and bool(app.diff_win.stats_lbl.cget("text"))
              and not app.meld_procs,
              "没装 meld 时不询问、直接弹内置差异窗口",
              diff[:100].replace("\n", "|"))
    finally:
        m.App.find_meld = staticmethod(orig_find)

    # ---- 阶段 4b: 装了 meld -> 导出 BASE 基线交给 meld 对比 ----
    m.App.find_meld = staticmethod(lambda: "/bin/true")
    try:
        with open(str(p / "src/a.c"), "a") as f:
            f.write("// meld-me\n")
        run_task(app, "status", {"wc": str(p)})
        idx = [i["path"] for i in app.up_items].index("src/a.c")
        n_ask = ASK_CALLS[0]
        dblclick_line(app, idx + 1, 300)
        out = (app.diff_ctx or {}).get("out")
        ev = pump_task(app, "cat")
        base_ok = False
        if out and os.path.exists(out):
            with open(out) as f:
                base_ok = "meld-me" not in f.read()
        check(ASK_CALLS[0] == n_ask + 1 and bool(out) and ev.get("ok") is True
              and base_ok and len(app.meld_procs) == 1
              and app.diff_win is not None
              and "diff-me" in app.diff_win.diff_text.get("1.0", "end"),
              "ask 模式询问、导出未修改 BASE 并交给 meld 左右对比",
              str(out))
        # 未版本控制的新文件没有基线 -> 空基线直接打开，不跑 cat
        with open(str(p / "src/tmp_meld.c"), "w") as f:
            f.write("int t;\n")
        run_task(app, "status", {"wc": str(p)})
        idx2 = [i["path"] for i in app.up_items].index("src/tmp_meld.c")
        n0 = len(app.meld_procs)
        dblclick_line(app, idx2 + 1, 300)
        check(len(app.meld_procs) == n0 + 1
              and not app.hub.busy() and app.diff_ctx is None,
              "无基线条目用空基线直接打开 meld，不启动 cat 任务")

        # 显式选“内置窗口”：即使装了 meld 也不导出基线、不启动 meld
        n_meld = len(app.meld_procs)
        app._diff_open("src/a.c", mode="builtin")
        ev = pump_task(app, "diff")
        check(ev.get("ok") is True
              and app.diff_win is not None
              and "meld-me" in app.diff_win.diff_text.get("1.0", "end")
              and len(app.meld_procs) == n_meld,
              "显式选内置时显示本地改动且不启动 meld")

        # 未版本控制 + 内置：没有基线，按“全新增”显示文件内容
        app._diff_open("src/tmp_meld.c", mode="builtin")
        txt = app.diff_win.diff_text.get("1.0", "end") if app.diff_win else ""
        check(not app.hub.busy() and "+int t;" in txt
              and app.diff_win is not None
              and app.diff_win.path_lbl.cget("text") == "src/tmp_meld.c",
              "未版本控制条目内置对比按全新增显示且不启动 svn 任务",
              txt[:100].replace("\n", "|"))

        # 右键菜单：与仓库浏览器同款简单命令列表 + “对比方式”子菜单；
        # 高亮多选时右键落在选区内要保留选区，批量项作用于整个选区
        app._up_none()
        app.up_sel_lines = set([0, 1])
        app.up_sel_line = 0
        app.up_selected = app.up_items[0]["path"]
        app.up_anchor_line = 0
        app._up_mark_current()
        app.up_text.update_idletasks()
        info = app.up_text.dlineinfo("1.0")
        y = info[1] + info[3] // 2
        app._up_menu(Click(300, y,
                           app.up_text.winfo_rootx() + 300,
                           app.up_text.winfo_rooty() + y))
        menu = app._up_menu_obj
        labels = []
        idx = {}
        for i in range(menu.index("end") + 1):
            if menu.type(i) != "separator":
                label = menu.entrycget(i, "label")
                labels.append(label)
                idx[label] = i
        sub = app._up_mode_menu
        sub_labels = [sub.entrycget(i, "label")
                      for i in range(sub.index("end") + 1)]
        keep_sel = app.up_sel_lines == set([0, 1])
        i_check = idx.get(u"勾选所选条目")
        i_uncheck = idx.get(u"取消勾选所选条目")
        batch_on = batch_off = False
        if i_check is not None and i_uncheck is not None:
            menu.invoke(i_check)
            batch_on = (len(app._checked_paths()) == 2
                        and all(app.up_items[i]["path"] in app.up_checked
                                for i in (0, 1)))
            menu.invoke(i_uncheck)
            batch_off = not app.up_checked
        check(labels == [u"用 meld 对比", u"用内置窗口对比",
                         u"查看提交历史", u"勾选所选条目",
                         u"取消勾选所选条目", u"对比方式"]
              and sub_labels == [u"每次询问", u"总是用 meld",
                                 u"总是用内置窗口"]
              and keep_sel and batch_on and batch_off,
              "右键菜单格式正确，批量勾选/取消作用于高亮选区: %s / %s"
              % (labels, sub_labels))
        menu.unpost()
        try:
            menu.grab_release()
        except Exception:
            pass
        app._up_none()

        # “查看提交历史”：版本控制条目按仓库地址；未版本控制退回工作副本
        calls = []
        orig_open_log = app._open_log_view
        old_url = app.url_entry.get()
        app._open_log_view = lambda url=None: calls.append(url)
        try:
            app.url_entry.delete(0, "end")
            app.url_entry.insert(0, URL)
            app._view_log_for("src/a.c")
            file_ok = (bool(calls)
                       and calls[-1] == m.core.join_url(URL, "src/a.c"))
            app._view_log_for("src/tmp_meld.c")
            wc_ok = calls[-1] is None
            check(file_ok and wc_ok,
                  "查看提交历史：版本控制条目按文件地址，未版本控制退回工作副本",
                  repr(calls[-2:]))
        finally:
            app._open_log_view = orig_open_log
            app.url_entry.delete(0, "end")
            app.url_entry.insert(0, old_url)
    finally:
        m.App.find_meld = staticmethod(orig_find)

    # ---- 阶段 4c: 仓库侧有新版本，列表与差异仍只看本地 ----
    setup_wc = TMP + "/wc_setup/wc"
    with open(os.path.join(setup_wc, "trunk/doc/readme.txt"), "a") as f:
        f.write("\nrepo-side-change\n")
    subprocess.check_call(["svn", "commit", "-q", "-m", "repo change"],
                          cwd=setup_wc)
    ev = run_task(app, "status", {"wc": str(p)})
    check(ev.get("ok") is True
          and not any(i["path"] == "doc/readme.txt" for i in app.up_items)
          and not app.up_checked,
          "仓库有新版本时状态列表仍只列本地改动且默认不勾选")
    ev = run_task(app, "diff", {"wc": str(p), "path": ""})
    check(ev.get("ok") is True and app.diff_win is not None
          and "repo-side-change" not in
          app.diff_win.diff_text.get("1.0", "end"),
          "整副本差异只含本地未提交改动")

    # ---- 阶段 4d: 更新按钮 -> svn update ----
    app.wc_path.delete(0, "end")
    app.wc_path.insert(0, str(p))
    app.btn_up_update.invoke()          # 点界面上的“更新”按钮
    ev = pump_task(app, "update")
    with open(str(p / "doc/readme.txt")) as f:
        updated = "repo-side-change" in f.read()
    check(ev.get("ok") is True and updated
          and not any(i["path"] == "doc/readme.txt" for i in app.up_items),
          "更新拉取仓库改动并自动刷新列表")

    # ---- 阶段 5: 二次下载 -> 同源增量更新 ----
    idx = app.log.index("end-1c")
    ev = run_task(app, "download",
                  {"url": URL, "dst": DST, "excludes": EXCLUDES})
    check(ev.get("ok") is True and "增量更新" in log_since(app, idx),
          "二次下载走同源 svn update 增量更新")

    # ---- 阶段 6: 异源工作副本拒绝 ----
    ev = run_task(app, "download",
                  {"url": "file://" + TMP + "/svnrepo/trunk/sub",
                   "dst": DST, "excludes": []})
    check(ev.get("ok") is False
          and "其他来源" in str(ev.get("detail") or ""),
          "异源工作副本被拒绝并说明原因")

    # ---- 阶段 7: 重新勾选 -> 恢复；再取消勾选 -> 重新排除 ----
    ev = run_task(app, "download",
                  {"url": URL, "dst": DST, "excludes": ["lib/Win"],
                   "restore": ["lib/Mips"]})
    check(ev.get("ok") is True and (p / "lib/Mips/m.bin").is_file()
          and not (p / "lib/Win/w.bin").exists(),
          "按新勾选更新：重新勾选的 lib/Mips 拉回、lib/Win 保持排除")

    ev = run_task(app, "download",
                  {"url": URL, "dst": DST, "excludes": EXCLUDES})
    check(ev.get("ok") is True and not (p / "lib/Mips/m.bin").exists()
          and (p / "lib/Keep/k.txt").is_file(),
          "再次按勾选更新：lib/Mips 重新排除、lib/Keep 不受影响")

    # ---- 阶段 7b: 删除（svn delete --force：未版本控制 + 版本控制） ----
    with open(str(p / "src/new2.c"), "w") as f:
        f.write("int n2;\n")
    with open(str(p / "sub/deep/d.txt"), "a") as f:
        f.write("deep-change\n")
    run_task(app, "status", {"wc": str(p)})
    names = dict((i["path"], i["item"]) for i in app.up_items)
    check(names.get("src/new2.c") == "unversioned"
          and names.get("sub/deep/d.txt") == "modified",
          "删除前 new2.c 未版本控制、d.txt 有本地修改")
    app._up_none()
    app._up_delete()
    check(not app.hub.busy()
          and app.toast_text.cget("text") == u"请先勾选要删除的条目",
          "未勾选任何条目时删除被拦截并提示")
    app.up_checked = set(["src/new2.c", "sub/deep/d.txt"])
    seen = {}
    orig_confirm = m.dialogs.ask_confirm
    m.dialogs.ask_confirm = (
        lambda parent, title, body, *a, **k:
        seen.setdefault("body", body) or True)
    try:
        app._up_delete()
    finally:
        m.dialogs.ask_confirm = orig_confirm
    check("sub/deep/d.txt" in seen.get("body", ""),
          "删除前确认框列出所选条目")
    ev = pump_task(app, "delete")
    names = dict((i["path"], i["item"]) for i in app.up_items)
    check(ev.get("ok") is True
          and app.toast_text.cget("text") == u"已删除所选条目"
          and not (p / "src/new2.c").exists()
          and not (p / "sub/deep/d.txt").exists()
          and names.get("sub/deep/d.txt") == "deleted"
          and "src/new2.c" not in names,
          "删除：磁盘删除、版本控制标记删除、列表刷新正确")
    subprocess.check_call(["svn", "revert", "sub/deep/d.txt"], cwd=str(p))

    # ---- 阶段 8: 忙碌互斥 ----
    ok_busy = False
    try:
        hub.runner = type("R", (), {"is_alive": lambda self: True})()
        try:
            hub.start("download", {"url": URL, "dst": DST, "excludes": []})
        except m.BusyError:
            ok_busy = True
    finally:
        hub.runner = None
    check(ok_busy, "任务运行中拒绝并发启动（BusyError）")

    # ---- 收尾 ----
    tmp = app._tmp_dir()
    existed = os.path.isdir(tmp)
    app._on_close()
    check(existed and not os.path.isdir(tmp), "对比临时目录创建并在退出时清理")
    print("-" * 46)
    print("通过 %d 项，失败 %d 项" % (PASSED[0], len(FAILS)))
    for f in FAILS:
        print("  FAILED: %s" % f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
