# AGENTS.md

模块化桌面应用 **SVNWorkBench**：入口 `SVNWorkBench.py`（约 70 行薄壳，
只 import 并兼容再导出）+ `svnwb/` 包（`app.py` 约 1655 行主界面、
`repo_browser.py` 约 2255 行仓库浏览器、`log_view.py` 提交历史窗口、
`core.py` 常量/纯函数/皮肤库与配色计算、`runner.py` svn 执行线程、
`hub.py` 任务调度、`dialogs.py` 弹窗与内置差异窗口、
`theme.py` 平面化主题与换肤、`config_store.py` 配置）+ `scripts/` 下的
打包/右键菜单脚本（根目录 `1-构建-打包绿色单文件.sh`、
`2-清理-构建产物与缓存.sh`，以及 `scripts/right-menu/UOS/`、
`scripts/right-menu/Kylin-V10/`、`scripts/right-menu/Kylin-V10-SP1/`
下的 `1-安装…` / `2-卸载…`，正本；编号与目录约定见
`scripts/README.md`）、`README.md` 和 `tests/` 回归测试脚本。
无包管理、无框架、无测试框架（`tests/` 是可直接运行的普通脚本）、无 CI。

**下载只有一个入口**：仓库浏览器的检出对话框（SVN 地址行的"仓库浏览" ->
右键"检出到…"）。原"下载"标签页与"预览命令"已整体删除，**不要再往
主界面加下载表单**。主界面只有"工作副本"一页（**不套标签页**——
笔记本页签那行高度被砍掉是为了让改动列表更高，用户明确要求过），
工作副本是唯一标识，选目录 -> `svn info` 自动反查地址回填 -> 改动列表
（双击某行弹出对比窗口），**不要再拆回多个标签页、也不要恢复
多项目/导入脚本、不要恢复"列表范围"单选**；
地址/目录/排除清单的持久化
只在 `~/.config/SVNWorkBench/_settings.json`（字段由 `store.update_fields` /
`store.set_option` 写入），检出或更新成功后由 `App._checkout_from_browser`
自动回写并用 `App._set_form` 带回界面。

## 硬约束（最容易踩的坑）

- **必须兼容 Python 3.5.2+**（目标机器是老系统自带的 Python）：
  - 禁止 f-string，用 `%` 格式化或 `.format()`
  - 禁止 `subprocess` 的 `text=`/`encoding=` 参数；用字节模式读输出
    再自行 decode（见 `Runner._exec_stream` 附近的注释）
  - 禁止 `subprocess.run` 等新 API
  - 只用标准库，**不引入任何第三方依赖**（README 明确承诺"零第三方依赖"）
  - tkinter 属标准库但需要系统包：Debian/Ubuntu 需 `python3-tk`，
    README 已注明；代码里已有缺库时的友好报错，勿删
- **工程名 = SVNWorkBench，包名 = `svnwb`，全仓库不得再出现旧工程名
  与旧包名的字样**（用户 5.0 改名时明确要求，覆盖 README、AGENTS、
  注释、临时文件前缀、环境变量名、打包产物名；下文一律用"旧名"代指）。
  环境变量前缀统一 `SVNWB_`。
- **文件组织 = 入口壳 + `svnwb/` 包，按职责拆分**；业务逻辑一律放在包里，
  入口 `SVNWorkBench.py` 只 import 并做兼容再导出（约 70 行，别往里加
  实现）。包内划分：
  - `core.py`：**不依赖 tkinter** 的常量/纯函数 + 界面文案配色常量 +
    `THEMES` 皮肤库与配色计算（`palette_for` / `apply_palette` /
    `current_palette` / `normalize_theme`、对比度助手）
    （放这里是为了让 `app.py` 与 `repo_browser.py` 共用而不循环导入）
  - `theme.py`：平面化主题与换肤（`apply_theme` 按当前 core 色板配 ttk
    样式与 option 数据库、`recolor` 把已有控件从旧色板迁到新色板、
    `surface()` 把 tk 输入框刷成面板色、`make_menu` 统一菜单样式、
    `pick_family` 挑中文字体族、`check_font(widget, mono=False)` 给勾选框
    字形挑放大加粗档位、`CheckBox` 全程序统一的文字复选框）
  - `config_store.py`、`runner.py`、`hub.py`、`dialogs.py`（弹窗与内置
    差异窗口，含登录凭据窗口 `show_credentials`、对比方式选择
    `ask_diff_mode`）、`app.py`、
    `repo_browser.py`（`RepoBrowser` / `CheckoutSelect` / `LsWorker`）、
    `log_view.py`（`LogView`，提交历史窗口，同样由 `App._open_log_view`
    懒加载）
  不要新建模板/静态资源目录；部署交付拷贝 `dist/` 整个目录（打包脚本
  生成：exe + 右键菜单脚本）。源码部署时程序目录只需入口 py + `svnwb/`
  （`tests/` 仅随仓库做回归测试，不参与部署；`configs/` 目录已删除——
  旧配置迁移源不再随工程提供，但迁移代码保留）。
  `svnwb/repo_browser.py` 顶部 `from . import core, dialogs, theme`、
  `from .app import App`（只借用 `App.browse_dir`）、
  `from .runner import Runner`——包内相对导入，以 `__main__` 方式运行入口
  也不会加载出第二份模块（旧的 `sys.modules.setdefault(...)` 别名已随重构
  删除，**不要再加回来**）。
  该模块由 `App._open_repo_browser` 懒加载，缺文件时主程序其余功能不受影响。
- **弹窗调用一律写 `dialogs.ask_confirm(...)` 这种模块属性形式**
  （`app.py` / `repo_browser.py` 顶部 `from . import dialogs`），**不要**
  `from .dialogs import ask_confirm`：测试靠 `m.dialogs.ask_confirm = ...`
  整体替换，晚绑定才生效。同理，测试改写迁移源用
  `m.config_store.LEGACY_SETTINGS`（改 `m.LEGACY_SETTINGS` 无效）。
- **版本号只有一处**：`svnwb/core.py` 顶部的 `APP_VERSION`
  （标题栏与 `main()` 的启动打印都从这里取）。窗口标题用 `APP_TITLE`
  （= `APP_NAME` = `SVNWorkBench`）。
- 用户可见文案（界面、提示、README、日志）一律**中文**，与现有文本风格一致。
- **配置在 `~/.config/SVNWorkBench/_settings.json`**（`core.default_config_dir()`，
  尊重 `XDG_CONFIG_HOME`；环境变量 `SVNWB_CONFIG_DIR` 可覆盖，tests/ 指向
  /tmp）：工作副本、SVN 地址、排除清单、证书选项、对比方式（`diff_tool`：
  ask / meld / builtin）、皮肤（`theme`，默认晴空，非法值由
  `normalize_theme` 回退）、仓库浏览器最近地址（`recent_repo_urls`：
  最新在前、按 `core.normalize_svn_url` 去重、最多 `core.RECENT_URL_LIMIT`
  = 10 条，由 `core.normalize_recent_urls` / `push_recent_url` 整理）。
  **工作副本与 SVN 地址只在反查成功（确认是有效工作副本）后落盘**：
  用户输入非法路径/不是工作副本时 `_save_form` 直接跳过；启动时
  `_load_settings` 发现配置里的 `dst` 不存在（或不是目录）会同时清掉
  `dst` 与 `svn_url`，`_startup_refresh` 读到"不是工作副本"也会清掉，
  避免下次启动显示非法路径和残留地址（用户要求）。
  不要硬编码改写；
  写入是原子的（`.tmp` + `os.replace`），保持这一做法。
  旧版（v4 及以前）配置在程序同级 `configs/_settings.json`，由
  `config_store._migrate()` 从 `LEGACY_SETTINGS`（环境变量
  `SVNWB_LEGACY_SETTINGS` 可覆盖）**一次性**迁入：只搬还没填过的字段，
  搬完打 `migrated` 标记，旧文件原样保留（不删用户数据）。**工程里的
  `configs/` 目录已删除**（20261014，迁移早已完成），但迁移代码与测试
  保留——旧版本用户把新 exe 放进带旧配置的目录仍要能迁，**别顺手删**。
  老的网页版单文件 / 多项目分文件迁移已整体删除，**不要恢复**（那些
  旧文件名里带旧工程名）。
- **运行日志在 `/tmp/SVNWorkBench-<用户名>/logs/`**（`log_dir()`，
  按用户名分子目录避免多用户互踩权限，重启即清；
  `SVNWB_LOG_DIR` 可覆盖，tests/ 用 `SVNWB_TEST_TMP` 指向独立临时目录），
  **不要放回程序目录或 `configs/`**——配置与日志必须分开。
- **目录选择**走 `App.browse_dir`：优先 `zenity`（跟随系统语言），
  不可用时回退 `filedialog.askdirectory`；两条路径都要保持可用，
  取消一律返回 `None`（不要用异常表达取消）。
- **界面样式只在 `svnwb/theme.py` 一处配**（平面化三招：配色 / 扁平化 /
  内边距），新增 tk 控件时跟着两条时序走，否则会出现"有的控件是灰底、
  有的还是立体边"：
  - `theme.apply_theme(root)` **必须在建任何控件之前**调用一次（`App.__init__`
    里已经调过）——tk 控件的默认底色/前景/字体是靠 option 数据库传下去的；
    ttk 样式按 Tk 解释器全局生效，所以弹窗/浏览器的 Toplevel 自动继承，
    不用逐窗再设
  - **10 套皮肤（换肤）**：`core.THEMES` 是唯一数据源（用户给定，键名/
    色值保持原样），`THEME_DEFAULT = "晴空"`，`THEME_ORDER` 是菜单与测试
    的固定顺序（Python 3.5 的 dict 无序，**别用 THEMES 迭代顺序**）。
    `core.apply_palette(name)` 按 8 个主题键算出整套语义色并写入 core 的
    模块级常量（`APP_BG`/`SURFACE`/`BORDER`/`TEXT`/`MUTED`/`ACCENT`/
    `ACCENT_HOVER`/`ACCENT_ALT`/`ACCENT_DIM`/.../`TREE_BG`），
    `palette_for` 是纯函数版，`normalize_theme` 把缺失/非法值回退晴空。
    `App.__init__` 的顺序必须是：normalize 配置里的 `theme` ->
    `core.apply_palette` -> `theme.apply_theme(root)` -> 再建控件。
    `App._set_theme` 的顺序：取旧快照 `core.current_palette()` ->
    `core.apply_palette` -> `theme.apply_theme` -> `theme.recolor(root, 旧)`
    -> 写配置；**不重建控件、不重新渲染列表、不弹 toast**（会把任务结果
    盖掉），文本/选中/滚动/勾选/当前行/busy 状态一律不动。
    新增颜色必须同时加进 `core._PALETTE_KEYS` 和
    `theme._PALETTE_NAMES`，否则已有窗口换肤时不会跟着变。
    控件代码一律读 `core.XXX` 模块属性（晚绑定）；**不要**在 app/dialogs/
    repo_browser/log_view 顶部 `from .core import ACCENT` 拿导入时快照——
    换肤后它不会更新（测试同理，断言当前色用 `m.core.ACCENT`）。
    状态色保持语义（修改蓝/新增绿/删除红/冲突橙），只由 `ensure_contrast`
    按面板明暗调亮度；主色上的文字用 `ON_ACCENT`（白字对比度 < 2.8 时
    自动换深色）；菜单、CheckBox、Text 标签由 `recolor` 按旧色→新色精确
    映射，菜单另有角色特判（activebackground 用 ACCENT、activeforeground
    用 ON_ACCENT）。顶栏"主题"按钮 -> `_fill_theme_menu` /
    `_show_theme_menu`，配置字段 `theme`，回归测试 `tests/test_theme.py`。
  - tk 的输入框/文本区**不吃 ttk 样式、也没有"按控件类"的 option 匹配**
    （Tk 按控件名匹配，自动名是小写 entry/text/frame 还带 entry2 后缀），
    所以**输入框一律用 ttk.Entry**（扁平配色与 32px 高度统一配在
    apply_theme 的 TEntry 样式里；tk.Entry 没有 ipady/height 选项、
    高只有 24px，与按钮并排不协调——用户反馈）；tk.Text（提交说明、
    改动列表、日志、差异窗口）仍要逐个 `theme.surface(w)` 刷成面板色。
    仓库浏览器地址栏是 `ttk.Combobox`，同色同高（TCombobox 样式，本机
    底高 24、padding y=4 -> 32px）；它弹出的列表是 Tk 经典 Listbox，
    option 数据库只在首次创建时生效，换肤后已有列表要靠
    `theme.style_combobox_popdown(widget)` 刷新（`recolor` 已调用，
    调用方另在 `postcommand` 里刷一次）。ttk 控件
    （Button/Treeview/Scrollbar）不用管，主题已覆盖。
    **控件高度全程序统一 32px**：按钮 padding y=`BTN_PADY`(3)、
    输入框 y=`FIELD_PADY`(4)、单行 Text `SINGLE_LINE_PADY`(5)——三个常量
    在 theme.py，都指向 32，调一个必须三个一起对齐（换字体时同步漂移）。
    主窗口三个行标签（工作副本/SVN 地址/提交说明）**定宽 8 字符**，
    三行输入框左边缘才对得齐，别删掉 width=8。
    **主界面按钮定宽对列**（用户要求大小统一、排版对齐）：同一排按钮
    用同一个 ttk `width`（单位=字符宽，1 汉字≈2 单位，本机 7px；常量
    `theme.BTN_W`(8，≤4 汉字) / `BTN_W_LONG`(12，≤6 汉字)），等距 6px
    排列；每排最右按钮统一 BTN_W，各排（含顶栏/日志行/状态栏，
    它们的右边距做成 10+6=16）按钮右缘对齐成一条竖线。**改按钮文案
    别超过定宽**（ttk 会把文字裁掉；量宽用 `winfo_reqwidth()`）。
    辅助窗口的同一排按钮也统一宽度（按文案选标准宽/长名宽）、右缘
    对齐（确认框、对比方式、认证/证书、运行日志、凭据、检出对话框、
    仓库浏览器、内容窗口、提交历史都一样）。
  - 主操作按钮加 `style=theme.ACCENT_STYLE`（强调色实底，文字色用
    `core.ON_ACCENT` 按对比度自动选白/深色），次要按钮保持默认 `TButton`
  - 本机 Tk 8.6.9 对 ttk.Treeview 的**行级**标签着色完全不生效，主题救不了
    它——需要逐行颜色的地方继续用 `tk.Text`（改动列表就是这么做的）。
  - **复选框全程序统一**：独立复选控件用 `theme.CheckBox`，行内复选框
    （改动列表、检出勾选列表）用同一个字形字体 `theme.check_font`
    （☐/☑ 字形 = base+`UP_CHECK_DELTA` 号加粗，勾选强调色 / 未勾选灰色 /
    禁用置灰；`CheckBox` 变量仍是 `tk.BooleanVar`，接口兼容
    `invoke()/get()/set()/configure(state,text)`）。不要再用
    `tk.Checkbutton`（小方框看不清）或 ttk `Checkbutton`（clam 指示符
    选中是个"叉"）。检出对话框的勾选列表已改为 `tk.Text` 行内大字形
    ☑/☐（与改动列表同款），旧的 `CHECK_STYLE`（`Check.Treeview`，
    因为"Treeview 一行只有一个字号"只能与目录名同字号不加粗）**已删除，
    别再加回来**。
  - **右键菜单一律用 `theme.make_menu(parent)`**：`tk.Menu` 不吃 ttk
    样式，缺省是系统灰底 + 立体边的老式菜单，与平面主题很不协调
    （用户反馈"太丑"）——统一面板底色、悬停强调色实底（文字用
    `core.ON_ACCENT`）、主题字体，
    **外加 1px 实线细边框（`borderwidth=1, relief="solid"`，不能省）**：
    菜单基本都弹在白色面板（树/列表）上，纯白无边框会与背景糊成一片、
    看起来像"右键菜单没了"（20261016 用户反馈）；新增右键菜单别再
    直接 `tk.Menu(...)`。
  - **弹窗一律基于父窗口居中**（用户要求，原来都偏左上角）：内容建完后、
    `grab_set`/`wait_window` 之前调 `theme.center_on_parent(win, parent)`
    （parent 缺省 `win.master`）。`_dialog` 骨架**不预设位置**（建时还
    量不到尺寸），谁建内容谁负责调用。**该函数同时把窗口登记为父窗的
    `transient`**（`win.transient(parent.winfo_toplevel())`；20261016
    用户要求"子窗口应该一直在主窗口之上"）：WM 据此把子窗始终压在父窗
    之上——点主窗、主窗被置前时也不会盖住提交历史 / 仓库浏览器 / 内置
    差异等子窗口（本机 KWin 实测过：没有 transient 时主窗一置前就把
    子窗盖住）。新增子窗口都必须走它，别只调 geometry 摆位。
    部分 WM（本机 DDE/KWin 实测）把 `wm geometry +x+y` 的坐标当
    **框架**（含标题栏）左上角，客户区还要
    偏 (1, 41)——`center_on_parent` 首次定位后用 `theme._calibrate`
    异步量出这个偏移并缓存（`theme._DECOR`），第一个弹窗也会被修正，
    一次标定全程受益。**标定不能只量一次**：新窗口在 WM 应用请求位置
    之前会先按默认摆位出现（本机 KWin = 父窗 +(40,21) 的层叠位，客户区
    偏移为负），只量一次会把这串乱值当标定缓存、之后所有弹窗全偏
    （20261016 实测踩过）——所以只认“合理”偏移（0 <= 偏移 < 200px，
    负值 = 请求还没生效）、窗口**映射满 `_CALIBRATE_MIN_WAIT`（0.12s）**
    且必须**连续两次量到同一个值**；量不到（窗口已销毁 / WM 不按请求
    摆位）就放弃不缓存，留给下个弹窗再标。映射满 0.12s 那道闸是后加的：
    窗口刚 map 时 WM 还没加标题栏，会量到未装饰的 (1,1) 暂态，事件循环
    泵得快时连续两次都可能是它，缓存后所有弹窗整体偏低 40px
    （20261106 测试实测）。新增弹窗时**这个调用不能省**，否则又会偏一个
    标题栏。
  - **模态窗口禁止/自动恢复最小化**（20261110 用户反馈"最小化子窗口后
    主窗口像卡死"）：`grab_set` 在窗口被最小化后仍然生效，只是窗口看不见，
    父窗口自然点不动。所有 `_dialog` 弹窗与 `CheckoutSelect` 都调
    `theme.install_modal_guard(win)`（**窗口映射前**调用）：X11 下
    `win.attributes("-type", "dialog")`（多数 WM 因此不提供最小化），
    并绑定 `<Unmap>`，发现 `state()=="iconic"` 就 `after_idle` 执行
    `deiconify + lift`。**不要**
    改成"最小化时释放 grab"——认证/确认期间主窗口可操作会启动新任务、
    弹出嵌套模态框，单任务与状态机都会乱。非模态窗口（仓库浏览器、提交
    历史、内置差异、查看内容）不要调用本函数，它们本来就不阻塞主窗口。
  - **确认框内容区限高可滚动**：`ask_confirm` 用只读 `tk.Text`（最高
    12 行，并按屏幕高度继续收紧）+ 垂直滚动条，按钮条先按底部 pack。
    提交清单/提交说明再长也不能把确认按钮顶出屏幕（20261110 用户反馈
    “确认按钮超出屏幕无法点击”）。别改回无高度上限的 `Label`，也别只
    按行数截断——用户需要能滚动看完整清单。

## 线程与事件（改界面前必读）

- **禁止在非主线程直接操作 Tk 控件**：`Runner` 与 `Hub._pump` 线程只把
  事件放进 `Hub.events`（`queue.Queue`），主线程 `App._poll` 每 80ms
  取出后调用 `_handle_event` 刷新界面。地址反查（`App._probe_url` 的
  后台线程）同理只把结果放进 `App.probe_q`，由 `_poll` 里的
  `_drain_probe()` 取用——**不要改成在工作线程里直接动 Entry**。
- 认证/证书弹窗由 `svnwb/dialogs.py` 的 `ask_auth`/`ask_cert` 打开模态框
  （`grab_set` +
  `wait_window`，期间轮询照常运行），答复经 `Hub.respond` 回传
  `Runner.auth_q`。密码打码只在 `cmd_str` 一处实现：其他地方打印原始
  命令列表会泄露密码。
- **根窗口布局用 grid**（见 `App._build`），不要改回 pack：pack 在窗口
  不够高时会把状态栏整体挤出可视区，grid 会压缩中间的区域。
- 日志区对高频输出做了限流（最多保留 2000 行、贴近底部才自动滚动），
  大检出时改坏这三点会卡死界面。
- **运行日志默认折叠**（`App._build_log` 只 pack 标题行，
  `self.log_expanded` 记状态）：**任务启动时也不再自动展开**（用户要求，
  `_set_busy` 里别加回 `_set_log_expanded(True)`），只有用户点标题
  （`_toggle_log`）才展开/收起，状态保持到下次点击。
  标题行右侧固定两个按钮：`清空显示`（`_clear_log`）与它后面的
  `日志文件`（`_show_logs`，用户要求从顶栏挪到这里）。
  收起用 `log_body.pack_forget()`——**折叠时控件未映射，键事件到不了
  log Text**，测试要先展开才能做快捷键断言。
- **运行结果显示在状态栏右下角且常驻**（`App._toast`，成功绿/警告橙/
  失败红/进行中提示蓝 `info`）：没有自动清除定时器，**只有下一条结果
  才覆盖它**（用户要求；别再引入 `_toast_timer` / `_clear_toast`）。自动
  （quiet）任务完成时**不弹结果**（`_run_start` 记 `self._quiet_runs`、
  `_handle_done` 消费），否则"提交成功 / 已删除所选条目"会被随后的自动
  状态刷新立刻盖掉。
- **通知类失败用 `App._notify(title, message, kind)`，不要再弹系统
  `messagebox`**：任务完成但失败、`_run_start` 的 BusyError/ApiError、
  仓库浏览器/提交历史打开失败都只是"告诉用户发生了什么"，不需要当场
  选择。`_notify` 把首行写到状态栏常驻结果、完整内容写进运行日志，绝不
  阻塞主窗口（系统 messagebox 是 Tk 内部模态窗，最小化后 grab 仍生效，
  用户会以为程序卡死）。运行日志/登录凭据窗口内的"请先选中…"等提示写在
  窗口自己的提示 Label 里，也不要用 messagebox；只有确认、认证、证书、
  检出/更新等真正需要决策的流程保留 `grab_set + wait_window` 模态窗口
  （并套 `theme.install_modal_guard`）。
- **仓库浏览器有自己的一套轮询**：`LsWorker`（`svnwb/repo_browser.py` 内，
  子类化 `Runner` 但覆盖 `run()` 为任务队列循环、`log()` 为空实现）
  把事件放进自己的队列，`RepoBrowser._poll` 每 80ms 取出按
  `("ls",(kind,url),...)` 的 tag 路由：kind = node/cat 给浏览器
  （`_on_node_ls` / `_on_cat`；cat 的 payload 是原始字节，其余是行列表），
  checkout/stat 给当前 `CheckoutSelect`。
  **`after` 必须排在处理完事件之后**：认证/证书弹窗阻塞期间不能有
  第二个 poll 链在跑，否则会出现嵌套弹窗。它不走 `Hub`，因此浏览
  不会触发 `BusyError`，也绝不往主日志区/日志文件写东西。

## 验证方式

回归测试在 `tests/`（普通脚本，直接运行，需要图形环境 DISPLAY；
运行时把配置与临时数据指向系统临时目录下的独立子目录，
`tests/_testtmp.py` 负责创建并在退出时清理，可用 `SVNWB_TEST_TMP`
指定固定目录保留现场）：

```bash
python3 tests/test_e2e.py      # 53 项：端到端（启动时自动重建本地 file:// 测试仓库，可重复跑）
                               #   含配置迁移（旧 configs/_settings.json -> ~/.config）、
                               #   配置/日志默认落点、启动参数（合法才写配置）、
                               #   非法工作副本不落盘/重启清理、工作副本变化自动反查并刷新、
                               #   日志目录、日志默认折叠、
                               #   状态排序与忽略文件（*.so）、键盘选择（含 Shift+方向键扩展）、高亮选择与勾选分离（资源管理器式 Ctrl/Shift 只改高亮、只有点 ☑/☐ 字形才改勾选、多行高亮跟随、空格/右键批量勾选）、删除（svn delete --force）、
                               #   默认全不勾选、空选提交拦截、双击对比（meld / 内置 / 对比方式
                               #   弹窗与记住、右键菜单与查看提交历史、无基线条目全新增）、改动列表正文垂直居中
python3 tests/test_browse.py   # 4 项：目录选择三分支（假 zenity / 取消 / Tk 回退）
python3 tests/test_dialogs.py  # 49 项：弹窗链路（确认框/对比方式选择框/日志折叠且不自动展开/状态栏结果常驻/通知类失败不弹模态框/模态窗 dialog 防护与最小化自动还原/地址反查与工作副本变化自动刷新/非法路径不写配置/启动清理失效配置/日志文件/认证/证书/CheckBox/登录凭据窗口含按钮可见性与父窗居中/子窗 transient 压父窗）
python3 tests/test_shortcuts.py # 9 项：输入控件快捷键（Ctrl+A 全选 / 复制粘贴，含 TCombobox）
python3 tests/test_repo_browser.py # 132 项：仓库浏览器（解析/本地状态/读取线程/懒加载/仓库集合根索引解析与 HTTP 200/401/403/404/缓存凭据/列表 UI 与菜单守卫/勾选/右键菜单含查看提交记录与平面风格、列表空白处右键、复制解码地址、最近地址下拉与清空、列表名称图标与缩进/后缀/大小列、查看内容窗口（编码自动适配与手动切换、二进制提示）及快捷键/右键复制、内置差异窗口同样的快捷键/右键复制、导出到…真实 svn export/检出与更新；含文件级勾选、键盘操作、本地目录实时校验、排除状态后台补读不卡弹窗、窗口装饰偏移标定与父子居中、翻转勾选不移滚动、子窗 transient 压父窗、检出对话框 dialog 防护、点"开始下载"自动收起辅助窗口与友好提示）
python3 tests/test_log_view.py # 31 项：提交历史（log 解析/对比"与上一版本"语义/单文件按地址 E155010 回归锁/meld 两版与内置选择/记住选择/取消/截断/地址目标/完整提交说明区含 3 行布局/关闭清理/子窗 transient/Tk 内部 _root 不被覆盖）
python3 tests/test_theme.py    # 54 项：换肤（10 套皮肤与固定顺序/默认晴空与非法值回退/配置持久化与重启恢复/换肤菜单单选/主窗口与辅助窗口/内置差异/菜单/CheckBox/Combobox 下拉列表/ttk 样式实时换色/文本选中滚动勾选与任务状态保持/状态色语义与对比度）
```
合计 332 项。

最小验证：

```bash
python3 -m py_compile SVNWorkBench.py svnwb/*.py   # 语法检查
python3 SVNWorkBench.py                 # 手动起窗口，肉眼过一遍工作副本页 + 仓库浏览器 + 提交历史
```

- 无 lint/typecheck 脚本
- 系统需有 `svn` 命令行；仓库操作（下载/提交/对比）依赖实际 SVN 服务器。
  tests/ 用 `svnadmin create` 建 `file://` 本地仓库冒烟
  （下载/排除/状态/提交/对比全流程可跑通）
- 无图形环境（未设置 DISPLAY）时程序会报友好错误并退出 1，属预期行为
- 改动窗口布局后要真开窗口确认（内容总高超过窗口时的压缩行为肉眼才看得出）

## 结构速览

- `svnwb/app.py` 的 `main(argv=None)` → `ConfigStore(CONFIG_DIR)`
  （**单文件 `_settings.json`**：`load()` 读取 + `_migrate()` 一次性把
  旧版程序同级 `configs/_settings.json` 的字段并进去 + `update_fields()` /
  `set_option()` 原子写）→ `Hub`（单任务执行 + 事件队列）→ `App`
  （Tk 主界面，构造时先按配置 normalize 皮肤并 `core.apply_palette`，
  再 `theme.apply_theme`，之后才建控件；`_poll` 轮询事件并回收 meld
  子进程，弹窗函数在 `svnwb/dialogs.py`）。**启动参数**：`argv` 非空时取 `argv[0]` 当工作
  副本目录交给 `App.open_wc(path)`（`resolve_dst` 展开成绝对路径 ->
  **先清空 `url_entry` 与 `url_auto`** 再 `_set_form(wc=..., save=False)`
  -> `_probe_url(True)` 反查地址）：反查成功才回填新地址、`_save_form`
  落盘并自动刷新改动列表；路径不是 SVN 工作副本则**地址框保持留空**、
  不写配置也不刷新，绝不把配置里的旧地址留在框里（用户反馈；
  `_wc_blur`/`_browse_wc`/`_probe_done` 的手改地址保留规则不受影响）。
  `argv is None` 时读 `sys.argv[1:]`，显式传入列表便于测试；double 点
  exe 无参数时行为与旧版一致。**启动后自动反查地址、成功再刷新状态**：
  main() 用 `root.after_idle(app._startup_refresh)` 调度（仅无启动参数时）
  ——等首帧渲染（expose/redraw 处理完）再跑，不拖慢启动；svn info/status
  都在 Runner 线程里跑。调度放在 main() 而不是 `App.__init__`：测试直接
  构造 App、自己泵事件，after_idle 会在测试的 update() 里触发自动任务、
  撞上 BusyError——**别把自动刷新挪进 __init__**。目录不存在/空路径时
  `_startup_refresh` 静默跳过；配置里的路径存在但不是工作副本时，
  启动反查失败会清掉界面与配置里的 `dst`/`svn_url`，不刷新、不弹窗。
- `Runner`（threading.Thread）执行实际 svn 命令，事件经 `Hub._pump`
  转投 `Hub.events`
- 纯函数区 `parse_info_url`（`svn info --xml` -> 地址，`repo_browser`
  的同名函数委托给它）与 `probe_wc_url(path)`：`svn info` 只读本地
  `.svn`、不联网不需要凭据，返回 `(地址, 错误说明)`。同族函数：
  `_svn_info_xml(path)`（子进程封装）、`parse_info_repo(text)`（`svn info
  --xml` -> (来源地址, 仓库根地址)，`_do_log` 用）、`parse_log_xml(text)`
  （`svn log --xml -v` -> 提交列表，含每个版本的文件）、
  `repo_path_to_url(repo_root, repo_path)`（仓库根地址 + 仓库路径 ->
  文件地址，提交历史单文件对比的唯一目标，拼不出返回 `u""`）、
  `fmt_date`（ISO 时间 -> 可读时间，`repo_browser.fmt_date` 委托给它）、
  `default_config_dir()` / `default_log_dir()`（见"硬约束"的路径条目）、
  `THEMES` / `THEME_DEFAULT` / `THEME_ORDER` / `normalize_theme` /
  `palette_for` / `apply_palette` / `current_palette`（皮肤库与配色计算，
  见"界面样式"里的换肤条）、
  `RECENT_URL_LIMIT` / `normalize_recent_urls` / `push_recent_url`
  （仓库浏览器最近地址：解码百分号、去尾斜杠、按地址去重、最新在前、
  最多 10 条，配置字段 `recent_repo_urls`）、
  `status_sort_key`（改动列表排序键：`STATUS_SORT_ORDER` 状态分组，
  **未版本控制/忽略排最后**，`parse_status_xml` 与 `_up_render` 都用它）、
  svn 登录凭据三个助手 `subversion_auth_dir`（`~/.subversion/auth/
  svn.simple`，环境变量 `SVNWB_SUBVERSION_DIR` 覆盖 .subversion 根，
  测试指向独立临时目录）/ `parse_auth_fields`（K/V 长度前缀格式）/ `list_credentials`
  （登录凭据窗口的数据源）/ `cached_credentials`（按 scheme/host/port
  找同源明文凭据，供集合根 HTTP 索引读取；只认 svn.simple 里真有密码的
  条目，不把 A 服务器的密码发给 B 服务器）、
  `parse_repo_index`（mod_dav_svn 的 `<svn><index>` -> 仓库列表；
  **index 带 base 属性的是具体仓库页，返回 None**，HTML/坏 XML 也返回
  None，仓库地址去掉尾部斜杠）与 `looks_like_collection_error`
  （E175009 / E130003 / 190001 / "does not contain the name of a
  repository"）
- 下载算法核心在 `Runner._do_download`（目标不存在时逐层
  `set-depth` 递归，可断点续跑；同源工作副本时先 `svn update` 整树，
  再按 `restore` 拉回、按 `excludes` 排除）；改动它前先读懂 README
  「下载逻辑」一节
- 认证/证书重试走 `Runner._ask` + `Hub.respond`，按 `AUTH_HINTS` /
  `CERT_HINTS`（文件中部定义）触发
- `svnwb/repo_browser.py`：纯函数 `parse_list_xml`（含文件大小 `<size>`）/
  `fmt_date` / `fmt_size`（字节 -> KB/MB 等，目录空串）/ `file_suffix`
  （后缀列，无后缀/隐藏文件空串）/
  `topmost`（-> `core.topmost_paths`，勾选/恢复清单都取最上层）/
  `checked_to_excludes` / `parse_info_url` / `parse_status_have`（目录与
  文件都有）/ `read_local_kind`（只跑 `svn info` 的快速判定：none/fresh/
  same/other/unknown，见 docstring）/ `decode_text`（原始字节 ->
  文本+编码名+是否二进制，BOM/UTF-16/严格 UTF-8/GB18030 依次尝试）/
  `cat_display`（svn cat 原始字节 -> 展示文本+状态说明，自动适配编码/
  二进制/截断，见"查看内容"条）→
  `LsWorker`（复用 `_decorate` / `_exec_stream` / `_run`；cat 用
  `sink="bytes"` 拿原始字节，目录/状态等 XML 用 `sink="buffer"`；
  120s 看门狗，等待凭据的时间不计超时）→ `CatView`（只读内容窗口，
  非模态、复用一份）→ `RepoBrowser`（iid=完整 URL、
  `node_rel` 存未编码相对路径、懒加载占位节点"（加载中…"）；地址栏
  `url_box` 是可编辑 `ttk.Combobox`，`_recent` 保存最近地址（配置字段
  `recent_repo_urls`）：**只有地址栏“转到”（含回车、下拉选历史）成功
  后才记录**——`_go` 把目标登记到 `_recent_pending`，读取成功的
  `_on_node_ls` / `_on_collection` 调 `_record_go_recent` 提到最前并落盘，
  失败则 `_drop_go_recent` 作废；树中展开/双击目录/刷新等普通浏览一律
  不写（`tests/test_repo_browser.py` 锁该行为）。`postcommand` ->
  `_fill_recent` 刷新下拉值/配色，
  右键 `menu_url` 的"清除最近记录" -> `_clear_recent`（无历史置灰）；
  **集合根**：`_collections` 存已确认的集合根（normalize 后），
  `_go` / `_ensure_loaded` / `_on_tree_select` / `_do_refresh` 命中时走
  `request_collection`（tag `("collection", url)`、cmd 为 None），
  `LsWorker.run` 对该 tag 不跑 svn，改由 `_fetch_collection` 用标准库
  `urllib` GET 索引（仍是后台线程，120s 看门狗照旧）；401 先
  `core.cached_credentials` 再 `_ask("ask_auth")`，证书错误复用
  `_ask("ask_cert")`。`_on_node_ls` 失败且
  `core.looks_like_collection_error` 时回退 `request_collection`；成功后
  `_on_collection` 把树根文本改成 `COLLECTION_TITLE`（仓库列表），并用
  `_apply_node_items` 把仓库同时铺到左树/右侧列表（条目带 `url`，
  地址已去掉尾部斜杠）。集合根不是具体仓库：`_configure_dir_menu`
  把检出/导出/查看提交记录置灰，`_do_checkout` / `_do_export` 入口
  再拦截一次 →
  `CheckoutSelect`（**已重写为 tk.Text 勾选列表**，见行为陷阱"检出对话框
  三变化"；模态 `run()` 返回 `{"url","dst","excludes","restore","mode"}`，
  对话框侧 `_read_local` 在五种 kind 外多一种 `"file"`：本地目录被文件
  占用——报错并禁用确认按钮）
- 检出与更新不写新代码：`App._checkout_from_browser(url, dst, excludes,
  restore, mode)` 确认后 `_run_start("download", ...)`，成功即
  `store.update_fields(...)` 回写配置，并 `_set_form(url, dst)` 把工作
  副本带回界面（检出完不用再手选一遍）。**首次下载（mode="download"）
  启动后还要走 `_begin_download_ui(abs_path)`**（用户要求：点"开始下载"
  后只剩主窗口 + 友好的下载中提示）：`_close_aux_windows` 收起仓库浏览器
  （`shutdown()`，含它的 LsWorker 读取线程）/ 提交历史（`destroy()`）/
  内置差异窗口，`root.deiconify+lift` 把主窗口带回前台，目标目录记到
  `App._download_hint` 并刷一次 `_set_busy(True, "download")`、右下角给一条
  蓝色 info 提示（下载完成的 toast 会自然覆盖它）。**友好状态栏文案必须
  在 `_set_busy` 里按 `_download_hint` 渲染**：Hub 启动任务后还会发一条
  busy 事件再走一次 `_set_busy`，只在 `_begin_download_ui` 里配文字会被
  立刻刷回"运行中：下载"（20261016 实测）；任务结束时 `_set_busy(False)`
  清掉 hint。**更新（mode="update"）不关窗**，别顺手统一；模态弹窗
  （认证/证书/确认/凭据/运行日志列表）与下载不可能同时开着，不用管。
- 导出是独立模式（用户要求"导出功能，不是检出"）：`Runner._do_export`
  + hub 校验 `mode="export"`（url/dst/force）+ `_handle_done` 的
  `export` 分支（toast"导出完成"）。仓库浏览器右键"导出到…"
  （`RepoBrowser._do_export`）先 `App.browse_dir` 选**父目录**，目标是
  "父目录/节点名"；目标已存在时 `dialogs.ask_confirm` 确认后带
  `--force`（svn 对已存在目标默认报 E155000；实测 1.10 `--force` 只覆盖
  同名文件、目标里的其他文件**不动**），确认文案如实写明。导出走主界面
  Hub 单任务链路（可取消、有运行日志、`_run_start` 失败弹警告），
  **不关仓库浏览器、不建工作副本、不写配置**；单文件地址也能导出。
- 工作副本页的方法都在 `svnwb/app.py`：`_build_wc`（改动列表占满剩余
  高度，rowconfigure 只给 body 分高）。行结构 = 0 工作副本 / 1 地址 /
  **2 勾选与条目操作合并行**（全选 / 全不选 + 添加 / 还原 / 删除
  左侧，更新右侧；“刷新”已挪到第一行，原先是两行）/ 3 列表标题行
  （只有“改动列表”标题与空列表提示，右侧不再放范围/双击提示）/ 4 body /
  5 提交说明（**高度 1**）+ 勾选计数 + 提交；**不套 ttk.Notebook**，顶栏放
  "账号管理"（`_show_credentials` -> `dialogs.show_credentials`）
  +"对比方式"（三种模式的单选菜单，写配置 `diff_tool`）
  +"主题"（10 套皮肤单选，`_set_theme` / `_fill_theme_menu` /
  `_show_theme_menu`，写配置 `theme`）三个按钮；"日志文件"
  （`_show_logs`）在运行日志标题行"清空显示"后面；"显示日志"
  （`_open_log_view`）放在地址行"仓库浏览"后面。第一行"刷新"
  （`App._refresh`）合并了原"读取地址"：
  先 `_probe_url(True)` 反查地址，再 `_refresh_status()` 刷新改动列表。
  用户明确要求改动列表尽量高——
  **别再往这页加页签、固定提示行或把提交说明加高**。
  `_refresh_status`（固定本地范围，
  不传 `show_updates`）/ `_wc_update`（"update" 任务：`svn update` 整个
  工作副本）、`_up_render`（列表渲染，**按 `status_sort_key` 排序**、
  **默认 `up_checked = set()`**，期间置 `self.rendering` 屏蔽回调）
  -> `_up_paint` / `_up_line_write` /
  `_up_body_text` / `_up_set_line` / `_up_set_lines` / `_up_mark_current` /
  `_up_hover_refresh`、`_up_click`（**资源管理器式选择，选择与勾选分离**：
  普通单击正文只高亮当前行、只有点中 ☑/☐ 字形（`_up_check_hit` 按
  字符 bbox 精确命中，点状态文字/正文不算）才改勾选；被点行在多行高亮
  选区内时整个选区同步成同一状态，未选中行只改自己；Ctrl 单击增/减
  单行高亮、Shift 单击高亮锚点到该行并清空段外、Ctrl+Shift 追加整段、
  空白处清空高亮，以上都不改勾选；勾选框优先于修饰键，Shift/Ctrl
  点方框也按选区同步。同时 `focus_set` 让键盘立即可用，
  `_skip_release` 挡掉双击的第二次 release；`event.state` 位 1=Shift、
  4=Ctrl）——选择走 `_up_shift_click(additive=...)` / `_up_toggle_line` /
  `_up_set_selection`（`up_sel_lines` 是唯一高亮源，勾选仍是
  `up_checked`）、键盘 `_up_move`
  （↑/↓/PgUp/PgDn/Home/End，越界停在两端，普通移动单选并更新锚点；
  `extend=True` 对应 Shift+方向键，从锚点扩展/收缩整段高亮，锚点与勾选
  都不动）/ `_up_toggle_current`（空格：有高亮选区时批量全勾/全取消——
  全已勾则全取消，否则全勾；无选区时切换当前行）/ `_up_set_checked` /
  `_up_check_selected`（右键菜单的批量勾选/取消）/ `_up_key_select_all`
  （Ctrl+A 只全选高亮，返回 `"break"` 挡住 Text 类的全选文本）、
  `_up_motion` / `_up_leave`（悬停高亮，不改光标）->
  `_up_select_line`（单选高亮并记锚点 `up_anchor_line`）-> `_up_dblclick` ->
  `_diff_open`（按配置/弹窗选路：meld / 内置）-> `_start_diff`（"diff" 任务）或
  `_run_start("cat", ...)` -> `_handle_done` 的 `cat` 分支 ->
  `_launch_meld`；辅助方法：
  `find_meld`（staticmethod，测试可替换）、`_diff_tool`（读配置）/
  `_set_diff_mode`（写配置）/ `_choose_diff_mode`（ask 时弹
  `dialogs.ask_diff_mode`，remember 则落盘）/ `_show_diff_mode_menu` /
  `_fill_diff_mode_menu`（顶栏与右键共用）/ `_up_menu`（改动列表右键：
  本次强制 meld/内置 + 三种默认模式；有高亮选区时给"勾选所选条目 /
  取消勾选所选条目"，右键落在选区内保留多选）/ `_show_new_file`（无基线条目按
  全新增渲染）、`_tmp_dir` / `_tmp_file` /
  `_up_item` / `_reap_meld`，以及 `_up_set_all` / `_up_add` /
  `_up_revert` / `_up_delete`（`svn delete --force`，空选拦截 + 确认框）/
  `_commit`（空选拦截）/ `_up_clear_msg`（提交成功后清空
  提交说明框，`_handle_done` 的 commit 分支调）、`open_wc`（启动参数入口）。
  自动触发的任务走 `_run_start(..., quiet=True)`，失败不弹窗、完成不弹
  状态栏结果（见"线程与事件"）。
- 双击对比的两条路都在 `svnwb/app.py`（**先按配置/弹窗选**，见
  "对比方式"条）：
  - **选 meld**（且装了 meld、条目不是目录）：`_diff_open` 启动 Runner
    新模式 `"cat"`（`_do_cat`：
    `svn cat -r BASE`，走 `_exec_stream(sink="file")` 把 stdout **按原始
    字节**写进临时文件，绝不进日志），完成后 `_handle_done` ->
    `_launch_meld([meld, base, local])`（`subprocess.Popen` 不阻塞，
    进程存 `self.meld_procs`，`_poll` 里 `poll()` 回收）。没有基线的条目
    （unversioned/ignored/added/replaced）直接用空临时文件当 base，本地
    缺失的用空文件当 local；临时目录 `self._tmpdir`（前缀 `svnwb_diff_`）
    在 `_on_close` 里清理。
  - **选内置 / 没有 meld / 该条目是目录**：跑 "diff" 任务，
    `_handle_done` 调 `dialogs.show_diff_win(...)` 弹**非模态**
    内置差异窗口（复用 `self.diff_win`，重复双击只刷新内容）。
    unversioned/ignored 没有 BASE 基线（对它们跑 `svn diff` 会 E155010），
    改由 `_show_new_file` 读本地文件按“全新增”渲染（二进制提示、超大
    截断），不启动 svn 任务。
  - `_exec_stream` 的 `sink` 三种取值：`log`（逐行进日志，默认）/
    `buffer`（进 `self._buffer` 供 `--xml` 解析）/ `file`（原始字节写
    `self._sink_file`）。
- 提交历史（地址行"显示日志"或仓库浏览器右键"查看提交记录" ->
  `App._open_log_view(url=None)` 懒加载 `svnwb/log_view.py` 的
  `LogView`；窗口已开时置前并 `lv.set_target(url or u"")`，目标变了才清
  列表重读、同目标只置前）**走主界面的 Hub**（不是 LsWorker，所以会占
  单任务位、失败在状态栏/运行日志/历史窗口提示（不弹阻塞式消息框）、
  取消按钮可用）：新模式 `"log"`（`_do_log`：
  `svn log --xml -v -l N -r HEAD:1`，为什么必须带 `-r HEAD:1` 见行为陷阱）
  返回 `{"entries", "wc_url", "root"}`——entries 是
  `core.parse_log_xml` 的提交列表，同一目标再跑一次 `svn info --xml`
  取 wc_url/root 供路径换算（Runner 线程内可走凭据/证书重试，info 失败
  只降级不失败，RunCancelled 重新抛出）；新模式 `"logdiff"`
  （`_do_logdiff`）目标三种，见行为陷阱两条（E155010 与 meld 补丁视图）：
  ① `file_url` + `pair`（单文件、用户选 meld 且装了 meld）：`_cat_to` 分别
  `svn cat -r N-1 <url>@N-1` / `-r N <url>@N` 写进 left/right 临时文件
  （前缀 `svnwb_prev_` / `svnwb_cur_`），
  路径在该版本不存在的一侧（新增的左 / 删除的右，W160013/E200009）写成
  空文件，返回 `{kind:"pair", rev, title, left, right}`；
  ② `file_url`（无 meld）：统一差异 `svn diff -c N <url>`（新增/删除/普通
  三种 peg 实测都直接成功）；③ `url` 或 `wc`（整版本）——统一差异
  返回 `{rev, title, lines, stats}`。**`-c N` 的语义就是
  rN-1 -> rN**（实测不掺本地未提交改动），窗口标题"rN 相比上一版本
  rN-1"即由此而来，**勿改成 `-r N`**（那会变成与工作副本对比）。
  hub 校验：log/logdiff 接受 `url` / `file_url` / `wc` 任一，全空才报
  ApiError。结果由 `App._handle_done` 里的 `lv.task_done(ev)` 回调——
  成功/失败/取消都走它（让窗口收尾"读取中…"状态），App 侧没有为
  log/logdiff 新增 mode 分支。`LogView._start_diff` 负责目标换算
  （`core.repo_path_to_url` 拼文件地址，**单文件一律按地址**；拿不到
  仓库根降级整版本）；`LogView.open_diff` 分流：pair -> meld 左右两版，
  统一差异 -> `dialogs.show_diff_win` 内置窗口（超过
  `core.DIFF_MAX_LINES=20000` 行先截断并写明，防整版本大差异卡死）。
  窗口中部还有**完整提交说明区**（`LogView.msg_text`，只读、按词换行、
  可滚动、可选中复制）：列表"说明"列只显示首行（多行以 `…` 结尾），
  选中版本后 `_on_select` 同时刷 `_show_files` + `_show_msg`；重建列表
  （`on_log`）与切目标（`set_target`）时要同步 `_show_msg(None)` 复位
  提示。用户反馈长说明在列表里看不全，**别把这区删了**。该区**只占
  3 行**（`height=3`，行距选项别加——加了第 3 行会被裁一条）：原来 6 行
  太高、把下面的改动列表挤到看不见、只有全屏才露出来（20261016 用户
  反馈），**别调高**。`tree` / `ftree` 的 `height=6/4` 是**保底请求值**、
  实际高度交给 `expand`——请求值给大（默认 10 行）时 pack 空间不够会把
  后 pack 的改动列表挤没。
- 打包交付：根目录 `1-构建-打包绿色单文件.sh`（架构无关）
  用 PyInstaller 出**绿色单文件** `dist/SVNWorkBench`（内置 Python+Tkinter，
  目标机只需 svn 命令行，不装 python3-tk），并把
  `scripts/right-menu/<系统>/` 下的右键菜单脚本按系统原样拷入
  `dist/right-menu/<系统>/`（当前为 `UOS/`、`Kylin-V10/`、
  `Kylin-V10-SP1/`）——
  **交付物 = `dist/` 整个目录**（exe + `right-menu/`），使用者双击运行、
  进入 `dist/` 执行对应系统的 `1-安装…` 装右键菜单；配置在
  `~/.config/SVNWorkBench/`、
  日志在 `/tmp/SVNWorkBench-<用户名>/logs/`，**都不在 exe 旁边**。
  **`core._base_dir()` 冻结运行时把 BASE_DIR 指向 exe 所在目录**——
  单文件模式的 `__file__` 在临时解压目录（`sys._MEIPASS`，退出即消失），
  `sys.executable` 才是用户双击的那个文件（实测），勿改回
  `Path(__file__)`。BASE_DIR 现在只用于定位旧配置迁移源
  （`LEGACY_SETTINGS = BASE_DIR/configs/_settings.json`）等程序旁资源，
  **别把配置/日志改回 BASE_DIR**。PyInstaller 不支持交叉编译：
  x86/ARM 各在对应架构的机器上跑一次同一脚本。**构建机必须有
  python3-tk**——tkinter 要打进包，缺它时 PyInstaller 只警告、产物一运行
  就报 `No module named 'tkinter'`（20261014 ARM 实测踩过）；目标机运行时
  不需要。脚本会自动 `sudo apt install python3-pip`/`python3-tk`
  （用户要求写入），构建后核对
  `build/SVNWorkBench/warn-SVNWorkBench.txt`（不存在也报错，说明空跑）
  中 tkinter 已入包（`missing module named tkinter` 即失败退出）。
  **PyInstaller 版本按 Python 选**：3.5 -> 3.6、3.6 -> 4.10、
  3.7 -> `pyinstaller<6`（5.x）、3.8 及以上 -> `pyinstaller<7`（6.x）。
  **20261111 实测 Python 3.8 必须走 `<7`，用 5.x 构建不可用**；
  脚本不只判断"有没有装"，还会核对已装大版本，不符时
  `pip install --user --upgrade` 到对应分支，装完仍不符就报错退出
  （系统级旧版本可能优先级更高）。改这段前先在对应 Python 版本上实测。
  **`--clean` 必须带**：PyInstaller 有增量缓存，`build/` 留着旧 TOC 时
  重跑会 `checking Analysis/PYZ/PKG/EXE` 全跳过、750ms 空跑 exit 0——旧 exe
  与旧 warn 文件原封不动，装完 python3-tk 重跑也不会重建（20261014
  实测踩过），核对读到的还是旧内容。
- 清理：根目录 `2-清理-构建产物与缓存.sh` 删 `build/`、
  `dist/` 与全项目 `__pycache__/`、`*.pyc`，**只删这三样**——源码、文档、
  脚本正本、用户配置（`~/.config`）与运行日志（/tmp）一律不动。脚本开头有
  安全闸（校验 `SVNWorkBench.py` + `svnwb/` 存在才动手，防止被误拷到别处
  执行乱删），可从任意目录执行（自动 `cd` 工程根）。清理后
  `./1-构建-打包绿色单文件.sh` 可完整重建
  （PyInstaller 本来就带 `--clean`，无缓存依赖）。
- 文件管理器右键集成的脚本**正本收在 `scripts/right-menu/<系统>/` 维护**
  （`UOS/`、`Kylin-V10/`、`Kylin-V10-SP1/`，每个系统目录内按
  `1-安装` / `2-卸载` 编号；`dist/right-menu/<系统>/` 里的是打包脚本
  自动拷贝的副本，**改正文本改 scripts/ 正本再同步**）。
  **`Kylin-V10-SP1/` 与 `Kylin-V10/` 是两套互不相干的方案，绝不能
  合并**：前者是 Peony 原生 C++ 插件，后者是 MATE/Caja 的用户级脚本。
  下面按系统说明：
  - **UOS / deepin**（`scripts/right-menu/UOS/`）：安装脚本往系统菜单
    扩展目录写**两个** `.desktop`（需要 sudo）：
    - `SVNWorkBench.desktop`：`X-DFM-MenuTypes=SingleDir`，`Exec=<exe> %F`
      ——右键**文件夹**，`%F` = 选中的目录
    - `SVNWorkBenchEmpty.desktop`：`X-DFM-MenuTypes=EmptyArea`，`Exec=<exe> %p`
      ——右键**空白处**，`%p` = 当前所在目录

    **别把两者合并回一个文件**：dde-file-manager 6.x 起 EmptyArea 不再
    展开 `%F`（空白处无选中项、`%F` 为空，5.x 才正常），只有拆成两个文件、
    空白处改 `%p` 才两种场景都正常（用户实测结论）。卸载脚本删的也是
    这两个文件，改文件名要同步。`%p` 是 dde-file-manager 的扩展字段码，
    `desktop-file-validate` 会报 "invalid field code %p"，属预期，**不要**
    改成标准 `%f/%F`（空白处没有选中项，会拿到空路径）。
  - **Kylin V10 / MATE（Caja）**（`scripts/right-menu/Kylin-V10/`）：
    安装脚本写用户级菜单脚本
    `~/.config/caja/scripts/使用SVN_WB打开`（不需要 sudo），入口是
    **右键 -> 脚本 -> 使用SVN_WB打开**；选中目录时打开该目录，选中普通
    文件时打开文件所在目录，空白处右键时打开当前目录。卸载脚本只删
    这一个菜单脚本，不动 `~/.config/caja/` 里的其它脚本；重启用
    `caja -q`（失败再 `killall caja`）。
  - **Kylin V10 SP1 / Peony**（`scripts/right-menu/Kylin-V10-SP1/`）：
    与上面的 Caja 方案**完全无关**。安装脚本在目标机现场用
    qmake/make 编译 Peony 原生 C++ 菜单插件，安装到
    `/usr/lib/<multiarch>/peony-extensions/libpeony-svnworkbench-plugin.so`
    （`<multiarch>` 由 `gcc -print-multiarch` / `dpkg-architecture` 算，
    ARM 通常是 `aarch64-linux-gnu`，x86_64 是 `x86_64-linux-gnu`）。
    **不随 dist/ 提供预编译 .so**——插件与架构、Qt/Peony 版本强相关，
    必须在目标机编译。目标机需要 `libpeony-dev`、`qt5-qmake`、
    `qtbase5-dev`、`g++`、`make`、`pkg-config`；只运行主程序不需要。
    安装脚本会先检查 `peony`、qmake 是否为 Qt5、`pkg-config --exists
    peony`，缺依赖时明确报错退出。
    - **插件元数据版本（common.json）必须与 Peony 的 `VERSION` 完全
      一致**，否则 `PluginManager` 会静默跳过插件。脚本默认用
      `pkg-config --modversion peony` 生成版本（Kylin V10 SP1 当前为
      `3.2.2`），可用 `SVNWB_PEONY_VERSION` 覆盖；**别硬编码成别的
      版本**，Peony 升级后要重跑安装脚本。
    - `menuActions` 只处理 `DirectoryView` 与 `DesktopWindow` 两种菜单
      类型，并先检查 `m_enable`；不按类型过滤会导致菜单项在多种菜单里
      重复（上游文档明确提醒）。选中目录打开目录本身，选中普通文件打开
      文件所在目录，空白处右键打开当前目录；多选取第一个（主程序只取
      `argv[0]`）。非本地 URI（trash://、smb://）不退回当前目录。
    - **QAction 的生命周期归 Peony 菜单所有**：Peony 的
      `DirectoryViewMenu` / `DesktopMenu` 会对插件返回的每个 action 执行
      `setParent(menu)` 再 `addAction`，菜单关闭时 action 随 `QMenu`
      一起销毁。所以**禁止复用成员 QAction 指针**（旧实现的 `m_action`
      就是坑）：每次 `menuActions` 都必须
      `new QAction(..., nullptr)`，parent 交给 Peony 接管（**不要挂
      `this`**），目标目录用值捕获进 lambda、`connect` 以 action 自身
      为上下文。复用旧指针会在下一次右键时访问已释放对象，Peony 直接
      闪退（20261111 用户实测：右键文件夹正常，再右键文件/空白处崩溃；
      本机夹具对旧插件复现 SIGSEGV，修复版 27 项通过）。
    - 卸载脚本**不能写死 `aarch64-linux-gnu`**（旧脚本在 x86 上会漏删）：
      按 multiarch 动态计算，并兜底扫
      `/usr/lib/*/peony-extensions/`、`/usr/local/lib/*/peony-extensions/`；
      只有确实删到插件才重启 Peony。
    - 临时编译目录用 `mktemp -d` 并在退出时清理，**不要改回固定的
      `/tmp/peony-svnworkbench-plugin`**（并发/符号链接风险）；卸载脚本
      会顺带清理旧版留下的这个固定目录（只删当前用户自己的）。
    - 环境变量 `SVNWB_PEONY_TRIPLET` / `SVNWB_PEONY_LIBDIR` 仅用于
      调试/非标准安装；普通安装不要设置（Peony 只从自己的插件目录加载）。
      `SVNWB_KEEP_BUILD=1` 可在编译失败时保留临时目录排查。
    - 本机（UOS x86_64）没有 Peony 环境，无法实机验证菜单；改动后至少
      `bash -n`，并在 Kylin V10 SP1 目标机实测“安装 -> 右键 -> 卸载”全流程。
  - 三套安装脚本都先检查环境（`dde-file-manager` / `caja` / `peony`），
    在不适用的系统上直接报错退出，避免把菜单写到错误的位置。
  - exe 定位：三套脚本都从脚本所在目录开始逐级向上查找
    `<目录>/SVNWorkBench`、`<目录>/dist/SVNWorkBench`（以及脚本上层的
    `dist/SVNWorkBench`），所以源码目录、`dist/right-menu/<系统>/`、
    桌面都能用；也接受第一个参数显式指定路径。
  - **改工程路径/产物名时同步检查这些脚本与已安装的菜单**（UOS 的
    `.desktop`、Caja 菜单脚本与 SP1 插件里都写死了 exe 绝对路径，挪了
    目录要重跑安装脚本，否则右键菜单指向失效路径）。用户另有一份免
    sudo 的用户级 `.desktop` 模板在 README「文件管理器右键集成」。

## 行为陷阱

- **同一时刻只允许一个任务**：`Hub.start` 已有任务在跑时抛 `BusyError`，
  界面弹警告框。这是有意设计，勿改成并行执行。
- 所有 svn 调用都经 `Runner._run` → `_decorate`，统一附加
  `--non-interactive`、证书信任与凭据参数。绕过 `_decorate` 直接调 svn
  会丢失这些行为。
- `--config-option` 必须是三段式 `分类:小节:选项`（记住密码用
  `servers:global:store-plaintext-passwords=yes`）；写成两段式
  `servers:选项` svn 会以 E205000"语法无效"拒绝整条命令。
- svn 输出会随系统语言变化：提交版本号解析同时匹配
  `Committed revision N.` 与 `提交后的版本为 N。`（只认英文会把成功提交
  报成"没有改动"）。新增输出解析时同理，优先用 `--xml`。
- 下载算法：目标不存在时 `checkout --depth=immediates` 后逐层
  `update --set-depth={exclude,immediates,infinity}`；同源工作副本转为
  `svn update` 后**先 `restore` 拉回、再 `excludes` 排除**（顺序不能颠倒：
  上层 `--set-depth=infinity` 会连带拉回它的子子孙孙，其中仍属排除的
  要靠随后的 exclude 步骤再排掉），异源工作副本直接拒绝。
  `restore` / `excludes` 里的条目**可能是单个文件**（勾选树可以精确到
  文件，见下条）：`_restore_excludes` / `_enforce_excludes` 按“路径存在
  就 `--set-depth=…`”处理即可，逐层 walk 只走目录、单个文件由
  `_enforce_excludes` 收尾补一刀——**别把文件过滤掉**。
  勿"简化"此逻辑，动手前先读 README「下载逻辑」一节。
- 本地排除状态只能靠 `svn status -v --xml` 判定：被 `--set-depth=exclude`
  的条目**不会出现在 status 输出里**（也没有 `X` 标记），因此
  "集合里没有 = 已排除"；`svn info --xml <被排除目录>` 反而返回 rc=0 且
  `<wc-info><depth>exclude</depth>`。改这块逻辑前先保留 `read_local_kind`
  的五种 kind 语义（界面走 read_local_kind + 后台补读，
  见"检出对话框"条）。`parse_status_have` / `read_local_kind`
  **目录与文件都算**（`--set-depth=exclude`
  对文件同样有效，实测 svn 1.10.4）。
- 检出/更新成功启动后必须回写 `store.update_fields`（地址、目录、
  排除清单），否则配置与实际工作副本会不同步——界面已无下载表单，
  这三项的唯一持久化入口就是 `_settings.json`。工作副本框失焦后先反查
  地址，成功才由 `_save_form` 写回；地址框失焦也经 `_save_form`（工作
  副本未验证时跳过）。
- **地址回填与自动刷新规则**：反查结果只在"地址框为空或等于上次自动
  回填值（`App.url_auto`）"时才覆盖，用户手改过的地址一律保留（只 toast
  提示）；反查失败（目录不存在 / 不是工作副本）不动地址框、不刷新列表、
  **不写配置**。反查成功（`url` 非空且路径仍是输入框当前值）才更新
  `_wc_ok_path`、`_save_form`，并在工作副本变化 / 手动读取 / 启动时
  调 `_refresh_status`（自动/启动用 quiet=True，不覆盖状态栏结果）。
  `_save_form` 只保存 `_wc_ok_path` 匹配且目录存在的工作副本；启动时
  `_load_settings` 发现 `dst` 不是目录会同时清掉 `dst`/`svn_url`，
  `_probe_done(startup=True)` 发现"不是 SVN 工作副本"也会清掉（用户
  反馈：下次启动不能显示非法路径和残留地址）。测试用
  `app.probe_q` + `app._drain_probe()` 等结果，别 sleep 猜时间。
- **改动列表不能用 ttk.Treeview**：本机 Tk（8.6.9，X11 的 default 与 clam
  主题都试过）对 Treeview **行标签**的 `foreground`/`background` 完全不渲染
  （样式级配色有效、标签级无效），所以列表是 `tk.Text`（`self.up_text`）
  + 逐行 Text 标签着色 + 制表位对齐列位
  （`UP_REV_X` / `UP_PATH_X`，与表头 label 的
  `place(x=...)` 一一对应）。行尾要补 `UP_FILL` 个空格，整行底色才盖满
  可视宽度。行号用 `@0,y` 取（`_up_line_at`），翻转勾选只重写状态变化的
  行（`_up_set_checked` -> `_up_set_line`/`_up_set_lines`；重写前先记
  yview、重写完 `yview_moveto` 恢复：视口
  顶部是半截行时 delete 会让 Tk 把视口对齐到行边界、跳半行，实测；
  与检出对话框 `_refresh_rows` 同一套），选中行（可多行）高亮靠 "cur"
  标签（创建在状态/悬停标签之后，优先级才更高；重写行后要重新调用
  `_up_mark_current`）。`repo_browser.py` 里的树仍是 Treeview——它们
  不需要逐行颜色。
  - **一行是分两次插进去的**（`_up_line_write`）：勾选框段单独挂 "chk"
    标签用更大更粗的字号（字形是 `CHECK_ON`/`CHECK_OFF` 的 ☑/☐，
    靠 `UP_CHECK_DELTA` 放大到 18 号加粗才醒目），
    状态文字
    仍用行状态标签，**正文段再加挂 "txt"**（垂直微调，见下条）。追加时
    两次插入都写字面量 `"end"` 且**先勾选框后正文**
    （顺序反了勾选框会跑到状态后面）；重写某行时正文落在
    `"%d.%d" % (行, len(head))` 精确列——**别换成 `end` 之类会被 Tk
    夹紧的索引**（空行、行末索引都会被夹到别处，行就串了）。
  - **正文与勾选框垂直居中**（用户要求"文字需要垂直居中"）：勾选框字
    形大、ascent 也大，正文与它共用一条基线，视觉上正文偏低——正文段
    挂 "txt" 标签套 `core.UP_TEXT_OFFSET`（=3，Tk 文本标签 `offset` 选
    项，**正值上移**），改动列表与检出勾选列表共用同一常量。**只挪正文是
    故意的**：挪勾选框会把行高撑高一截（descent 变大）。检出对话框的
    "加载中…"占位行没有勾选框，**不挂 "txt"**（`_write_row` 的 hint
    分支），否则单个小字号行会整体上飘。
  - **标签创建顺序 = 优先级**：状态色 → "chk"（只配字号）→ "hover" →
    "cur"，所以悬停盖得住状态底色、选中行又压得住悬停。选中行（可多行）
    底色 `UP_CUR_BG = #93c5fd`（醒目蓝；旧值 #e5e7eb 灰与状态底色、
    悬停都分不开——用户反馈"当前焦点行不够醒目"，20261015）。改动列表
    与检出对话框共用这个常量，改一处两边生效。
    `_up_motion` 记 `up_hover_y`，整表重绘会抹掉所有标签，
    `_up_paint` 收尾调 `_up_hover_refresh()` 按记录的 y 把悬停补回来；
    翻转勾选单行重写（`_up_set_lines`）同样会补回悬停与选中高亮。
  - **勾选框字号直接决定行高**（Text 行高取行内最大字号的 linespace，
    18 号时行高约 36px、一屏少看几行）：`UP_FONT_DELTA` /
    `UP_CHECK_DELTA` 在 `core.py`，调之前先开窗口数数一屏能放几行。
  - **悬停不改鼠标光标**（`_up_hover_set` 只动 hover 标签）：用户要的是
    系统原生光标，别再加 `cursor="hand2"`。
- **列表范围固定"本地改动"**：`_do_status` 跑
  `svn status --xml --no-ignore`（**不带 `-u`**；`--no-ignore` 是用户
  要求：被 svn 忽略规则命中的文件如 `*.so` 也列出来，显示 `I 忽略`，
  可以重新勾选加入版本控制），`show_updates` / `UNMODIFIED` /
  `against_head` / `UP_REPOS_X` 都已随"列表范围"单选一并删除——
  **别再加回来**，也别把 `repos_item` 当数据源用。`parse_status_xml`
  按 `core.status_sort_key` 排序（异常状态最前、**未版本控制与忽略在
  最后**——用户要求"默认将未版本控制的放到最后"），`_up_render` 再排
  一遍兜底。
- **改动列表默认一条都不勾选**（`_up_render` 里 `up_checked = set()`）：
  提交、恢复、加入版本控制、删除都必须先手动勾选。`_commit` 在空选时
  **直接拦截并 toast 提示**，不再退回"提交整个工作副本"（默认空选下那个
  fallback 太危险）；改动这条前先想想误提交的后果。
  **列表选择逻辑是资源管理器式，且行高亮与勾选完全分离**（20261112
  用户要求）：普通单击正文只高亮当前行、只有点中 ☑/☐ 字形本身才切换
  勾选（`_up_check_hit` 按字符 bbox 精确命中；点状态文字/正文不改勾选，
  别再按整列宽度判定）、Ctrl 增/减单行高亮、Shift 高亮锚点到该行并
  清空段外、Ctrl+Shift 追加整段、Shift+方向键从锚点扩展/收缩、点空白
  清空高亮、Ctrl+A 全选高亮；这些操作**都不改勾选**（点勾选框/按空格
  才改勾选）。`up_sel_lines` 是
  高亮选区的唯一来源，`up_sel_line` 只是当前行/键盘焦点，
  `up_anchor_line` 是 Shift 锚点；**别把选择写回 `up_checked`**
  （用户明确否定"勾选就是选择"）。
  **多行高亮时点选区内任一 ☑/☐，整个选区同步成同一状态**（20261113
  用户要求）；被点行不在选区时只切换它自己，不扩选。
  勾选框优先于 Shift/Ctrl：带修饰键点 ☑/☐ 也按上述规则处理。
  **批量勾选入口**：空格在有多行高亮时全勾/全取消（全已勾则全取消，
  否则全勾）；右键菜单"勾选所选条目 / 取消勾选所选条目"直接按选区
  设置（混合状态也能全取消）。右键点在高亮选区内时**保留多选**，
  不要无条件 `_up_select_line(line)` 把选区塌成单行。
  翻转勾选会重写状态变化的行（`_up_set_checked` -> `_up_set_lines`），
  `_up_set_lines` 末尾会补回悬停与选中高亮（`_up_hover_refresh` +
  `_up_mark_current`），否则选中行的高亮会被 delete 抹掉。
- **删除走 `svn delete --force`**（`Runner._do_delete`，hub 校验
  `("add","revert","delete")` 共用 paths）：--force 让未版本控制/忽略
  （直接从磁盘删除）、已修改的版本控制条目（本地移除 + 标记删除）、
  本地已缺失的条目（补记删除）一条命令走通，不带 --force 前三种都会
  报错。空选时 `_up_delete` 直接拦截并 toast，**别退回"删除整个工作副本"**。
- **双击与单击共用一次 release**：Tk 对双击会先发 `<Double-Button-1>`
  （press2）再发 `<ButtonRelease-1>`，而 `_up_click` 绑的是 release，
  不加拦截就会把勾选框**翻两次**。所以 `_up_dblclick` 一进来就置
  `self._skip_release = True`，`_up_click` 见到它就吃掉这次 release 并
  复位。测试里 `dblclick_line` 助手模拟的就是这条链路。
- **meld 相关的测试钩子**：探测函数是 `App.find_meld`（staticmethod，
  返回可执行路径或 None），测试用 `m.App.find_meld = staticmethod(...)`
  替换，**还原时也必须写 `staticmethod(...)`**——直接赋原始函数会变成
  实例方法，`self.find_meld()` 会多传一个 self 报错。选择对比方式的弹窗
  入口是 `dialogs.ask_diff_mode(parent)`（返回
  `{"mode":"meld"/"builtin","remember":bool}` 或 `None`），测试用
  `m.dialogs.ask_diff_mode = ...` 整体替换；默认配置是 `ask`，直接双击
  对比的用例**必须桩掉它**，否则会卡在模态框（`tests/test_e2e.py`、
  `tests/test_log_view.py` 顶部已统一桩成固定答复）。
- **对比方式（`diff_tool`）**：配置值 `ask`（默认）/ `meld` / `builtin`，
  由 `App._diff_tool()` 读取、`_set_diff_mode()` 写入（`ConfigStore.
  _normalize()` 必须保留这个键，否则重启就被丢掉）。双击时
  `_choose_diff_mode()` 决定：没装 meld → 内置（不询问）；配置不是 ask →
  用配置；ask → 弹 `dialogs.ask_diff_mode`，勾"记住"就落盘。**提交历史
  整版本对比永远不询问、始终内置**（meld 3.20 没有补丁视图）；只有单文件
  对比会问，且它和主界面共用同一个配置/助手（`LogView` 传
  `parent=self`，弹窗才压在历史窗口上而不是主窗口上）。改动入口两处：
  顶栏"对比方式"按钮（`_show_diff_mode_menu`）与改动列表右键菜单（`_up_menu`，
  空白处也可改默认模式）。右键菜单**与仓库浏览器同一格式**（简单命令
  列表）：有选中行时"用 meld 对比 / 用内置窗口对比 / 查看提交历史"，
  有高亮选区时再加"勾选所选条目 / 取消勾选所选条目"（作用于整个选区），
  空白处只有"查看提交历史"；末尾分隔线 + "对比方式"子菜单三档（子菜单
  存 `self._up_mode_menu`）。右键项"用 meld 对比 / 用内置窗口对比"是
  **本次强制**，不写配置；"查看提交历史"（`_view_log_for`）对版本控制
  条目用 `core.join_url(url_entry, path)` 打开该条目地址，未版本控制/
  忽略/新增或地址为空时退回整个工作副本。未版本控制/忽略的条目选内置时
  跑不了 `svn diff`（E155010），由 `_show_new_file` 读本地文件按"全新增"
  渲染——别把文件过滤掉或退回报错。右键菜单和顶栏菜单都要用
  `theme.make_menu`，并把菜单对象存到 `self._up_menu_obj` /
  `self._diff_mode_menu`（保持引用；`tk_popup` 后**不要**立刻
  `grab_release`，理由见下一条）。
- **右键菜单不能在 `tk_popup` 返回后立刻 `grab_release`**
  （`RepoBrowser._popup`）：菜单持有的抓取正是"点到菜单外 -> Tk 把事件
  转给菜单 -> 自动收起"的唯一机制，提前放掉后菜单就关不掉了（Tk 8.6.9
  用 xdotool 真实点击实测复现：右键后不选任何项，点空白处菜单一直悬着）。
  菜单被点选或按 Esc 收起时 Tk 自己会放抓取，"检出到…"模态框的
  `grab_set` 也不会被抢走；只有 `tk_popup` 同步抛 TclError 时才
  unpost + grab_release 兜底。测试锁的是"菜单持有抓取"。
- **仓库集合根不是具体仓库**（如服务器根下的 `/svn` 多仓库入口）：对它跑
  `svn list` 只会报 E175009 / E130003 / 190001（"URI 不含仓库名"），
  必须回退到 HTTP 索引——`LsWorker` 的 `("collection", url)` 任务用
  标准库 `urllib` GET 同一地址，`core.parse_repo_index` 只认**无 base
  属性**的 `<svn><index>`（具体仓库页/HTML/坏 XML 一律 None）。401 先
  `core.cached_credentials` 复用 svn 缓存凭据，失败再 `ask_auth`；
  证书错误复用 `ask_cert`。集合根只展示服务器索引实际列出的仓库：
  **不要硬编码任何服务器地址/仓库名，不要自动合并索引里没有的独立
  仓库**；索引地址和仓库名只来自用户输入与服务器响应。集合根只支持
  http(s) 的 mod_dav_svn 网页索引，`svn://` 等协议没有索引，只能直接
  填写具体仓库地址。集合根不是
  具体仓库，检出/导出/查看提交记录菜单置灰并在动作入口拦截，选中其中
  的仓库后才允许。测试用本机临时 HTTP 服务模拟，不连接真实仓库。
- **`svn log` 对工作副本必须写 `-r HEAD:1`**（`Runner._do_log`）：
  默认范围是 BASE+1..HEAD——工作副本已是最新时返回**空列表**（界面表现成
  "没有提交历史"）；而且范围方向决定排列顺序，写 `1:HEAD` 会变成最旧在
  最上面。`-l N` 与 `-r HEAD:1` 可以同时给（从最新往回取 N 条）。
- **`svn log -v` 的路径是仓库根相对的**（/trunk/a.c），仓库在服务器上
  还常带挂载前缀（/svn/xxx/trunk），只拿工作副本地址算不出子树前缀——
  要用 `_do_log` 里的 `svn info --xml` 取
  `<repository><root>`，再按目标换算：提交历史单文件对比换算成
  **文件地址**（`core.repo_path_to_url`，见下一条），**不要**换算成
  工作副本相对路径塞给 `svn diff`。
- **`svn diff -c N <工作副本相对路径>` 只要本地没有这个节点就报
  E155010"找不到节点"**：本版本新增的文件（工作副本还没更新到）、
  本版本删除的文件（本地已无）、被 `--set-depth=exclude` 排除的文件
  都算（20261013 用户日志实测）。所以提交历史的单文件对比
  （`_do_logdiff` 的 `file_url`）**一律按地址**跑：地址形式对
  新增/删除/普通三种情况实测都直接成功，peg 取 HEAD 即可、不需要重试。
  meld 两版模式同理按地址 `svn cat`（路径在该版本不存在的一侧写空文件）。
- **meld 3.20 的命令行没有补丁视图**：`meld xxx.diff` 只会把 diff
  文件和它自己做两路对比（蓝条"文件完全相同"，20261013 用户实测反馈）。
  提交历史的对比因此只有两条路：单文件且用户选 meld -> cat 两版原始内容
  给 meld 左右对比（`LogView._open_pair`）；统一差异（整版本、或选内置
  的单文件）-> 内置差异窗口，**绝不把 .diff 丢给 meld**，也别再
  写"临时 .diff 交给 meld 补丁视图"。整版本大差异会先按
  `core.DIFF_MAX_LINES` 截断（否则内置窗口卡死——同批用户反馈）。
- **“查看内容”走 LsWorker 的 `("cat", url)` 任务**（`RepoBrowser.request_cat`
  -> `["svn","cat",url]`，sink="bytes" 拿**原始字节**）：窗口（`CatView`）
  先显示"正在读取…"，结果由 `_handle_event` 的 `tkind == "cat"` 路由到
  `_on_cat`；`_on_cat` 校验 `win.url == url`，**窗口已换目标时旧结果作废**
  （连点两个文件、任务排队时迟到的旧结果不能盖掉新内容）。窗口复用一个
  （`_cat_url` 检查 `winfo_exists`）。**文本编码自动适配**（用户反馈 GBK
  文件显示乱码）：绝不能在 `_exec_stream` 里先按 UTF-8 解码再判断——那样
  原始字节已被替换成 U+FFFD，什么都救不回来；`sink="bytes"` 把原始字节
  交给纯函数 `decode_text`，按 BOM -> 无 BOM 的 UTF-16 -> 严格 UTF-8 ->
  GB18030/Big5/Shift-JIS/EUC-KR/Latin-1 依次尝试。GB18030 排在 Big5 等
  之前（目标机是中文系统，GBK 旧文件最常见）；两者字节范围有重叠，判断
  错时用内容窗口底部的**“编码”菜单**手动切换（`CatView._set_encoding`，
  `_raw` 保留原始字节供重新解码），状态栏会写明"共 N 行 · 编码 XXX"
  （自动识别为 UTF-8 时不显示，避免噪音）。二进制（含 NUL 等，只提示不
  渲染）/ 超长截断的规则都在纯函数 `cat_display` 里（`CAT_MAX_LINES=20000`
  截断，与 core.DIFF_MAX_LINES 同量级）；传文本行列表时保留旧的
  U+FFFD 提示（纯函数测试用）。
  CatView 布局用 **grid**（head / 正文 / 底栏，`rowconfigure(1, weight=1)`）：
  用 pack 时整体请求高度超过 860x560 会把底栏（状态 + 关闭按钮）挤出
  可视区（20261016 截图核对，与登录凭据窗口同一个坑）。**禁用态 Text
  被鼠标点击时 Tk 不会自动给焦点**，所以只读内容窗口与内置差异窗口
  共用 `dialogs.install_text_copy`：点击正文聚焦、Ctrl+A/Ctrl+C、
  右键菜单**复制 / 复制全部内容 / 全选**（无选区时"复制"禁用）；新增
  只读 Text 窗口都走它，别再各写一套。仓库浏览器右键"复制地址"**复制
  解码后的 URL**（`core.decode_svn_url`），别把百分号编码直接塞进剪贴板。
- **右侧列表的列 = 名称 / 后缀 / 版本 / 作者 / 大小 / 日期**（用户要求）：
  - 名称列用 Treeview 的**树列 `#0`**（`show="tree headings"`，表头
    文本 `heading("#0")`）：headings 模式下行 `image` 不渲染，只有树列
    能显示图标；树列自带 `indent`，名称也不再紧贴左边（用户要求）。
    列表是平的（没有子节点），不会出现展开箭头。
  - **所有列与表头都 `anchor="w"` 左对齐**（用户要求，含版本/大小这些
    数字列，别改回 center/e）；左侧目录树的根与子目录也挂同一个文件夹
    图标（`_icon_dir`）。
  - 图标由 `_make_icon(master, kind)` 直接画出来（工程不放图片资源、
    也不依赖 emoji 字体），必须存到 `self._icon_dir` / `self._icon_file`，
    否则被 GC 后图标变空白。图片宽度 = `LIST_ICON_W`(16) +
    `LIST_ICON_GAP`(5)，右侧 5px 不绘制（透明）充当图标与文本的间隙——
    Treeview 没有单元格 padding 选项，只能把图标本身画宽一点。
  - 后缀列走 `file_suffix`（不含点）：目录、无后缀文件、`.bashrc` 这类
    隐藏文件都留空；大小列走 `fmt_size`（`svn list --xml` 的 `<size>`，
    1024 进制），目录没有 `<size>` 也留空。`parse_list_xml` 已把 size
    一并解析出来。
  - 列宽合计要 ≤ 右侧面板默认宽度（窗口 920 时约 639px）：ttk 会按比例
    **拉伸**列，但不会压缩到请求宽度以下，合计超了日期列会被裁掉
    （20261106 实机截图核对）。
- **右侧列表的"空白处右键"作用于当前目录**（`_on_list_menu` 里
  `identify_row` 为空 -> `_menu_url = _current_url()`、弹 `menu_dir`；
  20261016 用户要求"空白处右键，支持查看提交记录"）。列表行上右键仍按
  行类型给 `menu_dir`/`menu_file`；**文件行双击 = 查看内容**
  （`_on_list_dbl` 的非目录分支），目录行双击仍跳对应树节点。
- **检出对话框（`CheckoutSelect`）按用户要求重做过，别退回 Treeview**：
  - 勾选列表是 `tk.Text`（`self.text`）：行 = `INDENT*层级 + ▾/▸ + 空格
    + ☑/☐ + 名称`，`self._rows` = [{"rel","depth","hint"}] 是唯一行源
    （树 iid 方案与 `_row_iid` 已删除）；勾选框挂 "chk" 标签用
    `theme.check_font`（与改动列表同款大字形），目录名挂 "dir" 强调色、
    占位文字挂 "hint"（加载中/空目录/读取失败），行尾补 `UP_FILL` 空格。
    勾选框之外的正文（缩进/箭头/名称）挂 "txt" 做垂直微调
    （`core.UP_TEXT_OFFSET`，正值上移）；"加载中…"占位行没有勾选框、
    **不挂 "txt"**
  - **单击只选中行**（高亮 + `focus_set`）；点 ☑/☐ 区域才翻转勾选、
    点箭头区才展开/收起（命中区由 `_zone_of` 按 `bbox` 算，
    **先勾选框后箭头、两者不重叠**）；双击目录行展开/收起，勾选框区
    双击当普通单击（`_skip_release` 与主界面改动列表同一套路）
  - **键盘操作**：↑/↓/PgUp/PgDn/Home/End 移动当前行（跳过占位行，
    `_selectable` 是可选行下标），空格勾选/取消（`_toggle_current`），
    ← 收起或跳到父目录、→ 展开或跳到第一个子目录
  - **翻转勾选时列表一点都不动**（用户要求）：`set_checked` 走
    `_refresh_rows` 只重写受影响的那几行、**不整表 `_render()`**——整表
    重绘 delete 全文再重插会把视口夹回顶部，键盘再 `see()` 把该行拉回
    视线，观感就是"勾选时列表乱动"（20261016 用户反馈）；`_toggle_current`
    里**别再加回 `see()`**，`_refresh_rows` 重写前先记 yview、重写完
    `yview_moveto` 恢复（视口顶部是半截行时 delete 会让 Tk 把视口对齐到
    行边界、跳半行，实测）。`_row_segments`（分段）/`_write_row`（整表
    追加）/`_write_row_at`（单行原地重写）三条路径共用同一套分段与标签
  - **本地目录实时校验**：`dst_var.trace("w")` -> 400ms 防抖
    `_dst_changed()`（失焦/浏览立即执行）；对话框侧 `_read_local` 在五种
    kind 外多一种 `"file"`：路径被文件占用——与 other/unknown 一样给
    错误提示并禁用确认按钮，留空提示"请填写本地目录"
  - **打开对话框不跑慢命令**：构造与 `_dst_changed` 只同步跑
    `read_local_kind`（`svn info`，毫秒级）；同源工作副本的排除状态
    （`svn status -v --xml`，大工作副本上要好几秒）由
    `RepoBrowser.request_stat` 交给 LsWorker 后台补读，事件 tag
    `("stat", dst)`，在 `RepoBrowser._handle_event` 路由回
    `CheckoutSelect.on_stat`；读完前确认按钮禁用、提示"正在读取本地
    排除状态…"，读完按 `have` 重铺勾选（`self._touched` 为真——用户已
    手改过——则只回填 have、不动勾选），`_ok` 在读数期间不放行（restore
    清单要按 have 算）。**别把 svn status 挪回同步路径**（20261015 用户
    反馈"检出目录文件多时弹窗很慢"；实测 12000 文件同步 1.2s -> 0.15s，
    慢读后台 1.5s 完成、期间窗口可操作）
  - 勾选粒度到**文件**（`--set-depth=exclude` 对文件实测有效）：
    `set_checked` 向上补祖先、向下传播到已加载子孙；`_ok` 的 `restore`
    只取"勾选但本地没有"的条目并 `topmost` 收顶层
- **登录凭据窗口（`dialogs.show_credentials`）的布局用 grid，别改回 pack**：
  窗口是固定几何 720x460，只有列表行 `rowconfigure(2, weight=1)`（高度
  不够时收缩列表行）。之前用 pack 时高度排不下，最后排的按钮条被整体挤出
  可视区（按钮只剩 1x1 像素）——用户看不到"删除所选…"，表现为"SVN 登录
  凭据无法删除"（20261015 实机截图复现；`tests/test_dialogs.py` 锁"按钮
  真实可见、不被布局挤出"）。列表行嵌套的 box 也是 grid（tree + 滚动条
  两列），别退回 pack 的 side 布局。
- **最近浏览地址只在用户点“转到”成功后记录**（含地址栏回车、从下拉
  选历史；`RepoBrowser._go` 登记 `_recent_pending`，`_on_node_ls` /
  `_on_collection` 读取成功后才 `_record_go_recent` 落盘，失败
  `_drop_go_recent` 作废）：树中展开/选中目录、双击目录、刷新等普通浏览
  **不写历史**，别把 `_record_recent` 挂回 `_render_list`（那会让每次
  浏览都改写配置）。`_recent` 是内存真源，变化后写
  `store.set_option("recent_repo_urls", ...)`；
  `_fill_recent` 是 Combobox 的 `postcommand`，负责刷新 values 与下拉
  列表配色。清空只动历史，**不动 `svn_url`/`dst`**。
- 仓库浏览器的两个 Tk 陷阱：
  - 程序化 `tree.item(iid, open=True)` **不会**触发 `<<TreeviewOpen>>`，
    懒加载必须绑事件 + 保留可直调的 handler（测试只能直调）；
    `<<TreeviewOpen>>` 的事件对象没有 `.item`，用
    `identify_row(event.y)` 或 `tree.focus()` 取节点
  - 勾选行点击判定：`identify_element(x,y) == "Treeitem.indicator"`
    **且** `get_children(iid)` 非空才算展开箭头（叶子行在缩进处也会
    返回 indicator），否则会把箭头点击误当成勾选翻转
- `CheckoutSelect` 里**不能**用 `_name` 做自定义属性名：
  tkinter 的 `Misc._name` 是控件的 Tcl 名，覆盖后 `destroy()` 直接
  TypeError。现有属性叫 `_disp`（相对路径 -> 显示名）。
- **Tk 控件上不能用 `_root` / `_name` 这类 Tk 内部属性名**：`LogView`
  曾用 `self._root` 存仓库根地址，结果 `winfo_toplevel()` 里
  `w._root()` 变成"str object is not callable"，`center_on_parent` 一调用
  就崩（20261021 用户实测）。仓库根已改名 `_repo_root`，新控件属性避开
  `_root`、`_name`、`_w`、`tk`、`children` 等 `Misc` 内部名。
- 勾选状态不变量：勾选一个目录会向上补齐祖先、向下传播到**已加载**
  子孙；因此"父未勾选但子勾选"不可能出现，`checked_to_excludes`
  只需按深度从浅到深取未勾选项即可，别再做覆盖合并以外的加工。

## 运行参数

`python3 SVNWorkBench.py [工作副本目录]`——可选第一个参数是工作副本
目录：启动后填入工作副本框并自动反查地址（`App.open_wc`，
**先清空地址框再反查**）；反查成功才写入配置并刷新改动列表，不是 SVN
工作副本就保持留空、不写配置（见结构速览）。
这是文件管理器右键集成的入口（README「文件管理器右键集成」有 .desktop
模板，按场景分 `Exec=... %F` 与 `Exec=... %p` 两份）。不带参数时行为与
旧版一致（原 Web 版的 `--host/--port/--no-browser` 已随 HTTP 服务移除）。
