# -*- coding: utf-8 -*-
"""SVN 仓库浏览器 + 检出目录勾选对话框（svnwb 包的伴随模块）。

主界面点击“仓库浏览”时才 import 本模块（懒加载）。顶部
`from . import core, dialogs, theme` 复用核心工具函数、弹窗与平面化主题，
`from .app import App` 只为借用 App.browse_dir（目录选择三分支）。

职责划分：
  - LsWorker      后台读目录 / 读文件内容（复用 Runner 的凭据/证书重试，
                  独立于主界面 Hub）
  - CatView       文件内容查看窗口（只读、非模态；svn cat 后台读取）
  - RepoBrowser   浏览器窗口（左树右列表，懒加载，右键菜单）
  - CheckoutSelect 检出/更新对话框（勾选目录 -> 排除清单；本地已是同源
                   工作副本时按当前排除状态还原勾选，可把已排除的重新勾回）
  检出与更新都不写新逻辑：交给 App._checkout_from_browser -> Hub 的下载任务；
  导出同理走 Hub 的 "export" 模式（svn export，不含 .svn 的干净副本）。
"""

import os
import queue
import socket
import ssl
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from . import core, dialogs, theme
from .app import App
from .runner import Runner

# 单个目录读取超时（秒）；等待用户输入凭据的时间不计入
LS_TIMEOUT = 120
LOADING = u"（加载中…）"
COLLECTION_TITLE = u"仓库列表"
# 集合根索引是给网页看的 XML（不是 SVN 协议响应），只能额外发 HTTP GET 取。
# 限制体积与超时，避免异常页面把后台线程/内存拖住。
COLLECTION_MAX_BYTES = 2 * 1024 * 1024
COLLECTION_TIMEOUT = 30
# “查看内容”最多展示的行数（超大文件先截断，防 Text 卡死；
# 与 core.DIFF_MAX_LINES 同量级）
CAT_MAX_LINES = 20000
# 文本编码自动适配的实现在 core（内置差异窗口也要用同一套判断）；
# 这里保留模块级别名，查看内容窗口与既有测试按原名字访问。
CAT_ENCODINGS = core.CAT_ENCODINGS
CAT_ENCODING_CHOICES = core.CAT_ENCODING_CHOICES
decode_text = core.decode_text
_encoding_label = core._encoding_label
_binary_bytes = core._binary_bytes
# 勾选树每层缩进（字符数 = 列号步进，见 CheckoutSelect._zone_of）
INDENT = u"    "


# ============================================================
# 一、纯函数
# ============================================================

def fmt_date(s):
    """svn 的 ISO 时间 -> “YYYY-MM-DD HH:MM”（实现在 core，保留本名）。"""
    return core.fmt_date(s)


def fmt_size(value):
    """字节数 -> 人可读大小（1024 进制，保留 1 位小数）。

    目录没有大小（svn list 不返回 <size>），返回空串；无法解析也返回空串。
    """
    if value is None or value == "":
        return u""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return u""
    if n < 0:
        return u""
    if n < 1024:
        return u"%d B" % n
    v = float(n)
    for unit in (u"KB", u"MB", u"GB", u"TB"):
        v /= 1024.0
        if v < 1024.0 or unit == u"TB":
            return u"%.1f %s" % (v, unit)
    return u""


def file_suffix(name):
    """文件名后缀（不含点）；目录与没有后缀的文件（含 .bashrc）返回空串。"""
    base = (name or u"").replace("\\", "/").rsplit("/", 1)[-1]
    if u"." not in base or base.endswith(u"."):
        return u""
    if base.startswith(u".") and base.count(u".") == 1:
        return u""
    return base.rsplit(u".", 1)[-1]


def parse_list_xml(text):
    """解析 `svn list --xml` 输出。

    返回 [{"kind", "name", "rev", "author", "date", "size"}]：目录在前、
    文件在后，同类按名称升序；name 保持 svn 给出的原文（XML 里目录名不带
    尾斜杠，中文等字符为 UTF-8 原文而非百分号编码）。size 是文件字节数
    （字符串），目录没有该元素时为空串。
    """
    try:
        root = ET.fromstring((text or "").strip() or "<lists/>")
    except ET.ParseError:
        raise RuntimeError(u"svn list 输出解析失败（不是有效的 XML）")
    items = []
    for entry in root.iter("entry"):
        name_el = entry.find("name")
        name = (name_el.text or "").strip() if name_el is not None else ""
        if not name:
            continue
        kind = entry.get("kind") or "file"
        rev = entry.get("revision") or ""
        author, date = "", ""
        size_el = entry.find("size")
        size = (size_el.text or u"").strip() if size_el is not None else u""
        commit = entry.find("commit")
        if commit is not None:
            rev = rev or commit.get("revision") or ""
            a = commit.find("author")
            d = commit.find("date")
            author = (a.text or "").strip() if a is not None and a.text else ""
            date = fmt_date(d.text if d is not None else "")
        items.append({"kind": kind, "name": name.rstrip("/"), "rev": rev,
                      "author": author, "date": date, "size": size})
    items.sort(key=lambda it: (0 if it["kind"] == "dir" else 1, it["name"]))
    return items


def parse_lines(lines):
    """LsWorker 返回的 stdout 行列表 -> 条目列表。"""
    return parse_list_xml("\n".join(lines or []))


def topmost(rels):
    """路径集合 -> 互不包含的最上层集合（浅者优先，同深度按字典序）。

    排除清单与恢复清单共用：上层目录的命令会覆盖其子孙，
    因此子孙没有重复列出的必要。实现复用主模块的 topmost_paths。
    """
    return core.topmost_paths(rels)


def checked_to_excludes(checked):
    """勾选状态 -> 排除目录列表（相对检出根，只保留最上层的未勾选目录）。

    checked: {相对路径: 是否下载}，根（""）恒为 True。
    未勾选目录的子孙即使不在表里也已被覆盖，无需重复列出。
    """
    return topmost([r for r, on in checked.items() if r and not on])


def _svn_text(cmd, timeout=60):
    """同步执行一条 svn 命令，返回 (rc, stdout 文本)；失败返回 (None, "")。

    字节模式读输出再自行 decode——主模块对 subprocess 的硬约束在此同样适用。
    """
    try:
        pr = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    except OSError:
        return None, u""
    try:
        out, _err = pr.communicate(timeout=timeout)
    except Exception:
        try:
            pr.kill()
            pr.communicate()
        except Exception:
            pass
        return None, u""
    return pr.returncode, out.decode("utf-8", "replace")


def parse_info_url(text):
    """`svn info --xml` 输出 -> 工作副本来源 URL（解析不出返回空串）。

    与主模块“按工作副本反查地址”共用同一份解析，实现委托给 core。
    """
    return core.parse_info_url(text)


def parse_status_have(text, dst):
    """`svn status -v --xml` 输出 -> 已下载条目相对 dst 的路径集合。

    被 `--set-depth=exclude` 排除的条目**不会出现在 status 输出里**，
    因此用集合成员关系即可判定“已下载 / 已排除”。
    解析失败返回 None（表示未知，界面退化为按父级继承）。
    """
    try:
        root = ET.fromstring((text or "").strip() or "<status/>")
    except ET.ParseError:
        return None
    base = os.path.abspath(str(dst))
    have = set()
    for entry in root.iter("entry"):
        p = entry.get("path") or ""
        if not p:
            continue
        try:
            rel = os.path.relpath(os.path.abspath(p), base)
        except (OSError, ValueError):
            continue
        if rel.startswith(".."):
            continue
        rel = rel.replace(os.sep, "/")
        have.add(u"" if rel == "." else rel)
    return have


def read_local_kind(url, dst):
    """快速判定本地目录与目标地址的关系（只跑 svn info，不跑 status）。

    返回 {"kind", "url", "have"}，kind 语义：
      none    本地目录不存在（可直接检出）
      fresh   目录存在且为空（非工作副本，可直接检出）
      same    同源工作副本（可按勾选更新）
      other   异源工作副本（拒绝，避免覆盖别人的检出）
      unknown 目录非空且不是工作副本，或读取失败
    have 恒为 None——排除状态要靠 svn status 读，在大工作副本上非常慢，
    由 LsWorker 后台补读（见 CheckoutSelect._start_stat），否则一打开
    检出/更新窗口就要同步等 svn status 扫完整棵树（20261015 用户反馈）。
    """
    res = {"kind": "none", "url": u"", "have": None}
    s = str(dst or "").strip()
    if not s:
        return res
    p = os.path.abspath(os.path.expanduser(s))
    if not os.path.isdir(p):
        return res
    rc, out = _svn_text(["svn", "info", "--xml", "--non-interactive", p])
    if rc != 0 or not out.strip():
        try:
            empty = not os.listdir(p)
        except OSError:
            empty = False
        res["kind"] = "fresh" if empty else "unknown"
        return res
    wc_url = parse_info_url(out)
    res["url"] = wc_url
    if core.normalize_svn_url(wc_url) != core.normalize_svn_url(url):
        res["kind"] = "other"
        return res
    res["kind"] = "same"
    return res


def cat_display(data, encoding=None):
    """`svn cat` 的原始字节（或文本行列表）-> (展示文本, 状态说明, 是否二进制)。

    - data 为 bytes 时自动适配编码（见 decode_text）；encoding 非空则按
      指定编码解码（内容窗口“编码”菜单的手动兜底）；
    - 二进制（含 NUL 等）不展示内容，状态说明里给出大小；
    - 超过 CAT_MAX_LINES 行先截断（防超大文件把界面卡死）；
    - data 仍是文本行列表时保留旧规则：U+FFFD 占比过高提示可能编码不对。
    """
    is_raw = isinstance(data, bytes)
    enc_label = u""
    if is_raw:
        raw = data
        if not raw:
            return u"", u"共 0 行", False
        if encoding:
            if _binary_bytes(raw):
                return u"", u"二进制文件（%d 字节），不显示内容" % len(raw), True
            enc_label = _encoding_label(encoding)
            try:
                text = raw.decode(encoding)
            except UnicodeDecodeError:
                text = raw.decode(encoding, "replace")
            except LookupError:
                text = raw.decode("utf-8", "replace")
                enc_label = u"UTF-8"
        else:
            text, enc_label, binary = decode_text(raw)
            if binary:
                return u"", u"二进制文件（%d 字节），不显示内容" % len(raw), True
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if lines and lines[-1] == u"":
            lines.pop()
    else:
        lines = [str(x) for x in (data or [])]
        joined = u"\n".join(lines)
        if u"\x00" in joined:
            return u"", u"二进制文件（%d 个字符），不显示内容" % len(joined), True
    total = len(lines)
    text = u"\n".join(lines)
    if total > CAT_MAX_LINES:
        text = u"\n".join(lines[:CAT_MAX_LINES])
        note = u"文件较大，仅显示前 %d 行（共 %d 行）" % (CAT_MAX_LINES, total)
    else:
        note = u"共 %d 行" % total
    if not is_raw:
        bad = text.count(chr(0xFFFD))
        if bad and len(text) and bad * 100 >= len(text):
            note += u"；内容疑似非 UTF-8 编码，可能显示乱码"
    elif encoding or enc_label != u"UTF-8":
        note += u" · 编码 %s" % enc_label
    return text, note, False


# ============================================================
# 二、后台读取线程
# ============================================================

class LsWorker(Runner):
    """仓库列表后台线程：任务队列循环，与主界面的 Hub 完全独立。

    事件（放入 self.q，由界面轮询取出）：
      ("ls", (kind, url), ok, payload)   成功 payload=stdout 行列表
                                         （kind="cat" 时是原始字节；
                                          kind="collection" 时是仓库列表）
      ("ask_auth", text) / ("ask_cert", text)
    认证/证书答复通过 respond() 回传 auth_q；凭据与证书信任状态跨请求复用。
    集合根（kind="collection"）不走 svn 协议，改用标准库 HTTP GET 读
    mod_dav_svn 的网页索引；仍是后台线程，绝不直接碰 Tk 控件。
    """

    def __init__(self, trust_server_cert=False):
        # log_path 只是占位：log() 已覆盖为空实现，不会写任何日志文件
        super().__init__("ls", queue.Queue(),
                         core.log_dir() / "repo_browser.log",
                         trust_server_cert=bool(trust_server_cert))
        self.tasks = queue.Queue()
        self._ask_pending = False
        self._timed_out = False
        self._stopped = False
        self._timer = None
        # HTTP 索引读取用的凭据来源（避免把 A 服务器的凭据发给 B 服务器）
        self._http_creds_netloc = u""

    # ---- 覆盖：浏览不写运行日志、不往主日志区刷命令 ----
    def log(self, text, tag="info"):
        pass

    def run(self):
        while True:
            task = self.tasks.get()
            if task is None:
                break
            tag, cmd = task
            if self._stopped:
                self.q.put(("ls", tag, False, u"已停止"))
                continue
            self._begin()
            timer = threading.Timer(LS_TIMEOUT, self._on_timeout)
            timer.daemon = True
            self._timer = timer
            timer.start()
            try:
                if isinstance(tag, tuple) and tag and tag[0] == "collection":
                    self.q.put(("ls", tag, True, self._fetch_collection(tag[1])))
                else:
                    # 查看内容要拿原始字节再判断编码（先按 UTF-8 解码会丢信息）；
                    # 目录/状态等 --xml 输出仍是逐行解码的 buffer
                    sink = ("bytes" if isinstance(tag, tuple) and tag
                            and tag[0] == "cat" else "buffer")
                    lines = self._run(cmd, None, sink)
                    self.q.put(("ls", tag, True, lines))
            except core.RunCancelled:
                if self._timed_out:
                    msg = u"读取超时（%d 秒），请检查网络或仓库地址" % LS_TIMEOUT
                elif self._stopped:
                    msg = u"已停止"
                else:
                    msg = u"已取消"
                self.q.put(("ls", tag, False, msg))
            except Exception as e:
                self.q.put(("ls", tag, False, str(e)))
            finally:
                self._ask_pending = False
                self._end_timer()

    # ---------- 集合根：HTTP 索引 ----------
    def _ssl_context(self):
        """按“信任自签名证书”开关构造 SSL 上下文。"""
        if self.trust_cert:
            return ssl._create_unverified_context()
        return ssl.create_default_context()

    @staticmethod
    def _netloc(url):
        try:
            return urllib.parse.urlsplit(str(url or "")).netloc.lower()
        except ValueError:
            return u""

    def _http_request(self, url):
        """GET 一个 URL，返回 (body_bytes, final_url)。

        401 时先复用 svn 缓存凭据，失败再弹登录框（与 svn 命令的认证
        弹窗是同一个 dialogs.ask_auth）；证书错误复用 ask_cert。
        """
        headers = {
            "User-Agent": "%s/%s" % (core.APP_NAME, core.APP_VERSION),
            "Accept": "text/xml, application/xml, */*",
            "Accept-Encoding": "identity",
        }
        req = urllib.request.Request(url, headers=headers)
        auth_failures = 0
        while True:
            ctx = self._ssl_context()
            handlers = [urllib.request.HTTPSHandler(context=ctx)]
            use_creds = (self.creds is not None
                         and self._http_creds_netloc == self._netloc(url))
            if use_creds:
                user, password, _remember = self.creds
                pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
                # 同时登记带/不带尾斜杠的地址，覆盖 /svn -> /svn/ 的重定向
                pm.add_password(None, url, user, password)
                pm.add_password(None, url.rstrip("/") + "/", user, password)
                handlers.append(urllib.request.HTTPBasicAuthHandler(pm))
            opener = urllib.request.build_opener(*handlers)
            try:
                resp = opener.open(req, timeout=COLLECTION_TIMEOUT)
                try:
                    data = resp.read(COLLECTION_MAX_BYTES + 1)
                    final = resp.geturl()
                finally:
                    resp.close()
                if self.cancel_flag:
                    raise core.RunCancelled
                if len(data) > COLLECTION_MAX_BYTES:
                    raise RuntimeError(
                        u"仓库列表过大（超过 %d KB），已停止读取"
                        % (COLLECTION_MAX_BYTES // 1024))
                return data, final
            except urllib.error.HTTPError as e:
                code = e.code
                try:
                    e.close()
                except Exception:
                    pass
                if code == 401 and auth_failures < 3:
                    auth_failures += 1
                    if not use_creds:
                        cached = core.cached_credentials(url)
                        if cached:
                            self.creds = (cached["username"],
                                          cached["password"], False)
                            self._http_creds_netloc = self._netloc(url)
                            continue
                    # 已用过的凭据（缓存或上次输入）不对：清掉再问
                    self.creds = None
                    self._http_creds_netloc = u""
                    self._ask(
                        "ask_auth",
                        u"读取仓库列表需要登录：\n%s\n\n"
                        u"请输入 SVN 用户名和密码。" % core.decode_svn_url(url))
                    self._http_creds_netloc = self._netloc(url)
                    continue
                if code == 403:
                    raise RuntimeError(
                        u"没有权限读取仓库列表（HTTP 403）：%s"
                        % core.decode_svn_url(url))
                if code == 404:
                    raise RuntimeError(
                        u"仓库列表地址不存在（HTTP 404）：%s"
                        % core.decode_svn_url(url))
                raise RuntimeError(
                    u"读取仓库列表失败（HTTP %d）：%s"
                    % (code, core.decode_svn_url(url)))
            except urllib.error.URLError as e:
                reason = getattr(e, "reason", e)
                text = str(reason)
                if (not self.trust_cert
                        and ("certificate verify failed" in text.lower()
                             or "CERTIFICATE_VERIFY_FAILED" in text)):
                    self._ask("ask_cert", text)
                    continue
                if (isinstance(reason, socket.timeout)
                        or "timed out" in text.lower()):
                    raise RuntimeError(
                        u"读取仓库列表超时（%d 秒）" % COLLECTION_TIMEOUT)
                raise RuntimeError(u"无法连接仓库列表地址：%s" % text)
            except ssl.SSLError as e:
                if not self.trust_cert:
                    self._ask("ask_cert", str(e))
                    continue
                raise RuntimeError(u"SSL 错误：%s" % e)
            except socket.timeout:
                raise RuntimeError(
                    u"读取仓库列表超时（%d 秒）" % COLLECTION_TIMEOUT)

    def _fetch_collection(self, url):
        """读取集合根索引并解析成仓库列表（在后台线程执行）。"""
        base = url if str(url).endswith("/") else str(url) + "/"
        data, final_url = self._http_request(base)
        items = core.parse_repo_index(data, final_url)
        if items is None:
            raise RuntimeError(
                u"该地址返回的不是仓库列表（可能不是仓库集合根，"
                u"或需要登录/证书信任）")
        return items

    # ---------- 任务生命周期 ----------
    def _begin(self):
        self.cancel_flag = False
        self._timed_out = False
        self._ask_count = 0
        while True:                      # 清掉上一任务残留的答复
            try:
                self.auth_q.get_nowait()
            except queue.Empty:
                break

    def _end_timer(self):
        t = self._timer
        self._timer = None
        if t is not None:
            t.cancel()

    def _on_timeout(self):
        self._timed_out = True
        self.cancel()

    def _ask(self, kind, text):
        if self._stopped:
            raise core.RunCancelled
        # 等用户输入凭据/点证书的时间不计入读取超时
        t = self._timer
        self._timer = None
        if t is not None:
            t.cancel()
        self._ask_pending = True
        try:
            super()._ask(kind, text)
        finally:
            if not self._stopped:
                timer = threading.Timer(LS_TIMEOUT, self._on_timeout)
                timer.daemon = True
                self._timer = timer
                timer.start()

    # ---------- 对外 ----------
    def request(self, tag, cmd):
        """排队一个读取任务；tag 形如 ("node", url) / ("checkout", url)。"""
        self.tasks.put((tag, cmd))

    def respond(self, resp):
        if self._ask_pending:
            self._ask_pending = False
            self.auth_q.put(resp)

    def stop(self):
        """停止线程：未答的弹窗先回“取消”，再中断正在跑的 svn。"""
        self._stopped = True
        if self._ask_pending:
            self.respond({"ok": False})
        self.cancel()
        self.tasks.put(None)


# ============================================================
# 三、检出对话框（勾选要下载的目录）
# ============================================================

class CheckoutSelect(tk.Toplevel):
    """模态对话框：勾选要下载/更新的目录与文件，返回结果 dict 或 None。

    勾选粒度精确到“目录与文件”（映射为下载算法的 set-depth 规则）：
      - 行结构 = 缩进 + ▾/▸ 展开箭头 + ☑/☐ + 名称（目录带尾斜杠），
        层级一目了然，文件同样可以勾选/排除；
      - 单击只选中行（高亮），**只有点勾选框才翻转勾选**（用户要求）；
      - 点箭头展开/收起（懒加载子级）；键盘 ↑/↓ 移动当前行、空格勾选、
        ←/→ 收起/展开、PgUp/PgDn/Home/End 快速移动；
      - 勾选一个目录会把它和已加载的子孙一起置为下载，并补齐祖先；
      - 检出根恒为 ☑，不可取消；未展开的目录默认跟随父级状态。

    列表用 tk.Text 而不是 ttk.Treeview（与主界面改动列表同一套路数）：
    本机 Tk 的 Treeview 一行只有一个字号，放大勾选框会把名称一起放大；
    Text 可以给勾选框单独套大号加粗字形，与改动列表共用
    theme.check_font，观感一致。

    本地目录已是同源工作副本时先读取当前排除状态（LsWorker 后台补读）：
      - 已排除的目录/文件初始为 ☐，重新勾选即恢复，取消勾选即重新排除；
      - 此时按钮变为“更新到所选”，确认后由主程序按勾选对齐本地内容。
    """

    def __init__(self, owner, url, items=None, dst=None):
        super().__init__(owner)
        self.owner = owner
        self.transient(owner)
        # 在窗口映射前标成 dialog（映射后再改 WM 可能不认），并挂最小化
        # 自动还原；grab 不能跟着窗口一起“消失”（见 theme.install_modal_guard）
        theme.install_modal_guard(self)
        self.url = url
        self.result = None
        self.checked = {u"": True}
        root_name = core.decode_svn_url(url).rstrip("/").rsplit("/", 1)[-1]
        self._url_rel = {url: u""}            # 完整 URL -> 相对检出根的路径
        self._rel_url = {u"": url}            # 相对路径 -> 完整 URL
        self._disp = {u"": root_name or url}  # 相对路径 -> 显示名
        self._kind = {u"": "dir"}             # 相对路径 -> "dir" / "file"
        self._kids = {}                       # 相对路径 -> 子级清单（读取顺序）
        self._expanded = set([u""])           # 已展开的目录（根默认展开）
        self._loaded = set()                  # 已读过子级的目录
        self._loading = set()                 # 正在读取的目录
        self._load_err = set()                # 读取失败的目录（再展开可重试）
        self._rows = []                       # 显示行：[{"rel", "depth", "hint"}]
        self._rel_line = {}                   # 相对路径 -> 行号（1 起）
        self._selectable = []                 # 真实行（可选中）的 0 起下标
        self.sel_rel = None                   # 当前选中行的相对路径
        self._hover_y = None                  # 鼠标悬停的 y（重绘后补高亮）
        self._hover_line = None
        self._skip_release = False            # 双击后忽略随之而来的 release
        self._after_dst = None                # 本地目录防抖校验的 after id
        self._stat_pending = False            # 正在后台补读本地排除状态
        self._stat_dst = None                 # 该读取对应的目录
        self._touched = False                 # 用户手动改过勾选（后台读数回来时别覆盖）
        if dst is None:
            dst = self._default_dst()
        self._state_dst = (dst or u"").strip()   # 上次校验本地状态用的目录
        # 只做快速判定（svn info）；同源工作副本的排除状态很慢，
        # 交给后台线程补读，窗口先弹出来（见 _start_stat）
        self.local = self._read_local(self._state_dst)
        # have=None 表示未知（按父级继承）；后台读数回来才有值
        self._have = (self.local.get("have")
                      if self.local.get("kind") == "same" else None)
        # 本地还没有工作副本时，用配置里的排除清单作初始勾选
        self._seed = self._config_excludes()
        self.dst_var = tk.StringVar(value=dst or u"")
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Destroy>", self._on_destroy)
        # 本地目录变化（手输/粘贴/浏览）立即校验：400ms 防抖，失焦立即执行
        self.dst_var.trace("w", self._dst_var_changed)
        if items is None:
            self._ensure_loaded(u"")
            self._render()
        else:
            self._apply(url, items)           # 内部会重绘
        if self.local.get("kind") == "same":
            self._start_stat(self._state_dst)  # 后台补读排除状态（不卡窗口）
        self._refresh_mode()

    # ---------- 界面 ----------
    def _build(self):
        self.title(u"检出 / 更新")
        # 宽度与其它模态弹窗统一（高度仍按内容/屏幕自适应）
        self.minsize(theme.DIALOG_W, 480)
        fam = theme.pick_family(self, mono=True)
        base = theme.base_size()
        self.font_body = tkfont.Font(family=fam,
                                     size=base + core.UP_FONT_DELTA)
        self.font_chk = theme.check_font(self, mono=True)

        head = tk.Frame(self)
        head.pack(fill="x", padx=12, pady=(10, 2))
        tk.Label(head, text=u"要下载的目录与文件（单击选中 · 点 ☑/☐ 或空格勾选）").pack(
            side="left")
        self.count_lbl = tk.Label(head, text="", fg=core.MUTED)
        self.count_lbl.pack(side="right")
        tk.Label(self, text=core.decode_svn_url(self.url), fg=core.MUTED,
                 anchor="w", justify="left", wraplength=600).pack(
            fill="x", padx=12)
        self.local_lbl = tk.Label(self, text=self._local_text(), fg=core.MUTED,
                                  anchor="w", justify="left", wraplength=600)
        self.local_lbl.pack(fill="x", padx=12)

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=6)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self.text = tk.Text(body, height=12, wrap="none", state="disabled",
                            cursor="arrow", undo=False, spacing1=2,
                            spacing2=2, font=self.font_body)
        theme.surface(self.text)          # 白色面板 + 1px 细边框
        # 标签按创建顺序排优先级：字号/前景色 < 悬停 < 当前行，
        # 当前行底色压得住悬停，悬停盖得住正常行底色
        self.text.tag_configure("chk", font=self.font_chk)   # 勾选框大字形
        # 正文相对勾选框垂直居中（用户要求；常量与原因见 core.UP_TEXT_OFFSET）
        self.text.tag_configure("txt", offset=core.UP_TEXT_OFFSET)
        self.text.tag_configure("chk_on", foreground=core.ACCENT)
        self.text.tag_configure("chk_off", foreground=core.MUTED)
        self.text.tag_configure("dir", foreground=core.ACCENT)  # 目录名一眼可辨
        self.text.tag_configure("hint", foreground=core.MUTED)
        self.text.tag_configure("hover", background=core.UP_HOVER_BG)
        # 当前行文字用正文色，保证深色皮肤下选中蓝底上的可读性
        self.text.tag_configure("cur", background=core.UP_CUR_BG,
                                foreground=core.TEXT)
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        hsb = ttk.Scrollbar(body, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.text.bind("<ButtonRelease-1>", self._on_click)
        self.text.bind("<Double-Button-1>", self._on_dblclick)
        self.text.bind("<Motion>", self._on_motion)
        self.text.bind("<Leave>", self._on_leave)
        # 键盘操作（用户要求）：上下移动当前行、空格勾选、
        # 左右收起/展开，PgUp/PgDn/Home/End 快速定位
        self.text.bind("<Up>", lambda _e: self._move_sel(-1))
        self.text.bind("<Down>", lambda _e: self._move_sel(1))
        self.text.bind("<Prior>", lambda _e: self._move_sel(-10))
        self.text.bind("<Next>", lambda _e: self._move_sel(10))
        self.text.bind("<Home>", lambda _e: self._move_sel(0, first=True))
        self.text.bind("<End>", lambda _e: self._move_sel(0, last=True))
        self.text.bind("<space>", lambda _e: self._toggle_current())
        self.text.bind("<Left>", lambda _e: self._collapse_current())
        self.text.bind("<Right>", lambda _e: self._expand_current())

        btns = tk.Frame(self)
        btns.pack(fill="x", padx=12, pady=(0, 4))
        ttk.Button(btns, text=u"全选", width=theme.BTN_W,
                   command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(btns, text=u"全不选", width=theme.BTN_W,
                   command=lambda: self._set_all(False)).pack(side="left",
                                                              padx=(6, 0))
        ttk.Button(btns, text=u"反选", width=theme.BTN_W,
                   command=self._invert).pack(side="left", padx=(6, 0))
        self.msg = tk.Label(btns, text="", fg=core.LOG_COLORS["err"])
        self.msg.pack(side="left", padx=10)

        row = tk.Frame(self)
        row.pack(fill="x", padx=12, pady=(4, 2))
        tk.Label(row, text=u"本地目录").pack(side="left")
        e = ttk.Entry(row, textvariable=self.dst_var)
        e.pack(side="left", fill="x", expand=True, padx=6)
        e.bind("<Return>", lambda ev: self._ok())
        e.bind("<FocusOut>", lambda ev: self._dst_changed())
        ttk.Button(row, text=u"浏览…", command=self._browse,
                   width=theme.BTN_W).pack(side="left")

        foot = tk.Frame(self)
        foot.pack(fill="x", padx=12, pady=(6, 12))
        ttk.Button(foot, text=u"取消", command=self.destroy,
                   width=theme.BTN_W).pack(side="right", padx=(8, 0))
        self.btn_ok = ttk.Button(foot, text=u"开始下载", command=self._ok,
                                 width=theme.BTN_W,
                                 style=theme.ACCENT_STYLE)
        self.btn_ok.pack(side="right")
        # 内容建完再定位：基于父窗口（仓库浏览器）居中（用户要求）
        theme.center_on_parent(self)

    def _default_dst(self):
        """默认本地目录 = 配置里上次用过的工作副本路径。"""
        try:
            return (self.owner.app.store.settings.get("dst", "") or u"")
        except Exception:
            return u""

    def _config_excludes(self):
        """配置里的排除清单（本地尚无工作副本时用作初始勾选）。"""
        try:
            return core.clean_excludes(
                self.owner.app.store.settings.get("excludes") or [])
        except Exception:
            return []

    def _read_local(self, dst):
        """快速读取本地目录状态（只跑 svn info，不跑 svn status）。

        路径被文件占用时单列一种 kind 供界面提示；同源工作副本的
        排除状态（have）由 _start_stat 后台补读。
        """
        s = str(dst or "").strip()
        if s:
            p = os.path.abspath(os.path.expanduser(s))
            try:
                occupied = os.path.exists(p) and not os.path.isdir(p)
            except OSError:
                occupied = False
            if occupied:
                return {"kind": "file", "url": u"", "have": None}
        return read_local_kind(self.url, s)

    def _start_stat(self, dst):
        """请浏览器后台线程读本地排除状态（svn status 大工作副本上很慢）。"""
        if self._stat_pending and dst == self._stat_dst:
            return
        self._stat_dst = dst
        self._stat_pending = True
        try:
            self.owner.request_stat(dst)
        except Exception:
            self._stat_pending = False

    def on_stat(self, dst, ok, payload):
        """后台排除状态读取完成（由浏览器轮询转发，结果可能已过期）。"""
        if dst != self._state_dst:
            return                       # 目录已改，丢弃过期结果
        self._stat_pending = False
        have = None
        if ok:
            try:
                # 与 svn 命令用的是同一个绝对路径（见 request_stat），
                # 否则 ~/ 或相对路径会把相对关系算错
                base = os.path.abspath(os.path.expanduser(str(dst or "")))
                have = parse_status_have("\n".join(payload or []), base)
            except Exception:
                have = None
        if have is not None:
            self._have = have
            self.local["have"] = have
            if not self._touched:
                # 用户还没动过勾选：按本地真实排除状态重铺
                # （已排除的初始为 ☐，重新勾选即恢复）
                self.checked[u""] = True
                for r in [r for r in self._disp if r]:
                    self.checked[r] = r in have
                self._render()
        self._refresh_mode()

    def _local_text(self):
        """本地目录状态说明（对话框顶部的一行小字）。"""
        kind = self.local.get("kind")
        dst = self.dst_var.get().strip()
        if not dst:
            return u""
        if kind == "same":
            return u"本地目录已是该地址的工作副本：将按下面的勾选更新，" \
                   u"重新勾选的目录/文件会被拉回，取消勾选的会被排除"
        if kind in ("none", "fresh"):
            return u"本地目录尚无工作副本，将执行首次检出"
        if kind == "file":
            return u"本地路径已被同名文件占用，请更换本地目录"
        if kind == "other":
            return u"本地目录已是其他来源的工作副本（%s），不能更新" % (
                core.decode_svn_url(self.local.get("url") or u""))
        return u"本地目录已存在且不是 SVN 工作副本，请更换本地目录"

    def _refresh_mode(self):
        """按本地状态切换按钮文案、提示与可用性（下载 / 更新 / 禁用）。"""
        kind = self.local.get("kind")
        dst = self.dst_var.get().strip()
        if not dst:
            text, enabled = u"开始下载", False
            msg = u"请填写本地目录"
        elif kind == "same":
            if self._stat_pending:
                text, enabled = u"更新到所选", False
                msg = u"正在读取本地排除状态…"
            else:
                text, enabled, msg = u"更新到所选", True, u""
        elif kind in ("none", "fresh"):
            text, enabled, msg = u"开始下载", True, u""
        elif kind == "file":
            text, enabled = u"开始下载", False
            msg = u"本地路径已被同名文件占用，请更换本地目录"
        elif kind == "other":
            text, enabled = u"开始下载", False
            msg = u"本地目录已是其他来源的工作副本，不能更新"
        else:
            text, enabled = u"开始下载", False
            msg = u"本地目录已存在且不是 SVN 工作副本，请更换本地目录"
        try:
            self.btn_ok.configure(text=text,
                                  state="normal" if enabled else "disabled")
        except tk.TclError:
            pass
        try:
            self.local_lbl.configure(text=self._local_text())
        except tk.TclError:
            pass
        self._set_msg(msg)

    def _dst_var_changed(self, *_args):
        """本地目录输入框变化：400ms 防抖后立即校验（用户要求）。"""
        if self._after_dst is not None:
            try:
                self.after_cancel(self._after_dst)
            except tk.TclError:
                pass
        self._after_dst = self.after(400, self._dst_changed)

    def _dst_changed(self):
        """重新校验本地目录：状态说明、按钮文案与初始勾选随之切换。

        只做快速判定；同源工作副本的排除状态后台补读（见 _start_stat）。
        """
        if self._after_dst is not None:
            try:
                self.after_cancel(self._after_dst)
            except tk.TclError:
                pass
            self._after_dst = None
        try:
            if not self.winfo_exists():
                return
            dst = self.dst_var.get().strip()
        except tk.TclError:                 # 窗口已随关闭流程销毁
            return
        self.local = self._read_local(dst)
        self._state_dst = dst
        self._have = None
        self._stat_pending = False
        self._touched = False               # 换了目录，之前的勾选不算数
        if self.local.get("kind") == "same":
            self._start_stat(dst)
        self._refresh_mode()

    def _on_destroy(self, event):
        """窗口销毁时撤掉未执行的防抖校验（避免关闭后回调再触发）。"""
        if event.widget is self and self._after_dst is not None:
            try:
                self.after_cancel(self._after_dst)
            except tk.TclError:
                pass
            self._after_dst = None

    def run(self):
        """模态打开，关闭后返回结果（None=取消）。"""
        self.grab_set()
        self.wait_window()
        return self.result

    # ---------- 数据 ----------
    def excludes(self):
        return checked_to_excludes(self.checked)

    def on_ls(self, url, ok, payload):
        """LsWorker 的读取结果（由浏览器轮询转发）。"""
        rel = self._url_rel.get(url)
        if rel is None:
            return
        if not ok:
            self._loading.discard(rel)
            self._load_err.add(rel)
            self._set_msg(u"读取失败: %s" % (payload or u""))
            self._render()
            return
        try:
            items = parse_lines(payload)
        except Exception as e:
            self._loading.discard(rel)
            self._load_err.add(rel)
            self._set_msg(u"读取失败: %s" % e)
            self._render()
            return
        self._set_msg(u"")
        self._apply(url, items)

    def _apply(self, url, items):
        """记录某目录的子级清单（目录与文件），需要时重绘。"""
        rel = self._url_rel.get(url)
        if rel is None:
            return
        self._forget_children(rel)
        parent_on = self.checked.get(rel, True)
        kids = []
        for it in items:
            name = it["name"]
            child_rel = (rel + "/" + name) if rel else name
            child_url = core.join_url(url, name)
            self._url_rel[child_url] = child_rel
            self._rel_url[child_rel] = child_url
            self._disp[child_rel] = name
            self._kind[child_rel] = it["kind"] or "file"
            if self._have is not None:
                # 已读到本地状态：按“本地是否已存在”还原勾选
                # （已排除的初始为 ☐，重新勾选即恢复）
                self.checked[child_rel] = child_rel in self._have
            else:
                # 尚无本地状态：跟随时父级，并按配置里的排除清单预置
                self.checked.setdefault(
                    child_rel,
                    parent_on and not core.is_excluded(child_rel, self._seed))
            kids.append(child_rel)
        self._kids[rel] = kids
        self._loaded.add(rel)
        self._loading.discard(rel)
        self._load_err.discard(rel)
        self._render()

    def _forget_children(self, rel):
        """丢弃 rel 的全部子孙数据（重新列出时避免残留脏数据）。"""
        if rel:
            dead = [r for r in list(self._disp) if r.startswith(rel + "/")]
        else:
            dead = [r for r in list(self._disp) if r]
        for r in dead:
            url = self._rel_url.pop(r, None)
            if url:
                self._url_rel.pop(url, None)
            self._disp.pop(r, None)
            self._kind.pop(r, None)
            self.checked.pop(r, None)
            self._kids.pop(r, None)
            self._loaded.discard(r)
            self._loading.discard(r)
            self._load_err.discard(r)
            self._expanded.discard(r)

    def _hint_text(self, rel):
        """展开但还没内容的目录的占位文字。"""
        if rel in self._load_err:
            return u"（读取失败，点箭头重新加载）"
        if rel in self._kids:
            return u"（空目录）"
        return LOADING                     # 加载中…

    def _ensure_loaded(self, rel):
        """请求读取某目录的子级（懒加载；读取失败后再展开会重试）。"""
        if rel in self._loaded or rel in self._loading:
            return
        url = self._rel_url.get(rel)
        if not url:
            return
        self._loading.add(rel)
        self._load_err.discard(rel)
        self.owner.request(url, "checkout")

    # ---------- 渲染 ----------
    def _render(self):
        """按展开状态整表重绘（展开树的前序遍历 = 显示行）。"""
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        self._rows = []
        self._walk(u"")
        self._rel_line = {}
        self._selectable = []
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for i, row in enumerate(self._rows):
            if row["rel"] is not None:
                self._rel_line[row["rel"]] = i + 1
                self._selectable.append(i)
            self._write_row(row)
        self.text.configure(state="disabled")
        if self.sel_rel is not None and self.sel_rel not in self._rel_line:
            self.sel_rel = None            # 选中的行已不在显示范围内
        self._paint_cur()
        self._hover_refresh()   # 重绘会抹掉悬停标签，按记录的 y 补回
        self._update_count()

    def _walk(self, rel):
        """前序遍历：rel 与它展开的子孙依次排进显示行。"""
        depth = 0 if not rel else rel.count("/") + 1
        self._rows.append({"rel": rel, "depth": depth, "hint": None})
        if self._kind.get(rel) != "dir" or rel not in self._expanded:
            return
        kids = self._kids.get(rel)
        if kids:
            for k in kids:
                self._walk(k)
        else:
            self._rows.append({"rel": None, "depth": depth + 1,
                               "hint": self._hint_text(rel)})

    def _row_segments(self, row):
        """行内容分段：[(文字, 标签元组)]，最后一段含行尾换行符。

        勾选框单独一段并挂 "chk" 标签：勾选字形与主界面改动列表同一套
        （theme.check_font），观感一致；目录名挂 "dir" 标签一眼可辨；
        勾选框之外的正文（缩进/箭头/名称）挂 "txt" 标签做垂直微调
        （见 core.UP_TEXT_OFFSET）。“加载中…”占位行没有勾选框，不加
        这个微调。整表重绘（_write_row）与单行重写（_write_row_at）
        共用本函数，保证两条路径的分段与标签完全一致。
        """
        if row["rel"] is None:
            return [(INDENT * row["depth"] + u"  " + row["hint"] + u"\n",
                     ("hint",))]
        rel, depth = row["rel"], row["depth"]
        kind = self._kind.get(rel)
        if kind == "dir":
            arrow = u"\u25be " if rel in self._expanded else u"\u25b8 "
        else:
            arrow = u"  "
        on = self.checked.get(rel, True)
        name = self._disp.get(rel, rel) + (u"/" if kind == "dir" else u"")
        return [
            (INDENT * depth + arrow, ("txt",)),
            (core.CHECK_ON if on else core.CHECK_OFF,
             ("chk", "chk_on" if on else "chk_off")),
            (u" " + name + u" " * core.UP_FILL + u"\n",
             ("dir", "txt") if kind == "dir" else ("txt",)),
        ]

    def _write_row(self, row):
        """整表重绘：把一行追加到末尾。"""
        for seg, tags in self._row_segments(row):
            self.text.insert("end", seg, tags)

    def _write_row_at(self, line, row):
        """原地重写第 line 行（勾选翻转等小改动）；**不碰滚动位置**。

        delete 到 "%d.end" 只删行内文字、行尾换行符还在，最后一段要去掉
        换行符再插（不然会多出一个空行）；插入位置从 "%d.0" 起按精确列号
        累加——用 "end" 之类会被 Tk 夹紧的索引会串行（同主界面
        _up_line_write 的约定）。
        """
        segs = list(self._row_segments(row))
        if segs and segs[-1][0].endswith(u"\n"):
            text, tags = segs[-1]
            segs[-1] = (text[:-1], tags)
        self.text.delete("%d.0" % line, "%d.end" % line)
        col = 0
        for seg, tags in segs:
            self.text.insert("%d.%d" % (line, col), seg, tags)
            col += len(seg)

    def _refresh_rows(self, rels):
        """只重写指定 rel 的可见行（勾选翻转不整表重绘、**列表不动**）。

        整表 _render 会 delete("1.0","end") 再逐行重插，Text 的 yview
        被夹回顶部——用户滚到列表中段点一下勾选框，列表就跳回顶部，
        键盘再 see() 把该行拉回视线，观感就是“勾选时列表乱动”
        （20261016 用户反馈：翻转勾选时列表要保持不动）。勾选不改变行
        结构，重写受影响的行即可；delete 会清掉行上的 cur/hover 标签，
        收尾按 _render 同款补回。
        """
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        lines = []
        for rel in rels:
            line = self._line_of_rel(rel)
            if line is not None:
                lines.append(line)
        if not lines:
            self._update_count()
            return
        ytop = self.text.yview()[0]    # 记住视口位置，重写后恢复（见上）
        self.text.configure(state="normal")
        for line in sorted(set(lines)):
            self._write_row_at(line, self._rows[line - 1])
        self.text.configure(state="disabled")
        self.text.yview_moveto(ytop)
        self._paint_cur()
        self._hover_refresh()
        self._update_count()

    def _paint_cur(self):
        """高亮当前行（该标签创建在悬停之后，优先级更高）。"""
        self.text.tag_remove("cur", "1.0", "end")
        line = self._line_of_rel(self.sel_rel)
        if line is not None:
            self.text.tag_add("cur", "%d.0" % line, "%d.end" % line)

    def _line_of_rel(self, rel):
        """相对路径 -> 行号（1 起）；不在当前显示行里返回 None。"""
        if rel is None:
            return None
        return self._rel_line.get(rel)

    def _hover_refresh(self):
        """整表重绘后按记录的鼠标 y 重新套悬停高亮（旧标签已被抹掉）。"""
        line = (self._line_of_y(self._hover_y)
                if self._hover_y is not None else None)
        self._hover_line = None
        self._set_hover_line(line)

    def _set_hover_line(self, line):
        if line == self._hover_line:
            return
        self._hover_line = line
        self.text.tag_remove("hover", "1.0", "end")
        if line is not None:
            self.text.tag_add("hover", "%d.0" % line, "%d.end" % line)

    def _update_count(self):
        on_cnt = off_cnt = 0
        for rel in self._disp:
            if not rel:
                continue
            if self.checked.get(rel, True):
                on_cnt += 1
            else:
                off_cnt += 1
        if on_cnt or off_cnt:
            self.count_lbl.configure(
                text=u"已勾选 %d / %d" % (on_cnt, on_cnt + off_cnt))
        else:
            self.count_lbl.configure(text=u"")

    # ---------- 交互 ----------
    def _line_of_y(self, y):
        """y 坐标 -> 行号（1 起）；空白处返回 None。"""
        try:
            n = int(self.text.index("@0,%d" % y).split(".")[0])
        except tk.TclError:
            return None
        return n if 1 <= n <= len(self._rows) else None

    def _zone_of(self, line):
        """行号 -> (勾选框起, 勾选框止, 箭头起, 箭头止) 的像素范围。

        勾选框命中区向两侧放宽几像素（大字形比字符格宽），箭头区取
        箭头字形到勾选框左沿之间；两区不重叠，勾选框优先。
        """
        row = self._rows[line - 1]
        ind = row["depth"] * len(INDENT)
        try:
            ab = self.text.bbox("%d.%d" % (line, ind))
            cb = self.text.bbox("%d.%d" % (line, ind + 2))
        except tk.TclError:
            return None
        if ab is None or cb is None:
            return None
        return (cb[0] - 3, cb[0] + cb[2] + 4, ab[0] - 3, cb[0] - 3)

    def _select_line(self, line):
        """选中行：只做高亮（勾选只能在勾选框/空格里改，用户要求）。"""
        if not (1 <= line <= len(self._rows)):
            return
        self.sel_rel = self._rows[line - 1]["rel"]
        self._paint_cur()

    def _see_line(self, line):
        try:
            self.text.see("%d.0" % line)    # 保证当前行留在可视区
        except tk.TclError:
            pass

    def _on_click(self, event):
        """单击行内任意位置选中该行；点勾选框翻转勾选、点箭头展开/收起。"""
        if self._skip_release:
            self._skip_release = False   # 双击引发的第二次 release，忽略
            return
        line = self._line_of_y(event.y)
        if line is None or self._rows[line - 1]["rel"] is None:
            return
        try:
            self.text.focus_set()        # 点过列表后键盘（上下/空格）立即可用
        except tk.TclError:
            pass
        self._select_line(line)
        rel = self._rows[line - 1]["rel"]
        z = self._zone_of(line)
        if z is None:
            return
        if z[0] <= event.x <= z[1]:
            self.set_checked(rel, not self.checked.get(rel, True))
        elif z[2] <= event.x <= z[3] and self._kind.get(rel) == "dir":
            self._toggle_expand(rel)

    def _on_dblclick(self, event):
        """双击行：目录展开/收起（双击勾选框只当普通单击，见 _on_click）。"""
        self._skip_release = True
        line = self._line_of_y(event.y)
        if line is None or self._rows[line - 1]["rel"] is None:
            return
        z = self._zone_of(line)
        if z is not None and z[0] <= event.x <= z[1]:
            return
        rel = self._rows[line - 1]["rel"]
        if self._kind.get(rel) == "dir":
            self._toggle_expand(rel)

    def _on_motion(self, event):
        """鼠标移入某行：淡高亮提示“这行能点”（光标保持系统原生样式）。"""
        self._hover_y = event.y
        line = self._line_of_y(event.y)
        if line is not None and self._rows[line - 1]["rel"] is None:
            line = None                  # 占位行不高亮
        self._set_hover_line(line)

    def _on_leave(self, _event):
        """鼠标移出列表：撤掉悬停高亮。"""
        self._hover_y = None
        self._set_hover_line(None)

    def _move_sel(self, delta, first=False, last=False):
        """键盘移动当前行（↑/↓/PgUp/PgDn/Home/End）；返回 "break" 吃掉按键。

        只在真实行之间移动（跳过“加载中…”占位行），越界停在两端。
        """
        if not self._selectable:
            return "break"
        if first:
            i = 0
        elif last:
            i = len(self._selectable) - 1
        else:
            cur = None
            line = self._line_of_rel(self.sel_rel)
            if line is not None and (line - 1) in self._selectable:
                cur = self._selectable.index(line - 1)
            if cur is None:
                i = 0 if delta > 0 else len(self._selectable) - 1
            else:
                i = max(0, min(len(self._selectable) - 1, cur + delta))
        self._select_line(self._selectable[i] + 1)
        self._see_line(self._selectable[i] + 1)
        return "break"

    def _toggle_current(self):
        """空格：翻转当前行的勾选（等价于点该行勾选框）。

        **不移动列表**（用户要求）：原先 set_checked 整表重绘把列表弹回
        顶部、这里再 see() 把当前行拉回视线，观感就是“空格勾选时列表
        自动滚动”；改成增量重写后两处都不需要了。
        """
        rel = self.sel_rel
        if rel is None:
            return "break"
        self.set_checked(rel, not self.checked.get(rel, True))
        return "break"

    def _toggle_expand(self, rel):
        """展开/收起目录；展开时按需发起懒加载。"""
        if rel in self._expanded:
            self._expanded.discard(rel)
        else:
            self._expanded.add(rel)
            self._ensure_loaded(rel)
        self._render()

    def _collapse_current(self):
        """←：展开的目录先收起；否则跳到父目录（传统树操作）。"""
        rel = self.sel_rel
        if rel is None:
            return "break"
        if self._kind.get(rel) == "dir" and rel in self._expanded:
            self._expanded.discard(rel)
            self._render()
            return "break"
        if rel:
            parent = rel.rsplit("/", 1)[0] if "/" in rel else u""
            line = self._line_of_rel(parent)
            if line is not None:
                self._select_line(line)
                self._see_line(line)
        return "break"

    def _expand_current(self):
        """→：未展开的目录先展开；已展开的跳到第一个子级。"""
        rel = self.sel_rel
        if rel is None or self._kind.get(rel) != "dir":
            return "break"
        if rel not in self._expanded:
            self._expanded.add(rel)
            self._ensure_loaded(rel)
            self._render()
        else:
            kids = self._kids.get(rel) or []
            line = self._line_of_rel(kids[0]) if kids else None
            if line is not None:
                self._select_line(line)
                self._see_line(line)
        return "break"

    def _set_msg(self, text):
        try:
            self.msg.configure(text=text)
        except tk.TclError:
            pass

    def _browse(self):
        d = App.browse_dir(self, self.dst_var.get())
        if d:
            self.dst_var.set(d)
            self._dst_changed()          # 选完目录立即校验（不等防抖）

    # ---------- 勾选 ----------
    def set_checked(self, rel, on):
        """设置某项的勾选，并向下传播到已加载的子孙（目录勾选语义）。

        只重写受影响的那几行、**不整表重绘**（翻转勾选时列表保持不动，
        原因见 _refresh_rows 的说明）。
        """
        if not rel:
            self.checked[u""] = True     # 检出根不可取消
            return
        self._touched = True             # 用户手改过：后台读数回来别覆盖
        on = bool(on)
        changed = []
        if self.checked.get(rel, True) != on:
            changed.append(rel)
        self.checked[rel] = on
        for r in [r for r in self.checked if r.startswith(rel + "/")]:
            if self.checked.get(r, True) != on:
                changed.append(r)
            self.checked[r] = on
        if on:
            self._ensure_ancestors(rel, changed)
        self._refresh_rows(changed)

    def _ensure_ancestors(self, rel, changed=None):
        """把 rel 的所有祖先补齐勾选；changed 传入时顺带收集“原来未勾选”
        的祖先（供增量重绘；_invert 全表重绘，不需要收集）。"""
        parts = rel.split("/")
        for i in range(len(parts)):
            a = u"/".join(parts[:i])
            if changed is not None and a and not self.checked.get(a, True):
                changed.append(a)
            self.checked[a] = True

    def _set_all(self, on):
        self._touched = True
        on = bool(on)
        for r in list(self.checked):
            if r:
                self.checked[r] = on
        self.checked[u""] = True
        self._render()

    def _invert(self):
        self._touched = True
        for r in list(self.checked):
            if r:
                self.checked[r] = not self.checked.get(r, True)
        for r in [r for r, v in self.checked.items() if r and v]:
            self._ensure_ancestors(r)
        self.checked[u""] = True
        self._render()

    # ---------- 确认 ----------
    def _ok(self):
        dst = self.dst_var.get().strip()
        if not dst:
            self._set_msg(u"请填写本地目录")
            return
        # 本地状态在目录变化或失焦时已重读过就直接复用（只跑 svn info 的
        # 快速判定）；防抖还没跑时在这里补一次，同样不跑慢的 svn status
        if dst != self._state_dst:
            self.local = self._read_local(dst)
            self._state_dst = dst
            self._have = None
            self._stat_pending = False
            self._touched = False
            if self.local.get("kind") == "same":
                self._start_stat(dst)
                self._set_msg(u"正在读取本地排除状态，请稍候…")
                return
        kind = self.local.get("kind")
        if kind == "file":
            self._set_msg(u"本地路径已被同名文件占用，请更换本地目录")
            return
        if kind == "other":
            self._set_msg(u"本地目录已是其他来源的工作副本，不能更新")
            return
        if kind == "unknown":
            self._set_msg(u"本地目录已存在且不是 SVN 工作副本，请更换本地目录")
            return
        if kind == "same" and self._stat_pending:
            # 排除状态还没读完：先别放行（restore 清单要按它算）
            self._set_msg(u"正在读取本地排除状态，请稍候…")
            return
        restore = []
        have = self.local.get("have")
        if kind == "same" and have is not None:
            # 勾选了、但本地没有（此前被排除）的目录/文件 -> 更新时拉回
            restore = topmost([r for r, on in self.checked.items()
                               if r and on and r not in have])
        self.result = {"url": self.url, "dst": dst,
                       "excludes": self.excludes(), "restore": restore,
                       "mode": "update" if kind == "same" else "download"}
        self.destroy()


# ============================================================
# 四、仓库浏览器窗口
# ============================================================

class CatView(tk.Toplevel):
    """文件内容窗口（只读、非模态）：仓库浏览器“查看内容”用。

    内容由 RepoBrowser 的 LsWorker 后台 `svn cat` 读取（见 request_cat），
    读取完成前先显示“正在读取…”。同一时间只开一个窗口，再次查看其它
    文件时由 start() 刷新标题与内容。
    """

    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.url = u""
        self._raw = None          # svn cat 原始字节（编码菜单重新解码用）
        self._encoding = None     # None=自动识别；否则是手动选择的编码名
        self.configure(bg=core.APP_BG)       # 与主窗口同一套平面底色
        self.title(u"文件内容 · " + core.APP_TITLE)
        self.geometry("%dx560" % theme.WINDOW_W)
        self.minsize(480, 300)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _e: self.destroy())

        head = tk.Frame(self)
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        self.path_lbl = tk.Label(head, anchor="w", fg=core.MUTED)
        self.path_lbl.pack(side="left", fill="x", expand=True)

        # 布局用 grid（与登录凭据窗口同一个坑）：整体请求高度超过窗口时，
        # 收缩的是正文行，底部状态栏与“关闭”按钮不会被挤出可视区
        body = tk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        # tk.Text 不吃 ttk 样式：逐个 surface 刷成白面板（见 AGENTS 主题规则）
        self.text = theme.surface(
            tk.Text(body, state="disabled", wrap="none", undo=False),
            mono=True)
        ysb = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        xsb = ttk.Scrollbar(body, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        self.text.tag_configure("muted", foreground=core.MUTED)
        # 禁用态 Text 点击不会自动聚焦，快捷键/右键复制统一由 dialogs 助手补
        # （内置差异窗口用同一套逻辑，见 dialogs.install_text_copy）
        self.menu = dialogs.install_text_copy(self.text, self)

        bar = tk.Frame(self)
        bar.grid(row=2, column=0, sticky="ew", padx=12, pady=(4, 10))
        self.status = tk.Label(bar, text=u"", fg=core.MUTED, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        ttk.Button(bar, text=u"关闭", command=self.destroy,
                   width=theme.BTN_W).pack(side="right")
        # 自动识别偶尔会判断错（GB18030 与 Big5 的字节范围有重叠），
        # 给一个手动切换编码的入口；默认“自动识别”。
        self.enc_btn = ttk.Button(bar, text=u"编码", command=self._show_enc_menu,
                                  width=theme.BTN_W)
        self.enc_btn.pack(side="right", padx=(0, 6))
        self.enc_menu = theme.make_menu(self)
        self.enc_menu.add_command(label=u"自动识别",
                                  command=lambda: self._set_encoding(None))
        self.enc_menu.add_separator()
        for enc, label in CAT_ENCODING_CHOICES:
            self.enc_menu.add_command(
                label=label, command=lambda e=enc: self._set_encoding(e))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        theme.center_on_parent(self, browser)

    # ---------- 内容 ----------
    def start(self, url, name):
        """切到目标文件：清空内容并显示“正在读取…”。"""
        self.url = url or u""
        self._raw = None
        self._encoding = None
        self.title(u"文件内容 · %s" % (name or self.url or core.APP_TITLE))
        self.path_lbl.configure(text=core.decode_svn_url(self.url))
        self.status.configure(text=u"正在读取…")
        self._fill(u"")
        try:
            self.text.focus_set()       # 打开/切换文件后快捷键立即可用
        except tk.TclError:
            pass

    def show_content(self, data):
        """展示 `svn cat` 的原始字节（也兼容旧的文本行列表）。"""
        self._raw = data
        self._encoding = None
        self._render()

    def show_error(self, msg):
        self._raw = None
        self._encoding = None
        self._fill(u"")
        self.status.configure(text=u"读取失败: %s" % (msg or u"未知错误"))

    def _render(self):
        if self._raw is None:          # 还在读取 / 读取失败：别把提示清成“共 0 行”
            return
        text, note, binary = cat_display(self._raw, self._encoding)
        if binary:
            self._fill(u"（二进制文件，不显示内容）", "muted")
        else:
            self._fill(text)
        self.status.configure(text=note)

    def _show_enc_menu(self):
        x = self.enc_btn.winfo_rootx()
        y = self.enc_btn.winfo_rooty() + self.enc_btn.winfo_height()
        try:
            self.enc_menu.tk_popup(x, y)
        except tk.TclError:
            for fn in (self.enc_menu.unpost, self.enc_menu.grab_release):
                try:
                    fn()
                except tk.TclError:
                    pass

    def _set_encoding(self, enc):
        self._encoding = enc or None
        self._render()

    def _fill(self, text, tag=None):
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        if text:
            if tag:
                t.insert("end", text, tag)
            else:
                t.insert("end", text)
        t.configure(state="disabled")


LIST_ICON_W = 16
# 图标与文本之间的透明间隙（Treeview 没有单元格 padding 选项，只能把
# 图标本身画宽一点，右侧留白）
LIST_ICON_GAP = 5


def _make_icon(master, kind):
    """右侧列表/左侧目录树用的扁平图标（直接画出来，不依赖外部图片资源）。

    工程没有资源目录，Tk 8.6 也不保证有彩色 emoji 字体；用 PhotoImage
    画两个简单色块图标，随主题配色（琥珀色文件夹 / 灰蓝文件）。
    宽度 = 图标 16px + 右侧透明间隙，图标与文件名之间就不会贴在一起。
    """
    img = tk.PhotoImage(master=master, width=LIST_ICON_W + LIST_ICON_GAP,
                        height=LIST_ICON_W)
    if kind == "dir":
        img.put("#d97706", to=(1, 4, 7, 7))       # 文件夹标签
        img.put("#f59e0b", to=(1, 6, 15, 14))     # 文件夹底
        img.put("#fbbf24", to=(2, 7, 14, 13))     # 高光面
    else:
        img.put("#94a3b8", to=(3, 1, 14, 15))     # 页面外框
        img.put("#ffffff", to=(4, 2, 13, 14))     # 页面
        img.put("#cbd5e1", to=(5, 5, 12, 6))      # 文本行
        img.put("#cbd5e1", to=(5, 8, 12, 9))
        img.put("#cbd5e1", to=(5, 11, 10, 12))
    return img


class RepoBrowser(tk.Toplevel):
    """仓库浏览器：左侧目录树（懒加载），右侧当前目录的条目列表。

    iid 一律用完整 URL（未编码的相对路径另存 _url_rel），因此树节点、
    右键菜单、复制地址之间不需要互相换算。
    """

    def __init__(self, app, initial_url=""):
        super().__init__(app.root)
        self.app = app
        self.store = app.store
        self.base = u""
        self._url_rel = {}        # 完整 URL -> 相对根的未编码路径
        self._node_items = {}     # 完整 URL -> 条目列表（缓存）
        self._inflight = set()    # 正在读取的 (kind, url)
        self._auto_open = set()   # 读取完成后自动展开的 URL
        self._list_kind = {}      # 右侧行 iid -> kind
        self._menu_url = None
        self._menu_kind = None
        self._collections = set()  # 已验证为仓库集合根的地址（normalize 后）
        self.checkout = None      # 当前打开的 CheckoutSelect
        self.cat_win = None       # “查看内容”窗口（复用一个）
        self._closed = False
        self._recent = core.normalize_recent_urls(
            self.store.settings.get("recent_repo_urls") or [])
        # 用户点“转到”（含回车/下拉选历史）后等待读取成功的地址；
        # 只有它读取成功才写入最近浏览，树中普通浏览/刷新都不写。
        self._recent_pending = None
        self.worker = LsWorker(self.store.settings.get("trust_server_cert",
                                                       False))
        self.worker.start()
        self._build(initial_url)
        self.protocol("WM_DELETE_WINDOW", self.shutdown)
        self.bind("<Escape>", lambda e: self.shutdown())
        self.after(80, self._poll)
        if initial_url:
            self.after(20, self._go)

    # ---------- 界面 ----------
    def _build(self, initial_url):
        self.title(u"仓库浏览 · " + core.APP_TITLE)
        self.geometry("%dx600" % theme.WINDOW_W)
        self.minsize(700, 440)

        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(top, text=u"地址").pack(side="left")
        self.url_var = tk.StringVar(value=initial_url or "")
        # 可编辑下拉框：既接受手输地址，也能从“最近浏览”里快速选
        self.url_box = ttk.Combobox(top, textvariable=self.url_var,
                                    values=list(self._recent))
        self.url_box.pack(side="left", fill="x", expand=True, padx=6)
        self.url_box.bind("<Return>", lambda ev: self._go())
        self.url_box.bind("<<ComboboxSelected>>", self._on_recent_selected)
        self.url_box.bind("<Button-3>", self._on_url_menu)
        self.url_box.configure(postcommand=self._fill_recent)
        ttk.Button(top, text=u"转到", command=self._go,
                   width=theme.BTN_W).pack(side="left")
        ttk.Button(top, text=u"刷新", command=self._refresh,
                   width=theme.BTN_W).pack(side="left", padx=(6, 0))
        ttk.Button(top, text=u"检出…", command=self._checkout_selected,
                   width=theme.BTN_W,
                   style=theme.ACCENT_STYLE).pack(
            side="left", padx=(6, 0))

        pan = tk.PanedWindow(self, orient="horizontal", sashwidth=5)
        pan.pack(fill="both", expand=True, padx=10, pady=4)
        left = tk.Frame(pan)
        right = tk.Frame(pan)
        pan.add(left, width=300, minsize=220)
        pan.add(right, minsize=320)

        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        tsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        tsb.grid(row=0, column=1, sticky="ns")
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        cols = ("suffix", "rev", "author", "size", "date")
        # 名称用 Treeview 的树列（#0）：自带缩进（名称不再紧贴左边），
        # 也才能显示条目图标（headings 模式的行图标不会渲染）；列表本身
        # 是平的，没有子节点，不会出现展开箭头。
        self.lst = ttk.Treeview(right, columns=cols, show="tree headings",
                                selectmode="browse")
        self.lst.heading("#0", text=u"名称", anchor="w")
        self.lst.column("#0", width=210, anchor="w")
        # 所有列（含表头）一律左对齐（用户要求）
        for key, title, width in (("suffix", u"后缀", 56),
                                  ("rev", u"版本", 52),
                                  ("author", u"作者", 82),
                                  ("size", u"大小", 66),
                                  ("date", u"日期", 118)):
            self.lst.heading(key, text=title, anchor="w")
            self.lst.column(key, width=width, anchor="w")
        self._icon_dir = _make_icon(right, "dir")
        self._icon_file = _make_icon(right, "file")
        lsb = ttk.Scrollbar(right, orient="vertical", command=self.lst.yview)
        self.lst.configure(yscrollcommand=lsb.set)
        self.lst.grid(row=0, column=0, sticky="nsew")
        lsb.grid(row=0, column=1, sticky="ns")
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        bar = tk.Frame(self)
        bar.pack(fill="x", padx=10, pady=(0, 8))
        self.status = tk.Label(bar, text=u"输入 SVN 地址后点击“转到”",
                               fg=core.MUTED, anchor="w")
        self.status.pack(side="left")
        # 浏览与检出都要过证书校验，信任开关放这里（与主界面共用同一配置项）
        self.trust_var = tk.BooleanVar(value=bool(
            self.store.settings.get("trust_server_cert", False)))
        self.trust_check = theme.CheckBox(
            bar, text=u"信任自签名证书", variable=self.trust_var,
            command=self._trust_changed)
        self.trust_check.pack(side="right")

        # 右键菜单统一走 theme.make_menu（白底扁平 + 强调色悬停；tk.Menu
        # 默认的系统灰底立体边样式与界面很不协调，用户反馈过）
        self.menu_dir = theme.make_menu(self)
        self.menu_dir.add_command(
            label=u"检出到…",
            command=lambda: self._do_checkout(self._take_menu_url()))
        self.menu_dir.add_command(
            label=u"导出到…",
            command=lambda: self._do_export(self._take_menu_url()))
        self.menu_dir.add_command(
            label=u"刷新此节点",
            command=lambda: self._do_refresh(self._take_menu_url()))
        self.menu_dir.add_command(
            label=u"查看提交记录",
            command=lambda: self._view_log(self._take_menu_url()))
        self.menu_dir.add_command(
            label=u"复制地址",
            command=lambda: self._copy_url(self._take_menu_url()))
        self.menu_file = theme.make_menu(self)
        self.menu_file.add_command(
            label=u"查看内容",
            command=lambda: self._cat_url(self._take_menu_url()))
        self.menu_file.add_command(
            label=u"查看提交记录",
            command=lambda: self._view_log(self._take_menu_url()))
        self.menu_file.add_command(
            label=u"导出到…",
            command=lambda: self._do_export(self._take_menu_url()))
        self.menu_file.add_command(
            label=u"复制地址",
            command=lambda: self._copy_url(self._take_menu_url()))
        # 地址栏右键：只清最近浏览记录，不动配置里的 SVN 地址/工作副本
        self.menu_url = theme.make_menu(self)
        self.menu_url.add_command(label=u"清除最近记录",
                                  command=self._clear_recent)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.tree.bind("<Button-3>", self._on_tree_menu)
        self.lst.bind("<Button-3>", self._on_list_menu)
        self.lst.bind("<Double-Button-1>", self._on_list_dbl)
        dialogs.install_edit_shortcuts(self)
        # 内容建完再定位：基于父窗口（主界面）居中（用户要求）
        theme.center_on_parent(self)

    # ---------- 导航 ----------
    def _go(self):
        url = self.url_var.get().strip()
        if not url:
            self._set_status(u"请先填写 SVN 地址")
            return
        self.base = url
        self._url_rel = {url: u""}
        self._node_items = {}
        self._auto_open = set([url])
        self._menu_url = None
        self._recent_pending = core.normalize_svn_url(url) or None
        for i in self.tree.get_children():
            self.tree.delete(i)
        for i in self.lst.get_children():
            self.lst.delete(i)
        is_collection = core.normalize_svn_url(url) in self._collections
        name = core.decode_svn_url(url).rstrip("/").rsplit("/", 1)[-1]
        self.tree.insert("", "end", iid=url,
                         text=COLLECTION_TITLE if is_collection
                         else (name or url),
                         open=True, image=self._icon_dir)
        self.tree.insert(url, "end", text=LOADING)
        self.tree.selection_set(url)
        self.tree.focus(url)
        self._set_status(core.decode_svn_url(url))
        if is_collection:
            self.request_collection(url)
        else:
            self.request(url, "node")

    def _fill_recent(self):
        """下拉前刷新历史值并给列表刷当前皮肤。"""
        try:
            self.url_box.configure(values=list(self._recent))
        except tk.TclError:
            return
        theme.style_combobox_popdown(self.url_box)

    def _on_recent_selected(self, _event=None):
        """从最近浏览下拉选中一项：直接跳转（等同回车）。"""
        self._go()

    def _record_recent(self, url):
        """把地址记入最近浏览并落盘（仅由“转到”成功后的路径调用）。"""
        url = core.normalize_svn_url(url)
        if not url:
            return
        recent = core.push_recent_url(self._recent, url)
        if recent == self._recent:
            return
        self._recent = recent
        try:
            self.url_box.configure(values=list(recent))
        except tk.TclError:
            pass
        try:
            self.store.set_option("recent_repo_urls", list(recent))
        except Exception as e:
            self._set_status(u"保存最近浏览地址失败: %s" % e)

    def _record_go_recent(self, url):
        """“转到”的目标读取成功后才记历史。

        地址栏的转到/回车、下拉选历史都会走 `_go` 并登记待记地址；
        树中展开、双击目录、刷新等普通浏览不登记，自然也不落盘。
        失败时由调用方清掉 pending，之后即使同样地址被普通浏览成功
        也不会补记。
        """
        pending = self._recent_pending
        if pending is None:
            return
        if core.normalize_svn_url(url) != pending:
            return
        self._recent_pending = None
        self._record_recent(url)

    def _drop_go_recent(self, url):
        """“转到”的目标读取失败：作废待记地址（普通浏览不补记）。"""
        pending = self._recent_pending
        if pending is not None and core.normalize_svn_url(url) == pending:
            self._recent_pending = None

    def _on_url_menu(self, event):
        """地址栏右键菜单：无历史时“清除最近记录”置灰。"""
        try:
            self.menu_url.entryconfigure(
                0, state="normal" if self._recent else "disabled")
        except tk.TclError:
            return
        self._popup(self.menu_url, event)

    def _clear_recent(self):
        if not self._recent:
            return
        self._recent = []
        try:
            self.url_box.configure(values=[])
        except tk.TclError:
            pass
        try:
            self.store.set_option("recent_repo_urls", [])
        except Exception as e:
            self._set_status(u"保存最近浏览地址失败: %s" % e)
            return
        self._set_status(u"已清除最近浏览记录")

    def _current_url(self):
        sel = self.tree.selection()
        if sel:
            return sel[0]
        return self.base

    def _refresh(self):
        """刷新当前选中的目录节点。"""
        self._do_refresh(self._current_url())

    def _is_collection(self, url):
        """该地址是否已确认是仓库集合根（不是具体仓库）。"""
        return core.normalize_svn_url(url) in self._collections

    def _do_refresh(self, url):
        if not url:
            return
        for k in [k for k in self._node_items
                  if k == url or k.startswith(url + "/")]:
            del self._node_items[k]           # 缓存作废，重新读取
        if self._is_collection(url):
            self._set_status(u"正在刷新仓库列表 %s …"
                             % core.decode_svn_url(url))
            self.request_collection(url)
            return
        self._set_status(u"正在刷新 %s …" % core.decode_svn_url(url))
        self.request(url, "node")

    def _checkout_selected(self):
        self._do_checkout(self._current_url())

    def _do_checkout(self, url):
        if not url:
            return
        if self._is_collection(url):
            self._set_status(
                u"仓库列表不是具体仓库，不能检出；请先选择其中的仓库")
            return
        if self.checkout is not None:
            try:
                if self.checkout.winfo_exists():
                    self.checkout.deiconify()
                    self.checkout.lift()
                    return
            except tk.TclError:
                pass
        co = CheckoutSelect(self, url, self._node_items.get(url))
        self.checkout = co
        try:
            result = co.run()
        finally:
            self.checkout = None
        if result:
            self.app._checkout_from_browser(
                result["url"], result["dst"], result["excludes"],
                result.get("restore") or [],
                result.get("mode") or "download")

    def _do_export(self, url):
        """右键“导出到…”：`svn export` 一份不含 .svn 的干净副本。

        先选目标父目录（系统目录选择框），导出到“父目录/节点名”；
        目标已存在时先确认再带 `--force`（svn 对已存在目标默认拒绝并报
        E155000，--force 只覆盖同名文件，目标里的其他文件不动，实测 1.10）。
        导出走主界面 Hub 的单任务链路（可取消、有运行日志），
        不像检出那样接管界面——仓库浏览器保持打开，可接着导出下一个。
        """
        if not url:
            return
        if self._is_collection(url):
            self._set_status(
                u"仓库列表不是具体仓库，不能导出；请先选择其中的仓库")
            return
        name = core.decode_svn_url(url).rstrip("/").rsplit("/", 1)[-1]
        if not name:
            self._set_status(u"无法从地址推断导出名称: %s"
                             % core.decode_svn_url(url))
            return
        parent = App.browse_dir(self, self.store.settings.get("dst") or "")
        if not parent:
            return
        target = os.path.join(parent, name)
        force = False
        if os.path.exists(target):
            if not dialogs.ask_confirm(
                    self, u"确认导出",
                    u"目标已存在：\n%s\n\n继续导出将覆盖其中的同名文件"
                    u"（目标里的其他文件不受影响）。" % target,
                    u"覆盖导出"):
                return
            force = True
        if self.app._run_start("export", {"url": url, "dst": target,
                                          "force": force}):
            self._set_status(u"已开始导出到 %s" % target)

    def _cat_url(self, url):
        """右键“查看内容”/双击文件：后台读取该文件在 HEAD 的内容。

        与目录读取共用 LsWorker 的任务队列（tag ("cat", url)），窗口先
        显示“正在读取…”，结果到了由 _on_cat 填内容；同一时间只开一个
        窗口，再次查看其它文件时刷新内容。
        """
        if not url:
            return
        name = core.decode_svn_url(url).rstrip("/").rsplit("/", 1)[-1]
        win = self.cat_win
        alive = False
        if win is not None:
            try:
                alive = bool(win.winfo_exists())
            except tk.TclError:
                alive = False
        if not alive:
            win = CatView(self)
            self.cat_win = win
        else:
            win.deiconify()
            win.lift()
        win.start(url, name)
        self.request_cat(url)

    def request_cat(self, url):
        """排队一个 `svn cat`（查看内容用；结果路由见 _handle_event）。"""
        tag = ("cat", url)
        if tag in self._inflight:
            return
        self._inflight.add(tag)
        self.worker.request(tag, ["svn", "cat", url])

    def _on_cat(self, url, ok, payload):
        win = self.cat_win
        if win is None:
            return
        try:
            if not win.winfo_exists() or win.url != url:
                return                       # 窗口已换目标：旧结果作废
        except tk.TclError:
            return
        if ok:
            win.show_content(payload)
            self._set_status(u"已读取 %s" % core.decode_svn_url(url))
        else:
            win.show_error(payload or u"")

    def _copy_url(self, url):
        if not url:
            return
        # 复制给人看/用的地址：不要把 SVN 的百分号编码（%E4%B8%AD…）带出去，
        # 状态栏提示也一直用解码后的文本
        url = core.decode_svn_url(url)
        try:
            self.clipboard_clear()
            self.clipboard_append(url)
            self._set_status(u"已复制地址: " + url)
        except tk.TclError:
            pass

    def _view_log(self, url):
        """右键“查看提交记录”：提交历史窗口切到选中路径的地址目标。

        走主界面的提交历史窗口（App._open_log_view），窗口已开时切目标
        并自动重读；读取与对比都经主界面 Hub，凭据弹窗等行为与主界面
        按钮打开时完全一致。
        """
        if not url:
            return
        if self._is_collection(url):
            self._set_status(
                u"仓库列表不是具体仓库，不能查看提交记录；请先选择其中的仓库")
            return
        self.app._open_log_view(url=url)

    def _take_menu_url(self):
        url = self._menu_url
        self._menu_url = None
        return url

    # ---------- 右键菜单 ----------
    def _configure_dir_menu(self, url):
        """集合根不是具体仓库：检出/导出/提交记录三项置灰。"""
        state = "disabled" if self._is_collection(url) else "normal"
        blocked = (u"检出到…", u"导出到…", u"查看提交记录")
        try:
            last = int(self.menu_dir.index("end"))
        except (tk.TclError, TypeError, ValueError):
            return
        for idx in range(last + 1):
            try:
                if self.menu_dir.entrycget(idx, "label") in blocked:
                    self.menu_dir.entryconfigure(idx, state=state)
            except tk.TclError:
                pass

    def _on_tree_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self._menu_url = iid
        self._menu_kind = "dir"
        self._configure_dir_menu(iid)
        self._popup(self.menu_dir, event)

    def _on_list_menu(self, event):
        iid = self.lst.identify_row(event.y)
        if not iid:
            # 空白处右键：作用对象是右侧列表当前所属的目录（即树里选中的
            # 节点），菜单与左树右键同一套——用户要求空白处也能
            # “查看提交记录”，顺手带上检出/导出/刷新/复制地址
            url = self._current_url()
            if not url:
                return
            self._menu_url = url
            self._menu_kind = "dir"
            self._configure_dir_menu(url)
            self._popup(self.menu_dir, event)
            return
        self.lst.selection_set(iid)
        self._menu_url = iid
        self._menu_kind = self._list_kind.get(iid, "file")
        menu = self.menu_dir if self._menu_kind == "dir" else self.menu_file
        if menu is self.menu_dir:
            self._configure_dir_menu(iid)
        self._popup(menu, event)

    def _popup(self, menu, event):
        """弹出右键菜单：点菜单外任意处即可收起。

        tk_popup 返回后**不能**立刻 grab_release——菜单持有的抓取正是
        “点到菜单外 -> 事件转给菜单 -> Tk 自动收起”的唯一机制，提前放掉
        后就再没有收起的路径（Tk 8.6.9 实测：右键后不选任何项，菜单会一直
        悬着关不掉）。菜单被点选或按 Esc 收起时 Tk 自己会放掉抓取，
        打开模态对话框（检出到…）的 grab 也不会被抢走。
        这里只兜底同步异常（例如抓取失败），把已挂出的菜单收掉。
        """
        try:
            menu.tk_popup(event.x_root, event.y_root)
        except tk.TclError:
            for fn in (menu.unpost, menu.grab_release):
                try:
                    fn()
                except tk.TclError:
                    pass

    # ---------- 树 / 列表交互 ----------
    def _on_tree_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        url = sel[0]
        self._set_status(core.decode_svn_url(url))
        if url in self._node_items:
            self._render_list(url)
        elif self._is_collection(url):
            self.request_collection(url)
        else:
            self.request(url, "node")

    def _on_tree_open(self, event):
        iid = self.tree.identify_row(event.y) or self.tree.focus()
        if iid:
            self._ensure_loaded(iid)

    def _on_list_dbl(self, event):
        iid = self.lst.identify_row(event.y)
        if not iid:
            return
        if self._list_kind.get(iid) != "dir":
            self._cat_url(iid)            # 文件：双击查看内容（用户要求）
            return
        if not self.tree.exists(iid):
            self._set_status(u"该目录尚未加载，请先展开上级目录")
            return
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.tree.see(iid)
        self._auto_open.add(iid)
        self._ensure_loaded(iid)
        try:
            self.tree.item(iid, open=True)
        except tk.TclError:
            pass

    def _ensure_loaded(self, url):
        if not url or url in self._node_items:
            return
        if self._is_collection(url):
            self.request_collection(url)
        else:
            self.request(url, "node")

    # ---------- 读取与渲染 ----------
    def request(self, url, kind):
        tag = (kind, url)
        if tag in self._inflight:
            return
        self._inflight.add(tag)
        self.worker.request(tag, ["svn", "list", "--xml",
                                  "--depth=immediates", url])

    def request_collection(self, url):
        """排队读取仓库集合根索引（HTTP GET，在 LsWorker 后台线程执行）。"""
        tag = ("collection", url)
        if tag in self._inflight:
            return
        self._inflight.add(tag)
        self.worker.request(tag, None)

    def request_stat(self, dst):
        """后台读取本地排除状态（检出对话框用）。

        svn status 在大工作副本上很慢，绝不能在界面线程里同步跑——
        否则打开检出/更新窗口会卡住（见 CheckoutSelect._start_stat）。
        """
        p = os.path.abspath(os.path.expanduser(str(dst or u"")))
        self.worker.request(("stat", str(dst)), ["svn", "status", "-v",
                                                 "--xml", p])

    def _render_list(self, url):
        for i in self.lst.get_children():
            self.lst.delete(i)
        self._list_kind = {}
        for it in self._node_items.get(url, []):
            child = it.get("url") or core.join_url(url, it["name"])
            self._list_kind[child] = it["kind"]
            is_dir = it["kind"] == "dir"
            self.lst.insert(
                "", "end", iid=child, text=it["name"],
                image=self._icon_dir if is_dir else self._icon_file,
                values=(u"" if is_dir else file_suffix(it["name"]),
                        it.get("rev") or "-", it.get("author") or "-",
                        u"" if is_dir else fmt_size(it.get("size")),
                        it.get("date") or "-"))

    def _apply_node_items(self, url, items):
        """把一批目录条目铺到左树（文件仍在右侧列表）。"""
        if not self.tree.exists(url):
            return
        for c in self.tree.get_children(url):
            self.tree.delete(c)
        rel = self._url_rel.get(url, u"")
        for it in items:
            if it.get("kind") != "dir":
                continue                      # 树只放目录，文件见右侧列表
            child = it.get("url") or core.join_url(url, it["name"])
            if not child:
                continue
            self._url_rel[child] = (rel + "/" + it["name"]) if rel else it["name"]
            self.tree.insert(url, "end", iid=child, text=it["name"],
                             image=self._icon_dir)
            self.tree.insert(child, "end", text=LOADING)
        if url in self._auto_open:
            self._auto_open.discard(url)
            try:
                self.tree.item(url, open=True)
            except tk.TclError:
                pass
        sel = self.tree.selection()
        if sel and sel[0] == url:
            self._render_list(url)

    def _on_node_ls(self, url, ok, payload):
        if not ok:
            # 集合根不是仓库：svn list 只能报“XML 解析失败”。这时改走
            # HTTP 索引（在后台线程），确认是集合根后再展示仓库列表。
            if core.looks_like_collection_error(payload):
                self._set_status(u"正在读取仓库列表…")
                self.request_collection(url)
                return
            self._drop_go_recent(url)
            if u"E175013" in (payload or u""):
                self._set_status(
                    u"没有权限读取该地址（服务端 403）。如果这是仓库根，"
                    u"请尝试其下的 trunk 等子目录。")
            else:
                self._set_status(u"读取失败: %s" % (payload or u""))
            self._drop_placeholder(url)
            return
        try:
            items = parse_lines(payload)
        except Exception as e:
            self._drop_go_recent(url)
            self._set_status(u"读取失败: %s" % e)
            return
        self._node_items[url] = items
        self._apply_node_items(url, items)
        self._record_go_recent(url)

    def _on_collection(self, url, ok, payload):
        """集合根索引读取完成：把仓库列表铺到左树/右侧列表。"""
        if not self.tree.exists(url):
            self._drop_go_recent(url)
            return
        if not ok:
            self._collections.discard(core.normalize_svn_url(url))
            self._drop_go_recent(url)
            self._set_status(u"读取仓库列表失败: %s" % (payload or u""))
            self._drop_placeholder(url)
            return
        items = payload or []
        self._collections.add(core.normalize_svn_url(url))
        self._node_items[url] = items
        try:
            self.tree.item(url, text=COLLECTION_TITLE)
        except tk.TclError:
            self._drop_go_recent(url)
            return
        self._apply_node_items(url, items)
        self._record_go_recent(url)
        if items:
            self._set_status(u"%s · %s" % (COLLECTION_TITLE,
                                           core.decode_svn_url(url)))
        else:
            self._set_status(u"%s为空 · %s" % (COLLECTION_TITLE,
                                               core.decode_svn_url(url)))

    def _drop_placeholder(self, url):
        if not self.tree.exists(url):
            return
        for c in self.tree.get_children(url):
            if self.tree.item(c, "text") == LOADING:
                self.tree.delete(c)

    # ---------- 事件轮询 ----------
    def _poll(self):
        if self._closed:
            return
        try:
            while True:
                ev = self.worker.q.get_nowait()
                try:
                    self._handle_event(ev)
                except Exception as e:
                    self._set_status(u"处理事件出错: %s" % e)
        except queue.Empty:
            pass
        except tk.TclError:              # 窗口已随主窗口销毁
            self._closed = True
            try:
                self.worker.stop()
            except Exception:
                pass
            return
        try:
            self.after(80, self._poll)   # 处理完事件才续排，避免弹窗期间重入
        except tk.TclError:
            self._closed = True
            try:
                self.worker.stop()
            except Exception:
                pass

    def _handle_event(self, ev):
        kind = ev[0]
        if kind == "log":
            return                        # 浏览不写日志
        if kind in ("ask_auth", "ask_cert"):
            self._handle_ask(kind, ev[1])
            return
        if kind == "ls":
            _, tag, ok, payload = ev
            self._inflight.discard(tag)
            tkind, url = tag
            if tkind == "node":
                self._on_node_ls(url, ok, payload)
            elif tkind == "collection":
                self._on_collection(url, ok, payload)
            elif tkind == "cat":
                self._on_cat(url, ok, payload)
            elif tkind in ("checkout", "stat"):
                co = self.checkout
                alive = False
                if co is not None:
                    try:
                        alive = co.winfo_exists()
                    except tk.TclError:
                        alive = False
                if alive:
                    if tkind == "checkout":
                        co.on_ls(url, ok, payload)
                    else:
                        co.on_stat(url, ok, payload)

    def _handle_ask(self, kind, text):
        parent = self
        co = self.checkout
        if co is not None:
            try:
                if co.winfo_exists():
                    parent = co
            except tk.TclError:
                pass
        if kind == "ask_auth":
            resp = dialogs.ask_auth(parent, text)
        else:
            resp = dialogs.ask_cert(parent, text)
            if resp.get("ok") and resp.get("remember"):
                self.app._remember_trust_cert()
        self.worker.respond(resp)
        if parent is not self:            # 恢复检出对话框的模态
            try:
                parent.grab_set()
            except tk.TclError:
                pass

    def _trust_changed(self):
        """勾选“信任自签名证书”：写入配置并同步给后台读取线程。"""
        on = bool(self.trust_var.get())
        try:
            self.store.set_option("trust_server_cert", on)
        except Exception as e:
            self._set_status(u"保存证书信任设置失败: %s" % e)
            return
        self.worker.trust_cert = on
        self.worker._trust_flags_cached = None   # 证书标志按次缓存，作废即可
        self._set_status(u"已保存证书信任设置")

    def _set_status(self, text):
        try:
            self.status.configure(text=text)
        except tk.TclError:
            pass

    # ---------- 关闭 ----------
    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.worker.stop()
        except Exception:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass


def open_repo_browser(app, initial_url=""):
    """打开仓库浏览器窗口并返回它（是否复用已有窗口由调用方负责）。"""
    return RepoBrowser(app, initial_url)
