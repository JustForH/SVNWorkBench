# -*- coding: utf-8 -*-
"""提交历史窗口：svn log 列表 + 每个版本改动的文件列表 + 用 meld 对比。

由主界面“显示日志”按钮打开（App._open_log_view 懒加载，窗口已开则
置前复用），也可以从仓库浏览器右键“查看提交记录”打开——此时目标是选中的
SVN 地址而不是工作副本（set_target 切换目标并自动重读，窗口标题显示当前
目标）。读取与差异都走主界面的 Hub 单任务链路（同一时刻只跑一个 svn
命令），结果由 App._handle_done 回调 LogView.task_done，因此凭据弹窗、
运行日志、取消按钮的行为与其它任务完全一致。

对比方式：
  - **单文件**（双击文件行）**一律按地址对比**（core.repo_path_to_url
    拼文件地址，见 Runner._do_logdiff）——文件在本版本新增/删除或被
    排除出工作副本时本地没有节点，用工作副本相对路径会报 E155010。
    对比方式按配置/弹窗选择（与主界面共用 App._choose_diff_mode）：
    选 meld 时改成“两版原始内容”模式（分别 cat rN-1 与 rN 两个临时
    文件），meld **左右两版**对比；选内置走统一差异 -> 内置窗口。
    没装 meld 时直接内置，不弹窗。
  - **整版本**（双击修订 / 对比改动按钮）：统一差异 -> 内置差异窗口，
    装不装 meld 都一样（也不询问）——**meld 3.20 的命令行打开不了补丁
    视图**，`meld xxx.diff` 只会拿 diff 文件和它自己对比（“文件完全
    相同”），勿再把 .diff 丢给它。差异超过 core.DIFF_MAX_LINES 行会
    截断，防止超大差异把内置窗口卡死。
  - **`-c N` 即 N-1 -> N：双击对比的永远是“本次提交与上一个版本”的
    差异**（窗口标题写明“rN 相比上一版本 rN-1”），不含本地未提交改动。
"""
import os
import subprocess
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from . import core, dialogs, theme
from .core import (DIFF_MAX_LINES, decode_svn_url, fmt_date,
                   repo_path_to_url)

# svn log --xml 的 action 字母 -> 显示文本
ACTION_TEXT = {"A": u"A 添加", "M": u"M 修改", "D": u"D 删除",
               "R": u"R 替换", "U": u"U 更新", "G": u"G 合并",
               "E": u"E 拓展", "X": u"X 交换"}


class LogView(tk.Toplevel):
    """提交历史窗口（非模态）。

    上半部：修订列表（修订 / 作者 / 时间 / 说明首行）；
    中部：选中版本的**完整提交说明**（列表“说明”列只放得下首行，
    长描述在这里滚动查看，用户要求能看全）；
    下半部：选中修订改动的文件列表；
    双击修订 = 对比整个版本（该版本与上一版本之间），双击文件 = 只对比
    该文件，顶栏“对比改动”按钮作用于当前选中的修订。

    目标二选一：`url` 非空（仓库浏览器右键“查看提交记录”带来的地址，
    不依赖本地是否有工作副本）或空（主界面当前工作副本）。
    """

    def __init__(self, app, url=u""):
        super().__init__(app.root)
        self.app = app
        self.url = url or u""      # 目标地址；空 = 主界面工作副本目标
        self._wc_url = u""         # 目标的来源地址（log 任务带回）
        self._repo_root = u""          # 仓库根地址（不能叫 _root：会覆盖 Tk 的 Misc._root）
        self._entries = []            # 当前提交列表（core.parse_log_xml 的结果）
        self._file_paths = {}         # 文件行 iid -> 仓库路径
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda e: self.destroy())
        # 任务运行时跟着主界面一起禁用（退出窗口时从清单里摘掉）
        self._idle = [self.btn_refresh, self.btn_diff]
        app._need_idle += self._idle
        self._set_target()
        if url or self.app.wc_path.get().strip():
            self.after(60, self.refresh)

    # ---------- 界面 ----------
    def _build(self):
        self.title(u"提交历史")
        self.geometry("%dx620" % theme.WINDOW_W)   # 宽度与其它辅助窗口统一
        self.minsize(680, 500)             # 再矮改动列表会被挤没（见下）

        bar = tk.Frame(self)
        bar.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(bar, text=u"条数").pack(side="left")
        self.limit_var = tk.StringVar(value=u"50")
        e = ttk.Entry(bar, textvariable=self.limit_var, width=6)
        e.pack(side="left", padx=(4, 6))
        e.bind("<Return>", lambda ev: self.refresh())
        self.btn_refresh = ttk.Button(bar, text=u"刷新", command=self.refresh,
                                      width=theme.BTN_W)
        self.btn_refresh.pack(side="left")
        self.btn_diff = ttk.Button(bar, text=u"对比改动", command=self.diff_rev,
                                   width=theme.BTN_W,
                                   style=theme.ACCENT_STYLE)
        self.btn_diff.pack(side="left", padx=(6, 0))
        self.status = tk.Label(bar, text=u"", fg=core.MUTED, anchor="w")
        self.status.pack(side="right")
        dialogs.install_edit_shortcuts(self)

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=3)
        body.grid_rowconfigure(2, weight=2)

        cols = ("rev", "author", "date", "msg")
        # height 只给"保底"请求值（6 行）：pack 在空间不够时从最后往前
        # 挤，请求值给大（默认 10 行）会把后面的改动列表挤到看不见——
        # 实际高度由 expand 撑开（20261016 用户反馈"只有全屏才看得见"）
        self.tree = ttk.Treeview(body, columns=cols, show="headings",
                                 selectmode="browse", height=6)
        for cid, title, w, anchor, stretch in (
                ("rev", u"修订", 76, "e", False),
                ("author", u"作者", 110, "w", False),
                ("date", u"时间", 130, "w", False),
                ("msg", u"说明", 420, "w", True)):
            self.tree.heading(cid, text=title)
            self.tree.column(cid, width=w, anchor=anchor, stretch=stretch)
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(body, orient="horizontal",
                            command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-Button-1>", self._on_rev_dbl)

        # 提交说明全文：列表“说明”列只显示首行（长描述在列里看不全，
        # 用户反馈），选中版本后在这里显示完整说明。**只占 3 行**（+滚动
        # 条）：原来 6 行太高，把下面的改动列表挤出可视区、只有全屏才
        # 看得到（20261016 用户反馈）；超长说明滚动查看，可选中复制
        self.msg_lbl = tk.Label(self, text=u"提交说明", fg=core.MUTED,
                                anchor="w")
        self.msg_lbl.pack(fill="x", padx=10, pady=(2, 0))
        mbox = tk.Frame(self)
        mbox.pack(fill="x", padx=10, pady=(2, 0))
        self.msg_text = tk.Text(
            mbox, height=3, wrap="word", state="disabled", undo=False,
            font=tkfont.Font(family=theme.pick_family(self),
                             size=theme.base_size()))
        theme.surface(self.msg_text)
        self.msg_text.tag_configure("hint", foreground=core.MUTED)
        msb = ttk.Scrollbar(mbox, orient="vertical",
                            command=self.msg_text.yview)
        self.msg_text.configure(yscrollcommand=msb.set)
        self.msg_text.pack(side="left", fill="both", expand=True)
        msb.pack(side="right", fill="y")

        self.file_lbl = tk.Label(self, text=u"", fg=core.MUTED, anchor="w")
        self.file_lbl.pack(fill="x", padx=10)

        fbody = tk.Frame(self)
        fbody.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        fbody.grid_columnconfigure(0, weight=1)
        fbody.grid_rowconfigure(0, weight=1)
        self.ftree = ttk.Treeview(fbody, columns=("action", "path"),
                                  show="headings", selectmode="browse",
                                  height=4)
        self.ftree.heading("action", text=u"改动")
        self.ftree.column("action", width=80, anchor="w")
        self.ftree.heading("path", text=u"路径")
        self.ftree.column("path", width=600, anchor="w", stretch=True)
        fvsb = ttk.Scrollbar(fbody, orient="vertical",
                             command=self.ftree.yview)
        fhsb = ttk.Scrollbar(fbody, orient="horizontal",
                             command=self.ftree.xview)
        self.ftree.configure(yscrollcommand=fvsb.set, xscrollcommand=fhsb.set)
        self.ftree.grid(row=0, column=0, sticky="nsew")
        fvsb.grid(row=0, column=1, sticky="ns")
        fhsb.grid(row=1, column=0, sticky="ew")
        self.ftree.bind("<Double-Button-1>", self._on_file_dbl)
        self._show_files(None)
        self._show_msg(None)
        # 内容建完再定位：基于父窗口（主界面）居中（用户要求）
        theme.center_on_parent(self)

    # ---------- 读取 ----------
    def _target_text(self):
        """标题里显示的目标：地址目标显示地址，否则显示工作副本路径。"""
        if self.url:
            return decode_svn_url(self.url)
        return self.app.wc_path.get().strip()

    def _set_target(self):
        self.title(u"提交历史 · %s" % (self._target_text() or u"未指定目标"))

    def set_target(self, url):
        """切换目标地址（浏览器右键“查看提交记录”带来）；空 = 切回主界面
        当前工作副本。目标变了清空列表并自动重读；没变只置前，不打断
        正在看的列表。返回是否发生了切换。
        """
        url = url or u""
        if url == self.url:
            return False
        self.url = url
        self._wc_url = self._repo_root = u""
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._show_files(None)
        self._show_msg(None)
        self._set_target()
        self.refresh()
        return True

    def refresh(self):
        """读取提交历史（走主界面 Hub；Busy 时由 _run_start 拦下）。"""
        self._set_target()
        try:
            limit = int(self.limit_var.get().strip() or "50")
        except ValueError:
            limit = 50
        params = {"limit": limit}
        if self.url:
            params["url"] = self.url
        else:
            wc = self.app.wc_path.get().strip()
            if not wc:
                self.status.configure(text=u"请先在主界面填写工作副本路径")
                return
            params["wc"] = wc
        if self.app._run_start("log", params):
            self.status.configure(text=u"正在读取提交历史…")

    def task_done(self, ev):
        """App._handle_done 的回调：把 log/logdiff 的结果接到本窗口。

        log 的结果是 {"entries", "wc_url", "root"}——地址信息留给
        _start_diff 做路径换算（换算在界面里完成，logdiff 就只管 diff）。
        """
        mode = ev.get("mode")
        if mode == "log":
            if ev.get("ok"):
                res = ev.get("result") or {}
                self._wc_url = res.get("wc_url") or u""
                self._repo_root = res.get("root") or u""
                self.on_log(res.get("entries") or [])
            else:
                self.status.configure(text=u"读取失败（详见主界面日志）")
        elif mode == "logdiff":
            if ev.get("ok"):
                self.open_diff(ev.get("result") or {})
            else:
                self.status.configure(text=u"生成差异失败（详见主界面日志）")

    def on_log(self, entries):
        """渲染提交列表（每次整表重建）。"""
        self._entries = list(entries)
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for i, e in enumerate(self._entries):
            rev = e.get("rev") or str(i)
            lines = (e.get("msg") or "").strip().splitlines()
            first = lines[0] if lines else u""
            if len(lines) > 1:
                first += u" …"
            self.tree.insert("", "end", iid=rev,
                             values=(u"r" + rev, e.get("author") or "",
                                     fmt_date(e.get("date")), first))
        self._show_files(None)
        self._show_msg(None)
        self.status.configure(
            text=u"共 %d 条（双击对比该版本与上一版本的差异）"
                 % len(self._entries))

    # ---------- 选中版本的文件列表 ----------
    def _entry(self, rev):
        for e in self._entries:
            if e.get("rev") == rev:
                return e
        return None

    def _selected_rev(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _on_select(self, _event=None):
        rev = self._selected_rev()
        entry = self._entry(rev) if rev else None
        self._show_files(entry)
        self._show_msg(entry)

    def _show_files(self, entry):
        for iid in self.ftree.get_children():
            self.ftree.delete(iid)
        self._file_paths = {}
        if not entry:
            self.file_lbl.configure(text=u"选中某个版本，这里显示它改动的文件")
            return
        paths = entry.get("paths") or []
        self.file_lbl.configure(
            text=u"r%s 改动的文件（%d 个，双击只对比该文件）"
                 % (entry.get("rev"), len(paths)))
        for i, p in enumerate(paths):
            iid = "p%d" % i
            self._file_paths[iid] = p.get("path") or ""
            action = ACTION_TEXT.get(p.get("action"), p.get("action") or "")
            self.ftree.insert("", "end", iid=iid,
                              values=(action, p.get("path") or ""))

    def _show_msg(self, entry):
        """把选中版本的完整提交说明填进说明区（只读）。

        列表列里只显示说明首行加省略号，完整内容（含多行）看这里；
        未选中版本显示提示，没有说明文字给“（无提交说明）”。
        填完回到顶部，避免上次滚到底部影响下一条的阅读。
        """
        self.msg_text.configure(state="normal")
        self.msg_text.delete("1.0", "end")
        if entry is None:
            self.msg_text.insert("1.0",
                                 u"选中某个版本，这里显示完整的提交说明",
                                 ("hint",))
        else:
            msg = (entry.get("msg") or "").strip()
            self.msg_text.insert("1.0", msg or u"（无提交说明）")
        self.msg_text.configure(state="disabled")
        self.msg_text.yview_moveto(0.0)

    # ---------- 对比 ----------
    def _on_rev_dbl(self, _event=None):
        self.diff_rev()

    def diff_rev(self):
        """对比选中版本的全部改动（svn diff -c N）。"""
        rev = self._selected_rev()
        if not rev:
            self.status.configure(text=u"请先选中一个版本")
            return
        self._start_diff(rev, u"", "")

    def _on_file_dbl(self, _event=None):
        """双击文件行：只对比该文件在该版本的改动。"""
        rev = self._selected_rev()
        if not rev:
            return
        iid = self.ftree.focus() or (self.ftree.selection() or [""])[0]
        self._start_diff(rev, self._file_paths.get(iid) or u"",
                         self._file_paths.get(iid) or u"")

    def _start_diff(self, rev, repo_path, display):
        """启动 rN 与上一版本的对比（svn diff -c N = N-1 -> N）。

        目标与换算：
          - 单文件（repo_path 非空且拿得到仓库根）：**一律按地址对比**
            （core.repo_path_to_url 拼文件地址）。对比方式按配置/弹窗
            选择（App._choose_diff_mode）：选 meld 时 Runner 分别 cat
            rN-1 与 rN 到 left/right 临时文件，meld 左右对比；选内置
            就按地址跑统一差异。拼不出文件地址（log 没带回仓库根）
            降级为整版本；
          - 整版本：地址目标给 url，工作副本目标给 wc，始终内置窗口。
        **不再使用工作副本相对路径**：文件在本版本新增/删除、或被排除
        出工作副本时本地没有节点，svn 会报 E155010"找不到节点"。
        """
        params = {"rev": rev, "title": display or u""}
        file_url = repo_path_to_url(self._repo_root, repo_path) \
            if repo_path else u""
        if file_url:
            params["file_url"] = file_url
            meld = self.app.find_meld()
            mode = self.app._choose_diff_mode(bool(meld), parent=self)
            if mode is None:
                self.status.configure(text=u"已取消对比")
                return
            if mode == "meld" and meld:
                # 临时文件带前后缀标记，meld 标签页里能分清左右
                ext = os.path.splitext(file_url.split("/")[-1])[1]
                params["pair"] = 1
                params["left"] = self.app._tmp_file(prefix="svnwb_prev_",
                                                    suffix=ext)
                params["right"] = self.app._tmp_file(prefix="svnwb_cur_",
                                                     suffix=ext)
        elif self.url:
            params["url"] = self.url
        else:
            wc = self.app.wc_path.get().strip()
            if not wc:
                self.status.configure(text=u"请先在主界面填写工作副本路径")
                return
            params["wc"] = wc
        self.status.configure(text=u"正在生成 r%s 与上一版本的差异…" % rev)
        started = self.app._run_start("logdiff", params)
        if not started:
            self.status.configure(text=u"")

    def open_diff(self, result):
        """差异结果分两条路：

        - `kind == "pair"`（单文件 + 装了 meld）：Runner 已把 rN-1 与 rN
          两版原始内容 cat 到临时文件，直接交给 meld **左右两版**对比；
        - 统一差异（整版本，或没装 meld 的单文件）：弹内置差异窗口。
          **不把 .diff 丢给 meld**——meld 3.20 的命令行打开不了补丁视图，
          只会拿 diff 文件和它自己对比（用户实测“文件完全相同”）。
          超过 DIFF_MAX_LINES 行截断，防超大差异卡死界面。
        """
        lines = result.get("lines") or []
        rev = result.get("rev") or ""
        path = result.get("title") or u""
        # 写明语义：svn diff -c N 比的就是本次提交（N）与上一个版本（N-1）
        try:
            prev = u"r%d" % (int(rev) - 1)
        except (TypeError, ValueError):
            prev = u""
        head = (u"r%s 相比上一版本 %s" % (rev, prev)) if prev \
            else u"r%s 与上一版本" % rev
        title = head + (u"：" + path if path else u" 的全部改动")
        if result.get("kind") == "pair":
            self._open_pair(title, result)
            return
        if not lines:
            self.status.configure(text=u"r%s 没有文本差异" % rev)
            return
        if len(lines) > DIFF_MAX_LINES:
            lines = lines[:DIFF_MAX_LINES] + [
                u"",
                u"# …差异过大已截断：共 %d 行，只显示前 %d 行"
                % (len(lines), DIFF_MAX_LINES)]
        payload = {"lines": lines, "stats": result.get("stats")}
        self._show_builtin(title, payload)

    def _open_pair(self, title, result):
        """单文件两版内容（Runner 已 cat 成 left/right）交给 meld 左右对比。"""
        meld = self.app.find_meld()
        left = result.get("left") or ""
        right = result.get("right") or ""
        if not meld or not (os.path.exists(left) and os.path.exists(right)):
            self.status.configure(text=u"无法用 meld 打开两版对比（文件缺失）")
            return
        try:
            proc = subprocess.Popen(
                [meld, left, right], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True)
        except OSError as e:
            self.status.configure(text=u"启动 meld 失败: %s" % e)
            return
        self.app.meld_procs.append(proc)
        self.status.configure(
            text=u"已用 meld 打开 %s（左上一版本 / 右本次提交）" % title)

    def _show_builtin(self, title, payload):
        self.app.diff_win = dialogs.show_diff_win(
            self.app.root, title, payload,
            font_bold=self.app.font_log_bold, win=self.app.diff_win)
        self.status.configure(text=u"已用内置差异窗口显示 %s" % title)

    # ---------- 生命周期 ----------
    def destroy(self):
        try:
            self.app._need_idle = [w for w in self.app._need_idle
                                   if w not in self._idle]
        except Exception:
            pass
        try:
            if self.app._log_view is self:
                self.app._log_view = None
        except Exception:
            pass
        tk.Toplevel.destroy(self)


def open_log_view(app, url=u""):
    """打开提交历史窗口（复用已开窗口由 App._open_log_view 处理）。

    url 非空时目标是该地址（仓库浏览器右键“查看提交记录”），否则是
    主界面当前工作副本。
    """
    return LogView(app, url=url)
