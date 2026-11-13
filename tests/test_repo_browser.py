# -*- coding: utf-8 -*-
"""仓库浏览器回归测试（repo_browser.py）。

覆盖：纯函数（解析/勾选与恢复清单/本地状态解析/查看内容展示规则）、
read_local_kind 的五种本地关系、LsWorker 读取线程（含 svn cat）、
浏览器窗口的懒加载与右键（含"查看提交记录"打开地址目标提交历史、
空白处右键作用于当前目录、信任证书 ☐/☑ 复选框、查看内容窗口、
复制地址解码与内容窗口的快捷键/右键复制、
导出到…走 Hub 的真实 svn export）、检出对话框的
层级/单击与勾选分离/键盘操作/目录与文件级勾选与排除、本地目录实时校验、
模态链路（首次检出 / 按本地排除状态还原 / 拒绝异源、非工作副本与
被文件占用的路径）、经 Hub 的真实检出与按勾选更新（恢复 + 再排除）、
真实点按链路（点"开始下载"后自动收起辅助窗口 + 友好提示）。

不进入 mainloop：用 after 时间线 + root.update() 泵事件（弹窗阻塞时
由嵌套事件循环驱动）。配置与临时数据全部指向 /tmp，不碰真实配置。
"""
import base64
import codecs
import os
import sys
from _testtmp import TMP  # noqa: E402
import time
import shutil
import subprocess
import queue as _queue
import threading
import http.server
import tkinter as tk

try:
    import faulthandler
    faulthandler.dump_traceback_later(180, exit=True)
except ImportError:
    pass

HOME = TMP + "/fakehome_repo"
shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME)
os.environ["HOME"] = HOME
os.environ["SVNWB_CONFIG_DIR"] = TMP + "/cfg_repo"
os.environ["SVNWB_LEGACY_SETTINGS"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/no_such_legacy_settings.json"   # 迁移源指向不存在的路径，不搬真实配置
os.environ["SVNWB_LOG_DIR"] = TMP + "/logs_repo"
# 凭据缓存指向 /tmp（集合根 HTTP 读取会先查 svn.simple，不碰真实用户凭据）
os.environ["SVNWB_SUBVERSION_DIR"] = TMP + "/subversion_repo"
# 集合根用例访问本机临时 HTTP 服务，不让环境里的代理把它带走
os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
os.environ["no_proxy"] = "127.0.0.1,localhost,::1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import SVNWorkBench as m   # noqa: E402
import svnwb.repo_browser as rb    # noqa: E402

URL = "file://" + TMP + "/svnrepo/trunk"
DST = TMP + "/dl_repo_rb"

FAILS = []
PASSED = [0]


def check(cond, msg, extra=""):
    if cond:
        PASSED[0] += 1
        print("PASS: %s" % msg)
    else:
        FAILS.append(msg)
        print("FAIL: %s %s" % (msg, extra))


def write_auth_file(auth_dir, realm, username, password=None, filename=None):
    """写一个 svn.simple 凭据文件（K/V 长度前缀格式，含 realmstring）。"""
    if not os.path.isdir(auth_dir):
        os.makedirs(auth_dir)
    fields = [("username", username)]
    if password is not None:
        fields.append(("password", password))
    fields.append(("svn:realmstring", realm))
    lines = []
    for key, value in fields:
        lines.extend(["K %d" % len(key), key,
                      "V %d" % len(value.encode("utf-8")), value])
    lines.append("END")
    path = os.path.join(auth_dir,
                        filename or ("cred_%d" % int(time.time() * 1000000)))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


# ---- 静默化所有弹窗 ----
m.messagebox.showerror = lambda *a, **k: None
m.messagebox.showwarning = lambda *a, **k: None
m.messagebox.showinfo = lambda *a, **k: None
m.dialogs.ask_auth = lambda parent, message: {"ok": False}
m.dialogs.ask_cert = lambda parent, message: {"ok": False}
m.dialogs.ask_confirm = lambda *a, **k: True
m.dialogs.show_logs = lambda *a, **k: None
m.filedialog.askdirectory = lambda **kw: ""


def setup_repo():
    """重建本地 file:// 测试仓库（与 test_e2e 同构，可重复运行）。"""
    repo = TMP + "/svnrepo"
    setup = TMP + "/wc_setup_rb"
    for p in (repo, setup):
        shutil.rmtree(p, ignore_errors=True)
    subprocess.check_call(["svnadmin", "create", repo])
    os.makedirs(setup)
    subprocess.check_call(["svn", "checkout", "-q", "file://" + repo,
                           os.path.join(setup, "wc")])
    wc = os.path.join(setup, "wc")
    files = ["trunk/src/a.c", "trunk/doc/file.txt", "trunk/sub/deep/d.txt",
             "trunk/lib/Keep/k.txt", "trunk/lib/Mips/m.bin",
             "trunk/lib/Win/w.bin", "trunk/README.txt"]
    for rel in files:
        p = os.path.join(wc, rel)
        d = os.path.dirname(p)
        if not os.path.isdir(d):
            os.makedirs(d)
        with open(p, "w") as f:
            f.write("content of %s\n" % rel)
    gbk_rel = "trunk/sub/deep/gbk.txt"
    with open(os.path.join(wc, gbk_rel), "wb") as f:
        f.write(u"中文注释\n第二行".encode("gbk"))
    subprocess.check_call(["svn", "add", "-q", "--parents"] + files
                          + [gbk_rel], cwd=wc)
    subprocess.check_call(["svn", "commit", "-q", "-m", "init"], cwd=wc)


def ls_lines(url):
    """同步取一次目录列表（用于给对话框直接喂数据）。"""
    pr = subprocess.Popen(["svn", "list", "--xml", "--depth=immediates", url],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = pr.communicate(timeout=60)
    if pr.returncode != 0:
        raise RuntimeError(err.decode("utf-8", "replace"))
    return out.decode("utf-8", "replace").splitlines()


def walk(w):
    out = []
    for c in w.winfo_children():
        out.append(c)
        out.extend(walk(c))
    return out


def all_toplevels():
    return [w for w in walk(app.root)
            if isinstance(w, tk.Toplevel) and w.winfo_exists()]


def pump(seconds=0.2):
    end = time.time() + seconds
    while time.time() < end:
        app.root.update()
        time.sleep(0.02)


def wait_for(pred, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        app.root.update()
        time.sleep(0.02)
        if pred():
            return True
    return False


def worker_wait(w, tag, timeout=30):
    """取 LsWorker 的下一个 ls 事件（tag 匹配才返回）。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            ev = w.q.get_nowait()
        except _queue.Empty:
            time.sleep(0.02)
            continue
        if ev[0] == "ls" and (tag is None or ev[1] == tag):
            return ev
    return None


def wait_hub_done(mode, timeout=120):
    """泵主界面事件直到当前 Hub 任务的 done（任务须已由别处启动）。"""
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
    return got


def drive(label, opener, steps, timeout=25):
    """opener 阻塞在 wait_window；steps 依序执行，返回 None 表示未就绪。"""
    st = {"i": 0, "done": False, "res": None, "err": None, "miss": 0,
          "stop": False, "deadline": time.time() + timeout}

    def close_all():
        for w in all_toplevels():
            if isinstance(w, rb.CheckoutSelect):
                try:
                    w.destroy()
                except tk.TclError:
                    pass

    def open_it():
        try:
            st["res"] = opener()
        except Exception as e:
            st["err"] = "opener: %r" % e
            st["stop"] = True
            close_all()
        finally:
            st["done"] = True

    def tick():
        if st["done"] or st["stop"]:
            return
        try:
            if time.time() > st["deadline"]:
                st["err"] = u"驱动超时"
                st["stop"] = True
                close_all()
                return
            if st["i"] < len(steps):
                if steps[st["i"]]() is not None:
                    st["i"] += 1
                    st["miss"] = 0
                else:
                    st["miss"] += 1
                    if st["miss"] > 80:
                        st["err"] = u"驱动无进展（第 %d 步）" % st["i"]
                        st["stop"] = True
                        close_all()
                        return
            else:
                st["miss"] = 0
        except Exception as e:
            st["err"] = "%r" % e
            st["stop"] = True
            close_all()
            return
        app.root.after(50, tick)

    app.root.after(30, open_it)
    app.root.after(80, tick)
    end = time.time() + timeout + 6
    while not st["done"] and time.time() < end:
        app.root.update()
        time.sleep(0.02)
    complete = st["done"] and st["err"] is None and st["i"] >= len(steps)
    check(complete, label, "steps=%d/%d err=%s" % (
        st["i"], len(steps), st["err"]))
    return st


# ============================================================
# 1. 纯函数
# ============================================================
setup_repo()
# 检出目标先清掉：上一次运行残留会让对话框误判为“同源工作副本”
shutil.rmtree(DST, ignore_errors=True)

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<lists>
<list path="file:///x/trunk">
<entry kind="file">
<name>zeta.txt</name>
<size>3</size>
<commit revision="7"><author>tester</author>
<date>2026-10-10T00:56:00.319991Z</date></commit>
</entry>
<entry kind="dir">
<name>src</name>
<commit revision="5"><author>alice</author>
<date>2026-01-02T03:04:05Z</date></commit>
</entry>
<entry kind="dir">
<name>doc</name>
<commit revision="6"><author>bob</author>
<date>2026-01-02T03:04:05Z</date></commit>
</entry>
</list>
</lists>"""

items = rb.parse_list_xml(SAMPLE)
check(len(items) == 3
      and [i["name"] for i in items] == ["doc", "src", "zeta.txt"]
      and items[0]["kind"] == "dir" and items[2]["kind"] == "file"
      and items[0]["rev"] == "6" and items[0]["author"] == "bob"
      and items[0]["date"] == "2026-01-02 03:04"
      and items[2]["date"] == "2026-10-10 00:56"
      and items[2]["size"] == "3" and items[0]["size"] == "",
      "parse_list_xml 条目/排序/kind/rev/author/日期/大小", str(items))
try:
    rb.parse_list_xml("<lists><entry")
    raised = False
except RuntimeError:
    raised = True
check(rb.fmt_date("2026-10-10T00:56:00.319991Z") == "2026-10-10 00:56"
      and rb.fmt_date("") == "" and rb.fmt_date("garbage") == "garbage"
      and rb.parse_list_xml("") == [] and raised,
      "fmt_date 与 parse_list_xml 的空值/非法输入")

check(rb.fmt_size(0) == u"0 B" and rb.fmt_size(1023) == u"1023 B"
      and rb.fmt_size(1024) == u"1.0 KB" and rb.fmt_size(1536) == u"1.5 KB"
      and rb.fmt_size(1048576) == u"1.0 MB"
      and rb.fmt_size("") == u"" and rb.fmt_size(None) == u""
      and rb.fmt_size("abc") == u"",
      "fmt_size 二进制单位换算与目录/非法值留空")
check(rb.file_suffix(u"a.c") == u"c" and rb.file_suffix(u"a.tar.gz") == u"gz"
      and rb.file_suffix(u".bashrc") == u"" and rb.file_suffix(u"dir") == u""
      and rb.file_suffix(u"foo.") == u"",
      "file_suffix 取末段后缀，无后缀/隐藏文件/目录留空")

_recents = m.core.normalize_recent_urls(
    [URL + "/", URL, u"", u"https://h/%E4%B8%AD", URL + "/doc"])
check(m.RECENT_URL_LIMIT == 10
      and _recents == [URL, u"https://h/中", URL + "/doc"]
      and m.core.push_recent_url(_recents, URL + "/doc/")
      == [URL + "/doc", URL, u"https://h/中"]
      and len(m.core.push_recent_url(
          [u"https://h/%d" % i for i in range(15)], u"https://h/new")) == 10,
      "最近地址归一化/去重/最新在前/最多 10 条",
      repr(_recents))

# ---- 仓库集合根索引（mod_dav_svn 的 <svn><index>） ----
COLL_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<svn version="1.8.8" href="http://subversion.apache.org/">
  <index rev="0" path="Collection of Repositories">
    <dir name="alpha" href="alpha/"/>
    <dir name="组 件" href="%E7%BB%84%20%E4%BB%B6/"/>
    <dir name="dup" href="alpha/"/>
    <dir name="" href="empty/"/>
    <file name="README.txt" href="README.txt"/>
  </index>
</svn>"""
_coll = m.core.parse_repo_index(COLL_INDEX_XML,
                                "https://svn.example.com/svn")
check(_coll is not None and [i["name"] for i in _coll] == ["alpha", u"组 件"]
      and _coll[0]["kind"] == "dir"
      and _coll[0]["url"] == "https://svn.example.com/svn/alpha"
      and _coll[1]["url"]
      == "https://svn.example.com/svn/%E7%BB%84%20%E4%BB%B6",
      "parse_repo_index 解析集合根、去重、跳过空名/文件",
      repr(_coll))
_ns_xml = ("""<ns:svn xmlns:ns="http://subversion.apache.org/xml/ns">"""
           """<ns:index><ns:dir name="x" href="x/"/></ns:index></ns:svn>""")
_plain_repo = ("""<svn><index rev="5" path="/" base="/svn/alpha">"""
               """<dir name="trunk" href="trunk/"/></index></svn>""")
check([i["name"] for i in (m.core.parse_repo_index(
          _ns_xml, "https://svn.example.com/svn/") or [])] == ["x"]
      and m.core.parse_repo_index(_plain_repo,
                                  "https://svn.example.com/svn/alpha/") is None
      and m.core.parse_repo_index("<html><body>login</body></html>",
                                  "https://svn.example.com/svn/") is None
      and m.core.parse_repo_index("<svn><index>", "https://h/svn/") is None
      and m.core.parse_repo_index("<lists/>", "https://h/svn/") is None
      and m.core.parse_repo_index(COLL_INDEX_XML, "") is None
      and m.core.parse_repo_index(
          "<svn><index></index></svn>", "https://h/svn/") == [],
      "parse_repo_index 拒绝具体仓库页/HTML/坏 XML/空地址，空索引返回空列表")
check(m.core.looks_like_collection_error(
          "svn: E175009: The XML response contains invalid XML")
      and m.core.looks_like_collection_error(
          "190001: The URI does not contain the name of a repository")
      and m.core.looks_like_collection_error(
          "does not contain the name of a repository")
      and not m.core.looks_like_collection_error("svn: E170013: 无法连接")
      and not m.core.looks_like_collection_error(""),
      "looks_like_collection_error 只认集合根特征错误")

# ---- svn 缓存凭据：同源匹配，绝不把 A 服务器密码发给 B 服务器 ----
AUTH_PURE = TMP + "/auth_pure_repo"
shutil.rmtree(AUTH_PURE, ignore_errors=True)
write_auth_file(AUTH_PURE, "<https://svn.example.com> 测试登录域",
                "alice", "s3cret", "a")
write_auth_file(AUTH_PURE, "<http://other.example.com:80> 其他",
                "bob", "other", "b")
write_auth_file(AUTH_PURE, "<https://nopass.example.com> 无密码", "carol",
                None, "c")
cc = m.core.cached_credentials("https://svn.example.com/svn", AUTH_PURE)
check(cc is not None and cc["username"] == "alice"
      and cc["password"] == "s3cret"
      and cc["realm"] == "<https://svn.example.com> 测试登录域"
      and m.core.cached_credentials(
          "https://svn.example.com:8443/svn", AUTH_PURE) is None
      and m.core.cached_credentials(
          "http://svn.example.com/svn", AUTH_PURE) is None
      and m.core.cached_credentials(
          "https://nopass.example.com/svn", AUTH_PURE) is None
      and m.core.cached_credentials("file:///tmp/x", AUTH_PURE) is None
      and m.core.cached_credentials("", AUTH_PURE) is None,
      "cached_credentials 按 scheme/host/默认端口匹配且跳过无密码条目",
      repr(cc))

check(rb.checked_to_excludes({"": True}) == []
      and rb.checked_to_excludes({"": True, "doc": False, "src": True})
      == ["doc"]
      and rb.checked_to_excludes(
          {"": True, "lib": True, "lib/Keep": True,
           "lib/Mips": False, "lib/Win": False}) == ["lib/Mips", "lib/Win"]
      and rb.checked_to_excludes(
          {"": True, "lib": False, "lib/Keep": False, "lib/Mips": False})
      == ["lib"]
      and rb.checked_to_excludes(
          {"": True, "a": False, "a/b": True, "b": False}) == ["a", "b"],
      "checked_to_excludes 全选/叶子/父目录/混合场景")

check(rb.topmost(["a/b", "a", "c", ""]) == ["a", "c"]
      and rb.topmost([]) == []
      and rb.topmost(["x/", "/x/y"]) == ["x"],
      "topmost 只保留最上层、忽略空路径并规范斜杠")

# ---- 本地状态解析 ----
check(rb.parse_info_url("") == ""
      and rb.parse_info_url("bad<xml") == ""
      and rb.parse_info_url(
          "<?xml version=\"1.0\"?><info><entry><url>file:///r/trunk</url>"
          "</entry></info>") == "file:///r/trunk",
      "parse_info_url 取 entry/url 并容忍空/非法输入")

SAMPLE_STATUS = """<?xml version="1.0" encoding="UTF-8"?>
<status>
<target path="%(dst)s">
<entry path="%(dst)s"><wc-status item="normal" revision="1"/></entry>
<entry path="%(dst)s/doc"><wc-status item="normal" revision="1"/></entry>
<entry path="%(dst)s/doc/file.txt"><wc-status item="normal" revision="1"/></entry>
<entry path="/tmp/other/leak"><wc-status item="normal" revision="1"/></entry>
</target>
</status>""" % {"dst": DST}
have = rb.parse_status_have(SAMPLE_STATUS, DST)
check(have == set(["", "doc", "doc/file.txt"])
      and rb.parse_status_have("", DST) == set()
      and rb.parse_status_have("bad<xml", DST) is None,
      "parse_status_have 相对路径集合/空输出/非法 XML", str(have))

# ---- read_local_kind：本地目录与目标地址的五种关系 ----
NONE_DIR = TMP + "/no_such_dir_rb"
shutil.rmtree(NONE_DIR, ignore_errors=True)
st_none = rb.read_local_kind(URL, NONE_DIR)
st_empty = rb.read_local_kind(URL, "")
FRESH_DIR = TMP + "/fresh_dir_rb"
shutil.rmtree(FRESH_DIR, ignore_errors=True)
os.makedirs(FRESH_DIR)
st_fresh = rb.read_local_kind(URL, FRESH_DIR)
check(st_none["kind"] == "none" and st_none["have"] is None
      and st_empty["kind"] == "none" and st_fresh["kind"] == "fresh",
      "不存在/空路径 -> none，空目录 -> fresh")

NONWC_DIR = TMP + "/nonwc_dir_rb"
shutil.rmtree(NONWC_DIR, ignore_errors=True)
os.makedirs(NONWC_DIR)
with open(os.path.join(NONWC_DIR, "f.txt"), "w") as _f:
    _f.write("x")
FILE_DST = TMP + "/file_dst_rb"       # 本地目录被同名文件占用
if os.path.isdir(FILE_DST):
    shutil.rmtree(FILE_DST, ignore_errors=True)
with open(FILE_DST, "w") as _f:
    _f.write("x")
check(rb.read_local_kind(URL, NONWC_DIR)["kind"] == "unknown"
      and rb.read_local_kind(URL, TMP + "/wc_setup_rb/wc")["kind"]
      == "other",
      "非空非工作副本 -> unknown，异源工作副本 -> other")

# ---- 查看内容：cat_display 的展示规则 ----
text, note, binary = rb.cat_display(["a", "b"])
normal_ok = (text == "a\nb" and note == u"共 2 行" and binary is False)
text, note, binary = rb.cat_display([u"代码", u"\x00\x01binary"])
binary_ok = (binary is True and text == u"" and u"二进制文件" in note)
etext, enote, ebinary = rb.cat_display([])
empty_ok = (etext == u"" and enote == u"共 0 行" and ebinary is False)
check(normal_ok and binary_ok and empty_ok,
      "cat_display 普通文本/二进制/空文件")
big = [u"line %d" % i for i in range(rb.CAT_MAX_LINES + 10)]
text, note, binary = rb.cat_display(big)
trunc_ok = (text.count("\n") == rb.CAT_MAX_LINES - 1
            and u"仅显示前" in note
            and (u"%d" % (rb.CAT_MAX_LINES + 10)) in note)
bad_lines = [u"中文注释".encode("gbk").decode("utf-8", "replace")] * 5
_btext, _bnote, _bbinary = rb.cat_display(bad_lines)
check(trunc_ok and u"疑似非 UTF-8" in _bnote,
      "cat_display 超长截断并提示非 UTF-8 编码")

# ---- 查看内容：自动适配文本编码（用户反馈 GBK 文件显示乱码） ----
gbk_raw = u"中文注释\n第二行".encode("gbk")
_dtext, _denc, _dbin = rb.decode_text(gbk_raw)
check(_dtext == u"中文注释\n第二行" and _denc == u"GB18030"
      and _dbin is False,
      "decode_text 自动识别 GBK/GB18030 中文", repr((_dtext, _denc)))

_gtext, _gnote, _gbin = rb.cat_display(gbk_raw)
check(_gtext == u"中文注释\n第二行" and u"编码 GB18030" in _gnote
      and _gbin is False and u"\ufffd" not in _gtext,
      "cat_display 原始字节按实际编码解码，不再出现替换字符",
      repr((_gtext, _gnote)))

_utf16 = codecs.BOM_UTF16_LE + u"中文 UTF-16".encode("utf-16-le")
_u16text, _u16enc, _u16bin = rb.decode_text(_utf16)
check(_u16text == u"中文 UTF-16" and _u16enc == u"UTF-16 LE"
      and _u16bin is False,
      "decode_text 按 BOM 识别 UTF-16 LE", repr((_u16text, _u16enc)))

_ot, _on, _ob = rb.cat_display(gbk_raw, "latin-1")
_mt, _mn, _mb = rb.cat_display(b"\x89PNG\r\n\x1a\n\x00\x00\x00", "gb18030")
check(u"编码 Latin-1" in _on and not _ob
      and _mt == u"" and _mb is True,
      "内容窗口手动指定编码，二进制（含 NUL）仍只提示不渲染",
      repr((_on, _mt, _mb)))

# ============================================================
# 2. LsWorker
# ============================================================
w = rb.LsWorker()
w.start()
tag = ("node", URL)
w.request(tag, ["svn", "list", "--xml", "--depth=immediates", URL])
ev = worker_wait(w, tag)
got = rb.parse_lines(ev[3]) if ev and ev[2] else []
names = [i["name"] for i in got]
check(ev is not None and ev[2] is True
      and names == ["doc", "lib", "src", "sub", "README.txt"]
      and not os.path.exists(str(w.log_path)),
      "LsWorker 成功读取根目录且不写日志文件", str(names))

bad_tag = ("node", "file://" + TMP + "/no_such_repo_rb")
w.request(bad_tag, ["svn", "list", "--xml", "--depth=immediates",
                    "file://" + TMP + "/no_such_repo_rb"])
ev2 = worker_wait(w, bad_tag)
check(ev2 is not None and ev2[2] is False and ev2[3]
      and "svn" in str(ev2[3]),
      "不存在的地址返回带 svn 详情的错误", str(ev2)[:160])

cat_tag = ("cat", URL + "/doc/file.txt")
w.request(cat_tag, ["svn", "cat", URL + "/doc/file.txt"])
evc = worker_wait(w, cat_tag)
check(evc is not None and evc[2] is True and isinstance(evc[3], bytes)
      and evc[3] == b"content of trunk/doc/file.txt\n",
      "LsWorker 查看内容保留原始字节（供自动识别编码）", repr(evc)[:160])
w.stop()
w.join(timeout=8)
check(not w.is_alive(), "stop() 后线程退出")

# ---- 集合根：本地 HTTP 索引（不连接任何真实仓库） ----
class _CollHandler(http.server.BaseHTTPRequestHandler):
    """只读测试服务器：模拟 mod_dav_svn 的集合根/仓库页/权限错误。"""

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="text/xml; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _need_auth(self, user, password):
        want = "Basic " + base64.b64encode(
            ("%s:%s" % (user, password)).encode("utf-8")).decode("ascii")
        got = self.headers.get("Authorization") or ""
        if got == want:
            return False
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="test"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/idx/svn", "/idx/svn/"):
            self._send(200, COLL_INDEX_XML)
        elif path in ("/first", "/first/"):
            self._send(200, COLL_INDEX_XML)
        elif path in ("/secure", "/secure/"):
            if self._need_auth("alice", "s3cret"):
                return
            self._send(200, COLL_INDEX_XML)
        elif path in ("/ask", "/ask/"):
            if self._need_auth("manual", "pw"):
                return
            self._send(200, COLL_INDEX_XML)
        elif path in ("/priv", "/priv/"):
            self._send(403, "forbidden", "text/plain")
        elif path in ("/repo", "/repo/"):
            self._send(200, """<svn><index rev="5" base="/repo/">"""
                            """<dir name="trunk" href="trunk/"/></index></svn>""")
        elif path in ("/bad", "/bad/"):
            self._send(200, "<html>not xml</html>", "text/html")
        else:
            self._send(404, "not found", "text/plain")


srv = http.server.HTTPServer(("127.0.0.1", 0), _CollHandler)
PORT = srv.server_address[1]
COLL_ROOT = "http://127.0.0.1:%d" % PORT
th = threading.Thread(target=srv.serve_forever)
th.daemon = True
th.start()

# 缓存凭据：只有与服务器同源（host+port）的才可用于 HTTP Basic
write_auth_file(str(m.core.subversion_auth_dir()),
                "<%s/> 测试登录域" % COLL_ROOT,
                "alice", "s3cret", "http_server")

w2 = rb.LsWorker()
w2.start()

tag = ("collection", COLL_ROOT + "/idx/svn")
w2.request(tag, None)
ev = worker_wait(w2, tag)
_got = ev[3] if ev and ev[2] else []
check(ev is not None and ev[2] is True
      and [i["name"] for i in _got] == ["alpha", u"组 件"]
      and _got[0]["url"] == COLL_ROOT + "/idx/svn/alpha",
      "LsWorker 读取集合根 HTTP 索引并解析出仓库列表", str(_got)[:200])

tag_s = ("collection", COLL_ROOT + "/secure")
w2.request(tag_s, None)
ev_s = worker_wait(w2, tag_s)
check(ev_s is not None and ev_s[2] is True
      and [i["name"] for i in ev_s[3]] == ["alpha", u"组 件"],
      "401 时优先复用 svn 缓存凭据，不弹登录框", str(ev_s)[:200])

# 没有匹配缓存时退回登录框：事件由测试直接答复（真实界面走 dialogs.ask_auth）
tag_a = ("collection", COLL_ROOT + "/ask")
w2.request(tag_a, None)
end = time.time() + 30
ev_a = None
asked = False
while time.time() < end:
    try:
        _ev = w2.q.get_nowait()
    except _queue.Empty:
        time.sleep(0.02)
        continue
    if _ev[0] == "ask_auth":
        asked = True
        w2.respond({"ok": True, "username": "manual", "password": "pw",
                    "remember": False})
    elif _ev[0] == "ls" and _ev[1] == tag_a:
        ev_a = _ev
        break
check(asked and ev_a is not None and ev_a[2] is True,
      "缓存凭据不可用时发 ask_auth，答复后重试成功",
      "%r / %r" % (asked, ev_a))

tag_p = ("collection", COLL_ROOT + "/priv")
w2.request(tag_p, None)
ev_p = worker_wait(w2, tag_p)
check(ev_p is not None and ev_p[2] is False and u"403" in str(ev_p[3]),
      "集合根 HTTP 403 给出友好错误", str(ev_p)[:200])

tag_r = ("collection", COLL_ROOT + "/repo")
w2.request(tag_r, None)
ev_r = worker_wait(w2, tag_r)
check(ev_r is not None and ev_r[2] is False
      and u"不是仓库列表" in str(ev_r[3]),
      "具体仓库页（index 带 base）不当作集合根", str(ev_r)[:200])

tag_b = ("collection", COLL_ROOT + "/bad")
w2.request(tag_b, None)
ev_b = worker_wait(w2, tag_b)
check(ev_b is not None and ev_b[2] is False
      and u"不是仓库列表" in str(ev_b[3]),
      "HTML/非 XML 响应不当作集合根", str(ev_b)[:200])

tag_n = ("collection", COLL_ROOT + "/no_such")
w2.request(tag_n, None)
ev_n = worker_wait(w2, tag_n)
check(ev_n is not None and ev_n[2] is False and u"404" in str(ev_n[3]),
      "集合根 HTTP 404 给出友好错误", str(ev_n)[:200])

w2.stop()
w2.join(timeout=8)
srv.shutdown()
srv.server_close()
check(not w2.is_alive(), "集合根测试线程退出")

# ============================================================
# 3. 主窗口入口
# ============================================================
store = m.ConfigStore(m.CONFIG_DIR)
store.load()
store.update_fields(URL, DST, [])
# 种子一条历史，验证读回归一化 + 浏览后仍最新在前
store.set_option("recent_repo_urls", [URL + "/doc/"])
hub = m.Hub(store)
app = m.App(store, hub)
app.root.update()
# 检出目标尚未创建：启动时会清掉无效的 dst，这里单独给仓库浏览器
# 一个初始地址（模拟用户只填了 SVN 地址、还没选工作副本）
app.url_entry.insert(0, URL)
store.set_option("svn_url", URL)
store.set_option("dst", DST)         # 检出对话框的默认目录（测试种子）

texts = [c.cget("text") for c in walk(app.root)
         if c.winfo_class() in ("TButton", "Button") and c.cget("text")]
top_btns = [c.cget("text") for c in app.btn_theme.master.pack_slaves()
            if c.winfo_class() in ("TButton", "Button") and c.cget("text")]
url_row_btns = [c.cget("text") for c in app.url_entry.master.pack_slaves()
                if c.winfo_class() in ("TButton", "Button")
                and c.cget("text")]
row2_btns = [c.cget("text") for c in app.btn_up_add.master.pack_slaves()
             if c.winfo_class() in ("TButton", "Button") and c.cget("text")]
log_hd = app.log_toggle.master
log_hd_btns = [c for c in log_hd.pack_slaves()
               if c.winfo_class() in ("TButton", "Button") and c.cget("text")]
log_btns_by_text = dict((c.cget("text"), c) for c in log_hd_btns)
main_btns = [c for c in walk(app.root)
             if c.winfo_class() in ("TButton", "Button") and c.cget("text")]
right_col = [c for c in main_btns if c.cget("text") in (
    u"账号管理", u"刷新", u"显示日志", u"更新", u"提交", u"日志文件",
    u"取消任务")]
# “刷新”先反查地址，反查成功后才由 _probe_done 刷新改动列表
calls = []
old_wc = app.wc_path.get()
orig_probe, orig_status = app._probe_url, app._refresh_status
app._probe_url = lambda manual=False: calls.append(("probe", manual))
app._refresh_status = lambda quiet=False: calls.append(("status", quiet))
app.wc_path.delete(0, "end")
app.wc_path.insert(0, "/tmp")
app.btn_refresh.invoke()
app._probe_url, app._refresh_status = orig_probe, orig_status
app.wc_path.delete(0, "end")
app.wc_path.insert(0, old_wc)
check(u"仓库浏览" in texts and u"显示日志" in texts
      and u"刷新" in texts and u"更新" in texts
      and u"读取地址" not in texts and u"刷新状态" not in texts
      and top_btns == [u"账号管理", u"对比方式", u"主题"]
      and url_row_btns[-2:] == [u"仓库浏览", u"显示日志"]
      and row2_btns == [u"全选", u"全不选", u"添加", u"还原", u"删除", u"更新"]
      and [c.cget("text") for c in log_hd_btns] == [u"日志文件", u"清空显示"]
      and log_btns_by_text[u"日志文件"].winfo_x()
      > log_btns_by_text[u"清空显示"].winfo_x()
      and u"仅未版本控制" not in texts
      and u"加入版本控制" not in texts and u"恢复所选" not in texts
      and u"删除所选" not in texts
      and len(set(c.winfo_width() for c in main_btns)) == 1
      and len(set(c.winfo_height() for c in main_btns)) == 1
      and len(set(c.winfo_rootx() + c.winfo_width()
                  for c in right_col)) == 1
      and app.btn_refresh.master is app.wc_path.master
      and app.btn_log_files.master is log_hd
      and calls == [("probe", True)]
      and not any(t in texts for t in (u"导入脚本", u"新建", u"编辑")),
      "按钮改名/换位、日志文件移到清空显示后、刷新先反查地址、"
      "按钮等宽右对齐、无多项目按钮",
      str(texts))

app._open_repo_browser()
app.root.update()
rbw = app._repo_browser
check(rbw is not None and rbw.winfo_exists(), "仓库浏览窗口已打开")
app._open_repo_browser()
check(app._repo_browser is rbw, "窗口已开时复用不再新建")


def center_gap(win, parent):
    """窗口客户区中心与父窗口客户区中心的差（居中则接近 0,0）。"""
    return (win.winfo_rootx() + win.winfo_width() // 2
            - parent.winfo_rootx() - parent.winfo_width() // 2,
            win.winfo_rooty() + win.winfo_height() // 2
            - parent.winfo_rooty() - parent.winfo_height() // 2)


def centered(win, parent, tol=5):
    return max(abs(v) for v in center_gap(win, parent)) <= tol


# 弹窗基于父窗口居中（用户要求），不偏左上角。部分 WM（本机 DDE/KWin）
# 把请求位置当窗口框架左上角，客户区还要偏 (边框, 标题栏)——theme 首次
# 定位后异步标定并缓存（见 theme._calibrate），标定完第一个弹窗也会被
# 修正，所以用 wait_for 等它落地
check(wait_for(lambda: m.theme._DECOR is not None)
      and wait_for(lambda: centered(rbw, app.root))
      and str(rbw.transient()) == str(app.root),
      "仓库浏览器居中于主窗口并登记为父窗 transient",
      "%r / %r" % (m.theme._DECOR, center_gap(rbw, app.root)))

# ============================================================
# 4. 浏览器：加载 / 导航 / 右键 / 复制
# ============================================================
check(wait_for(lambda: URL in rbw._node_items
               and all(rbw.tree.item(c, "text") != rb.LOADING
                       for c in rbw.tree.get_children(URL))),
      "根节点子目录已加载", str(rbw.tree.get_children(URL)))
kids = rbw.tree.get_children(URL)
check(len(kids) == 4
      and URL in rbw._node_items and len(rbw._node_items[URL]) == 5
      and len(rbw.lst.get_children()) == 5
      and (u"trunk" in rbw.status.cget("text")
           or URL in rbw.status.cget("text")),
      "树根/条目缓存/右侧列表/状态栏一致",
      "%s / %s" % (kids, rbw.status.cget("text")))

# 地址栏是 32px 的可编辑下拉框；初始地址经“转到”成功后成为最近地址第一条
_recent_now = [URL, URL + "/doc"]
_recent_saved = m.ConfigStore(m.CONFIG_DIR).load().settings.get(
    "recent_repo_urls")
check(rbw.url_box.winfo_class() == "TCombobox"
      and rbw.url_box.winfo_reqheight() == 32
      and rbw._recent == _recent_now
      and list(rbw.url_box.cget("values")) == _recent_now
      and store.settings.get("recent_repo_urls") == _recent_now
      and _recent_saved == _recent_now,
      "地址栏为 32px Combobox，“转到”成功后记入最近地址并落盘",
      "%s / %s / %s" % (rbw._recent, rbw.url_box.cget("values"),
                        _recent_saved))

# 从下拉列表选择历史地址 -> 触发 <<ComboboxSelected>> -> 跳转
_picked = []
_orig_go = rbw._go
rbw._go = lambda: _picked.append(rbw.url_var.get())
rbw.url_var.set(URL + "/doc")
rbw.url_box.event_generate("<<ComboboxSelected>>")
rbw.master.update()
rbw._go = _orig_go
rbw.url_var.set(URL)
check(_picked == [URL + "/doc"],
      "从最近地址下拉选择后立即跳转", repr(_picked))

doc_url = [i for i in kids if i.endswith("/doc")][0]
dir_vals = rbw.lst.item(doc_url, "values")
check(dir_vals[0] == u"" and dir_vals[3] == u""
      and rbw.lst.item(doc_url, "text") == "doc"
      and bool(rbw.lst.item(doc_url, "image")),
      "目录行后缀/大小留空，名称列有图标与缩进", str(dir_vals))
# 所有列（含表头）左对齐；左树目录也有图标；图标右侧留出透明间隙
all_left = all(str(rbw.lst.column(c, "anchor")) == "w"
               and str(rbw.lst.heading(c, "anchor")) == "w"
               for c in ("#0",) + tuple(rbw.lst["columns"]))
check(all_left and bool(rbw.tree.item(doc_url, "image"))
      and rbw._icon_dir.width() == rb.LIST_ICON_W + rb.LIST_ICON_GAP,
      "列表所有列（含表头）左对齐，左树目录带图标且图标与文本留间隙",
      str([rbw.lst.column(c, "anchor") for c in rbw.lst["columns"]]))
rbw.tree.selection_set(doc_url)
check(wait_for(lambda: doc_url in rbw._node_items
               and len(rbw.lst.get_children()) == 1),
      "选中 doc 触发读取")
doc_rows = [rbw.lst.item(i, "values") for i in rbw.lst.get_children()]
row = rbw.lst.get_children()[0] if rbw.lst.get_children() else None
check(row is not None and len(doc_rows) == 1
      and rbw.lst.item(row, "text") == "file.txt"
      and doc_rows[0][0] == u"txt"
      and doc_rows[0][3] == u"30 B"
      and bool(rbw.lst.item(row, "image"))
      and len(rbw.tree.get_children(doc_url)) == 0
      and rbw._list_kind.get(row) == "file",
      "doc 下文件只出现在列表：名称带图标、后缀 txt、大小 30 B",
      str(doc_rows))
check(rbw._recent == [URL, doc_url]
      and list(rbw.url_box.cget("values")) == [URL, doc_url]
      and store.settings.get("recent_repo_urls") == [URL, doc_url],
      "树中浏览目录不写入最近地址（只有点“转到”才落盘）",
      repr(rbw._recent))

src_url = [i for i in kids if i.endswith("/src")][0]
rbw.tree.selection_set(src_url)
check(wait_for(lambda: src_url in rbw._node_items
               and len(rbw.lst.get_children()) == 1)
      and rbw._list_kind.get(rbw.lst.get_children()[0]) == "file",
      "选中 src 列出文件 a.c")
n_cached = len(rbw._node_items)
rbw._on_tree_select()          # 选择未变，应命中缓存
check(len(rbw._node_items) == n_cached, "命中缓存不重新请求",
      str(rbw._node_items.keys()))

labels = [rbw.menu_dir.entrycget(i, "label") for i in
          range(rbw.menu_dir.index("end") + 1)]
flabels = [rbw.menu_file.entrycget(i, "label") for i in
           range(rbw.menu_file.index("end") + 1)]
check(labels == [u"检出到…", u"导出到…", u"刷新此节点", u"查看提交记录",
                 u"复制地址"]
      and flabels == [u"查看内容", u"查看提交记录", u"导出到…", u"复制地址"],
      "目录/文件右键菜单项正确", "%s / %s" % (labels, flabels))
check(str(rbw.menu_dir.cget("background")) == m.SURFACE
      and str(rbw.menu_file.cget("background")) == m.SURFACE
      and str(rbw.menu_dir.cget("activebackground")) == m.ACCENT
      and str(rbw.menu_dir.cget("activeforeground")) == "#ffffff"
      and str(rbw.menu_dir.cget("relief")) == "solid"
      and int(rbw.menu_dir.cget("borderwidth")) == 1
      and int(rbw.menu_dir.cget("activeborderwidth")) == 0
      and int(rbw.menu_dir.cget("tearoff")) == 0,
      "右键菜单白底、强调色悬停、1px 实线边框且不可撕下",
      "%s/%s" % (rbw.menu_dir.cget("relief"),
                 rbw.menu_dir.cget("borderwidth")))

# 信任证书复选框：☐/☑ 文字字形（clam 的 ttk 指示符选中是个“叉”，不能用）
initial_ok = (isinstance(rbw.trust_check, m.theme.CheckBox)
              and rbw.trust_check.glyph.cget("text") == m.CHECK_OFF)
rbw.trust_check.invoke()
on_ok = (rbw.trust_var.get() is True
         and rbw.trust_check.glyph.cget("text") == m.CHECK_ON)
rbw.trust_check.invoke()
off_ok = rbw.trust_var.get() is False
check(initial_ok and on_ok and off_ok,
      "信任证书复选框为文字 CheckBox，可勾选/取消并同步配置")

# 右键“查看提交记录”：提交历史窗口切到选中路径的地址目标（不依赖工作副本）
rbw._menu_url = src_url
rbw._view_log(rbw._take_menu_url())
lv = app._log_view
check(lv is not None and lv.url == src_url and src_url in lv.title(),
      "查看提交记录打开历史窗口并切到选中路径地址",
      "%r / %r" % (lv, lv.url if lv else None))
loaded = wait_for(lambda: not app.busy and bool(lv.tree.get_children()))
lv.destroy()
app.root.update()
check(loaded and app._log_view is None,
      "地址目标读到提交记录，关闭后引用清空")

# 右侧列表右键：行上按行类型给菜单；**空白处**作用于当前目录，菜单与
# 左树一致（用户要求：空白处也能“查看提交记录”）
class _Ev2(object):
    x_root = 0
    y_root = 0
    y = 0


# 地址栏右键“清除最近记录”：有历史时可点，清空后置灰、配置同步清空
_pops_url = []
_orig_popup_url = rbw._popup
rbw._popup = lambda menu, ev: _pops_url.append(menu)
rbw._on_url_menu(_Ev2())
_menu_on = (bool(_pops_url) and _pops_url[-1] is rbw.menu_url
            and str(rbw.menu_url.entrycget(0, "state")) == "normal")
rbw._clear_recent()
_cleared = (rbw._recent == []
            and list(rbw.url_box.cget("values")) == []
            and store.settings.get("recent_repo_urls") == []
            and u"已清除最近浏览记录" in rbw.status.cget("text"))
rbw._on_url_menu(_Ev2())
_menu_off = (_pops_url[-1] is rbw.menu_url
             and str(rbw.menu_url.entrycget(0, "state")) == "disabled")
rbw._popup = _orig_popup_url
check(_menu_on and _cleared and _menu_off,
      "地址栏右键可清除最近记录，清空后菜单项置灰",
      "%s / %s / %s" % (_menu_on, _cleared, _menu_off))

pops = []
orig_popup = rbw._popup
orig_ident = rbw.lst.identify_row
rbw._popup = lambda menu, ev: pops.append(menu)
rbw.tree.selection_set(src_url)
check(wait_for(lambda: src_url in rbw._node_items
               and len(rbw.lst.get_children()) == 1),
      "重选 src 供列表右键用例")
a_iid = rbw.lst.get_children()[0]           # src 下唯一文件 a.c
rbw.lst.identify_row = lambda y: ""
rbw._on_list_menu(_Ev2())
blank_ok = (pops and pops[-1] is rbw.menu_dir
            and rbw._menu_url == src_url)
rbw.lst.identify_row = lambda y: a_iid
rbw._on_list_menu(_Ev2())
row_ok = (pops[-1] is rbw.menu_file and rbw._menu_url == a_iid)
check(blank_ok and row_ok,
      "列表空白处/行上右键分别弹目录菜单与文件菜单",
      "%s / %s" % (pops[-1:] or None, rbw._menu_url))

# 空白处右键“查看提交记录”：目标换成当前目录后同样能打开提交历史
rbw.lst.identify_row = lambda y: ""
rbw._on_list_menu(_Ev2())
rbw._view_log(rbw._take_menu_url())
lv = app._log_view
check(lv is not None and lv.url == src_url,
      "空白处菜单的“查看提交记录”目标是当前目录",
      "%s / %s" % (repr(lv), lv.url if lv else None))
lv.destroy()
app.root.update()
rbw.lst.identify_row = orig_ident
rbw._popup = orig_popup

# 右键“查看内容” / 双击文件：后台 `svn cat` 读取，窗口只读展示（用户要求）
rbw.lst.identify_row = lambda y: a_iid
rbw._on_list_dbl(_Ev2())
rbw.lst.identify_row = orig_ident
cat = rbw.cat_win
opened_ok = (cat is not None and cat.winfo_exists()
             and u"正在读取" in cat.status.cget("text"))
loaded_ok = wait_for(lambda: cat.status.cget("text") == u"共 1 行")
check(opened_ok and loaded_ok
      and cat.text.get("1.0", "end-1c") == "content of trunk/src/a.c"
      and u"文件内容" in cat.title() and "a.c" in cat.title()
      and str(cat.text.cget("state")) == "disabled"
      and cat.text.cget("wrap") == "none"
      and cat.focus_get() is cat.text,
      "双击文件打开只读内容窗口：先提示读取中，再显示 HEAD 内容",
      repr(cat.text.get("1.0", "end-1c")))

# 只读内容窗口的复制链路：点击正文要拿到焦点（禁用态 Tk 自己不聚焦，
# 之前 Ctrl+A/Ctrl+C 会落到父窗口），快捷键与右键菜单都能复制
app.root.clipboard_clear()
rbw.tree.focus_force()
app.root.update()
cat.text.event_generate("<Button-1>", x=8, y=8)
app.root.update()
click_focus_ok = cat.focus_get() is cat.text
cat.text.event_generate("<Control-a>")
app.root.update()
all_sel = cat.text.tag_ranges("sel")
app.root.clipboard_clear()
cat.text.event_generate("<Control-c>")
app.root.update()
full_text = cat.text.get("1.0", "end-1c")
check(click_focus_ok and all_sel and cat.clipboard_get() == full_text,
      "内容窗口点击正文聚焦，Ctrl+A 全选、Ctrl+C 复制",
      "%r / %r" % (click_focus_ok, all_sel))

mlabels = [cat.menu.entrycget(i, "label") for i in
           range(cat.menu.index("end") + 1)]
cat.text.tag_remove("sel", "1.0", "end")
cat.text.tag_add("sel", "1.0", "1.4")
cat.menu.invoke(0)
sel_copy = cat.clipboard_get()
cat.menu.invoke(1)
all_copy = cat.clipboard_get()
check(mlabels == [u"复制", u"复制全部内容", u"全选"]
      and sel_copy == "cont" and all_copy == full_text,
      "内容窗口右键菜单：复制选区/复制全部内容/全选",
      "%s / %r" % (mlabels, sel_copy))

# 右键弹出时根据选区决定“复制”是否可用（无选区禁用）
cat.text.tag_remove("sel", "1.0", "end")
cat.text.event_generate("<Button-3>", x=8, y=8)
app.root.update()
disabled_ok = str(cat.menu.entrycget(0, "state")) == "disabled"
cat.menu.unpost()
cat.menu.grab_release()
app.root.update()
cat.text.tag_add("sel", "1.0", "1.4")
cat.text.event_generate("<Button-3>", x=8, y=8)
app.root.update()
enabled_ok = str(cat.menu.entrycget(0, "state")) == "normal"
cat.menu.unpost()
cat.menu.grab_release()
app.root.update()
check(disabled_ok and enabled_ok,
      "内容窗口右键菜单按选区启用/禁用“复制”")

# 再次查看其它文件：复用同一窗口并刷新内容
rbw._cat_url(URL + "/README.txt")
reuse_reading = u"正在读取" in cat.status.cget("text")
reuse_loaded = wait_for(lambda: cat.text.get("1.0", "end-1c")
                        == "content of trunk/README.txt")
check(reuse_reading and reuse_loaded and rbw.cat_win is cat,
      "换文件时复用同一窗口并刷新内容")

# GBK 文件：真实 svn cat 返回原始字节，窗口按实际编码解码（用户反馈乱码）
rbw._cat_url(URL + "/sub/deep/gbk.txt")
gbk_ok = wait_for(lambda: cat.text.get("1.0", "end-1c") == u"中文注释\n第二行"
                  and u"编码 GB18030" in cat.status.cget("text"))
check(gbk_ok and u"\ufffd" not in cat.text.get("1.0", "end-1c"),
      "GBK 文件查看内容自动解码，不再乱码",
      repr((cat.text.get("1.0", "end-1c"), cat.status.cget("text"))))

# 旧结果作废：窗口已换目标时迟到的读取结果不能覆盖
before = cat.text.get("1.0", "end-1c")
rbw._on_cat("file://" + TMP + "/other_file.c", True, [u"changed"])
stale_ok = cat.text.get("1.0", "end-1c") == before
cat.show_content([u"\x00\x01binary"])
bin_ok = (cat.text.get("1.0", "end-1c") == u"（二进制文件，不显示内容）"
          and u"二进制文件" in cat.status.cget("text"))
rbw._on_cat(cat.url, False, u"E170001: 认证失败")
err_ok = (u"读取失败" in cat.status.cget("text")
          and u"E170001" in cat.status.cget("text"))
check(stale_ok and bin_ok and err_ok,
      "迟到的旧结果作废，二进制/读取失败只给提示")

# 内容窗口“编码”菜单：自动识别为 GB18030，手动切换后按新编码重解码
cat.show_content(u"中文注释".encode("gbk"))
auto_ok = (cat.text.get("1.0", "end-1c") == u"中文注释"
           and u"编码 GB18030" in cat.status.cget("text"))
labels = []
for _i in range(cat.enc_menu.index("end") + 1):
    if cat.enc_menu.type(_i) == "command":
        labels.append(cat.enc_menu.entrycget(_i, "label"))
cat._set_encoding("latin-1")
manual_ok = (u"编码 Latin-1" in cat.status.cget("text")
             and cat.text.get("1.0", "end-1c") != u"中文注释")
cat._set_encoding(None)
back_ok = cat.text.get("1.0", "end-1c") == u"中文注释"
check(auto_ok and manual_ok and back_ok
      and u"自动识别" in labels and u"GB18030" in labels,
      "内容窗口自动识别编码并可手动切换兜底", str(labels))
cat.destroy()
app.root.update()
rbw.cat_win = None

# 双击目录仍跳转对应树节点（原行为保留）
rbw.tree.selection_set(URL)
root_list_ok = wait_for(lambda: len(rbw.lst.get_children()) == 5)
rbw.lst.identify_row = lambda y: doc_url
rbw._on_list_dbl(_Ev2())
rbw.lst.identify_row = orig_ident
check(root_list_ok and rbw.tree.selection()
      and rbw.tree.selection()[0] == doc_url,
      "双击目录仍选中对应树节点", str(rbw.tree.selection()))

# 右键菜单必须**持有抓取**直到收起：抓取是“点到菜单外 -> Tk 自动收起”
# 的唯一机制。曾因 tk_popup 后立刻 grab_release 导致右键后不选任何项就
# 关不掉（Tk 8.6.9 实测），这里锁住该行为。
class _Ev(object):
    x_root = rbw.tree.winfo_rootx() + 20
    y_root = rbw.tree.winfo_rooty() + 20


rbw._popup(rbw.menu_dir, _Ev())
rbw.master.update()
mapped = rbw.menu_dir.winfo_ismapped()
grab = str(rbw.master.tk.call("grab", "current", rbw.master))
rbw.menu_dir.unpost()
rbw.menu_dir.grab_release()
rbw.master.update()
check(mapped and "menu" in grab
      and not rbw.menu_dir.winfo_ismapped(),
      "右键菜单弹出后持有抓取，取消后收起", grab)

rbw._menu_url = src_url
rbw._copy_url(rbw._take_menu_url())
check(rbw.clipboard_get() == src_url, "复制地址到剪贴板",
      str(rbw.clipboard_get()))

# 复制地址给人看/用：百分号编码要解码（中文、空格等），不能把 %E4%B8%AD 带出去
enc_url = URL + "/%E4%B8%AD%E6%96%87%20file.txt"
rbw._copy_url(enc_url)
check(rbw.clipboard_get() == URL + u"/中文 file.txt"
      and u"中文 file.txt" in rbw.status.cget("text"),
      "复制地址为解码后的 URL", str(rbw.clipboard_get()))

# 刷新：缓存作废并重新读取
rbw.tree.selection_set(doc_url)
wait_for(lambda: doc_url in rbw._node_items)
del rbw._node_items[doc_url]
rbw._do_refresh(doc_url)
check(wait_for(lambda: doc_url in rbw._node_items), "刷新后重新读取")

# 读取失败：状态栏提示，且失败地址不记入最近浏览
_bad_url = "file://" + TMP + "/no_such_repo_rb"
_before_recent = list(rbw._recent)
rbw._do_refresh(_bad_url)
check(wait_for(lambda: rbw.status.cget("text").startswith(u"读取失败"))
      and rbw._recent == _before_recent
      and _bad_url not in rbw._recent,
      "读取失败时状态栏提示且不记入最近地址", rbw.status.cget("text"))

# ============================================================
# 4b. 导出到…（svn export：不含 .svn 的干净副本，走 Hub 单任务链路）
# ============================================================
EXPORT_PARENT = TMP + "/export_rb"
shutil.rmtree(EXPORT_PARENT, ignore_errors=True)
os.makedirs(EXPORT_PARENT)
orig_browse = rb.App.browse_dir
rb.App.browse_dir = staticmethod(lambda parent, current="": EXPORT_PARENT)

# 参数校验：地址 / 目标缺一都拒绝
missing_url = missing_dst = False
try:
    app.hub.start("export", {"url": "", "dst": TMP + "/x"})
except m.ApiError:
    missing_url = True
try:
    app.hub.start("export", {"url": URL, "dst": ""})
except m.ApiError:
    missing_dst = True
check(missing_url and missing_dst, "导出缺少地址/目标都被拒绝")

# 目录导出：选父目录后目标是“父目录/节点名”，Hub 真实跑 svn export
rbw._do_export(src_url)
started_ok = (app.hub.mode == "export" and app.hub.busy()
              and app.hub.params.get("dst")
              == os.path.join(EXPORT_PARENT, "src")
              and app.status_text.cget("text") == u"运行中：导出"
              and u"已开始导出到" in rbw.status.cget("text"))
ev = wait_hub_done("export")
target = os.path.join(EXPORT_PARENT, "src")
file_ok = False
if os.path.isfile(os.path.join(target, "a.c")):
    with open(os.path.join(target, "a.c")) as f:
        file_ok = f.read() == "content of trunk/src/a.c\n"
check(started_ok and ev is not None and ev.get("ok")
      and os.path.isfile(os.path.join(target, "a.c"))
      and not os.path.exists(os.path.join(target, ".svn"))
      and file_ok
      and app.toast_text.cget("text") == u"导出完成"
      and app.log_file.cget("text").endswith("_export.log"),
      "目录导出走 Hub、目标为父目录/节点名、内容正确且无 .svn")

# 目标已存在：先确认；取消则什么都不做
with open(os.path.join(target, "extra.txt"), "w") as f:
    f.write("keep")
rbw._set_status(u"待命")
m.dialogs.ask_confirm = lambda *a, **k: False
rbw._do_export(src_url)
check(not app.hub.busy() and rbw.status.cget("text") == u"待命",
      "目标存在时取消确认不启动导出", rbw.status.cget("text"))
m.dialogs.ask_confirm = lambda *a, **k: True

# 确认覆盖：带 --force；只覆盖同名文件，目标里的其它文件保留
rbw._do_export(src_url)
ev = wait_hub_done("export")
check(ev is not None and ev.get("ok")
      and app.hub.params.get("force") is True
      and os.path.isfile(os.path.join(target, "extra.txt")),
      "确认后带 --force 覆盖导出且不动目标里的其它文件",
      str(ev)[:160])

# 单文件导出：目标就是“父目录/README.txt”
rbw._do_export(URL + "/README.txt")
ev = wait_hub_done("export")
one = os.path.join(EXPORT_PARENT, "README.txt")
content_ok = False
if os.path.isfile(one):
    with open(one) as f:
        content_ok = f.read() == "content of trunk/README.txt\n"
check(ev is not None and ev.get("ok") and os.path.isfile(one)
      and content_ok,
      "单文件导出为同名文件且内容正确", str(ev)[:120])
rb.App.browse_dir = staticmethod(orig_browse)   # 还原成 staticmethod（见 find_meld 的坑）

# ============================================================
# 5. 检出对话框：勾选规则与交互（非模态直接操作）
# ============================================================
co = rb.CheckoutSelect(rbw, URL, rbw._node_items.get(URL))
rbw.checkout = co
pump(0.1)
check(wait_for(lambda: centered(co, rbw))
      and str(co.transient()) == str(rbw),
      "检出对话框居中并登记为仓库浏览器的 transient",
      "%r / %r" % (center_gap(co, rbw), co.transient()))
# 模态窗最小化防护：标记为 dialog（自动还原逻辑由 test_dialogs 锁）
_guard_ok = "dialog" in str(co.attributes("-type"))
check(_guard_ok, "检出对话框标为 dialog（禁止/自动恢复最小化）",
      repr(co.attributes("-type")))
check(co.result is None and co._default_dst() == DST
      and co.local.get("kind") == "none"
      and co.btn_ok.cget("text") == u"开始下载"
      and co.excludes() == [] and co.checked.get("") is True,
      "首次检出初始状态：默认目录、全选、开始下载")

# 行结构 = 缩进 + ▾/▸ 箭头 + ☑/☐ + 名称（目录带尾斜杠）；目录与文件
# 都能勾选（用户要求），列表用 tk.Text 单独给勾选框放大字形
check([r["rel"] for r in co._rows]
      == [u"", "doc", "lib", "src", "sub", "README.txt"]
      and co._kind.get("README.txt") == "file"
      and co._kind.get("doc") == "dir"
      and co._rows[0]["depth"] == 0 and co._rows[1]["depth"] == 1,
      "勾选列表行序、类型与缩进层级正确",
      str([r["rel"] for r in co._rows]))
_line1 = co.text.get("1.0", "1.end").rstrip()
check(_line1.startswith(u"\u25be ") and m.CHECK_ON in _line1
      and _line1.endswith(u"trunk/")
      and co.text.get("2.0", "2.end").startswith(u"    \u25b8 ")
      and co.text.get("6.0", "6.end").startswith(u"      ")
      and co.text.cget("state") == "disabled",
      "根/目录/文件行结构与只读状态正确", repr(_line1[:24]))
# 勾选字形与主界面改动列表同一套（大号加粗；Treeview 一行一个字号做不到），
# 正文与勾选框垂直居中（txt 微调只挪正文，行高不被撑大）
co.update_idletasks()
_cb = co.text.bbox("1.2")           # 根行勾选框字符格
_tb = co.text.bbox("1.4")           # 根行名称首字符格
_dc = abs((_cb[1] + _cb[3] / 2.0) - (_tb[1] + _tb[3] / 2.0))
check(int(co.font_chk.cget("size")) == m.theme.base_size() + m.UP_CHECK_DELTA
      and str(co.font_chk.cget("weight")) == "bold"
      and str(co.text.tag_cget("chk", "font")) == str(co.font_chk)
      and co.text.tag_cget("txt", "offset") == str(m.UP_TEXT_OFFSET)
      and "txt" in co.text.tag_names("1.4")
      and "txt" not in co.text.tag_names("1.2")
      and _dc <= 2,
      "勾选框大号加粗、名称与勾选框垂直居中（中心差 %.1f px）" % _dc)
# 布局回归：按钮条是最后 pack 的，窗口高度不够时会被挤出可视区
# （登录凭据窗口就是这么坏掉的，20261015）——确认按钮必须真实可见
co.update_idletasks()
check(co.btn_ok.winfo_height() > 1 and co.btn_ok.winfo_width() > 1,
      "确认按钮真实可见（没被布局挤出可视区）",
      "%dx%d" % (co.btn_ok.winfo_width(), co.btn_ok.winfo_height()))


def row_bbox(rel, col):
    """rel 行相对行首第 col 个字符格的 bbox（col=0 箭头 / 2 勾选框 / 5 名称）。"""
    line = co._rel_line[rel]
    row = co._rows[line - 1]
    co.update_idletasks()
    return co.text.bbox("%d.%d" % (line, row["depth"] * 4 + col))


def click_rel(rel, col, dx=0):
    """按像素模拟单击某行的某个位置（col 语义同 row_bbox）。"""
    bb = row_bbox(rel, col)
    co._on_click(type("Ev", (), {"x": bb[0] + dx, "y": bb[1] + 5})())


# 单击名称只选中，点勾选框才翻转（用户要求）
click_rel("doc", 5, dx=10)
name_ok = co.checked.get("doc") is True and co.excludes() == []
sel_ok = co.sel_rel == "doc"
click_rel("doc", 2, dx=5)
off_ok = co.checked.get("doc") is False and co.excludes() == ["doc"]
click_rel("doc", 2, dx=5)
on_ok = co.excludes() == []
check(name_ok and sel_ok and off_ok and on_ok,
      "单击名称只选中、点勾选框才翻转勾选")

# 点箭头展开/收起（懒加载）
click_rel("doc", 0, dx=3)
expanded_ok = "doc" in co._expanded
loaded_ok = wait_for(lambda: "doc" in co._loaded)
row_ok = ("doc/file.txt" in co._rel_line
          and co._kind.get("doc/file.txt") == "file")
click_rel("doc", 0, dx=3)
check(expanded_ok and loaded_ok and row_ok
      and "doc" not in co._expanded,
      "点箭头展开触发懒加载、再点收起")

# 文件级勾选 -> 排除清单精确到文件
click_rel("doc", 0, dx=3)              # 重新展开
wait_for(lambda: "doc" in co._expanded)
click_rel("doc/file.txt", 2, dx=5)
file_off = (co.checked.get("doc/file.txt") is False
            and co.excludes() == ["doc/file.txt"])
click_rel("doc/file.txt", 2, dx=5)
check(file_off and co.excludes() == [],
      "文件级勾选可精确排除单个文件并恢复")

# 目录勾选传播与顶层合并（勾选父目录 -> 子孙全选；取消 -> 子孙全取消）
co.set_checked("doc", False)
doc_off = co.excludes() == ["doc"]
co.set_checked("doc", True)
doc_on = co.excludes() == []
co.set_checked("", False)
check(doc_off and doc_on
      and co.checked.get("") is True and co.excludes() == [],
      "目录勾选传播、恢复且检出根不可取消")
co._ensure_loaded("lib")
loaded_ok = wait_for(lambda: "lib" in co._loaded)
inherit_ok = all(co.checked.get(r) for r in ("lib/Keep", "lib/Mips", "lib/Win"))
co.set_checked("lib/Mips", False)
co.set_checked("lib/Win", False)
leaf_ok = co.excludes() == ["lib/Mips", "lib/Win"]
check(loaded_ok and inherit_ok and leaf_ok,
      "新加载目录继承父级勾选，只排除取消的两个叶子")
co.set_checked("lib", False)
parent_off = co.excludes() == ["lib"]
co.set_checked("lib", True)
check(parent_off and co.excludes() == [],
      "取消父目录覆盖子孙，恢复父目录一并恢复")

# 键盘操作（用户要求）：↑/↓ 移动当前行，空格勾选/取消勾选，
# ←/→ 收起/展开；在真实控件上发按键事件，验证绑定生效
co.text.focus_set()
co.update_idletasks()
co._select_line(1)                     # 从根行出发
moves = []
co.text.event_generate("<Down>")
co.update()
moves.append(co.sel_rel == "doc")
co.text.event_generate("<Up>")
co.update()
moves.append(co.sel_rel == "")
co.text.event_generate("<Next>")
co.update()
moves.append(co.sel_rel == "README.txt")
co.text.event_generate("<Prior>")
co.update()
moves.append(co.sel_rel == "")
co.text.event_generate("<End>")
co.update()
moves.append(co.sel_rel == "README.txt")
co.text.event_generate("<Home>")
co.update()
moves.append(co.sel_rel == "")
check(all(moves), "键盘 ↑/↓/PgUp/PgDn/Home/End 移动当前行正确",
      str(co.sel_rel))
co._select_line(co._rel_line["doc"])
co.text.event_generate("<space>")
co.update()
space_off = co.checked.get("doc") is False and co.excludes() == ["doc"]
co.text.event_generate("<space>")
co.update()
check(space_off and co.checked.get("doc") is True and co.excludes() == [],
      "空格取消/恢复当前行勾选（用户要求）")

# 翻转勾选不改变滚动位置（20261016 用户反馈：鼠标点勾选框、列表跳回
# 顶部，空格勾选又把该行拉回视线，列表"自己动"）。先注入一批合成行把
# 列表撑到可滚动，再看翻转前后 yview 是否一致
_top_kids = co._kids[u""]
co._kids[u""] = list(_top_kids) + [u"gen%02d" % i for i in range(40)]
for i in range(40):
    _rel_i = u"gen%02d" % i
    co._kind[_rel_i] = "file"
    co._disp[_rel_i] = _rel_i
co._render()
co.update()
co.text.yview_moveto(1.0)              # 滚到底
co.update_idletasks()
scrollable = co.text.yview()[0] > 0
_gen_line = int(co.text.index("@0,0").split(".")[0])
_gen_rel = co._rows[_gen_line - 1]["rel"]
_y0 = co.text.yview()[0]
click_rel(_gen_rel, 2, dx=5)           # 鼠标：翻转视野内某行
mouse_off = co.checked.get(_gen_rel) is False
_y1 = co.text.yview()[0]
mouse_scroll_ok = abs(_y1 - _y0) < 0.001
co._select_line(co._line_of_rel(_gen_rel))
co.text.event_generate("<space>")      # 键盘：勾回来
co.update()
space_on = co.checked.get(_gen_rel) is True
_y2 = co.text.yview()[0]
check(scrollable and mouse_off and mouse_scroll_ok
      and space_on and abs(_y2 - _y1) < 0.001,
      "滚动场景下鼠标/空格翻转生效且都不改变滚动位置",
      "%.3f -> %.3f -> %.3f" % (_y0, _y1, _y2))
co._kids[u""] = _top_kids              # 撤掉合成行，恢复原状
for i in range(40):
    _rel_i = u"gen%02d" % i
    del co._kind[_rel_i]
    del co._disp[_rel_i]
    co.checked.pop(_rel_i, None)
co._render()

co._select_line(co._rel_line["doc"])
co.text.event_generate("<Right>")
co.update()
right_expand = "doc" in co._expanded and "doc" in co._loaded
co.text.event_generate("<Right>")
co.update()
right_child = co.sel_rel == "doc/file.txt"
co.text.event_generate("<Left>")
co.update()
left_parent = co.sel_rel == "doc"
co.text.event_generate("<Left>")
co.update()
check(right_expand and right_child and left_parent
      and "doc" not in co._expanded,
      "→ 展开/进入子级、← 回父级/收起目录")

co._set_all(False)
all_off = (co.excludes() == ["README.txt", "doc", "lib", "src", "sub"]
           and co.checked.get("") is True)
co._set_all(True)
all_on = co.excludes() == []
co.set_checked("lib/Mips", False)
co._invert()
invert = co.excludes() == ["README.txt", "doc", "src", "sub",
                           "lib/Keep", "lib/Win"]
co._set_all(True)
check(all_off and all_on and invert
      and u"已勾选" in co.count_lbl.cget("text"),
      "全选/全不选/反选与计数标签正确", str(co.excludes()))

# 空本地目录不允许提交
co.dst_var.set("")
co._ok()
empty_ok = (co.winfo_exists() and co.result is None
            and u"本地目录" in co.msg.cget("text"))
co.dst_var.set(DST)
co._ok()
pump(0.1)
check(empty_ok and not co.winfo_exists()
      and co.result == {"url": URL, "dst": DST, "excludes": [],
                        "restore": [], "mode": "download"},
      "本地目录为空时拒绝提交并给出提示；填写后关闭并返回结果",
      str(co.result))
rbw.checkout = None

# 本地目录输入框变化后自动重读状态（用户要求：立即校验路径）
co = rb.CheckoutSelect(rbw, URL, [], FRESH_DIR)
rbw.checkout = co
fresh_ok = co.local.get("kind") == "fresh"
co.dst_var.set(NONWC_DIR)
auto_ok = wait_for(lambda: co.local.get("kind") == "unknown", 5)
disabled_ok = (str(co.btn_ok.cget("state")) == "disabled"
               and u"工作副本" in co.msg.cget("text"))
co.dst_var.set(NONE_DIR)
restored_ok = wait_for(lambda: co.btn_ok.cget("text") == u"开始下载"
                        and str(co.btn_ok.cget("state")) == "normal", 5)
check(fresh_ok and auto_ok and disabled_ok and restored_ok,
      "本地目录实时校验：空目录可检出、非法目录禁用按钮、恢复后按钮复原")
co.destroy()
rbw.checkout = None

# 被文件占用的路径：立即判定为非法并禁用按钮
co = rb.CheckoutSelect(rbw, URL, [], FILE_DST)
rbw.checkout = co
file_ok = (co.local.get("kind") == "file"
           and str(co.btn_ok.cget("state")) == "disabled"
           and u"文件占用" in co.msg.cget("text"))
co._ok()
check(file_ok and co.winfo_exists() and co.result is None,
      "被文件占用的路径禁用按钮并拒绝提交")
co.destroy()
rbw.checkout = None

# 项目配置里的排除清单 -> 本地尚无工作副本时的初始勾选
store.update_fields(URL, DST, ["doc", "lib/Mips"])
co2 = rb.CheckoutSelect(rbw, URL, rbw._node_items.get(URL))
rbw.checkout = co2
pump(0.1)
pre_ok = co2.excludes() == ["doc"]
co2._ensure_loaded("lib")
deep_ok = wait_for(lambda: "lib" in co2._loaded) and \
    co2.excludes() == ["doc", "lib/Mips"]
co2.destroy()
rbw.checkout = None
store.update_fields(URL, DST, [])      # 还原配置
check(pre_ok and deep_ok,
      "配置中的排除清单（顶层与深层）预置为初始勾选")

# ============================================================
# 6. 模态链路：点勾选框 -> 开始下载（结果交回主界面）
# ============================================================
CAP = {}
orig_checkout = app._checkout_from_browser


def capture(url, dst, excludes, restore=None, mode="download"):
    CAP.update({"url": url, "dst": dst, "excludes": list(excludes),
                "restore": list(restore or []), "mode": mode})
    return False


app._checkout_from_browser = capture


def step_toggle():
    c = rbw.checkout
    if c is None:
        return None
    line = c._rel_line.get("doc")
    if line is None:
        return None
    c.update_idletasks()
    row = c._rows[line - 1]
    bb = c.text.bbox("%d.%d" % (line, row["depth"] * 4 + 2))
    if not bb:
        return None
    c._on_click(type("Ev", (), {"x": bb[0] + 5, "y": bb[1] + 5})())
    if c.checked.get("doc") is False:
        return True
    return None


def step_start():
    c = rbw.checkout
    if c is None:
        return None
    for b in walk(c):
        if b.winfo_class() == "TButton" and b.cget("text") == u"开始下载":
            if not c.dst_var.get().strip():
                c.dst_var.set(DST)
            b.invoke()
            return True
    return None


def step_cancel():
    c = rbw.checkout
    if c is None:
        return None
    for b in walk(c):
        if b.winfo_class() == "TButton" and b.cget("text") == u"取消":
            b.invoke()
            return True
    return None


st = drive(u"检出对话框点勾选框并开始下载",
           lambda: rbw._do_checkout(URL), [step_toggle, step_start])
check(CAP.get("url") == URL
      and CAP.get("excludes") == ["doc"]
      and CAP.get("dst") == DST
      and CAP.get("mode") == "download" and CAP.get("restore") == []
      and rbw.checkout is None,
      "检出对话框结果交回主界面（排除清单/目录/模式）且对话框已释放",
      str(CAP))

CAP.clear()
st = drive(u"检出对话框可取消", lambda: rbw._do_checkout(URL), [step_cancel])
check(CAP == {}, "取消不触发下载", str(CAP))

app._checkout_from_browser = orig_checkout

# ============================================================
# 7. 经 Hub 的真实检出（含文件级排除）
# ============================================================
shutil.rmtree(DST, ignore_errors=True)
co = rb.CheckoutSelect(rbw, URL)
rbw.checkout = co
root_loaded = wait_for(lambda: "" in co._loaded)
co._ensure_loaded("lib")
co._ensure_loaded("src")
sub_loaded = wait_for(lambda: "lib" in co._loaded and "src" in co._loaded)
co.set_checked("doc", False)
co.set_checked("sub", False)
co.set_checked("lib/Mips", False)
co.set_checked("lib/Win", False)
co.set_checked("src/a.c", False)
ex = co.excludes()
check(root_loaded and sub_loaded
      and ex == ["doc", "sub", "lib/Mips", "lib/Win", "src/a.c"],
      "检出对话框加载各层，排除清单可精确到目录与文件", str(ex))
co.destroy()
rbw.checkout = None

# 打开提交历史与内置差异两个辅助窗口：首次下载启动时应被自动关闭
app._open_log_view(url=URL)
lv0 = app._log_view
lv_open = lv0 is not None and lv0.winfo_exists()
# wait_hub_done 只收 Hub 事件、不跑 Tk 定时器：先泵到窗口的 60ms 定时
# 刷新真的把 log 任务启动，再去等它的 done
log_started = wait_for(lambda: app.hub.busy())
ev = wait_hub_done("log")
log_ok = ev is not None and ev.get("ok") is True
app.diff_win = m.dialogs.show_diff_win(
    app.root, u"占位差异", {"lines": [], "stats": (0, 0, 0)},
    font_bold=app.font_log_bold)
dw0 = app.diff_win
check(lv_open and log_started and log_ok and dw0.winfo_exists(),
      "提交历史与内置差异窗口已打开（下载前）")

# 内置差异窗口同一套只读复制链：点击正文聚焦、Ctrl+A/Ctrl+C、右键菜单
diff_body = dw0.diff_text.get("1.0", "end-1c")
app.root.clipboard_clear()
dw0.diff_text.event_generate("<Button-1>", x=8, y=8)
app.root.update()
diff_focus = dw0.focus_get() is dw0.diff_text
dw0.diff_text.event_generate("<Control-a>")
app.root.update()
diff_sel = bool(dw0.diff_text.tag_ranges("sel"))
app.root.clipboard_clear()
dw0.diff_text.event_generate("<Control-c>")
app.root.update()
diff_copy = dw0.clipboard_get() == diff_body
diff_labels = [dw0.diff_menu.entrycget(i, "label") for i in
               range(dw0.diff_menu.index("end") + 1)]
dw0.diff_menu.invoke(1)
check(diff_focus and diff_sel and diff_copy
      and diff_labels == [u"复制", u"复制全部内容", u"全选"]
      and dw0.clipboard_get() == diff_body,
      "内置差异窗口点击正文聚焦，Ctrl+A/Ctrl+C 与右键复制可用",
      "%r / %r / %r / %s" % (diff_focus, diff_sel, diff_copy, diff_labels))

ok_dl = app._checkout_from_browser(URL, DST, ex)
check(ok_dl is True
      and not rbw.winfo_exists() and not lv0.winfo_exists()
      and not dw0.winfo_exists()
      and app._repo_browser is None and app._log_view is None
      and app.diff_win is None,
      "首次下载启动后仓库浏览器/提交历史/内置差异窗口全部自动关闭")
check(u"正在下载" in app.status_text.cget("text")
      and u"下载已开始" in app.toast_text.cget("text"),
      "状态栏提示正在下载、右下角提示下载已开始",
      "%s / %s" % (app.status_text.cget("text"),
                   app.toast_text.cget("text")))
ev = wait_hub_done("download")
p = m.resolve_dst(DST)
check(ev is not None and ev.get("ok") is True
      and app.status_text.cget("text") == u"就绪"
      and app.toast_text.cget("text") == u"下载完成",
      "检出成功，完成后状态栏回到就绪、toast 覆盖为下载完成")
check((p / "src").is_dir() and (p / "src/a.c").is_file() is False
      and (p / "lib/Keep/k.txt").is_file()
      and (p / "doc/file.txt").exists() is False
      and (p / "sub/deep/d.txt").exists() is False
      and not (p / "lib/Mips/m.bin").exists()
      and not (p / "lib/Win/w.bin").exists(),
      "文件级排除生效（目录与文件都被排除，lib/Keep 保留）")

# 仓库浏览器已随下载自动关闭：重开一个继续后面的对话框用例
# （配置里的 svn_url 已是 URL，新窗口会自己加载）
app._open_repo_browser()
rbw = app._repo_browser
check(rbw is not None and rbw.winfo_exists(), "下载后重新打开仓库浏览器")
pump(0.15)

# ============================================================
# 7b. 更新对话框：按本地排除状态还原勾选（含文件），按钮切换为更新
# ============================================================
# 打开对话框不再同步跑 svn status（大工作副本上很慢，20261015 用户反馈）：
# 同步路径只允许 svn info，排除状态交给后台线程补读
CALLS = []
_orig_svn_text = rb._svn_text


def _rec_svn_text(args):
    CALLS.append(" ".join(args))
    return _orig_svn_text(args)


rb._svn_text = _rec_svn_text
co = rb.CheckoutSelect(rbw, URL)
rbw.checkout = co
same_ok = co.local.get("kind") == "same"
no_status = not [c for c in CALLS if " status " in c]
only_info = bool([c for c in CALLS if " info " in c])
pending_ok = (co._stat_pending is True
              and str(co.btn_ok.cget("state")) == "disabled"
              and u"读取" in co.msg.cget("text"))
co._ok()
blocked_ok = co.winfo_exists() and co.result is None
rb._svn_text = _orig_svn_text
check(same_ok and no_status and only_info and pending_ok and blocked_ok,
      "同源工作副本立即识别、构造不跑 svn status、排除状态后台读取",
      str(CALLS))
root_loaded = wait_for(lambda: "" in co._loaded)
stat_done = wait_for(lambda: not co._stat_pending, 15)
have_ok = co.local.get("have") is not None
btn_ok = (co.btn_ok.cget("text") == u"更新到所选"
          and str(co.btn_ok.cget("state")) == "normal"
          and u"工作副本" in co.local_lbl.cget("text"))
top_ok = (co.excludes() == ["doc", "sub"]
          and co.checked.get("src") is True
          and co.checked.get("lib") is True)
co._ensure_loaded("lib")
co._ensure_loaded("src")
sub_loaded = wait_for(lambda: "lib" in co._loaded and "src" in co._loaded)
leaf_ok = (co.excludes() == ["doc", "sub", "lib/Mips", "lib/Win", "src/a.c"]
           and co.checked.get("src/a.c") is False)
check(root_loaded and stat_done and have_ok and btn_ok and top_ok
      and sub_loaded and leaf_ok,
      "后台读完排除状态后按钮切为更新、勾选按本地状态还原（含文件）",
      str(co.excludes()))
# 本地目录改到别处 -> 自动重读状态，按钮与勾选随之切换
co.dst_var.set(FRESH_DIR)
co._dst_changed()
switch_ok = co.btn_ok.cget("text") == u"开始下载"
co.dst_var.set(DST)
co._dst_changed()
back_ok = co.btn_ok.cget("text") == u"更新到所选"
wait_for(lambda: not co._stat_pending, 15)
reload_ok = co.excludes() == ["doc", "sub", "lib/Mips", "lib/Win", "src/a.c"]
co.set_checked("doc", True)
re_doc = co.excludes() == ["sub", "lib/Mips", "lib/Win", "src/a.c"]
co.set_checked("src/a.c", True)
re_file = co.excludes() == ["sub", "lib/Mips", "lib/Win"]
check(switch_ok and back_ok and reload_ok and re_doc and re_file,
      "改本地目录后按钮与勾选随之重读，重新勾选可恢复目录与文件")
co.dst_var.set(DST)
co._ok()
pump(0.1)
check(not co.winfo_exists()
      and co.result and co.result["mode"] == "update"
      and co.result["restore"] == ["doc", "src/a.c"]
      and co.result["excludes"] == ["sub", "lib/Mips", "lib/Win"],
      "更新对话框返回 mode/恢复清单/排除清单正确", str(co.result))
res = co.result
rbw.checkout = None

# ---- 7c. 执行更新：重新勾选的目录与文件都拉回来 ----
ok_up = app._checkout_from_browser(res["url"], res["dst"], res["excludes"],
                                   res["restore"], res["mode"])
ev = wait_hub_done("download")
check(ok_up is True and ev is not None and ev.get("ok") is True
      and (p / "doc/file.txt").is_file() and (p / "src/a.c").is_file()
      and (p / "lib/Keep/k.txt").is_file()
      and not (p / "sub/deep/d.txt").exists()
      and not (p / "lib/Mips/m.bin").exists()
      and store.settings["excludes"] == res["excludes"],
      "更新成功：重新勾选的目录与文件拉回，其余仍排除并写回配置")

# ---- 7d. 取消勾选 -> 目录与文件都被再次排除 ----
ok_up = app._checkout_from_browser(
    URL, DST, ["doc", "sub", "lib/Mips", "lib/Win", "src/a.c"], [], "update")
ev = wait_hub_done("download")
check(ok_up is True and ev is not None and ev.get("ok") is True
      and not (p / "doc/file.txt").exists()
      and not (p / "src/a.c").exists()
      and (p / "lib/Keep/k.txt").is_file(),
      "取消勾选后目录与文件都被再次排除（set-depth=exclude 支持文件）")

# ---- 7e. 异源 / 非工作副本 / 空目录 / 被文件占用四种拒绝与放行 ----
other_dst = TMP + "/wc_setup_rb/wc"
co = rb.CheckoutSelect(rbw, URL, [], other_dst)
rbw.checkout = co
other_ok = (co.local.get("kind") == "other"
            and str(co.btn_ok.cget("state")) == "disabled")
co.dst_var.set(other_dst)
co._ok()
check(other_ok and co.winfo_exists() and co.result is None
      and u"其他来源" in co.msg.cget("text"),
      "异源工作副本被识别、禁用按钮并拒绝提交")
co.destroy()
rbw.checkout = None

co = rb.CheckoutSelect(rbw, URL, [], NONWC_DIR)
rbw.checkout = co
unknown_ok = (co.local.get("kind") == "unknown"
              and str(co.btn_ok.cget("state")) == "disabled")
co.dst_var.set(NONWC_DIR)
co._ok()
check(unknown_ok and co.winfo_exists() and co.result is None,
      "非工作副本目录被识别、禁用按钮并拒绝提交")
co.destroy()
rbw.checkout = None

co = rb.CheckoutSelect(rbw, URL, [], FRESH_DIR)
rbw.checkout = co
fresh_ok = (co.local.get("kind") == "fresh"
            and co.btn_ok.cget("text") == u"开始下载")
co.dst_var.set(FRESH_DIR)
co._ok()
check(fresh_ok and co.result and co.result["mode"] == "download",
      "空目录可直接检出并按首次检出处理", str(co.result))
co.destroy()
rbw.checkout = None

# ============================================================
# 7f. 真实交互路径：点“开始下载”后浏览器在自己的调用栈里被关闭
# ============================================================
# 第 7 节是直接调 App._checkout_from_browser；这里补完整链路
# rbw._do_checkout -> 模态对话框 -> 真实 _checkout_from_browser，
# 验证“浏览器在自己的 _do_checkout 调用栈里被 shutdown”不炸。
DL_REAL = TMP + "/dl_real_rb"
shutil.rmtree(DL_REAL, ignore_errors=True)


def step_dst_real():
    c = rbw.checkout
    if c is None:
        return None
    if c.dst_var.get().strip() != DL_REAL:
        c.dst_var.set(DL_REAL)
        c._dst_changed()        # 不等 400ms 防抖，立即校验并刷新按钮
        return None
    return True


def step_start_real():
    c = rbw.checkout
    if c is None:
        return None
    for b in walk(c):
        if b.winfo_class() == "TButton" and b.cget("text") == u"开始下载":
            b.invoke()
            return True
    return None


st = drive(u"完整链路：对话框点“开始下载”",
           lambda: rbw._do_checkout(URL), [step_dst_real, step_start_real])
# drive 返回时“对话框 -> _checkout_from_browser”整条链已同步跑完、
# 下载任务刚启动：此刻的界面就应该是“只剩主窗口 + 友好提示”
closed_ok = (not rbw.winfo_exists() and app._repo_browser is None)
status_ok = (u"正在下载" in app.status_text.cget("text")
             and u"下载已开始" in app.toast_text.cget("text"))
done_ok = wait_for(lambda: not app.busy
                   and app.toast_text.cget("text") == u"下载完成")
check(closed_ok and status_ok and done_ok
      and os.path.isdir(os.path.join(DL_REAL, ".svn")),
      "真实路径检出：浏览器自动关闭、友好提示、目标目录已检出",
      app.toast_text.cget("text"))
# 这轮把配置 dst 写成了 DL_REAL，还原成 DST，免得影响下次运行的用例
store.update_fields(URL, DST, [])

# ============================================================
# 7g. 仓库集合根：左树“仓库列表” + 右侧仓库行 + 守卫
# ============================================================
# 只用本机临时 HTTP 服务模拟，不连接任何真实仓库
srv2 = http.server.HTTPServer(("127.0.0.1", 0), _CollHandler)
PORT2 = srv2.server_address[1]
COLL_ROOT2 = "http://127.0.0.1:%d" % PORT2
COLL_BASE = COLL_ROOT2 + "/idx/svn"
th2 = threading.Thread(target=srv2.serve_forever)
th2.daemon = True
th2.start()

# 上一节的真实检出把浏览器自动关掉了，这里重新打开一个再测集合根
app._open_repo_browser()
rbw = app._repo_browser
pump(0.2)                    # 让构造时的初始地址读取先跑完，避免与下面冲突
check(rbw is not None and rbw.winfo_exists(), "集合根用例重新打开仓库浏览器")

# 首次访问集合根：svn list 报 E175009 -> 自动回退 HTTP 索引 -> 显示仓库列表
FIRST_URL = COLL_ROOT2 + "/first"
rbw._collections.discard(m.core.normalize_svn_url(FIRST_URL))
rbw.url_var.set(FIRST_URL)
_orig_request = rbw.request


def _fake_node_ls(url, kind):
    rbw._on_node_ls(url, False,
                    "svn: E175009: The XML response contains invalid XML\n"
                    "190001: The URI does not contain the name of a repository")


rbw.request = _fake_node_ls
rbw._go()
rbw.request = _orig_request
_first_ok = wait_for(lambda: FIRST_URL in rbw._node_items
                     and len(rbw.lst.get_children()) == 2)
check(_first_ok and rbw.tree.item(FIRST_URL, "text") == rb.COLLECTION_TITLE
      and m.core.normalize_svn_url(FIRST_URL) in rbw._collections,
      "首次访问集合根自动回退索引并显示“仓库列表”",
      "%r / %s" % (_first_ok, rbw.status.cget("text")))

# 模拟“地址之前已确认是集合根”——_go 应直接读索引，不发 svn list
rbw._collections.add(m.core.normalize_svn_url(COLL_BASE))
rbw.url_var.set(COLL_BASE)
rbw._go()
coll_ok = wait_for(lambda: COLL_BASE in rbw._node_items
                   and len(rbw.lst.get_children()) == 2)
_repos = rbw.tree.get_children(COLL_BASE)
check(coll_ok and rbw.tree.item(COLL_BASE, "text") == rb.COLLECTION_TITLE
      and len(_repos) == 2
      and [rbw.tree.item(i, "text") for i in _repos] == ["alpha", u"组 件"]
      and [rbw.lst.item(i, "text") for i in rbw.lst.get_children()]
      == ["alpha", u"组 件"]
      and all(rbw._list_kind.get(i) == "dir"
              for i in rbw.lst.get_children())
      and u"仓库列表" in rbw.status.cget("text"),
      "集合根显示为“仓库列表”，仓库铺到左树/右侧列表",
      "%s / %s / %s" % (_repos, rbw.status.cget("text"),
                        rbw.lst.get_children()))
check(rbw._recent and rbw._recent[0] == COLL_BASE
      and store.settings.get("recent_repo_urls")[0] == COLL_BASE,
      "集合根成功显示后也记入最近地址", repr(rbw._recent))

# 集合根不是具体仓库：检出/导出/查看提交记录三项置灰，刷新/复制地址可用
rbw._configure_dir_menu(COLL_BASE)
_states = [str(rbw.menu_dir.entrycget(i, "state")) for i in range(5)]
check(_states == ["disabled", "disabled", "normal", "disabled", "normal"],
      "集合根右键菜单禁用检出/导出/提交记录", str(_states))

rbw._do_checkout(COLL_BASE)
_guard_co = (rbw.checkout is None
             and u"不能检出" in rbw.status.cget("text"))
rbw._do_export(COLL_BASE)
check(_guard_co and u"不能导出" in rbw.status.cget("text"),
      "集合根的检出/导出动作被拦截",
      "%r / %s" % (_guard_co, rbw.status.cget("text")))

_orig_open_log = rbw.app._open_log_view
_opened_logs = []
rbw.app._open_log_view = lambda **kw: _opened_logs.append(kw)
rbw._view_log(COLL_BASE)
rbw.app._open_log_view = _orig_open_log
check(not _opened_logs and u"不能查看提交记录" in rbw.status.cget("text"),
      "集合根不能直接打开提交记录", repr(_opened_logs))

# svn list 对集合根报 E175009/190001 时自动回退到 HTTP 索引
_orig_rc = rbw.request_collection
_fallback = []
rbw.request_collection = lambda url: _fallback.append(url)
rbw._on_node_ls(COLL_BASE, False,
                "svn: E175009: The XML response contains invalid XML\n"
                "190001: The URI does not contain the name of a repository")
rbw.request_collection = _orig_rc
check(_fallback == [COLL_BASE]
      and u"正在读取仓库列表" in rbw.status.cget("text"),
      "_on_node_ls 识别集合根错误并改走 HTTP 索引",
      "%r / %s" % (_fallback, rbw.status.cget("text")))

# 其他读取错误仍按普通错误处理，不回退
rbw._on_node_ls(COLL_BASE, False, "svn: E170013: Unable to connect")
check(u"读取失败" in rbw.status.cget("text"),
      "非集合根错误不回退读取索引", rbw.status.cget("text"))

# 双击仓库行：选中左树对应节点并排队读取该仓库（不误开内容窗口）
repo_url = rbw.tree.get_children(COLL_BASE)[0]
_req_calls = []
_orig_request = rbw.request
rbw.request = lambda url, kind: _req_calls.append((url, kind))
_orig_ident = rbw.lst.identify_row
rbw.lst.identify_row = lambda y: repo_url
rbw._on_list_dbl(_Ev2())
rbw.lst.identify_row = _orig_ident
rbw.request = _orig_request
check(rbw.tree.selection() and rbw.tree.selection()[0] == repo_url
      and _req_calls == [(repo_url, "node")]
      and rbw.tree.item(repo_url, "open"),
      "双击仓库行进入对应树节点并读取仓库内容",
      "%s / %r / %s" % (rbw.tree.selection(), _req_calls,
                        rbw.tree.item(repo_url, "open")))

srv2.shutdown()
srv2.server_close()

# ============================================================
# 8. 关闭
# ============================================================
rbw.shutdown()
pump(0.1)
rbw.worker.join(timeout=8)
check(not rbw.winfo_exists() and rbw._closed is True
      and not rbw.worker.is_alive(),
      "shutdown 关闭窗口、标记已关闭、后台线程退出")

app.root.destroy()
print("-" * 46)
print("通过 %d 项，失败 %d 项" % (PASSED[0], len(FAILS)))
for f in FAILS:
    print("  FAILED: %s" % f)
sys.exit(1 if FAILS else 0)
