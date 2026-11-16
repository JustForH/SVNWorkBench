# -*- coding: utf-8 -*-
"""平面化主题：把 tk/ttk 的默认立体观感统一成“浅灰底 + 白色面板 + 细边框 + 大内边距”。

只用标准库 tkinter.ttk 自带的 clam 主题，不引入任何第三方皮肤包。
扁平化三招：

  配色     颜色全部来自 core.py 的纯字符串常量（core 不 import tkinter），
           见 APP_BG / SURFACE / BORDER / ACCENT
  扁平化   ttk 用 clam 主题并把 relief、borderwidth 归零重配（按钮不再有
           渐变与凸起，只留 1px 细边框）；tk 控件的 sunken 立体边换成
           highlightthickness=1 的细边框（surface()）
  内边距   按钮、表头、树行统一 padding，行高加大到 28px

使用与约束：

  - **必须在创建控件之前调用 apply_theme(root)**：tk 控件的底色/前景/
    字体靠 option 数据库（`option_add("*background", ...)`）传递，
    建完控件再设就晚了
  - **tk 控件不吃 ttk 样式**，也没有“按控件类”的 option 匹配
    （Tk 按控件**名**匹配，自动名是小写的 entry/text/frame，还有 entry2
    这种后缀，靠 pattern 抓不住）——所以文本区要逐个调
    `surface(widget)` 刷成白色面板（改动列表 + 提交说明 + 日志 +
    内置差异窗口）。**输入框不用再调**：一律 ttk.Entry，扁平配色与
    32px 高度统一配在 TEntry 样式里（见 BTN_PADY / FIELD_PADY），
    tk.Entry 没有 ipady/height 选项、高只有 24px，与按钮并排不协调。
  - **ttk 样式按 Tk 解释器全局生效**：主窗口、仓库浏览器、检出对话框、
    各类弹窗共用一套，Toplevel 里的 ttk 控件自动继承，不用逐窗设置
  - 本机 Tk 8.6.9 对 ttk.Treeview 的**行级**标签着色完全不生效（见 core 的
    TREE_COLORS 注释），主题只能改表头/选中行/行高，逐行颜色仍要靠
    tk.Text（改动列表就是这么做的），别指望在这里救 Treeview
"""

import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from . import appicon, core
from .core import CHECK_OFF, CHECK_ON, UP_CHECK_DELTA

ACCENT_STYLE = "Accent.TButton"   # 主操作按钮（提交 / 开始下载 / 确定 …）

# 统一控件高度 = 32px（本机 10 号中文字体下的实测值，换字体时三者同步
# 漂移，比例不变）。按钮与输入框同高，行内并排才协调（用户要求）：
#   TButton   padding y=3 -> 高 26 + 2*3 = 32
#   TEntry    padding y=4 -> 高 24 + 2*4 = 32
#   单行 Text pady=5      -> 高 18 + 2*5 + 2*边框 = 32
# tk.Entry 没有 ipady/height 选项（Tk 8.6 实测报 unknown option），
# 所以输入框一律用 ttk.Entry，靠 TEntry 样式的 padding 加高。
BTN_PADY = 3
BTN_PADX = 14        # 主按钮水平内边距（强调按钮也用它，保证同排等宽）
FIELD_PADY = 4
FIELD_PADX = 10      # 输入框文字左右留白
SINGLE_LINE_PADY = 5  # 单行 tk.Text（提交说明）用它对齐到 32px

# 按钮统一宽度（ttk width 单位，1 个汉字 ≈ 2 单位；本机 1 单位 = 7px）：
# 主界面按钮按组取同一宽度、等距排列，每排最右那个统一用 BTN_W，
# 各排按钮右边缘对成一条竖线（用户要求“大小尽量统一、排版对齐”）
BTN_W = 8         # 标准钮：≤4 个汉字（刷新 / 仓库浏览 / 显示日志 / 更新…）
BTN_W_LONG = 12   # 长名钮：≤6 个汉字（取消本次操作 / 打开所选文件…）

# 字体族候选：优先中文CJK 齐全的；都缺就退回系统等宽族（老机器上是 monospace）
UI_FAMILIES = (u"Noto Sans CJK SC", u"WenQuanYi Zen Hei", u"Droid Sans Fallback",
               u"Noto Sans Mono CJK SC")
MONO_FAMILIES = (u"Noto Sans Mono CJK SC", u"Noto Sans CJK SC",
                 u"WenQuanYi Zen Hei", u"Droid Sans Fallback")


def pick_family(root, mono=False):
    """挑一个本机装了的中文字体族（都缺时退回 TkFixedFont 的族名）。"""
    avail = set(s.strip() for s in tkfont.families(root))
    for cand in (MONO_FAMILIES if mono else UI_FAMILIES):
        if cand in avail:
            return cand
    return tkfont.nametofont("TkFixedFont").cget("family")


def base_size():
    """系统默认字号（TkDefaultFont 解析后的实际值，本机是 10）。"""
    return int(tkfont.nametofont("TkDefaultFont").actual("size") or 10)


def check_font(widget, mono=False):
    """勾选字形字体（☑/☐ 大号加粗）——改动列表、检出勾选树与
    theme.CheckBox 统一从这里取，保证三处“复选框”观感一致。"""
    return tkfont.Font(family=pick_family(widget, mono=mono),
                       size=base_size() + UP_CHECK_DELTA, weight="bold")


def set_window_icon(win):
    """给窗口设置程序图标（标题栏 / 任务栏 / Alt+Tab 共用）。

    图标是 base64 内嵌的 PNG（`svnwb/appicon.py`），不依赖外部资源文件，
    单文件 exe 也能用；同时登记 256/64/32 三档，WM 按场景挑尺寸。
    `iconphoto(..., True)` 的 `-default` 会让**之后创建的所有 Toplevel
    自动继承**，所以主窗口建好后调用一次即可（仓库浏览器/提交历史/
    各类弹窗都跟着显示，不用逐窗设置）。
    PhotoImage 必须挂在根窗口上留引用：Tk 不持有强引用，被 GC 回收后
    图标会变空白（任务栏只剩默认羽毛）。窗口已销毁/PNG 解码失败时静默
    跳过，绝不能因为图标影响程序启动。
    """
    try:
        root = win.winfo_toplevel()
        imgs = getattr(root, "_app_icon_imgs", None)
        if not imgs:
            big = tk.PhotoImage(master=root, data=appicon.PNG_B64)
            imgs = [big, big.subsample(4, 4), big.subsample(8, 8)]
            root._app_icon_imgs = imgs
        win.iconphoto(True, *imgs)
    except Exception:
        pass


def apply_theme(root):
    """给 root 及其所有 Toplevel 套统一的平面主题。**建控件之前调用**。

    颜色全部从 core 的模块级常量读取（core.apply_palette 按皮肤写入），
    所以切换皮肤后重新调用本函数即可刷新 ttk 样式；已有 tk 控件的
    颜色由 recolor() 迁移。
    """
    size = base_size()
    font_ui = (pick_family(root), size)
    font_bold = (font_ui[0], size, "bold")

    root.configure(bg=core.APP_BG)
    # tk 控件的默认底色/前景/字体：catch-all pattern 对 Frame/Label/
    # Checkbutton/Toplevel 都有效（Entry/Text 见 surface()）
    root.option_add("*background", core.APP_BG)
    root.option_add("*Background", core.APP_BG)
    root.option_add("*foreground", core.TEXT)
    root.option_add("*Foreground", core.TEXT)
    root.option_add("*Font", font_ui)
    root.option_add("*selectBackground", core.ACCENT)
    root.option_add("*selectForeground", core.ON_ACCENT)
    # Combobox 的下拉列表是 Tk 经典 Listbox（不吃 ttk 样式）；这里的
    # option 只对新建列表生效，已有列表由 style_combobox_popdown() 刷新
    root.option_add("*TCombobox*Listbox.background", core.SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", core.TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", core.ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", core.ON_ACCENT)
    root.option_add("*TCombobox*Listbox.font", font_ui)

    style = ttk.Style(root)
    for name in ("clam", "alt", "default"):
        try:
            style.theme_use(name)      # clam 才吃下面这些扁平选项
            break
        except tk.TclError:
            continue

    # 按钮：扁平 + 1px 细边框，悬停只换底色（没有渐变、没有凸起阴影）；
    # 垂直 padding = BTN_PADY，与输入框同高（见 BTN_PADY 处的实测说明）
    style.configure("TButton", background=core.SURFACE, foreground=core.TEXT,
                    bordercolor=core.BORDER, lightcolor=core.BORDER,
                    darkcolor=core.BORDER, borderwidth=1, relief="flat",
                    padding=(BTN_PADX, BTN_PADY), font=font_ui, width=0)
    style.map("TButton",
              background=[("active", core.HOVER_BG),
                          ("pressed", core.PRESSED_BG),
                          ("disabled", core.APP_BG)],
              foreground=[("disabled", core.DISABLED_FG)],
              bordercolor=[("focus", core.ACCENT), ("active", core.BORDER)])
    # 主操作按钮：强调色实底（文字色按对比度自动选白/深色；padding 与普通
    # 按钮完全一致 -> 同排同宽等高，用户要求按钮尽量对齐）
    style.configure(ACCENT_STYLE, background=core.ACCENT,
                    foreground=core.ON_ACCENT, bordercolor=core.ACCENT,
                    padding=(BTN_PADX, BTN_PADY))
    style.map(ACCENT_STYLE,
              background=[("active", core.ACCENT_HOVER),
                          ("pressed", core.ACCENT_HOVER),
                          ("disabled", core.ACCENT_DIM)],
              foreground=[("disabled", core.ON_ACCENT_DISABLED)],
              bordercolor=[("active", core.ACCENT_HOVER),
                           ("focus", core.ACCENT_HOVER)])

    # 输入框（ttk.Entry）：与按钮同高的白色扁平面板 + 1px 细边框，
    # 焦点时边框变强调色。配色统一配在这里，调用点不再逐个 surface()
    style.configure("TEntry", background=core.SURFACE,
                    fieldbackground=core.SURFACE, foreground=core.TEXT,
                    bordercolor=core.BORDER, lightcolor=core.BORDER,
                    darkcolor=core.BORDER, borderwidth=1, relief="flat",
                    padding=(FIELD_PADX, FIELD_PADY), font=font_ui)
    style.map("TEntry",
              bordercolor=[("focus", core.ACCENT), ("active", core.BORDER)],
              foreground=[("disabled", core.DISABLED_FG)])

    # 可编辑下拉框（仓库浏览器地址栏）：与 TEntry 同色同高（本机
    # Combobox 底高 24，padding y=4 -> 32px）。下拉按钮的箭头用次要
    # 文字色，悬停时与输入框一样变强调色。
    style.configure("TCombobox", background=core.SURFACE,
                    fieldbackground=core.SURFACE, foreground=core.TEXT,
                    bordercolor=core.BORDER, lightcolor=core.BORDER,
                    darkcolor=core.BORDER, arrowcolor=core.MUTED,
                    borderwidth=1, relief="flat",
                    padding=(FIELD_PADX, FIELD_PADY), font=font_ui)
    style.map("TCombobox",
              fieldbackground=[("readonly", core.SURFACE),
                               ("disabled", core.APP_BG)],
              foreground=[("disabled", core.DISABLED_FG)],
              bordercolor=[("focus", core.ACCENT), ("active", core.BORDER)],
              arrowcolor=[("active", core.ACCENT)])

    # 笔记本：选中页签与页面同色，看起来是“当前项”而不是一块翘起的标签
    style.configure("TNotebook", background=core.APP_BG, borderwidth=0,
                    tabmargins=(4, 4, 0, 0))
    style.configure("TNotebook.Tab", background=core.TAB_BG,
                    foreground=core.MUTED, padding=(18, 8), borderwidth=0,
                    font=font_ui)
    style.map("TNotebook.Tab",
              background=[("selected", core.APP_BG),
                          ("active", core.TAB_HOVER_BG)],
              foreground=[("selected", core.TEXT), ("active", core.TEXT)])

    # 树：面板底色、28px 行高、表头浅色无边框、选中行用强调色（仓库浏览器的
    # 目录树与右侧列表）。**勾选字形放大版树样式已删除**：检出勾选树
    # 改成与改动列表同款的 tk.Text（本机 Treeview 一行只有一个字号，
    # 放大勾选字形会把目录名一起放大），勾字符串统一走 check_font()。
    style.configure("Treeview", background=core.SURFACE,
                    fieldbackground=core.SURFACE, foreground=core.TEXT,
                    bordercolor=core.BORDER, borderwidth=0, relief="flat",
                    rowheight=28, font=font_ui)
    style.configure("Treeview.Heading", background=core.HEAD_BG,
                    foreground=core.MUTED, relief="flat", borderwidth=0,
                    padding=(8, 7), font=font_bold)
    style.map("Treeview",
              background=[("selected", core.ACCENT)],
              foreground=[("selected", core.ON_ACCENT)])
    style.map("Treeview.Heading", background=[("active", core.TAB_HOVER_BG)])

    # 滚动条：细条，滑块浅色，轨道与页面同色
    style.configure("TScrollbar", background=core.SCROLL_BG,
                    troughcolor=core.APP_BG, bordercolor=core.APP_BG,
                    arrowcolor=core.MUTED, borderwidth=0, relief="flat",
                    width=10)
    style.map("TScrollbar", background=[("active", core.SCROLL_HOVER_BG)])

    style.configure("TCheckbutton", background=core.APP_BG,
                    foreground=core.TEXT, font=font_ui)
    style.map("TCheckbutton", background=[("active", core.APP_BG)],
              foreground=[("disabled", core.DISABLED_FG)])
    return font_ui


def surface(widget, mono=False):
    """把 tk 文本区刷成白色面板：1px 细边框 + 强调色选区。

    Tk 没有“按控件类”的 option 匹配（见模块注释），只能逐个调。
    只读文本区（改动列表、日志、差异窗口）与单行的提交说明走这里，
    保证观感一致。**输入框不走这里**——它们是 ttk.Entry，
    配色与高度统一在 apply_theme 的 TEntry 样式里。
    mono=True 再套等宽字体（日志/差异这类要对齐的内容）。
    """
    widget.configure(bg=core.SURFACE, fg=core.TEXT, relief="flat", bd=0,
                     highlightthickness=1, highlightbackground=core.BORDER,
                     highlightcolor=core.ACCENT, insertbackground=core.TEXT,
                     selectbackground=core.ACCENT,
                     selectforeground=core.ON_ACCENT)
    if mono:
        widget.configure(font=tkfont.Font(family=pick_family(widget, mono=True),
                                          size=base_size()))
    return widget


def style_combobox_popdown(widget):
    """把 ttk.Combobox 的下拉列表刷成当前皮肤。

    ttk.Combobox 弹出的是 Tk 经典 Listbox，不吃 ttk 样式；option 数据库只
    在列表第一次创建时生效，换肤后已有列表不会自动变色。调用方在
    postcommand（每次弹下拉之前）与 recolor 里再刷一次。列表尚未创建时
    调用 `ttk::combobox::PopdownWindow` 会顺手创建它，代价很小。
    """
    try:
        popdown = str(widget.tk.call("ttk::combobox::PopdownWindow", widget))
        lb = popdown + ".f.l"
        widget.tk.call(popdown, "configure", "-background", core.BORDER)
        widget.tk.call(lb, "configure",
                       "-background", core.SURFACE,
                       "-foreground", core.TEXT,
                       "-selectbackground", core.ACCENT,
                       "-selectforeground", core.ON_ACCENT,
                       "-borderwidth", 0, "-highlightthickness", 1,
                       "-highlightbackground", core.BORDER,
                       "-highlightcolor", core.BORDER,
                       "-font", (pick_family(widget), base_size()))
    except tk.TclError:
        pass


def make_menu(parent):
    """创建与平面主题一致的右键菜单（白底、1px 细边框、强调色悬停）。

    tk.Menu 不吃 ttk 样式，缺省是系统灰底 + 立体边框 + 系统字体的老式
    菜单，与本程序观感很不协调（用户反馈"右键菜单太丑"）——右键菜单
    一律从这里建：白底、扁平、悬停用强调色实底白字（与主操作按钮/
    选中行同一套配色）、字体跟主题正文族一致。

    **边框不能省**（borderwidth=1, relief="solid"）：菜单大概率弹在
    白色面板上（树/列表），纯白无边框时整个菜单跟背景糊成一片、只剩
    几行文字，看起来像"右键菜单没了"（20261016 用户实测）；relief=flat
    或 borderwidth=0 都一样不可见，实测只有 solid 能画出这条 1px 边。
    """
    return tk.Menu(
        parent, tearoff=0,
        background=core.SURFACE, foreground=core.TEXT,
        activebackground=core.ACCENT, activeforeground=core.ON_ACCENT,
        disabledforeground=core.MUTED, selectcolor=core.SURFACE,
        relief="solid", borderwidth=1, activeborderwidth=0,
        font=(pick_family(parent), base_size()))


# ---- 切换皮肤：把已有控件的旧色就地刷成新色 ----
# Tk 没有“重读 option 数据库”的机制，已有控件只能逐个改颜色。这里按
# “旧色值 -> 新色值”精确映射（只认色板里出现过的颜色），只动颜色选项与
# Text 标签颜色；文本内容、选中范围、滚动位置、勾选状态都不动，也不重建
# 控件。菜单与选中态按角色单独处理，避免“白色面板”与“主色上的白字”混淆。
_COLOR_OPTIONS = ("background", "foreground", "activebackground",
                  "activeforeground", "disabledforeground",
                  "highlightbackground", "highlightcolor",
                  "insertbackground", "selectbackground", "selectforeground",
                  "troughcolor", "fieldbackground")
_PALETTE_NAMES = ("APP_BG", "SURFACE", "BORDER", "TEXT", "MUTED", "ACCENT",
                  "ACCENT_HOVER", "ACCENT_ALT", "ACCENT_DIM", "HOVER_BG",
                  "PRESSED_BG", "HEAD_BG", "TAB_BG", "TAB_HOVER_BG",
                  "SCROLL_BG", "SCROLL_HOVER_BG", "DISABLED_FG",
                  "UP_HOVER_BG", "UP_CUR_BG")


def _palette_map(old, new):
    """旧色板 -> 新色板的精确颜色映射（不包含 ON_ACCENT）。"""
    mapping = {}
    for key in _PALETTE_NAMES:
        src, dst = old.get(key), new.get(key)
        if src and dst:
            mapping.setdefault(str(src).lower(), str(dst))
    for group in ("LOG_COLORS", "TREE_COLORS", "TREE_BG"):
        old_group = old.get(group) or {}
        new_group = new.get(group) or {}
        for key in old_group:
            src, dst = old_group[key], new_group.get(key)
            if src and dst:
                mapping.setdefault(str(src).lower(), str(dst))
    return mapping


def _recolor_widget(widget, mapping):
    try:
        cls = widget.winfo_class()
    except tk.TclError:
        return
    if cls == "Menu":
        try:
            widget.configure(background=core.SURFACE, foreground=core.TEXT,
                             activebackground=core.ACCENT,
                             activeforeground=core.ON_ACCENT,
                             disabledforeground=core.MUTED,
                             selectcolor=core.SURFACE)
        except tk.TclError:
            pass
    else:
        for opt in _COLOR_OPTIONS:
            try:
                cur = str(widget.cget(opt)).lower()
            except tk.TclError:
                continue
            dst = mapping.get(cur)
            if dst is not None and dst.lower() != cur:
                try:
                    widget.configure(**{opt: dst})
                except tk.TclError:
                    pass
    if cls == "TCombobox":
        # 已创建的下拉列表不跟 option 数据库走，换肤时单独刷一次
        style_combobox_popdown(widget)
    if cls == "Text":
        try:
            widget.configure(insertbackground=core.TEXT,
                             selectbackground=core.ACCENT,
                             selectforeground=core.ON_ACCENT)
            for tag in widget.tag_names():
                for opt in ("foreground", "background"):
                    try:
                        cur = str(widget.tag_cget(tag, opt)).lower()
                    except tk.TclError:
                        continue
                    dst = mapping.get(cur)
                    if dst is not None and dst.lower() != cur:
                        widget.tag_configure(tag, **{opt: dst})
        except tk.TclError:
            pass
    if isinstance(widget, CheckBox):
        try:
            widget.refresh_theme()
        except tk.TclError:
            pass
    try:
        children = widget.winfo_children()
    except tk.TclError:
        return
    for child in children:
        _recolor_widget(child, mapping)


def recolor(root, old_palette):
    """把 root 及所有子窗口的旧皮肤颜色就地刷成当前 core 色板。

    old_palette 是切换前的 core.current_palette() 快照。只改颜色选项与
    Text 标签颜色；文本内容、选中范围、滚动位置、勾选状态都不动。
    """
    mapping = _palette_map(old_palette or {}, core.current_palette())
    if not mapping:
        return
    try:
        root.configure(bg=core.APP_BG)
    except tk.TclError:
        pass
    _recolor_widget(root, mapping)


# 窗口装饰偏移标定结果 (left, top)：用户机上的 WM（DDE/KWin）把
# `wm geometry +x+y` 的坐标当作**框架**（含标题栏）左上角，客户区实际
# 还要再偏移 (left, top)（实测 +1/+41）。center_on_parent 第一次定位
# 后量出来缓存到这里，之后的弹窗直接用它修正；None = 还没标定。
_DECOR = None
# 标定参数（秒）：窗口刚 map 时 WM 往往还没加上标题栏，此时量到的
# (1, 1) 是“未装饰”的暂态；必须等窗口映射稳定一段时间再认。测试里
# 事件循环按 20ms 泵、首次 map 后 50ms 才摆好，之前只要求“连续两次
# 相同”会把这个暂态缓存成 (1, 1)，之后所有弹窗整体偏低一个标题栏。
_CALIBRATE_MIN_WAIT = 0.12
_CALIBRATE_INTERVAL = 0.02
_CALIBRATE_MAX_TRIES = 100


def center_on_parent(win, parent=None):
    """把新弹出的 Toplevel 摆到父窗口正中（用户要求：弹窗基于父窗口居中，
    不要都偏到左上角）。

    尺寸优先取窗口当前大小（显式 geometry 在 update_idletasks 后即可读到，
    未映射也能读），未定尺寸（按内容自适应）时退回请求大小，并至少不小于
    窗口自己的 minsize——实际以 max(请求大小, minsize) 出现，不取大值会
    偏一点。摆位后仍越出屏幕边缘时收进屏幕内（父窗贴着屏幕边、或弹窗比
    屏幕还大时，不至于把标题栏/按钮区推到屏幕外）。

    部分 WM（本机 DDE/KWin 实测）把请求位置当“框架左上角”，客户区整体
    再偏 (1, 41)——不修正的话每个弹窗都偏低一个标题栏。首次定位后由
    _calibrate 量出偏移并修正（结果缓存，一次标定全程受益）。

    parent 缺省用 win.master（弹窗都直接挂在父窗上）。调用时机：内容
    建完之后、grab_set/wait_window 之前（尺寸才准，也避免窗口先闪在
    左上角再跳）。

    同时把窗口登记为父窗的 transient（wm transient）：WM 据此把它
    **始终压在父窗口之上**——点主窗时主窗不会盖住提交历史、仓库浏览器、
    内置差异等子窗口（用户要求“子窗口应该一直在主窗口之上”）。新增
    子窗口都必须走本函数，别只调 geometry 摆位。
    """
    global _DECOR
    if parent is None:
        parent = win.master
    try:
        win.transient(parent.winfo_toplevel())   # 子窗口始终压在父窗之上
    except (tk.TclError, AttributeError):
        pass
    try:
        win.update_idletasks()
        w, h = win.winfo_width(), win.winfo_height()
        if w <= 1 or h <= 1:
            w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        mw, mh = win.minsize()
        if mw > 1:
            w = max(w, mw)
        if mh > 1:
            h = max(h, mh)
        dl, dt = _DECOR or (0, 0)
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2 - dl
        y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2 - dt
        x = max(0, min(x, win.winfo_screenwidth() - w))
        y = max(0, min(y, win.winfo_screenheight() - h))
    except tk.TclError:
        return
    win.geometry("+%d+%d" % (x, y))
    if _DECOR is None:
        _calibrate(win, x, y)


def install_modal_guard(win):
    """给模态窗口加最小化防护：不让它“消失”后还攥着 Tk 抓取。

    模态窗靠 grab_set + wait_window 阻塞父窗口；用户把它最小化后窗口只是
    不可见，grab 仍然生效，主窗口点哪儿都没反应，看起来像程序卡死
    （用户反馈）。这里做两件事：

      - X11 下把窗口类型标成 dialog：多数 WM 会隐藏/禁用最小化按钮；
      - 监听 <Unmap>：一旦发现窗口进入 iconic（被最小化）就 after_idle
        还原（deiconify + lift），相当于“不给最小化”。

    **不要**改成“最小化时释放 grab”：认证/确认期间主窗口若能操作，会
    启动新任务、弹出嵌套模态框，单任务与状态机都会乱。真正需要用户
    决策的窗口保留模态语义，只加这层防护。非模态窗口不要调用本函数。

    调用时机：窗口**映射之前**（`-type` 在映射后再改，部分 WM 不认）。
    """
    try:
        win.attributes("-type", "dialog")
    except tk.TclError:
        pass                        # 某些平台/WM 不支持 -type，忽略
    state = {"pending": False}

    def restore():
        state["pending"] = False
        try:
            if not win.winfo_exists():
                return
            if win.state() == "iconic":
                win.deiconify()
                win.lift()
        except tk.TclError:
            pass

    def on_unmap(_event=None):
        # 收起、销毁都会触发 Unmap；只在 idle 时复查状态，避免误还原
        if state["pending"]:
            return
        state["pending"] = True
        try:
            win.after_idle(restore)
        except tk.TclError:
            state["pending"] = False

    win.bind("<Unmap>", on_unmap, add="+")


def _calibrate(win, rx, ry):
    """标定 WM 的框架偏移，并把第一个弹窗也修正到真正居中的位置。

    做法：定位后周期性量窗口实际客户区位置，与请求的 (rx, ry) 相减就是
    偏移（WM 把请求位置当框架左上角时 = 边框/标题栏厚度；KWin 实测 map
    后 ~18ms 摆完）。**不能只量一次**：新窗口在 WM 应用请求位置之前会先
    按默认摆位出现（本机 KWin 实测 = 父窗 +(40,21) 的层叠位，客户区在
    请求位置左上、偏移为负），只量一次就可能把这串乱值当装饰偏移缓存，
    之后所有弹窗全偏（20261016 实测踩过）。

    判定过三道闸：偏移必须“合理”——0 <= 偏移 < 200（客户区在框架内，
    装饰只可能把客户区往右下推；负值说明请求还没生效）；窗口已映射至少
    `_CALIBRATE_MIN_WAIT`（刚 map 的那几十毫秒 WM 可能还没加标题栏，
    这时量到的 (1, 1) 是暂态，见下方注释）；且**连续两次量到同一个值**
    （WM 摆稳了才会稳定）。量不到（窗口已销毁 / WM 根本不按请求摆位）
    就放弃、不缓存，后续弹窗继续按未修正坐标摆（比乱修强）。标定一次
    就够：缓存进 _DECOR 后不再采样。

    20261106 实测：测试进程里窗口 map 后的第一次采样仍可能是未装饰的
    暂态 (1, 1)，第二次（约 20ms 后）才是真正的 (1, 41)——只看“连续
    两次相同”会把 (1, 1) 缓存下来，之后所有弹窗偏低 40px。所以先等
    窗口映射满 `_CALIBRATE_MIN_WAIT` 再开始认值。
    """
    global _DECOR
    state = {"last": None, "tries": 0, "mapped_at": None}

    def sample():
        global _DECOR
        state["tries"] += 1
        try:
            dx = win.winfo_rootx() - rx
            dy = win.winfo_rooty() - ry
            mapped = bool(win.winfo_ismapped())
        except tk.TclError:
            return                      # 窗口已销毁：不缓存，留给下次标定
        if mapped:
            now = time.monotonic()
            if state["mapped_at"] is None:
                state["mapped_at"] = now
            settled = now - state["mapped_at"] >= _CALIBRATE_MIN_WAIT
        else:
            state["mapped_at"] = None
            settled = False
        if settled and 0 <= dx < 200 and 0 <= dy < 200:
            if state["last"] == (dx, dy):       # 连续两次一样：WM 已摆稳
                _DECOR = (dx, dy)
                if dx or dy:
                    try:            # 第一个弹窗也挪到真正居中的位置
                        win.geometry("+%d+%d" % (max(0, rx - dx),
                                                 max(0, ry - dy)))
                    except tk.TclError:
                        pass
                return
            state["last"] = (dx, dy)
        else:
            state["last"] = None        # 请求还没生效/未装饰暂态/未映射
        if state["tries"] < _CALIBRATE_MAX_TRIES:
            try:
                win.after(int(_CALIBRATE_INTERVAL * 1000), sample)
            except tk.TclError:
                pass

    try:
        win.after(int(_CALIBRATE_INTERVAL * 1000), sample)
    except tk.TclError:
        pass


class CheckBox(tk.Frame):
    """☑/☐ 文字复选框：与改动列表的勾选框同一观感。

    取代 tk/ttk 的 Checkbutton——clam 主题的指示符选中后是一个“叉”，
    tk.Checkbutton 的小方框也放大不到改动列表那样；本控件把改动列表的
    勾选字形（CHECK_ON/CHECK_OFF、大号加粗）搬进一个可点击的行：

      - 字形单独用大号加粗（base + UP_CHECK_DELTA），文字保持正常字号，
        和改动列表“字形大、正文正常”的比例一致；
      - 勾选后字形用强调色，未勾选用弱化色，禁用置灰；
      - 变量仍是 tk.BooleanVar（.get()/.set() 语义照旧），点击行内任意
        位置翻转；invoke() 供程序化触发（与 Checkbutton 用法一致），
        configure(state="disabled") 可禁用（禁用时点击无效）。

    用法：`theme.CheckBox(win, text=u"…", variable=var, command=…)`，
    pack/grid 布局照常。
    """

    def __init__(self, parent, text=u"", variable=None, command=None,
                 state="normal", **kw):
        tk.Frame.__init__(self, parent, **kw)
        self._var = (variable if variable is not None
                     else tk.BooleanVar(value=False))
        self._cmd = command
        self._state = str(state)
        self._text = text
        self._glyph_font = check_font(self)
        self.glyph = tk.Label(self, font=self._glyph_font)
        self.label = tk.Label(self, text=text)
        self.glyph.pack(side="left")
        self.label.pack(side="left", padx=(4, 0))
        for w in (self, self.glyph, self.label):
            w.bind("<Button-1>", self._click, add="+")
        self._paint()

    # ---- 与 tk.Checkbutton 兼容的最小接口（现有调用点与测试用到的）----
    def invoke(self):
        """翻转勾选并执行 command；禁用时不做任何事。"""
        if self._state == "disabled":
            return
        self._var.set(not bool(self._var.get()))
        self._paint()
        if self._cmd:
            self._cmd()

    def get(self):
        return bool(self._var.get())

    def set(self, on):
        self._var.set(bool(on))
        self._paint()

    def configure(self, cnf=None, **kw):
        """支持 state / text 两项；其余原样交给 Frame（照常报错）。"""
        merged = dict(cnf or {})
        merged.update(kw)
        state = merged.pop("state", None)
        text = merged.pop("text", None)
        if state is not None:
            self._state = str(state)
            self._paint()
        if text is not None:
            self._text = str(text)
            self.label.configure(text=self._text)
        if merged:
            tk.Frame.configure(self, merged)
        return self

    config = configure

    def refresh_theme(self):
        """按当前 core 色板重刷字形/文字颜色（切换皮肤时由 recolor 调用）。"""
        self._paint()

    # ---------- 内部 ----------
    def _click(self, _event=None):
        self.invoke()

    def _paint(self):
        on = bool(self._var.get())
        off = self._state == "disabled"
        self.glyph.configure(text=CHECK_ON if on else CHECK_OFF,
                             fg=core.DISABLED_FG if off else
                             (core.ACCENT if on else core.MUTED))
        self.label.configure(fg=core.DISABLED_FG if off else core.TEXT)
