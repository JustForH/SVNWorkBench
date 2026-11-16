# -*- coding: utf-8 -*-
"""主窗口（工作副本页）与程序入口 main()。

单页布局：地址行（含“仓库浏览”/“显示日志”）-> 工作副本行（选目录自动反查地址回填）
-> 改动列表（勾选 / 加入版本控制 / 恢复 / 删除 / 提交 / 双击看差异，
支持键盘上下移动与空格勾选）-> 底部运行日志（默认折叠，不自动展开）。
弹窗一律经 svnwb.dialogs 模块属性调用（dialogs.ask_xxx），便于测试替换。
"""

import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from tkinter import font as tkfont

from . import core, dialogs, theme
from .config_store import ConfigStore
from .core import (APP_TITLE, APP_VERSION, ApiError, BASE_DIR, BusyError,
                   CHECK_OFF,
                   CHECK_ON, CONFIG_DIR, DIFF_MAX_LINES, ITEM_TAG, ITEM_TEXT,
                   MODE_NAMES, UP_CHECK_DELTA,
                   UP_FILL, UP_FONT_DELTA, UP_PATH_X, UP_REV_X,
                   UP_TEXT_OFFSET, diff_stats, join_url, log_dir, probe_wc_url,
                   resolve_dst, status_sort_key)
from .hub import Hub

# 对比方式（持久化在 _settings.json 的 diff_tool 字段）
DIFF_MODE_TEXT = {"ask": u"每次询问", "meld": u"总是用 meld",
                  "builtin": u"总是用内置窗口"}

# ============================================================
# 六、主窗口
# ============================================================

class App(object):
    """Tkinter 主界面：表单 -> Hub 启动任务 -> 轮询事件刷新界面。"""

    def __init__(self, store, hub):
        self.store = store
        self.hub = hub
        self.root = tk.Tk()
        # 皮肤：先按配置挑色板，再套主题。必须在建任何控件之前完成，
        # tk 控件的默认底色是靠 option 数据库传下去的（见 theme 模块）。
        # 没有配置记录/配置值非法时 normalize_theme 一律回退“晴空”。
        self.theme_name = core.normalize_theme(
            (getattr(store, "settings", {}) or {}).get("theme"))
        core.apply_palette(self.theme_name)
        # 平面化主题（配色/扁平边框/内边距）
        theme.apply_theme(self.root)
        dialogs.install_edit_shortcuts(self.root)
        self.root.title("%s v%s" % (APP_TITLE, APP_VERSION))
        self.root.geometry("1060x780")
        self.root.minsize(880, 640)
        self.busy = False
        self.up_items = []          # 改动列表数据
        self.up_checked = set()     # 已勾选条目（相对路径）
        self.up_selected = None     # 当前行（路径），双击时对比该条目
        self.up_sel_line = None     # 当前行号（0 起），键盘/双击的目标
        self.up_sel_lines = set()   # 高亮选中的行号（与勾选无关，可多行）
        self.up_anchor_line = None  # Shift 连选锚点行（0 起）
        self.up_hover_line = None   # 鼠标悬停行号（0 起），提示“这行能点”
        self.up_hover_y = None      # 最近一次鼠标 y：整表重绘后据此补回高亮
        self.rendering = False      # 渲染列表期间屏蔽选中回调
        self.diff_ctx = None        # 进行中的对比 {path, wc, local, out, meld}
        self.diff_win = None        # 内置差异窗口（复用刷新，不重复开窗）
        self.meld_procs = []        # 已启动的 meld 进程，_poll 里回收
        self._tmpdir = None         # 对比临时文件目录，退出时清理
        self._skip_release = False  # 双击后忽略随之而来的第二次 release
        self.log_expanded = False   # 运行日志是否展开
        self.probe_seq = 0          # 地址反查序号（丢弃过期结果）
        self.probe_q = queue.Queue()  # 反查结果回主线程（见 _poll）
        self.url_auto = None        # 上次由工作副本反查回填的地址
        self._wc_ok_path = None     # 已反查成功的工作副本（绝对路径）
        self._need_idle = []
        self._quiet_runs = 0        # 自动（quiet）任务计数：完成时不覆盖结果提示
        self._repo_browser = None
        self._log_view = None       # 提交历史窗口（懒加载，见 _open_log_view）
        self._download_hint = None  # 首次下载的目标目录（状态栏友好文案）
        # “对比方式”菜单的选中值（ask / meld / builtin），菜单打开时刷新
        self._diff_mode_var = tk.StringVar(value="ask")
        self._diff_mode_menu = None   # 顶栏“对比方式”菜单（保引用防回收）
        # “主题”菜单的选中值与菜单对象（菜单打开时重建）
        self._theme_var = tk.StringVar(value=self.theme_name)
        self._theme_menu = None
        self._up_menu_obj = None      # 改动列表右键菜单（测试可检查）
        self._up_mode_menu = None     # 右键菜单里的“对比方式”子菜单
        # 字体统一交给 theme：正文族 + 等宽族各一套，字号在默认值上加档
        default = tkfont.nametofont("TkDefaultFont")
        self.font_bold = tkfont.Font(family=default.cget("family"),
                                     size=default.cget("size"), weight="bold")
        fam = theme.pick_family(self.root, mono=True)
        base = theme.base_size()
        self.font_mono = tkfont.Font(family=fam, size=base)   # 日志/提交说明
        self.font_log_bold = tkfont.Font(family=fam, size=base, weight="bold")
        # 改动列表字号：正文比默认大一号，勾选框再大一档并加粗——
        # 默认 TkFixedFont（10 号）里 ☐ 只有 8px 宽，肉眼几乎看不清
        self.font_up = tkfont.Font(family=fam, size=base + UP_FONT_DELTA)
        self.font_chk = tkfont.Font(family=fam, size=base + UP_CHECK_DELTA,
                                    weight="bold")
        self._build()
        self._load_settings()
        self._set_busy(False, None)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._poll)
        self._append_log(u"程序已启动。配置目录: %s" % CONFIG_DIR, "info")
        # 启动反查/刷新由 main() 的 after_idle -> _startup_refresh 调度：
        # 这样测试直接构造 App 时不会自动起后台任务（见 AGENTS.md）。

    # ---------------- 界面构建 ----------------
    def _build(self):
        # 根窗口用 grid：窗口不够高时压缩中间的列表区域，
        # 保证日志区与状态栏始终可见（pack 在“亏空”时会把状态栏挤出窗口）
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        self._build_top()
        # 只有“工作副本”一页：不再套 ttk.Notebook，省掉页签行的高度
        self._build_wc()
        self._build_log()
        self._build_status()

    def _build_top(self):
        top = tk.Frame(self.root)
        # 右边距 16 = 正文区的 10+6：顶栏按钮与正文各排按钮右缘对齐成一条线
        top.grid(row=0, column=0, sticky="ew", padx=(10, 16), pady=(8, 0))
        tk.Label(top, text=APP_TITLE, font=self.font_bold).pack(side="left")
        tk.Label(top, text="v%s" % APP_VERSION, fg=core.MUTED).pack(
            side="left", padx=(4, 12))
        # 右侧按钮从右往左排，统一宽度（theme.BTN_W），右边缘对齐；
        # “日志文件”已挪到运行日志标题行“清空显示”后面
        # svn 缓存在 ~/.subversion/auth 的登录凭据：查看 / 删除（删前确认）
        ttk.Button(top, text=u"账号管理", command=self._show_credentials,
                   width=theme.BTN_W).pack(side="right")
        # 对比方式（每次询问 / 总是 meld / 总是内置）：与改动列表右键菜单
        # 写同一个配置项，勾了“记住”之后从这里改回来
        self.btn_diff_mode = ttk.Button(top, text=u"对比方式",
                                        command=self._show_diff_mode_menu,
                                        width=theme.BTN_W)
        self.btn_diff_mode.pack(side="right", padx=(0, 6))
        # 主题：10 套皮肤单选，选中立即生效并写入配置（视觉上排最左）
        self.btn_theme = ttk.Button(top, text=u"主题",
                                    command=self._show_theme_menu,
                                    width=theme.BTN_W)
        self.btn_theme.pack(side="right", padx=(0, 6))

    def _build_wc(self):
        """工作副本单页：地址/目录 -> 改动列表（勾选、双击看差异）-> 提交。

        差异不再占下方固定区域：双击列表行弹出对比窗口
        （装了 meld 就用 meld 对比，没装用内置彩色差异窗口）。
        界面尽量精简（用户要求改动列表更高）：不套笔记本、勾选/状态操作
        并成一行、提交说明压成单行，省出的高度全部给改动列表。
        """
        f = tk.Frame(self.root)
        # 只有一页：页面直接铺在主区域，省掉笔记本页签那一行高度
        f.grid(row=1, column=0, sticky="nsew", padx=10, pady=(6, 4))
        inner = tk.Frame(f)
        inner.pack(fill="both", expand=True, padx=6, pady=(2, 4))
        inner.columnconfigure(0, weight=1)

        r0 = tk.Frame(inner)
        r0.grid(row=0, column=0, sticky="ew")
        # 三个行标签定宽（8 字符格）：三行的输入框左边缘才对得齐
        tk.Label(r0, text=u"工作副本", width=8, anchor="w").pack(side="left")
        self.wc_path = ttk.Entry(r0)
        self.wc_path.pack(side="left", fill="x", expand=True, padx=8)
        self.wc_path.bind("<FocusOut>", lambda _e: self._wc_blur())
        self.wc_path.bind("<Return>", lambda _e: self._probe_url(True))
        btn_browse = ttk.Button(r0, text=u"浏览", command=self._browse_wc,
                                width=theme.BTN_W)
        btn_browse.pack(side="left")
        # 原“读取地址”按钮并入“刷新”：同一按钮先按工作副本反查地址，
        # 再刷新改动列表；位置保持在原来的“读取地址”处
        btn_refresh = ttk.Button(r0, text=u"刷新", command=self._refresh,
                                 width=theme.BTN_W)
        btn_refresh.pack(side="left", padx=(6, 0))
        self.btn_browse_wc = btn_browse
        self.btn_refresh = btn_refresh
        self._need_idle += [self.btn_browse_wc, self.btn_refresh]

        r1 = tk.Frame(inner)
        r1.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        tk.Label(r1, text=u"SVN 地址", width=8, anchor="w").pack(side="left")
        self.url_entry = ttk.Entry(r1)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=8)
        self.url_entry.bind("<FocusOut>", lambda _e: self._save_form())
        # 仓库浏览放在地址框后面：没有工作副本时直接从这里浏览并检出
        # （只读且走独立后台线程，不加入 _need_idle，任务运行时也可查看）
        btn_repo = ttk.Button(r1, text=u"仓库浏览",
                              command=self._open_repo_browser,
                              width=theme.BTN_W)
        btn_repo.pack(side="left")
        self.btn_repo_browser = btn_repo
        # “显示日志”紧跟在“仓库浏览”后面（原在顶栏）
        btn_show_log = ttk.Button(r1, text=u"显示日志",
                                  command=self._open_log_view,
                                  width=theme.BTN_W)
        btn_show_log.pack(side="left", padx=(6, 0))
        self.btn_show_log = btn_show_log

        # 行 2：勾选操作 + 条目操作合并成一行（原先是两行，省出的高度
        # 全部给下面的改动列表）；按钮统一 BTN_W、等距排列，两组之间
        # 留段空当；右侧只放“更新”（“刷新”已挪到第一行）。
        # 勾选计数挪到提交行挨着提交按钮
        r2 = tk.Frame(inner)
        r2.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        for text, cmd in ((u"全选", self._up_all), (u"全不选", self._up_none)):
            b = ttk.Button(r2, text=text, command=cmd, width=theme.BTN_W)
            b.pack(side="left", padx=(0, 6))
            self._need_idle.append(b)
        self.btn_up_add = ttk.Button(r2, text=u"添加",
                                     command=self._up_add,
                                     width=theme.BTN_W)
        self.btn_up_add.pack(side="left", padx=(12, 6))
        self.btn_up_revert = ttk.Button(r2, text=u"还原",
                                        command=self._up_revert,
                                        width=theme.BTN_W)
        self.btn_up_revert.pack(side="left", padx=(0, 6))
        self.btn_up_del = ttk.Button(r2, text=u"删除",
                                     command=self._up_delete,
                                     width=theme.BTN_W)
        self.btn_up_del.pack(side="left")
        self._need_idle += [self.btn_up_add, self.btn_up_del,
                            self.btn_up_revert]
        self.btn_up_update = ttk.Button(r2, text=u"更新",
                                        command=self._wc_update,
                                        width=theme.BTN_W)
        self.btn_up_update.pack(side="right")
        self._need_idle.append(self.btn_up_update)

        lh = tk.Frame(inner)
        lh.grid(row=3, column=0, sticky="ew", pady=(8, 2))
        tk.Label(lh, text=u"改动列表").pack(side="left")
        self.up_empty = tk.Label(lh, fg=core.MUTED,
                                 text=u"点击“刷新”查看工作副本改动")
        self.up_empty.pack(side="left", padx=12)
        body = tk.Frame(inner)
        body.grid(row=4, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        # 表头：改动列表是 tk.Text（要逐行着色），没有内建表头，
        # 用固定高度的 label 行按像素对齐列位
        head = tk.Frame(body, height=20)
        head.grid(row=0, column=0, sticky="ew")
        head.grid_propagate(False)
        for x, title in ((0, u"勾选 / 状态"), (UP_REV_X, u"修订"),
                         (UP_PATH_X, u"路径")):
            tk.Label(head, text=title, fg=core.MUTED, anchor="w").place(
                x=x, y=0)
        self.up_text = tk.Text(body, height=6, wrap="none",
                               font=self.font_up, spacing1=2, spacing2=2,
                               state="disabled", cursor="arrow", undo=False)
        theme.surface(self.up_text)          # 白色面板 + 1px 细边框
        self.up_text.configure(tabs=(UP_REV_X, UP_PATH_X))
        for tag in set(ITEM_TAG.values()):
            self.up_text.tag_configure(
                tag, foreground=core.TREE_COLORS.get(tag, core.TEXT),
                background=core.TREE_BG.get(tag, core.SURFACE))
        self.up_text.tag_configure("chk", font=self.font_chk)   # 勾选框放大
        # 正文相对勾选框垂直居中（用户要求；常量与原因见 core.UP_TEXT_OFFSET）
        self.up_text.tag_configure("txt", offset=UP_TEXT_OFFSET)
        # 标签按创建顺序排优先级：状态色 < 悬停 < 当前行，
        # 所以悬停会盖住行状态底色、当前行又压得住悬停
        self.up_text.tag_configure("hover", background=core.UP_HOVER_BG)
        # 当前行同时把文字改成正文色：深色皮肤下状态色是提亮过的浅色，
        # 落在中等亮度的选中蓝底上会看不清；选中行以“被选中”为主，
        # 状态仍由未选中行的底色表达（标签优先级：状态 < 悬停 < 当前行）
        self.up_text.tag_configure("cur", background=core.UP_CUR_BG,
                                   foreground=core.TEXT)
        usb = ttk.Scrollbar(body, orient="vertical", command=self.up_text.yview)
        hsb = ttk.Scrollbar(body, orient="horizontal",
                            command=self.up_text.xview)
        self.up_text.configure(yscrollcommand=usb.set, xscrollcommand=hsb.set)
        self.up_text.grid(row=1, column=0, sticky="nsew")
        usb.grid(row=1, column=1, sticky="ns")
        hsb.grid(row=2, column=0, sticky="ew")
        self.up_text.bind("<ButtonRelease-1>", self._up_click)
        self.up_text.bind("<Double-Button-1>", self._up_dblclick)
        self.up_text.bind("<Button-3>", self._up_menu)
        self.up_text.bind("<Motion>", self._up_motion)
        self.up_text.bind("<Leave>", self._up_leave)
        # 键盘操作（用户要求）：上下键移动当前行，空格切换勾选。
        # PgUp/PgDn/Home/End 一起补上，长列表里不用一路按
        self.up_text.bind("<Up>", lambda _e: self._up_move(-1))
        self.up_text.bind("<Down>", lambda _e: self._up_move(1))
        self.up_text.bind("<Prior>", lambda _e: self._up_move(-10))
        self.up_text.bind("<Next>", lambda _e: self._up_move(10))
        self.up_text.bind("<Home>", lambda _e: self._up_move(0, first=True))
        self.up_text.bind("<End>", lambda _e: self._up_move(0, last=True))
        # Shift+方向键扩展高亮选区（锚点不动，勾选不变）
        self.up_text.bind(
            "<Shift-Up>", lambda _e: self._up_move(-1, extend=True))
        self.up_text.bind(
            "<Shift-Down>", lambda _e: self._up_move(1, extend=True))
        self.up_text.bind(
            "<Shift-Prior>", lambda _e: self._up_move(-10, extend=True))
        self.up_text.bind(
            "<Shift-Next>", lambda _e: self._up_move(10, extend=True))
        self.up_text.bind(
            "<Shift-Home>", lambda _e: self._up_move(0, first=True,
                                                     extend=True))
        self.up_text.bind(
            "<Shift-End>", lambda _e: self._up_move(0, last=True,
                                                    extend=True))
        # 空格：有高亮选区时批量勾选/取消，否则切换当前行
        self.up_text.bind("<space>", lambda _e: self._up_toggle_current())
        # Ctrl+A 全选高亮行（资源管理器习惯，只改选择、不改勾选）；
        # 返回 break 挡住 Text 类的“全选文本”绑定（列表只读，选文本没意义）
        self.up_text.bind("<Control-a>", lambda _e: self._up_key_select_all())
        self.up_text.bind("<Control-A>", lambda _e: self._up_key_select_all())

        # 提交行：说明压成单行高（仍可粘贴多行，超出部分内部滚动），
        # 省出的高度也归改动列表；勾选计数挨着提交按钮，
        # 一眼看到“勾了多少条会被提交”
        r3 = tk.Frame(inner)
        r3.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        tk.Label(r3, text=u"提交说明", width=8, anchor="w").pack(side="left")
        self.up_msg = theme.surface(tk.Text(r3, height=1, width=60))
        # 单行说明框加内部垂直留白，凑到与按钮同高（32px，见 theme 常量）
        self.up_msg.configure(pady=theme.SINGLE_LINE_PADY)
        self.up_msg.pack(side="left", fill="both", expand=True, padx=8)
        self.up_count = tk.Label(r3, fg=core.MUTED, text=u"")
        self.up_count.pack(side="left", padx=(0, 8))
        self.btn_commit = ttk.Button(r3, text=u"提交", command=self._commit,
                                     style=theme.ACCENT_STYLE,
                                     width=theme.BTN_W)
        self.btn_commit.pack(side="left")
        self._need_idle.append(self.btn_commit)

        # 差异改为双击弹窗，改动列表占满本页剩余高度
        # （只给 body 分高，label 行不参与；否则窗口变矮时状态栏会被挤出）
        inner.rowconfigure(4, weight=1)

    def _build_log(self):
        """运行日志：默认折叠，只有用户点标题才展开/收起（任务不自动展开）。"""
        f = tk.Frame(self.root)
        f.grid(row=2, column=0, sticky="ew", padx=(10, 16))
        hd = tk.Frame(f)
        hd.pack(fill="x", pady=(6, 2))
        self.log_toggle = tk.Label(hd, text=self._log_title(),
                                   font=self.font_bold, cursor="hand2")
        self.log_toggle.pack(side="left")
        self.log_toggle.bind("<Button-1>", lambda _e: self._toggle_log())
        self.log_file = tk.Label(hd, text="", fg=core.MUTED)
        self.log_file.pack(side="left", padx=12)
        # 右侧从右往左排：“日志文件”在最右，“清空显示”在它左边
        # （用户要求日志文件放到清空显示后面）
        self.btn_log_files = ttk.Button(hd, text=u"日志文件",
                                        command=self._show_logs,
                                        width=theme.BTN_W)
        self.btn_log_files.pack(side="right")
        ttk.Button(hd, text=u"清空显示", command=self._clear_log,
                   width=theme.BTN_W).pack(side="right", padx=(0, 6))
        body = tk.Frame(f)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.log = tk.Text(body, height=6, state="disabled", wrap="word",
                           undo=False, font=self.font_mono, spacing1=1,
                           spacing2=1)
        theme.surface(self.log)
        lsb = ttk.Scrollbar(body, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=lsb.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        lsb.grid(row=0, column=1, sticky="ns")
        for tag, color in core.LOG_COLORS.items():
            self.log.tag_configure(tag, foreground=color)
        self.log.tag_configure("cmd", foreground=core.LOG_COLORS["cmd"],
                               font=self.font_log_bold)
        self.log.tag_configure("phase", foreground=core.TEXT,
                               font=self.font_log_bold)
        self.log_body = body
        self.log_parent = f
        self.log_body.pack_forget()      # 默认折叠

    def _build_status(self):
        f = tk.Frame(self.root)
        f.grid(row=3, column=0, sticky="ew", padx=(10, 16), pady=(0, 8))
        self.status_dot = tk.Label(f, text=u"\u25cf", fg=core.MUTED)
        self.status_dot.pack(side="left", padx=(2, 6))
        self.status_text = tk.Label(f, text=u"就绪")
        self.status_text.pack(side="left")
        self.btn_cancel = ttk.Button(f, text=u"取消任务",
                                     command=self.hub.cancel,
                                     width=theme.BTN_W)
        self.btn_cancel.pack(side="right")
        self.toast_text = tk.Label(f, text="", fg=core.MUTED)
        self.toast_text.pack(side="right", padx=12)

    # ---------------- 事件轮询 ----------------
    def _poll(self):
        try:
            while True:
                ev = self.hub.events.get_nowait()
                try:
                    self._handle_event(ev)
                except Exception as e:
                    self._toast(u"处理事件出错: %s" % e, "err")
        except queue.Empty:
            pass
        self._drain_probe()
        self._reap_meld()
        self.root.after(80, self._poll)

    def _drain_probe(self):
        """取出地址反查结果（工作线程只入队，控件操作一律在主线程）。"""
        try:
            while True:
                seq, path, url, err, manual, startup = \
                    self.probe_q.get_nowait()
                self._probe_done(seq, path, url, err, manual, startup)
        except queue.Empty:
            pass

    def _handle_event(self, ev):
        kind = ev.get("type")
        if kind == "log":
            self._append_log(ev.get("text", ""), ev.get("tag"))
        elif kind == "busy":
            self._set_busy(bool(ev.get("busy")), ev.get("mode"))
        elif kind == "ask_auth":
            resp = dialogs.ask_auth(self.root, ev.get("message", ""))
            self.hub.respond(resp)
        elif kind == "ask_cert":
            resp = dialogs.ask_cert(self.root, ev.get("message", ""))
            if resp.get("ok") and resp.get("remember"):
                try:
                    self.store.set_option("trust_server_cert", True)
                except Exception:
                    pass
            self.hub.respond(resp)
        elif kind == "done":
            self._handle_done(ev)

    def _handle_done(self, ev):
        self._set_busy(False, None)
        mode = ev.get("mode")
        # 自动任务（quiet）完成时不弹状态栏结果，免得把上一条真正
        # 需要常驻的结果（提交成功/已删除/更新完成）立刻覆盖掉
        quiet = self._quiet_runs > 0
        if quiet:
            self._quiet_runs -= 1
        # 提交历史窗口的任务结果自己接（读取失败/取消也要让它收尾状态）
        lv = getattr(self, "_log_view", None)
        if lv is not None and mode in ("log", "logdiff"):
            try:
                lv.task_done(ev)
            except Exception as e:
                self._toast(u"更新提交历史窗口出错: %s" % e, "err")
        if not ev.get("ok"):
            if ev.get("detail") == "__cancelled__":
                self._toast(u"已取消", "warn")
                return
            self._notify(u"操作失败",
                         str(ev.get("detail") or u"未知错误"), "err")
            return
        result = ev.get("result")
        if mode == "status":
            items = result or []
            self._up_render(items)
            if not quiet:
                self._toast(u"状态已刷新，共 %d 项" % len(items), "ok")
        elif mode in ("add", "revert"):
            self._toast(u"已加入版本控制" if mode == "add" else u"已恢复", "ok")
            self._refresh_status(quiet=True)
        elif mode == "delete":
            self._toast(u"已删除所选条目", "ok")
            self._refresh_status(quiet=True)
        elif mode == "update":
            self._toast(u"更新完成", "ok")
            self._refresh_status(quiet=True)
        elif mode == "commit":
            self._toast(u"提交成功，新版本 r%s" % result if result
                        else u"没有需要提交的改动", "ok")
            if result:
                # 真的提交掉了才清说明框；“没有需要提交的改动”时保留，
                # 免得用户白写一段又得重敲
                self._up_clear_msg()
            self._refresh_status(quiet=True)
        elif mode == "diff":
            ctx = self.diff_ctx or {}
            self.diff_ctx = None
            self.diff_win = dialogs.show_diff_win(
                self.root, ctx.get("path") or u"全部改动",
                result or {"lines": [], "stats": (0, 0, 0)},
                font_bold=self.font_log_bold, win=self.diff_win)
        elif mode == "cat":
            ctx = self.diff_ctx or {}
            self.diff_ctx = None
            if not ctx:
                return
            self._launch_meld(result or ctx.get("out") or "",
                              ctx.get("local") or "")
        elif mode == "download":
            self._toast(u"更新完成" if result == "updated" else u"下载完成",
                        "ok")
        elif mode == "export":
            self._toast(u"导出完成", "ok")

    # ---------------- 忙碌状态 / 提示 ----------------
    def _set_busy(self, busy, mode):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for w in self._need_idle:
            try:
                w.configure(state=state)
            except tk.TclError:
                pass
        try:
            self.btn_cancel.configure(state="normal" if busy else "disabled")
        except tk.TclError:
            pass
        if busy:
            self.status_dot.configure(fg=core.ACCENT)
            # 首次下载（_begin_download_ui 记了目标）显示友好文案；Hub 的
            # busy 事件稍后还会再走一次 _set_busy(True)，这里统一渲染，
            # 否则“正在下载到 …”会被随后的事件刷回“运行中：下载”
            hint = self._download_hint if mode == "download" else None
            self.status_text.configure(
                text=(u"正在下载到 %s，请稍候…" % hint if hint else
                      u"运行中：%s" % MODE_NAMES.get(mode, mode or u"任务")))
            # 运行日志**不自动展开**：默认折叠，只有用户点标题才展开/收起
            # （用户要求，别在任务启动时再自动展开）
        else:
            self._download_hint = None
            self.status_dot.configure(fg=core.MUTED)
            self.status_text.configure(text=u"就绪")

    def _toast(self, msg, kind="ok"):
        """在状态栏右下角显示运行结果；**不自动消失**。

        只有下一条结果才会覆盖它（用户要求任务结果常驻可见，
        原先 4 秒后自动清掉的做法已按用户反馈删除）。
        kind：ok 成功绿 / warn 警告橙 / err 失败红 / info 进行中提示蓝。
        """
        color = core.LOG_COLORS.get(kind, core.TEXT)
        self.toast_text.configure(text=msg, foreground=color)

    def _notify(self, title, message, kind="err"):
        """非模态通知：状态栏常驻结果 + 运行日志，不弹阻塞式消息框。

        任务失败、已有任务在跑、辅助窗口打开失败这类事件只是“告诉用户
        发生了什么”，不需要当场做选择。以前用系统 messagebox，它是 Tk
        内部模态窗：被最小化后 grab 仍然生效，主窗口点哪儿都没反应，像
        程序卡死（用户反馈）。确认/认证/证书等真正需要决策的窗口仍走
        dialogs 的模态弹窗（见 theme.install_modal_guard）。
        """
        text = str(message or u"").strip() or u"未知错误"
        first = text.splitlines()[0]
        short = (u"%s：%s" % (title, first)
                 if title and title != APP_TITLE else first)
        if len(short) > 80:
            short = short[:79] + u"…"
        self._toast(short, kind)
        tag = kind if kind in ("ok", "warn", "err", "info") else "err"
        self._append_log(u"%s：%s" % (title, text), tag)

    def _append_log(self, text, tag="info"):
        at_end = self.log.yview()[1] >= 0.985
        self.log.configure(state="normal")
        self.log.insert("end", str(text) + "\n", tag or "info")
        n = int(self.log.index("end-1c").split(".")[0])
        if n > 2000:
            self.log.delete("1.0", "%d.0" % (n - 2000))
        if at_end:
            self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _log_title(self):
        return (u"\u25be 运行日志" if self.log_expanded else u"\u25b8 运行日志")

    def _toggle_log(self):
        self._set_log_expanded(not self.log_expanded)

    def _set_log_expanded(self, on):
        on = bool(on)
        if on == self.log_expanded:
            return
        self.log_expanded = on
        try:
            self.log_toggle.configure(text=self._log_title())
        except tk.TclError:
            pass
        if on:
            self.log_body.pack(fill="both", expand=True, pady=(0, 6))
        else:
            self.log_body.pack_forget()

    # ---------------- 通用 ----------------
    @staticmethod
    def browse_dir(parent, current=""):
        """系统目录选择框：优先 zenity（跟随系统语言），缺失时回退 Tk 自带。"""
        initial = str(BASE_DIR)
        s = str(current or "").strip()
        if s:
            p = resolve_dst(s)
            try:
                if p.is_dir():
                    initial = str(p)
                elif p.parent.is_dir():
                    initial = str(p.parent)
            except OSError:
                pass
        picked = App._zenity_dir(initial)
        if picked is None:
            picked = filedialog.askdirectory(parent=parent, title=u"选择目录",
                                             initialdir=initial) or ""
        return picked or None

    @staticmethod
    def _zenity_dir(initial):
        """zenity 目录选择：None=不可用（回退），''=用户取消，其余为所选路径。"""
        try:
            pr = subprocess.Popen(
                ["zenity", "--file-selection", "--directory",
                 u"--title=选择目录",
                 "--filename=" + initial.rstrip("/") + "/"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError:
            return None
        try:
            out, _err = pr.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            pr.kill()
            pr.communicate()
            return ""
        if pr.returncode != 0:
            return ""
        return out.decode("utf-8", "replace").strip() or ""

    def _browse(self, entry):
        d = self.browse_dir(self.root, entry.get())
        if d:
            entry.delete(0, "end")
            entry.insert(0, d)

    def _run_start(self, mode, params, quiet=False):
        """启动任务；quiet=True 时失败不弹窗（自动触发的任务不该打断用户）。

        quiet 还会记到 _quiet_runs：这类任务完成时**不弹状态栏结果**
        （否则“提交成功/已删除”等结果会被随后的“状态已刷新”立刻覆盖，
        用户要求运行结果常驻可见）。
        """
        try:
            self.hub.start(mode, params)
        except (ApiError, BusyError) as e:
            if not quiet:
                self._notify(APP_TITLE, str(e), "warn")
            return False
        except Exception as e:
            if not quiet:
                self._notify(APP_TITLE, str(e), "err")
            return False
        if quiet:
            self._quiet_runs += 1
        self.log_file.configure(text=self.hub.log_path or "")
        self._set_busy(True, mode)
        return True

    # ---------------- 表单 / 地址反查 ----------------
    def _wc_abs(self):
        """当前工作副本输入框对应的绝对路径（空路径返回空串）。"""
        raw = self.wc_path.get().strip()
        if not raw:
            return u""
        try:
            return str(resolve_dst(raw))
        except Exception:
            return u""

    def _wc_verified(self):
        """当前工作副本是否已经反查成功（成功才允许落盘/刷新状态）。"""
        path = self._wc_abs()
        return (bool(path) and path == (self._wc_ok_path or u"")
                and os.path.isdir(path))

    def _load_settings(self):
        """启动时把配置带入界面：上次的工作副本与 SVN 地址。

        配置里的工作副本必须真实存在；非法路径（目录不存在/被文件占用）
        及跟随它的旧地址一律不显示，并从配置中清掉——否则下次启动还会
        把无效路径和残留地址带出来（用户反馈）。
        """
        st = self.store.settings
        raw_dst = str(st.get("dst") or "").strip()
        url = str(st.get("svn_url") or "").strip()
        valid = bool(raw_dst) and os.path.isdir(str(resolve_dst(raw_dst)))
        dst = raw_dst if valid else u""
        if raw_dst and not valid:
            url = u""            # 无效工作副本：连同残留地址一起清掉
        self.wc_path.delete(0, "end")
        if dst:
            self.wc_path.insert(0, dst)
        self.url_entry.delete(0, "end")
        if url:
            self.url_entry.insert(0, url)
        self.url_auto = url or None
        self._wc_ok_path = None
        if raw_dst and not valid:
            # 旧版本可能已把非法路径/残留下盘：启动时一并清掉
            try:
                self.store.update_fields(u"", u"",
                                         st.get("excludes") or [])
            except Exception as e:
                self._toast(u"清理无效的工作副本配置失败: %s" % e, "err")

    def _save_form(self):
        """工作副本与 SVN 地址写回配置（配置是这两项的唯一持久化入口）。

        只保存已经反查成功的工作副本：路径非法/不是工作副本时绝不落盘，
        免得下次启动把无效路径和残留地址带出来。清空工作副本时地址一并
        清空（工作副本是唯一标识）。
        """
        wc = self.wc_path.get().strip()
        url = self.url_entry.get().strip()
        if wc and not self._wc_verified():
            return
        try:
            self.store.update_fields(url, wc,
                                     self.store.settings.get("excludes") or [])
        except Exception as e:
            self._toast(u"保存配置失败: %s" % e, "err")

    def _set_form(self, url="", wc="", save=True):
        """把地址/工作副本带回界面：工作副本是唯一标识，地址由它派生。"""
        if wc:
            self.wc_path.delete(0, "end")
            self.wc_path.insert(0, str(wc))
        if url:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, str(url))
            self.url_auto = str(url)
        if wc and url:
            # 检出/更新等已知来源的路径直接视为已验证（无需再反查一次）
            self._wc_ok_path = str(resolve_dst(str(wc)))
        if save and (url or wc):
            self._save_form()

    def open_wc(self, path):
        """启动参数指定的工作副本：填入表单并反查地址。

        反查成功后才写配置；路径非法/不是工作副本时只显示在输入框里，
        不会记录到配置（下次启动不会带出来）。

        地址框**先清空再反查**：启动参数换掉工作副本时，配置里的旧
        地址属于上一个工作副本，不能留在框里——反查成功会回填新
        地址，路径不是 SVN 工作副本就保持留空（用户反馈）。
        """
        p = resolve_dst(path)
        self.url_entry.delete(0, "end")
        self.url_auto = None
        self._wc_ok_path = None
        self._set_form(wc=str(p), save=False)
        self._probe_url(True)

    def _wc_blur(self):
        if not self.wc_path.get().strip():
            # 清空工作副本：地址一并清空，避免留下无归属的地址
            self.url_entry.delete(0, "end")
            self.url_auto = None
            self._wc_ok_path = None
            self._save_form()
            return
        self._probe_url(False)

    def _browse_wc(self):
        d = self.browse_dir(self.root, self.wc_path.get())
        if not d:
            return                          # 取消一律返回 None
        self.wc_path.delete(0, "end")
        self.wc_path.insert(0, d)
        self._wc_ok_path = None
        self._probe_url(True)

    def _probe_url(self, manual=False, startup=False):
        """按工作副本反查 SVN 地址：svn info 只读本地，放后台线程跑。

        工作线程只把结果放进 probe_q，取用统一在 _poll 里（见 _drain_probe）。
        startup=True 表示路径来自配置：反查失败说明配置已失效（目录不
        存在/不是工作副本），由 _probe_done 清掉界面与配置。
        """
        s = self.wc_path.get().strip()
        if not s:
            if manual:
                self._toast(u"请先填写工作副本路径", "warn")
            return
        self.probe_seq += 1
        seq = self.probe_seq
        path = str(resolve_dst(s))

        def work():
            url, err = probe_wc_url(path)
            self.probe_q.put((seq, path, url, err, bool(manual),
                              bool(startup)))

        threading.Thread(target=work, daemon=True).start()

    def _clear_bad_wc(self):
        """清掉启动时发现已失效的工作副本及残留地址（不动改动列表）。"""
        self.wc_path.delete(0, "end")
        self.url_entry.delete(0, "end")
        self.url_auto = None
        self._wc_ok_path = None
        try:
            self.store.update_fields(u"", u"",
                                     self.store.settings.get("excludes") or [])
        except Exception as e:
            self._toast(u"清理无效的工作副本配置失败: %s" % e, "err")

    def _probe_done(self, seq, path, url, err, manual, startup=False):
        if seq != self.probe_seq:
            return                                   # 过期结果，丢弃
        if path != self._wc_abs():
            return                                   # 用户又改了路径，作废
        if not url:
            if path == (self._wc_ok_path or u""):
                self._wc_ok_path = None       # 之前验证过，现在已失效
            if startup and (u"目录不存在" in (err or u"")
                            or u"不是 SVN 工作副本" in (err or u"")):
                # 配置里带出的路径已失效：不显示、不刷新、不落盘
                self._clear_bad_wc()
            if manual:
                self._toast(err or u"读取地址失败", "warn")
            return
        changed = path != (self._wc_ok_path or u"")
        cur = self.url_entry.get().strip()
        if not cur or cur == (self.url_auto or ""):
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)
            self.url_auto = url
            if manual:
                self._toast(u"已按工作副本读取 SVN 地址", "ok")
        elif manual:
            self._toast(u"工作副本地址为 %s（已保留你填写的地址）" % url, "warn")
        self._wc_ok_path = path
        self._save_form()
        # 工作副本变化（或用户主动读取/启动）且地址读取成功 -> 自动刷新
        # 改动列表；地址读不到时上面已经返回，不做任何操作。
        if manual or startup or changed:
            self._refresh_status(quiet=not manual)

    def _show_logs(self):
        dialogs.show_logs(self.root)

    def _show_credentials(self):
        """svn 登录凭据窗口（列出 ~/.subversion/auth 缓存，可确认后删除）。"""
        dialogs.show_credentials(self.root)

    # ---------------- 仓库浏览 ----------------
    def _open_repo_browser(self):
        """打开仓库浏览器（模块懒加载，窗口已开则置前复用）。"""
        rb = self._repo_browser
        if rb is not None:
            try:
                if rb.winfo_exists():
                    rb.deiconify()
                    rb.lift()
                    return
            except tk.TclError:
                pass
        try:
            from . import repo_browser
            self._repo_browser = repo_browser.open_repo_browser(
                self, self.store.settings.get("svn_url", "") or "")
        except Exception as e:
            self._notify(u"仓库浏览", str(e), "err")

    # ---------------- 提交历史 ----------------
    def _open_log_view(self, url=None):
        """打开提交历史窗口（模块懒加载，窗口已开则置前复用）。

        主界面按钮不带 url -> 目标是当前工作副本；仓库浏览器右键
        “查看提交记录”带 url -> 目标是选中的地址（窗口已开时切目标并
        自动重读）。
        """
        lv = self._log_view
        if lv is not None:
            try:
                if lv.winfo_exists():
                    lv.deiconify()
                    lv.lift()
                    lv.set_target(url or u"")
                    return
            except tk.TclError:
                pass
        try:
            from . import log_view
            self._log_view = log_view.open_log_view(self, url=url or u"")
        except Exception as e:
            self._notify(u"提交历史", str(e), "err")

    def _checkout_from_browser(self, url, dst, excludes, restore=None,
                               mode="download"):
        """浏览器检出/更新对话框的确认与启动：完全复用下载任务链路。

        mode="download" 本地尚无工作副本（首次检出）；
        mode="update"    本地已是同源工作副本，按勾选对齐：
                         restore 里是需要拉回的目录，excludes 里是需要排除的。
        """
        restore = list(restore or [])
        excludes = list(excludes or [])
        try:
            abs_path = str(resolve_dst(dst))
        except OSError:
            abs_path = dst
        if mode == "update":
            title, ok_text = u"确认更新", u"开始更新"
            body = (u"SVN 地址：%s\n本地目录：%s\n实际位置：%s\n\n"
                    u"恢复下载：%s\n排除目录：%s\n\n"
                    u"本地目录已是该地址的工作副本，将按上面的勾选对齐："
                    u"恢复勾选的目录、排除未勾选的目录，其余内容增量更新。" % (
                        url, dst, abs_path,
                        u"、".join(restore) if restore else u"（无）",
                        u"、".join(excludes) if excludes else u"（无）"))
        else:
            title, ok_text = u"确认下载", u"开始下载"
            body = (u"SVN 地址：%s\n本地目录：%s\n实际位置：%s\n排除目录：%s\n\n"
                    u"将按目录层级增量下载，重复执行时仅更新有变化的内容。" % (
                        url, dst, abs_path,
                        u"、".join(excludes) if excludes else u"（无）"))
        if not dialogs.ask_confirm(self.root, title, body, ok_text):
            return False
        started = self._run_start("download", {"url": url, "dst": dst,
                                               "excludes": excludes,
                                               "restore": restore})
        if started:
            if mode == "download":
                # 用户要求：点“开始下载”后只剩主窗口 + 友好的下载中提示
                # （更新不关窗，方便接着看仓库，见 _begin_download_ui）
                self._begin_download_ui(abs_path)
            # 配置是地址/目录/排除清单的唯一持久化入口（界面已无下载表单）：
            # 检出或更新成功启动后写回，下次打开浏览器直接带出；
            # 同时把工作副本带回界面（工作副本是唯一标识）
            try:
                self.store.update_fields(url, dst, excludes)
                self._set_form(url, dst, save=False)
            except Exception as e:
                self._toast(u"保存配置失败: %s" % e, "err")
        return started

    def _close_aux_windows(self):
        """收起除主窗口外的辅助窗口（首次下载启动时调用，用户要求）。

        仓库浏览器（连同它自己的读取线程）、提交历史、内置差异窗口一并
        关闭；认证 / 证书 / 确认 / 凭据 / 运行日志列表都是模态弹窗，
        与下载操作不可能同时开着，不用管。
        """
        rb = self._repo_browser
        self._repo_browser = None
        if rb is not None:
            try:
                rb.shutdown()          # 停 LsWorker 线程 + destroy
            except Exception:
                pass
        lv = self._log_view
        self._log_view = None
        if lv is not None:
            try:
                lv.destroy()           # LogView.destroy 里会清理 _need_idle
            except Exception:
                pass
        win = self.diff_win
        self.diff_win = None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass

    def _begin_download_ui(self, dst):
        """首次下载启动后的界面收尾：只剩主窗口 + 友好提示（用户要求）。

        只给 mode="download"（首次检出）用，更新（mode="update"）保留
        仓库浏览器方便接着看。友好提示 = 状态栏“正在下载到 …”+
        右下角蓝色 info（下载完成/失败的 toast 会自然覆盖它）。
        """
        self._close_aux_windows()
        try:
            self.root.deiconify()
            self.root.lift()
        except tk.TclError:
            pass
        # 记下下载目标：busy 事件随后还会调一次 _set_busy(True, "download")，
        # 由它按 _download_hint 重放友好文案；这里先按同一逻辑刷一遍见效更快
        self._download_hint = dst
        try:
            self._set_busy(True, "download")
            self._toast(u"下载已开始，可随时点「取消任务」中断", "info")
        except tk.TclError:
            pass

    def _remember_trust_cert(self):
        """仓库浏览的证书弹窗勾选“记住”后写入配置（之后自动信任）。"""
        try:
            self.store.set_option("trust_server_cert", True)
        except Exception:
            pass
        rb = self._repo_browser
        if rb is not None:
            try:
                rb.trust_var.set(True)
                rb.worker.trust_cert = True
                rb.worker._trust_flags_cached = None
            except Exception:
                pass

    # ---------------- 工作副本页：改动列表 / 提交 / 差异 ----------------
    def _refresh(self):
        """“刷新”按钮：先按工作副本反查 SVN 地址。

        反查成功（拿到地址）后由 _probe_done 自动刷新改动列表；路径非法
        或读不到地址时不做任何操作。原“读取地址”按钮已并入这里。
        """
        wc = self.wc_path.get().strip()
        if not wc:
            self._toast(u"请先填写工作副本路径", "warn")
            return
        self._probe_url(True)

    def _refresh_status(self, quiet=False):
        wc = self.wc_path.get().strip()
        if not wc:
            if not quiet:
                self._toast(u"请先填写工作副本路径", "warn")
            return False
        if not self._wc_verified():
            # 工作副本还没反查成功（路径非法/不是工作副本）：不刷新列表
            if not quiet:
                self._toast(u"请先刷新读取 SVN 地址（工作副本路径需有效）",
                            "warn")
            return False
        self._save_form()
        return self._run_start("status", {"wc": wc}, quiet=quiet)

    def _startup_refresh(self):
        """启动后自动读取工作副本地址，成功后刷新状态。

        由 main() 用 `after_idle` 调度：等首帧渲染（expose/redraw 事件
        处理完）再跑，不拖慢窗口出现；svn info/status 都在后台线程执行。
        startup=True 让失效的配置路径在反查失败时被清掉；目录不存在时
        直接静默跳过，不弹窗不打扰首次启动。
        """
        wc = self.wc_path.get().strip()
        if wc and os.path.isdir(str(resolve_dst(wc))):
            self._probe_url(False, startup=True)

    def _wc_update(self):
        """更新整个工作副本（svn update），完成后自动刷新改动列表。"""
        wc = self.wc_path.get().strip()
        if not wc:
            self._toast(u"请先填写工作副本路径", "warn")
            return
        if not self._wc_verified():
            self._toast(u"请先刷新读取 SVN 地址（工作副本路径需有效）", "warn")
            return
        self._save_form()
        self._run_start("update", {"wc": wc})

    def _up_render(self, items):
        self.rendering = True                        # 渲染期间屏蔽选中回调
        try:
            # 默认排序（用户要求）：版本控制内的改动按状态分组靠前，
            # 未版本控制（?）与忽略（I）排在最后（见 core.status_sort_key）
            self.up_items = sorted(list(items or []), key=status_sort_key)
            # 默认一条都不勾选：提交/恢复/加入都要求先手动勾选，
            # 避免“刷新状态后顺手点提交”把整批改动一次提上去
            self.up_checked = set()
            self.up_selected = None
            self.up_sel_line = None
            self.up_sel_lines = set()
            self.up_anchor_line = None
            self._up_paint()
        finally:
            self.rendering = False
        self.up_empty.configure(text="" if items else u"（没有改动）")
        self._up_count()

    def _up_paint(self):
        """整表重绘。

        改动列表用 tk.Text 而不是 ttk.Treeview：本机 Tk 的 Treeview 行标签
        颜色完全不生效（见 TREE_COLORS 注释），Text 标签可以逐行着色。
        """
        self.up_text.configure(state="normal")
        self.up_text.delete("1.0", "end")
        for it in self.up_items:
            self._up_line_write(it, "end")
        self.up_text.configure(state="disabled")
        self._up_mark_current()
        self._up_hover_refresh()   # 重绘会抹掉悬停标签，按鼠标位置补回

    def _up_line_write(self, it, where):
        """写一行：勾选框段单独挂 “chk” 标签（字号更大、加粗），正文段挂
        “txt”（垂直微调，见 core.UP_TEXT_OFFSET）。

        where 为 "end" 时追加——两次插入都得走 append 语义（字面量 "end"），
        且必须先插勾选框、后插正文，顺序反了勾选框会跑到状态文字后面；
        where 为 1 起行号时重写该行——正文落到 “行.勾选框长度” 的精确列，
        用 “end” 之类会被夹紧的索引会串行。
        """
        on = it["path"] in self.up_checked
        head = u"%s " % (CHECK_ON if on else CHECK_OFF)
        tag = (ITEM_TAG.get(it["item"], "gray"),)
        if where == "end":
            head_i, body_i, tail = "end", "end", u"\n"
        else:
            head_i = "%d.0" % where
            body_i = "%d.%d" % (where, len(head))
            tail = u""      # 该行的换行符还在（delete 只删到 end），别重复加
        self.up_text.insert(head_i, head, ("chk",) + tag)
        self.up_text.insert(body_i, self._up_body_text(it) + tail, tag + ("txt",))

    def _up_body_text(self, it):
        """勾选框之后的内容：状态<TAB>修订<TAB>路径（行尾补白着色）。"""
        return u"%s\t%s\t%s%s" % (
            ITEM_TEXT.get(it["item"], it["item"]),
            it.get("rev") or u"-",
            it["path"], u" " * UP_FILL)

    def _up_set_lines(self, lines):
        """批量重写若干行；**不移动滚动位置**。

        与检出对话框（_refresh_rows）同一套做法：先记下 yview 再恢复——
        视口顶部正好是半截行时，delete 会让 Tk 把视口对齐到行边界、
        跳半行（用户要求改动列表操作时列表不动）。
        """
        lines = [n for n in lines if 0 <= n < len(self.up_items)]
        if not lines:
            return
        ytop = self.up_text.yview()[0]
        self.up_text.configure(state="normal")
        for line in lines:
            it = self.up_items[line]
            self.up_text.delete("%d.0" % (line + 1), "%d.end" % (line + 1))
            self._up_line_write(it, line + 1)
        self.up_text.configure(state="disabled")
        self.up_text.yview_moveto(ytop)
        # 重写会抹掉该行的 hover/cur 标签：按鼠标位置补回悬停，
        # 再按 up_sel_lines 补回选中高亮
        self._up_hover_refresh()
        self._up_mark_current()

    def _up_set_line(self, line):
        """重写某一行（勾选框翻转时用）；不移动滚动位置。"""
        self._up_set_lines([line])

    def _up_mark_current(self):
        """高亮所有选中行（该标签创建在状态/悬停标签之后，优先级更高）。

        选区与勾选是两套独立状态：`up_sel_lines` 只负责行高亮，
        勾选（☑/☐）仍由 `up_checked` 单独维护。
        """
        self.up_text.tag_remove("cur", "1.0", "end")
        for line in sorted(self.up_sel_lines):
            n = line + 1
            if 1 <= n <= len(self.up_items):
                self.up_text.tag_add("cur", "%d.0" % n, "%d.end" % n)

    def _up_set_selection(self, lines):
        """把高亮选区换成 lines（只改选择，不动勾选）。"""
        self.up_sel_lines = set(
            n for n in lines if 0 <= n < len(self.up_items))
        self._up_mark_current()

    def _up_hover_set(self, line):
        """设置/清除悬停行高亮（只改底色，鼠标光标保持系统样式）。"""
        if line == self.up_hover_line:
            return
        self.up_hover_line = line
        self.up_text.tag_remove("hover", "1.0", "end")
        if line is not None:
            n = line + 1
            self.up_text.tag_add("hover", "%d.0" % n, "%d.end" % n)

    def _up_hover_refresh(self):
        """整表重绘后按记录的鼠标 y 重新套悬停高亮（旧标签已被抹掉）。"""
        line = (self._up_line_at(self.up_hover_y)
                if self.up_hover_y is not None else None)
        self.up_hover_line = None
        self._up_hover_set(line)

    def _up_motion(self, event):
        """鼠标在列表上移动：高亮所在行，提示这一行可以点。"""
        self.up_hover_y = event.y
        self._up_hover_set(self._up_line_at(event.y))

    def _up_leave(self, _event):
        """鼠标移出列表：撤掉悬停高亮，光标还原。"""
        self.up_hover_y = None
        self._up_hover_set(None)

    def _up_line_at(self, y):
        """y 坐标 -> 行号（0 起）；点在最末行下方/首行上方的空白返回 None。"""
        try:
            n = int(self.up_text.index("@0,%d" % y).split(".")[0]) - 1
            if not (0 <= n < len(self.up_items)):
                return None
            first = self.up_text.dlineinfo("1.0")
            last = self.up_text.dlineinfo("%d.0" % len(self.up_items))
            if first and y < first[1]:
                return None
            if last and y >= last[1] + last[3]:
                return None            # 最后一行下方的空白：不算点中该行
        except tk.TclError:
            return None
        return n

    def _up_check_hit(self, line, x):
        """x 是否落在该行的 ☑/☐ 字形上（左右各留几像素方便点中）。

        命中区必须按字形的实际 bbox 算：勾选列宽 140px，把整列都当
        勾选框会让“点状态文字也改勾选”（用户反馈）。字形位置随字体、
        横向滚动变化，所以不能用固定像素。
        """
        try:
            box = self.up_text.bbox("%d.0" % (line + 1))
        except tk.TclError:
            return False
        if not box:
            return False
        left, _y, width, _h = box
        return left - 3 <= x <= left + width + 4

    def _up_count(self):
        if self.up_items:
            self.up_count.configure(
                text=u"已勾选 %d / %d" % (len(self.up_checked), len(self.up_items)))
        else:
            self.up_count.configure(text="")

    def _up_click(self, event):
        """单击列表（资源管理器式选择；**选择与勾选完全分离**）。

        - 单击正文：只高亮当前行，勾选不变；
        - 单击 ☑/☐ 字形：切换勾选；被点行在多行高亮选区内时，
          整个选区同步成同一状态（用户要求），选区本身不变；
        - Ctrl+单击：增/减这一行的高亮，勾选不变；
        - Shift+单击：高亮锚点到该行的整段并清空段外，勾选不变；
        - Ctrl+Shift+单击：把整段追加到高亮选区，勾选不变；
        - 单击空白处：清空高亮选区，勾选不变。
        锚点是上次普通/Ctrl 单击或键盘移动的行，Shift 连选不改变锚点。
        """
        if self._skip_release:
            self._skip_release = False   # 双击引发的第二次 release，忽略
            return
        if self.busy or not self.up_items:
            return
        try:
            self.up_text.focus_set()     # 点过列表后键盘（上下/空格）立即可用
        except tk.TclError:
            pass
        line = self._up_line_at(event.y)
        if line is None:
            # 空白处：只清空高亮选择（用户要求：勾选保留）
            self.up_sel_lines = set()
            self.up_sel_line = None
            self.up_selected = None
            self.up_anchor_line = None
            self._up_mark_current()
            return
        if self._up_check_hit(line, event.x):
            # 勾选框是独立开关：只有点小方框本身才改勾选，点状态文字/
            # 正文不动（用户反馈：整列判定会误触）。被点行在多行高亮
            # 选区内时，整个选区跟着变成同一状态（用户要求）；未选中
            # 的行只切换它自己。Shift/Ctrl 落在勾选框上也按此处理。
            path = self.up_items[line]["path"]
            check = path not in self.up_checked
            if line in self.up_sel_lines:
                lines = sorted(self.up_sel_lines)
            else:
                lines = [line]
            # 只移动键盘焦点/锚点，不把未选中行并入高亮选区（选择分离）
            self.up_sel_line = line
            self.up_selected = path
            self.up_anchor_line = line
            self._up_set_checked(lines, check)
            return
        state = int(getattr(event, "state", 0) or 0)
        shift = bool(state & 0x0001)
        ctrl = bool(state & 0x0004)
        if shift:
            self._up_shift_click(line, additive=ctrl)
            return
        if ctrl:
            self._up_toggle_line(line)
            return
        # 普通单击正文：只高亮当前行，不动任何勾选
        self._up_select_line(line)

    def _up_toggle_line(self, line):
        """Ctrl+单击：增/减一行高亮，并把该行设为当前行/锚点；不动勾选。"""
        selected = set(self.up_sel_lines)
        if line in selected:
            selected.discard(line)
        else:
            selected.add(line)
        self.up_sel_lines = selected
        self.up_sel_line = line
        self.up_selected = self.up_items[line]["path"]
        self.up_anchor_line = line
        self._up_mark_current()

    def _up_shift_click(self, line, additive=False):
        """Shift+左键：高亮锚点到该行整段（只改选择，不动勾选）。

        默认清空段外高亮（资源管理器 Shift 连选）；按住 Ctrl 时把整段
        追加到现有高亮选区。锚点（上次普通/Ctrl 单击或键盘移动的行）
        在连续 Shift 点击之间保持不变；没有锚点时从被点行开始。
        """
        anchor = self.up_anchor_line
        if anchor is None or not (0 <= anchor < len(self.up_items)):
            anchor = line
        lo, hi = (anchor, line) if anchor <= line else (line, anchor)
        selected = set(range(lo, hi + 1))
        if additive:
            selected |= self.up_sel_lines
        self.up_sel_lines = selected
        self.up_sel_line = line
        self.up_selected = self.up_items[line]["path"]
        self._up_mark_current()

    def _up_select_line(self, line, anchor=True):
        """选中单行：高亮只保留这一行，并把它设为当前行/双击目标。

        只影响高亮选择，**不动勾选**；差异在双击时才弹窗。
        anchor=True 时同时记下 Shift 连选锚点；Shift 点击本身不改锚点。
        """
        self.up_sel_line = line
        self.up_selected = self.up_items[line]["path"]
        if anchor:
            self.up_anchor_line = line
        self._up_set_selection([line])

    def _up_move(self, delta, first=False, last=False, extend=False):
        """键盘移动当前行（↑/↓/PgUp/PgDn/Home/End）；返回 "break" 吃掉按键。

        普通移动：高亮只保留目标行并更新锚点，勾选不变。
        Shift+方向键（extend=True）：从锚点到目标行整段高亮，锚点保持
        不变，勾选也不变。没有当前行时按方向从首行/末行开始；
        越界停在两端。
        """
        if self.busy or not self.up_items:
            return "break"
        n = len(self.up_items)
        if first:
            line = 0
        elif last:
            line = n - 1
        elif self.up_sel_line is None:
            line = 0 if delta > 0 else n - 1
        else:
            line = max(0, min(n - 1, self.up_sel_line + delta))
        if extend:
            anchor = self.up_anchor_line
            if anchor is None or not (0 <= anchor < n):
                anchor = (self.up_sel_line
                          if self.up_sel_line is not None
                          and 0 <= self.up_sel_line < n else line)
            lo, hi = (anchor, line) if anchor <= line else (line, anchor)
            self.up_sel_lines = set(range(lo, hi + 1))
            self.up_sel_line = line
            self.up_selected = self.up_items[line]["path"]
            self._up_mark_current()
        else:
            self._up_select_line(line)
        try:
            self.up_text.see("%d.0" % (line + 1))    # 保证当前行留在可视区
        except tk.TclError:
            pass
        return "break"

    def _up_set_checked(self, lines, check):
        """把 lines 里的条目全部勾选（check=True）或取消勾选。

        只重画状态真的变化的行，列表滚动不动；返回是否有变化。
        """
        changed = []
        for line in lines:
            if not (0 <= line < len(self.up_items)):
                continue
            path = self.up_items[line]["path"]
            on = path in self.up_checked
            if check and not on:
                self.up_checked.add(path)
                changed.append(line)
            elif not check and on:
                self.up_checked.discard(path)
                changed.append(line)
        if changed:
            if len(changed) == 1:
                self._up_set_line(changed[0])
            else:
                self._up_set_lines(changed)
            self._up_count()
        return bool(changed)

    def _up_check_selected(self, check):
        """右键菜单：把高亮选区内的条目全部勾选/取消勾选（不改选择）。"""
        lines = sorted(self.up_sel_lines)
        if not lines and self.up_sel_line is not None:
            lines = [self.up_sel_line]
        self._up_set_checked(lines, check)

    def _up_toggle_current(self):
        """空格：批量切换高亮选区的勾选；没有选区时切换当前行。

        全部已勾选 -> 全部取消；否则（含混合状态）全部勾选。
        """
        if self.busy or not self.up_items:
            return "break"
        lines = sorted(self.up_sel_lines)
        if not lines and self.up_sel_line is not None:
            lines = [self.up_sel_line]
        lines = [n for n in lines if 0 <= n < len(self.up_items)]
        if not lines:
            return "break"
        all_on = all(self.up_items[n]["path"] in self.up_checked
                     for n in lines)
        self._up_set_checked(lines, not all_on)
        return "break"

    def _up_key_select_all(self):
        """Ctrl+A：全选高亮行（只改选择，不改变任何勾选）。"""
        if self.busy or not self.up_items:
            return "break"
        self.up_sel_lines = set(range(len(self.up_items)))
        self.up_sel_line = 0
        self.up_selected = self.up_items[0]["path"]
        self.up_anchor_line = 0
        self._up_mark_current()
        return "break"

    def _up_dblclick(self, event):
        """双击列表行 -> 弹出对比窗口。"""
        if self.busy or not self.up_items:
            return
        self._skip_release = True      # 挡掉随之而来的第二次 release
        line = self._up_line_at(event.y)
        if line is None:
            return
        if self._up_check_hit(line, event.x):
            return                     # 双击小方框仍当普通点击
        self._up_select_line(line)
        self._diff_open(self.up_items[line]["path"])

    # ---------------- 对比方式（配置 / 菜单） ----------------
    def _diff_tool(self):
        """当前对比方式：ask / meld / builtin（配置值非法时按 ask）。"""
        mode = str(self.store.settings.get("diff_tool") or "ask")
        return mode if mode in DIFF_MODE_TEXT else "ask"

    def _set_diff_mode(self, mode, quiet=False):
        """写入配置并刷新菜单选中项（quiet：勾“记住”时不覆盖状态栏提示）。"""
        if mode not in DIFF_MODE_TEXT:
            return
        self.store.set_option("diff_tool", mode)
        try:
            self._diff_mode_var.set(mode)
        except tk.TclError:
            pass
        if not quiet:
            self._toast(u"对比方式：%s" % DIFF_MODE_TEXT[mode], "info")

    def _choose_diff_mode(self, has_meld=True, parent=None):
        """为本次对比决定方式；返回 meld / builtin / None（取消）。

        没装 meld 时直接内置；配置不是 ask 就用配置；ask 时弹窗询问。
        弹窗里勾了“记住”就把选择写回配置。parent 缺省主窗口；提交历史
        窗口传自己，弹窗才会压在它上面（transient）并基于它居中。
        """
        if not has_meld:
            return "builtin"
        mode = self._diff_tool()
        if mode != "ask":
            return mode
        answer = dialogs.ask_diff_mode(parent or self.root)
        if not answer:
            return None
        picked = answer.get("mode")
        if picked not in ("meld", "builtin"):
            return None
        if answer.get("remember"):
            self._set_diff_mode(picked, quiet=True)
        return picked

    def _fill_diff_mode_menu(self, menu):
        """把三种对比方式作为单选菜单项追加到 menu（顶栏/右键共用）。"""
        self._diff_mode_var.set(self._diff_tool())
        for value in ("ask", "meld", "builtin"):
            menu.add_radiobutton(
                label=DIFF_MODE_TEXT[value], variable=self._diff_mode_var,
                value=value,
                command=lambda v=value: self._set_diff_mode(v))

    def _show_diff_mode_menu(self):
        """顶栏“对比方式”按钮：弹出三种模式的选择菜单。"""
        menu = theme.make_menu(self.root)
        self._fill_diff_mode_menu(menu)
        self._diff_mode_menu = menu
        x = self.btn_diff_mode.winfo_rootx()
        y = (self.btn_diff_mode.winfo_rooty()
             + self.btn_diff_mode.winfo_height())
        try:
            menu.tk_popup(x, y)
        except tk.TclError:
            for fn in (menu.unpost, menu.grab_release):
                try:
                    fn()
                except tk.TclError:
                    pass

    # ---------------- 主题（配置 / 菜单） ----------------
    def _set_theme(self, name):
        """应用皮肤并写入配置：只重配颜色，不重建控件、不动任务与列表状态。"""
        name = core.normalize_theme(name)
        if name == self.theme_name:
            try:
                self._theme_var.set(name)
            except tk.TclError:
                pass
            return
        old = core.current_palette()
        core.apply_palette(name)
        theme.apply_theme(self.root)      # 刷新 ttk 样式 + option 默认值
        theme.recolor(self.root, old)     # 已有 tk 控件/菜单/Text 标签换色
        self.theme_name = name
        try:
            self._theme_var.set(name)
        except tk.TclError:
            pass
        try:
            self.store.set_option("theme", name)
        except Exception as e:
            self._toast(u"保存皮肤设置失败: %s" % e, "err")

    def _fill_theme_menu(self, menu):
        """把 10 套皮肤作为单选菜单项追加到 menu（顺序固定，见 core.THEME_ORDER）。"""
        self._theme_var.set(self.theme_name)
        for name in core.THEME_ORDER:
            menu.add_radiobutton(
                label=name, variable=self._theme_var, value=name,
                command=lambda n=name: self._set_theme(n))

    def _show_theme_menu(self):
        """顶栏“主题”按钮：弹出 10 套皮肤的选择菜单。"""
        menu = theme.make_menu(self.root)
        self._fill_theme_menu(menu)
        self._theme_menu = menu
        x = self.btn_theme.winfo_rootx()
        y = (self.btn_theme.winfo_rooty()
             + self.btn_theme.winfo_height())
        try:
            menu.tk_popup(x, y)
        except tk.TclError:
            for fn in (menu.unpost, menu.grab_release):
                try:
                    fn()
                except tk.TclError:
                    pass

    def _up_menu(self, event):
        """改动列表右键：与仓库浏览器右键菜单同一套格式（简单命令列表）。

        有选中行时给两种对比方式 + 该条目的提交历史 + 批量勾选/取消；
        空白处只给工作副本历史。最后是“对比方式”子菜单（三档默认值）。
        右键点在高亮选区内时保留多选（不塌成单行），批量项作用于选区。
        """
        if self.busy:
            return
        line = self._up_line_at(event.y)
        path = None
        if line is not None:
            if line in self.up_sel_lines:
                self.up_sel_line = line
                self.up_selected = self.up_items[line]["path"]
                self._up_mark_current()
            else:
                self._up_select_line(line)
            path = self.up_items[line]["path"]
        wc = self.wc_path.get().strip()
        local = str(resolve_dst(wc) / path) if (wc and path) else ""
        can_meld = bool(path and wc and self.find_meld() and local
                        and not os.path.isdir(local))
        menu = theme.make_menu(self.root)
        if path and wc:
            if can_meld:
                menu.add_command(
                    label=u"用 meld 对比",
                    command=lambda: self._diff_open(path, mode="meld"))
            menu.add_command(
                label=u"用内置窗口对比",
                command=lambda: self._diff_open(path, mode="builtin"))
        menu.add_command(
            label=u"查看提交历史",
            command=lambda: self._view_log_for(path))
        if line is not None and self.up_sel_lines:
            menu.add_separator()
            menu.add_command(
                label=u"勾选所选条目",
                command=lambda: self._up_check_selected(True))
            menu.add_command(
                label=u"取消勾选所选条目",
                command=lambda: self._up_check_selected(False))
        menu.add_separator()
        sub = theme.make_menu(menu)
        self._fill_diff_mode_menu(sub)
        menu.add_cascade(label=u"对比方式", menu=sub)
        self._up_menu_obj = menu
        self._up_mode_menu = sub
        try:
            menu.tk_popup(event.x_root, event.y_root)
        except tk.TclError:
            for fn in (menu.unpost, menu.grab_release):
                try:
                    fn()
                except tk.TclError:
                    pass

    def _view_log_for(self, path=None):
        """改动列表右键“查看提交历史”：优先看该条目的仓库历史。

        未版本控制/忽略/新增（仓库里还没有这个节点）或地址框为空时，
        退回整个工作副本的提交历史（与地址行“显示日志”一致）。
        """
        item = self._up_item(path) if path else None
        base = self.url_entry.get().strip()
        if path and base and item not in ("unversioned", "ignored", "added"):
            self._open_log_view(url=join_url(base, path))
            return
        self._open_log_view()

    # ---------------- 双击对比（按配置/弹窗选择 meld 或内置） ----------------
    @staticmethod
    def find_meld():
        """找 meld（第三方图形对比工具）；没装返回 None，改用内置差异窗口。"""
        try:
            found = shutil.which("meld")
        except AttributeError:                     # Python < 3.3 兜底
            found = None
        if found:
            return found
        for cand in ("/usr/bin/meld", "/usr/local/bin/meld", "/bin/meld",
                     "/snap/bin/meld"):
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
        return None

    def _up_item(self, path):
        for i in self.up_items:
            if i["path"] == path:
                return i.get("item")
        return None

    def _tmp_dir(self):
        if self._tmpdir is None:
            self._tmpdir = tempfile.mkdtemp(prefix="svnwb_diff_")
        return self._tmpdir

    def _tmp_file(self, suffix=".txt", prefix="svnwb_"):
        """建一个空的对比临时文件（退出程序时统一清理）。"""
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix,
                                    dir=self._tmp_dir())
        os.close(fd)
        return path

    def _diff_open(self, path, mode=None):
        """按用户选择打开对比。

        mode=None 时按配置/弹窗决定（ask 才询问）；右键菜单会显式传入
        meld/builtin。目录和未装 meld 的情况强制走内置；未版本控制/忽略
        的条目没有 BASE 基线（svn diff 会报 E155010），内置窗口按“全新增”
        渲染本地文件内容。
        """
        wc = self.wc_path.get().strip()
        if not wc:
            self._toast(u"请先填写工作副本路径", "warn")
            return
        local = str(resolve_dst(wc) / path)
        item = self._up_item(path)
        meld = self.find_meld()
        if mode is None:
            if not meld or os.path.isdir(local):
                mode = "builtin"
            else:
                mode = self._choose_diff_mode(True)
                if mode is None:
                    self._toast(u"已取消对比", "info")
                    return
        elif mode not in ("meld", "builtin"):
            mode = "builtin"
        if mode == "meld" and (not meld or os.path.isdir(local)):
            mode = "builtin"       # 目录 / 未安装 meld：无法走外部对比
        if mode == "builtin":
            if item in ("unversioned", "ignored"):
                self._show_new_file(path, local)
                return
            self.diff_ctx = {"path": path, "wc": wc}
            self._start_diff(path)
            return
        ctx = {"path": path, "wc": wc, "local": local, "meld": meld}
        self.diff_ctx = ctx
        if item in ("unversioned", "ignored", "added", "replaced"):
            # 没有基线版本：空文件当左侧，直接打开
            self._launch_meld(self._tmp_file(suffix=".base"), local)
            return
        out = self._tmp_file(suffix=".base")
        ctx["out"] = out
        if not self._run_start("cat", {"wc": wc, "path": path, "out": out}):
            self.diff_ctx = None

    def _show_new_file(self, path, local):
        """无基线条目的内置对比：把本地文件内容按“全新增”渲染。

        未版本控制/忽略的文件 svn diff 会报 E155010，内置窗口拿不到差异；
        这里直接读文件，二进制/超大文件给提示或截断，避免整窗卡死。
        """
        if os.path.isdir(local):
            self._toast(u"该条目是未纳入版本控制的目录，内置窗口无法显示差异",
                        "warn")
            return
        limit = 4 * 1024 * 1024
        try:
            with open(local, "rb") as f:
                data = f.read(limit + 1)
        except OSError as e:
            self._toast(u"读取文件失败: %s" % e, "err")
            return
        cut = len(data) > limit
        data = data[:limit]
        if b"\x00" in data:
            lines = [u"# %s 是二进制文件，无法显示文本差异" % path]
        else:
            rows = data.decode("utf-8", "replace").splitlines()
            more = len(rows) > DIFF_MAX_LINES
            rows = rows[:DIFF_MAX_LINES]
            lines = [u"Index: %s" % path,
                     u"=" * 67,
                     u"--- %s\t（不存在）" % path,
                     u"+++ %s\t（工作副本）" % path,
                     u"@@ -0,0 +1,%d @@" % len(rows)]
            lines += [u"+" + row for row in rows]
            if more or cut:
                lines += [u"",
                          u"# …文件过大已截断，只显示前 %d 行" % len(rows)]
        payload = {"lines": lines, "stats": diff_stats(lines)}
        self.diff_win = dialogs.show_diff_win(
            self.root, path, payload, font_bold=self.font_log_bold,
            win=self.diff_win)

    def _launch_meld(self, base, local):
        """启动 meld 对比左右两个文件（不阻塞主界面）。"""
        ctx = self.diff_ctx or {}
        meld = ctx.get("meld") or self.find_meld()
        if not os.path.exists(local):
            local = self._tmp_file(suffix=".local")   # 本地已删除 -> 空文件
        if not meld:
            self._start_diff(ctx.get("path") or "", quiet=True)
            return
        try:
            proc = subprocess.Popen(
                [meld, base, local], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True)
        except OSError as e:
            self._toast(u"启动 meld 失败: %s" % e, "err")
            self._start_diff(ctx.get("path") or "", quiet=True)
            return
        self.meld_procs.append(proc)
        self.diff_ctx = None       # 对比已交给 meld，上下文用完即清
        self._toast(u"已用 meld 打开对比: %s" % (ctx.get("path") or ""), "ok")

    def _reap_meld(self):
        """回收已退出的 meld 进程，避免僵尸进程。"""
        if not self.meld_procs:
            return
        alive = []
        for pr in self.meld_procs:
            if pr.poll() is None:
                alive.append(pr)
        self.meld_procs = alive

    def _start_diff(self, path="", quiet=False):
        """生成差异（只看本地未提交改动）并弹内置差异窗口。"""
        wc = self.wc_path.get().strip()
        if not wc:
            if not quiet:
                self._toast(u"请先填写工作副本路径", "warn")
            return False
        self.diff_ctx = {"path": path or "", "wc": wc}
        started = self._run_start("diff", {"wc": wc, "path": path or ""},
                                  quiet=quiet)
        if not started:
            self.diff_ctx = None
        return started

    def _up_set_all(self, mode):
        if self.busy or not self.up_items:
            return
        if mode == "all":
            self.up_checked = set(i["path"] for i in self.up_items)
        else:
            self.up_checked = set()
        self._up_paint()
        self._up_count()

    def _up_all(self):
        self._up_set_all("all")

    def _up_none(self):
        self._up_set_all("none")

    def _checked_paths(self):
        return [i["path"] for i in self.up_items if i["path"] in self.up_checked]

    def _up_add(self):
        """加入版本控制：勾选的“未版本控制/忽略”条目交给 svn add --force。

        忽略条目（如被 svn 全局忽略规则命中的 *.so）也要能加入——
        `svn add --force` 本就支持（用户要求列表不忽略任何文件）。
        """
        addable = set(i["path"] for i in self.up_items
                      if i["item"] in ("unversioned", "ignored"))
        paths = [p for p in self._checked_paths() if p in addable]
        if not paths:
            self._toast(u"请先勾选要加入版本控制的条目（未版本控制/忽略）", "warn")
            return
        wc = self.wc_path.get().strip()
        if not wc:
            self._toast(u"请先填写工作副本路径", "warn")
            return
        self._run_start("add", {"wc": wc, "paths": paths})

    def _up_delete(self):
        """删除勾选的条目（svn delete）；未版本控制/忽略的条目一并删除。"""
        sel = self._checked_paths()
        if not sel:
            self._toast(u"请先勾选要删除的条目", "warn")
            return
        wc = self.wc_path.get().strip()
        if not wc:
            self._toast(u"请先填写工作副本路径", "warn")
            return
        body = (u"将对以下 %d 项执行 svn delete：\n%s\n\n"
                u"版本控制的条目会被标记为删除（提交后才从仓库移除，"
                u"本地文件立即移除）；未版本控制/忽略的条目直接从磁盘删除。"
                % (len(sel), "\n".join(sel)))
        if not dialogs.ask_confirm(self.root, u"删除所选", body, u"确认删除"):
            return
        self._run_start("delete", {"wc": wc, "paths": sel})

    def _up_revert(self):
        """还原勾选的条目；新增/删除/缺失的目录按整棵子树恢复。

        深恢复清单按条目状态算好传给 Runner（见 core.REVERT_TREE_ITEMS 与
        Runner._do_revert 的 docstring）：只对“整棵树形状变化”的条目递归，
        普通修改仍只恢复勾选的节点，不丢未勾选子条目的本地修改。
        """
        sel = self._checked_paths()
        if not sel:
            self._toast(u"请先勾选要恢复的条目", "warn")
            return
        wc = self.wc_path.get().strip()
        if not wc:
            self._toast(u"请先填写工作副本路径", "warn")
            return
        deep = [i["path"] for i in self.up_items
                if i["path"] in self.up_checked
                and i["item"] in core.REVERT_TREE_ITEMS]
        body = (u"将丢弃以下 %d 项的本地修改，且不可撤销：\n%s"
                % (len(sel), "\n".join(sel)))
        if deep:
            body += u"\n\n新增/删除/缺失的条目若为目录，会连同其下的条目一起恢复。"
        if not dialogs.ask_confirm(self.root, u"恢复所选", body, u"确认恢复"):
            return
        self._run_start("revert", {"wc": wc, "paths": sel, "deep": deep})

    def _up_clear_msg(self):
        """清空提交说明框（提交成功后调用）。

        提交成功后地址/改动列表都按新状态刷新了，旧的提交说明留着容易被
        原样带进下一次提交（用户反馈），所以这里清掉。
        """
        try:
            self.up_msg.delete("1.0", "end")
        except tk.TclError:
            pass            # 窗口正在关闭，控件可能已销毁

    def _commit(self):
        msg = self.up_msg.get("1.0", "end").strip()
        if not msg:
            self._toast(u"请填写提交说明", "warn")
            return
        wc = self.wc_path.get().strip()
        if not wc:
            self._toast(u"请先填写工作副本路径", "warn")
            return
        sel = self._checked_paths()
        if not sel:
            # 列表默认全不勾选：空选时提交会变成“整个工作副本”，太危险
            self._toast(u"请先勾选要提交的条目", "warn")
            return
        body = u"将提交以下 %d 项：\n%s\n\n提交说明：%s" % (
            len(sel), "\n".join(sel), msg)
        if not dialogs.ask_confirm(self.root, u"确认提交", body, u"确认提交"):
            return
        self._run_start("commit", {"wc": wc, "message": msg, "paths": sel})

    # ---------------- 关闭 ----------------
    def _on_close(self):
        if self.hub.busy():
            name = MODE_NAMES.get(self.hub.mode, self.hub.mode or u"任务")
            if not dialogs.ask_confirm(self.root, u"退出程序",
                               u"任务正在运行（%s），退出将取消当前任务，确定退出？"
                               % name, u"退出并取消"):
                return
            self.hub.cancel()
        if self._tmpdir is not None:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None
        rb = self._repo_browser
        if rb is not None:
            try:
                rb.shutdown()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main(argv=None):
    """程序入口。可带一个启动参数：工作副本目录路径。

    argv 显式传入时用之（测试友好），否则取 sys.argv[1:]。
    启动参数用于文件管理器右键"打开方式"集成：选中目录 ->
    SVNWorkBench 启动并把该目录填进工作副本（自动反查地址）。
    """
    if sys.version_info < (3, 5):
        print(u"需要 Python 3.5.2 或更高版本，当前为 %s" %
              ".".join(map(str, sys.version_info[:3])))
        return 1
    args = list(sys.argv[1:] if argv is None else argv)
    store = ConfigStore(CONFIG_DIR)
    store.load()
    hub = Hub(store)
    print("%s v%s" % (APP_TITLE, APP_VERSION))
    print(u"配置目录: %s" % CONFIG_DIR)
    print(u"日志目录: %s" % log_dir())
    try:
        app = App(store, hub)
    except tk.TclError as e:
        sys.stderr.write(u"错误: 无法连接图形界面（DISPLAY=%s）: %s\n" % (
            os.environ.get("DISPLAY", u"未设置"), e))
        return 1
    if args:
        app.open_wc(args[0])
    else:
        # 首帧渲染完成后再自动反查地址并刷新状态（after_idle 保证窗口先
        # 画出来，expose/redraw 事件处理完才回调），不拖慢启动速度。
        app.root.after_idle(app._startup_refresh)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
