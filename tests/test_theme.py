# -*- coding: utf-8 -*-
"""换肤测试：主题库、默认晴空、持久化、实时换色、状态保持、菜单与对比度。

覆盖用户要求的几条硬指标：
  - THEMES 是唯一数据源（10 套、键齐、值原样），默认与非法值都回退“晴空”；
  - 选择写入 _settings.json，重启后恢复；
  - 切换只改颜色：文本内容、选中范围、滚动位置、勾选/当前行、任务状态
    与状态栏结果都保持不变；
  - 主窗口、辅助 Toplevel、内置差异窗口、菜单、CheckBox、ttk 样式一起
    换色，新开的窗口自动继承；
  - 状态色保持语义（修改蓝/新增绿/删除红/冲突橙），深色皮肤下自动提亮。
"""
import json
import os
import shutil
import sys
from _testtmp import TMP  # noqa: E402

HOME = TMP + "/fakehome_theme"
shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME)
os.environ["HOME"] = HOME
os.environ["SVNWB_CONFIG_DIR"] = os.path.join(HOME, "cfg")
os.environ["SVNWB_LEGACY_SETTINGS"] = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "no_such_legacy_settings.json")
os.environ["SVNWB_LOG_DIR"] = os.path.join(HOME, "logs")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import SVNWorkBench as m   # noqa: E402
import tkinter as tk   # noqa: E402
from tkinter import ttk   # noqa: E402

FAILS = []
COUNT = [0]


def check(cond, msg, extra=""):
    COUNT[0] += 1
    if cond:
        print("PASS: %s" % msg)
    else:
        FAILS.append(msg)
        print("FAIL: %s %s" % (msg, extra))


def same_color(a, b):
    return str(a or "").strip().lower() == str(b or "").strip().lower()


THEME_KEYS = {"bg", "panel", "primary", "primary_active", "accent",
              "text", "text_dim", "border"}
EXPECTED = {
    u"青野": ("#EDEDED", "#07C160"),
    u"晴空": ("#F2F6FA", "#0099FF"),
    u"深空": ("#1C1C1E", "#5E5CE6"),
    u"暖阳": ("#FDF6E3", "#268BD2"),
    u"素纸": ("#FFFFFF", "#2383E2"),
    u"极光": ("#0F172A", "#38BDF8"),
    u"原木": ("#FDFCF8", "#D97757"),
    u"青竹": ("#C7EDCC", "#3F8F51"),
    u"雾灰": ("#F0F4F8", "#7F9EB2"),
    u"暗金": ("#121212", "#D4AF37"),
}

# ---------- 1. 主题库本身 ----------
check(len(m.THEMES) == 10 and set(m.THEMES) == set(m.THEME_ORDER),
      "主题库 10 套且 THEME_ORDER 完整")
check(tuple(m.THEME_ORDER) == (u"青野", u"晴空", u"深空", u"暖阳", u"素纸",
                               u"极光", u"原木", u"青竹", u"雾灰", u"暗金"),
      "主题顺序固定（Python 3.5 的 dict 无序，菜单靠这个元组）")
check(m.THEME_DEFAULT == u"晴空", "默认主题是晴空: %r" % m.THEME_DEFAULT)

keys_ok = True
hex_ok = True
for _name, _th in m.THEMES.items():
    if set(_th) != THEME_KEYS:
        keys_ok = False
    for _key in THEME_KEYS:
        _v = str(_th.get(_key) or "")
        if len(_v) != 7 or not _v.startswith("#"):
            hex_ok = False
        else:
            try:
                int(_v[1:], 16)
            except ValueError:
                hex_ok = False
check(keys_ok, "每套皮肤恰好 8 个语义键（bg/panel/primary/...）")
check(hex_ok, "所有颜色都是 #RRGGBB")

spot_ok = True
for _name, (_bg, _primary) in EXPECTED.items():
    _th = m.THEMES.get(_name) or {}
    if _th.get("bg") != _bg or _th.get("primary") != _primary:
        spot_ok = False
        print("  %s: %r/%r" % (_name, _th.get("bg"), _th.get("primary")))
check(spot_ok, "10 套皮肤的关键色与用户给定值一致（未擅自改色）")

# ---------- 2. 默认/非法值回退 ----------
check(m.core.normalize_theme(None) == u"晴空"
      and m.core.normalize_theme("") == u"晴空"
      and m.core.normalize_theme(u"火星") == u"晴空",
      "缺失/未知皮肤名回退晴空")
check(m.core.normalize_theme(u" 深空 ") == u"深空",
      "配置值两端空白可容忍")
check(m.core.APP_BG == "#F2F6FA"
      and m.core.SURFACE == "#FFFFFF"
      and m.core.ACCENT == "#0099FF"
      and m.core.TEXT == "#000000"
      and m.core.MUTED == "#666666",
      "导入即套晴空（APP_BG/SURFACE/ACCENT/TEXT/MUTED）")
check(m.ACCENT_ALT == "#12B7F5" and m.ON_ACCENT == "#ffffff",
      "兼容导出 ACCENT_ALT / ON_ACCENT")

# 晴空：浅色主题的语义状态色保持原值（只换皮肤不改语义）
pal = m.core.palette_for(u"晴空")
check(pal["APP_BG"] == "#F2F6FA" and pal["SURFACE"] == "#FFFFFF"
      and pal["ACCENT"] == "#0099FF" and pal["ACCENT_HOVER"] == "#0088E6"
      and pal["ACCENT_ALT"] == "#12B7F5" and pal["BORDER"] == "#D6E4F0",
      "晴空 8 键映射到界面语义色")
check(pal["TREE_COLORS"] == {"mod": "#1d4ed8", "add": "#15803d",
                             "del": "#dc2626", "conf": "#b45309",
                             "gray": "#666666"},
      "晴空状态色：修改蓝/新增绿/删除红/冲突橙/灰")

# 所有皮肤的可读性（深色皮肤自动提亮，状态色不丢语义）
text_ok = on_ok = cur_ok = status_ok = True
for _name in m.THEME_ORDER:
    _p = m.core.palette_for(_name)
    if m.core.contrast_ratio(_p["TEXT"], _p["SURFACE"]) < 3.5:
        text_ok = False
    if m.core.contrast_ratio(_p["ON_ACCENT"], _p["ACCENT"]) < 2.8:
        on_ok = False
    if m.core.contrast_ratio(_p["UP_CUR_BG"], _p["TEXT"]) < 2.2:
        cur_ok = False
    for _k in ("mod", "add", "del", "conf"):
        if m.core.contrast_ratio(_p["TREE_COLORS"][_k],
                                 _p["SURFACE"]) < 3.49:
            status_ok = False
check(text_ok, "所有皮肤正文/面板对比度 >= 3.5")
check(on_ok, "主色按钮文字（ON_ACCENT）对比度 >= 2.8")
check(cur_ok, "当前行高亮与正文对比度 >= 2.2")
check(status_ok, "所有皮肤下状态色与面板对比度 >= 3.5")

dark_ok = True
for _name in (u"深空", u"极光", u"暗金"):
    _p = m.core.palette_for(_name)
    if not m.core.is_dark(_p["SURFACE"]):
        dark_ok = False
    for _k in ("mod", "add", "del", "conf"):
        if m.core.contrast_ratio(_p["TREE_COLORS"][_k],
                                 _p["SURFACE"]) < 3.5:
            dark_ok = False
check(dark_ok, "深空/极光/暗金判定为深色且状态色已提亮")

snap = m.core.current_palette()
snap_ok = all(k in snap for k in (
    "APP_BG", "SURFACE", "BORDER", "TEXT", "MUTED", "ACCENT",
    "ACCENT_HOVER", "ACCENT_ALT", "ACCENT_DIM", "HOVER_BG", "PRESSED_BG",
    "HEAD_BG", "TAB_BG", "TAB_HOVER_BG", "SCROLL_BG", "SCROLL_HOVER_BG",
    "DISABLED_FG", "UP_HOVER_BG", "UP_CUR_BG", "ON_ACCENT",
    "LOG_COLORS", "TREE_COLORS", "TREE_BG"))
check(snap_ok and m.core.apply_palette(u"晴空") == pal,
      "current_palette 快照与 apply_palette 往返一致")

# ---------- 3. 配置持久化 ----------
fresh = m.ConfigStore(os.path.join(HOME, "cfg_fresh"))
fresh.load()
check(fresh.settings["theme"] == u"晴空",
      "没有配置记录时 theme 默认晴空: %r" % fresh.settings.get("theme"))

bad_dir = os.path.join(HOME, "cfg_bad")
os.makedirs(bad_dir)
with open(os.path.join(bad_dir, "_settings.json"), "w") as f:
    json.dump({"theme": u"火星"}, f, ensure_ascii=False)
bad = m.ConfigStore(bad_dir)
bad.load()
check(bad.settings["theme"] == u"晴空", "配置文件里的非法皮肤名回退晴空")

good_dir = os.path.join(HOME, "cfg_good")
os.makedirs(good_dir)
with open(os.path.join(good_dir, "_settings.json"), "w") as f:
    json.dump({"theme": u"深空"}, f, ensure_ascii=False)
good = m.ConfigStore(good_dir)
good.load()
check(good.settings["theme"] == u"深空", "配置文件里的合法皮肤名被保留并归一")

store = m.ConfigStore(m.CONFIG_DIR)
store.load()
store.set_option("theme", u"深空")
reloaded = m.ConfigStore(m.CONFIG_DIR)
reloaded.load()
check(reloaded.settings["theme"] == u"深空",
      "set_option 写入后重新 load 仍是深空")

# ---------- 4. 启动恢复 + 顶栏入口 ----------
app = m.App(reloaded, m.Hub(reloaded))
app.root.update()
check(app.theme_name == u"深空"
      and m.core.APP_BG == "#1C1C1E"
      and m.core.SURFACE == "#2C2C2E"
      and same_color(app.root.cget("bg"), "#1C1C1E"),
      "启动时按配置恢复深空并套到 root: %r" % app.theme_name)
check(app.btn_theme.cget("text") == u"主题"
      and app._theme_var.get() == u"深空",
      "顶栏有主题按钮且单选变量同步")
style = ttk.Style(app.root)
check(same_color(style.lookup("TButton", "background"), m.core.SURFACE)
      and same_color(style.lookup("TEntry", "fieldbackground"),
                     m.core.SURFACE)
      and same_color(style.lookup("TCombobox", "fieldbackground"),
                     m.core.SURFACE)
      and same_color(style.lookup("Treeview", "background"), m.core.SURFACE)
      and same_color(style.lookup("Accent.TButton", "background"),
                     m.core.ACCENT)
      and same_color(style.lookup("Accent.TButton", "foreground"),
                     m.core.ON_ACCENT)
      and same_color(style.lookup("TScrollbar", "troughcolor"),
                     m.core.APP_BG),
      "ttk 按钮/输入框/树/主按钮/滚动条样式跟随皮肤")

# ---------- 5. 固定一份“界面状态”，换肤时必须原样保留 ----------
app.up_text.configure(state="normal")
app.up_text.delete("1.0", "end")
for i in range(120):
    app.up_text.insert("end", u"line %d\n" % i,
                       ("mod" if i % 2 else "add"))
app.up_text.configure(state="disabled")
app.up_text.tag_add("sel", "10.1", "10.4")
app.up_text.mark_set("insert", "20.0")
app.root.update_idletasks()
app.up_text.yview_moveto(0.5)
app.root.update()
app.up_checked = set(["src/a.c", "src/b.c"])
app.up_selected = "src/a.c"
app.up_sel_line = 0
app._toast(u"提交失败", "err")
app._append_log(u"日志一行", "ok")
app._set_busy(True, "download")
app.root.update()

before_text = app.up_text.get("1.0", "end-1c")
before_sel = tuple(app.up_text.tag_ranges("sel"))
before_y = app.up_text.yview()[0]
before_insert = app.up_text.index("insert")
before_log = app.log.get("1.0", "end-1c")
before_status = app.status_text.cget("text")
before_toast = app.toast_text.cget("text")

app._set_theme(u"暗金")
app.root.update()

check(app.theme_name == u"暗金"
      and m.core.APP_BG == "#121212"
      and same_color(app.root.cget("bg"), "#121212")
      and same_color(app.up_text.cget("bg"), m.core.SURFACE)
      and same_color(app.up_text.cget("fg"), m.core.TEXT),
      "切到暗金：root 与改动列表立刻换色")
check(reloaded.settings["theme"] == u"暗金",
      "换肤写入配置对象: %r" % reloaded.settings.get("theme"))
with open(os.path.join(m.CONFIG_DIR, "_settings.json")) as f:
    saved = json.load(f)
check(saved.get("theme") == u"暗金", "换肤落盘到 _settings.json")

check(app.up_text.get("1.0", "end-1c") == before_text,
      "换肤不改改动列表正文")
check(tuple(app.up_text.tag_ranges("sel")) == before_sel,
      "换肤不改选中范围")
check(abs(app.up_text.yview()[0] - before_y) < 0.01,
      "换肤不跳滚动位置: %.3f -> %.3f" %
      (before_y, app.up_text.yview()[0]))
check(app.up_text.index("insert") == before_insert,
      "换肤不改光标位置")
check(app.up_checked == set(["src/a.c", "src/b.c"])
      and app.up_selected == "src/a.c" and app.up_sel_line == 0,
      "换肤不丢勾选/当前行状态")
check(app.busy is True and app.status_text.cget("text") == before_status,
      "换肤不改任务运行状态与状态栏文案")
check(app.toast_text.cget("text") == before_toast
      and same_color(app.toast_text.cget("foreground"),
                     m.core.LOG_COLORS["err"]),
      "换肤不覆盖运行结果，只把失败色换成新皮肤的可读色")
check(app.log.get("1.0", "end-1c") == before_log
      and same_color(app.log.cget("bg"), m.core.SURFACE)
      and same_color(app.log.tag_cget("ok", "foreground"),
                     m.core.LOG_COLORS["ok"]),
      "换肤不改日志内容，日志面板与标签一起换色")
check(same_color(app.up_text.tag_cget("mod", "foreground"),
                 m.core.TREE_COLORS["mod"])
      and same_color(app.up_text.tag_cget("mod", "background"),
                     m.core.TREE_BG["mod"])
      and same_color(app.up_text.tag_cget("add", "foreground"),
                     m.core.TREE_COLORS["add"])
      and same_color(app.up_text.tag_cget("hover", "background"),
                     m.core.UP_HOVER_BG)
      and same_color(app.up_text.tag_cget("cur", "background"),
                     m.core.UP_CUR_BG),
      "改动列表状态/悬停/当前行标签全部换色")
check(same_color(app.up_empty.cget("fg"), m.core.MUTED)
      and same_color(app.up_count.cget("fg"), m.core.MUTED)
      and same_color(app.status_dot.cget("fg"), m.core.ACCENT),
      "次要文字与运行中状态点换色")
app._set_busy(False, None)
app.root.update()

# ---------- 6. 菜单：10 项单选、即时生效、自身也换色 ----------
menu = m.theme.make_menu(app.root)
app._fill_theme_menu(menu)
labels = [menu.entrycget(i, "label")
          for i in range(menu.index("end") + 1)]
types = [menu.type(i) for i in range(menu.index("end") + 1)]
check(labels == list(m.THEME_ORDER) and set(types) == {"radiobutton"},
      "换肤菜单 10 项顺序与 THEME_ORDER 一致且都是单选")
check(same_color(menu.cget("background"), m.core.SURFACE)
      and same_color(menu.cget("activebackground"), m.core.ACCENT)
      and same_color(menu.cget("activeforeground"), m.core.ON_ACCENT),
      "菜单使用当前皮肤（白底/强调色悬停）")

idx = labels.index(u"素纸")
menu.invoke(idx)
app.root.update()
check(app.theme_name == u"素纸" and m.core.APP_BG == "#FFFFFF"
      and app._theme_var.get() == u"素纸"
      and reloaded.settings["theme"] == u"素纸",
      "从菜单选素纸立即生效并写入配置")
check(same_color(menu.cget("background"), m.core.SURFACE)
      and same_color(menu.cget("activebackground"), m.core.ACCENT)
      and same_color(menu.cget("activeforeground"), m.core.ON_ACCENT),
      "已弹出的菜单对象也跟随换色")

# ---------- 7. 辅助窗口：已有 Toplevel / 内置差异窗口 / 新建窗口 ----------
win = tk.Toplevel(app.root)
win.configure(bg=m.core.APP_BG)
lbl = tk.Label(win, text=u"辅助窗口")
lbl.pack()
txt = m.theme.surface(tk.Text(win, height=3, width=20))
txt.pack()
txt.tag_configure("muted", foreground=m.core.MUTED,
                  background=m.core.SURFACE)
txt.insert("1.0", u"内容不变", "muted")
cb = m.theme.CheckBox(win, text=u"记住")
cb.pack()
cb.set(True)
combo = ttk.Combobox(win, values=[u"https://svn.example.com/repo"])
combo.pack()
win.update()
_popdown = str(combo.tk.call("ttk::combobox::PopdownWindow", combo))
_combo_lb = _popdown + ".f.l"
_combo_pre = (combo.winfo_reqheight() == 32
              and same_color(combo.tk.call(_combo_lb, "cget", "-background"),
                             m.core.SURFACE))
check(same_color(lbl.cget("bg"), m.core.APP_BG)
      and same_color(txt.cget("bg"), m.core.SURFACE)
      and _combo_pre,
      "辅助窗口创建时继承当前皮肤；Combobox 高 32px、下拉列表同色")

diff = m.dialogs.show_diff_win(
    app.root, u"src/a.c",
    {"lines": [u"@@ -1 +1 @@", u"-old", u"+new"],
     "stats": (1, 1, 1)})
diff.update()

app._set_theme(u"青竹")
app.root.update()

check(same_color(win.cget("bg"), m.core.APP_BG)
      and same_color(lbl.cget("bg"), m.core.APP_BG)
      and same_color(lbl.cget("fg"), m.core.TEXT),
      "已有辅助窗口的底色/前景换色")
check(same_color(txt.cget("bg"), m.core.SURFACE)
      and same_color(txt.cget("fg"), m.core.TEXT)
      and same_color(txt.tag_cget("muted", "foreground"), m.core.MUTED)
      and same_color(txt.tag_cget("muted", "background"), m.core.SURFACE)
      and txt.get("1.0", "end-1c") == u"内容不变",
      "辅助窗口 Text 与标签颜色换色且内容不变")
check(cb.get() is True
      and same_color(cb.glyph.cget("fg"), m.core.ACCENT)
      and same_color(cb.label.cget("fg"), m.core.TEXT),
      "CheckBox 勾选状态保留并换色")
check(same_color(combo.tk.call(_combo_lb, "cget", "-background"),
                 m.core.SURFACE)
      and same_color(combo.tk.call(_combo_lb, "cget", "-foreground"),
                     m.core.TEXT)
      and same_color(combo.tk.call(_combo_lb, "cget", "-selectbackground"),
                     m.core.ACCENT)
      and same_color(combo.tk.call(_combo_lb, "cget", "-selectforeground"),
                     m.core.ON_ACCENT),
      "换肤后 Combobox 已有下拉列表一起换色")

check(same_color(diff.cget("bg"), m.core.APP_BG)
      and same_color(diff.diff_text.cget("bg"), m.core.SURFACE)
      and same_color(diff.diff_text.tag_cget("add", "foreground"),
                     m.core.TREE_COLORS["add"])
      and same_color(diff.diff_text.tag_cget("del", "foreground"),
                     m.core.TREE_COLORS["del"])
      and same_color(diff.diff_text.tag_cget("hunk", "foreground"),
                     m.core.LOG_COLORS["cmd"])
      and same_color(diff.diff_text.tag_cget("file", "foreground"),
                     m.core.MUTED),
      "内置差异窗口的底色与增/删/块/文件标签一起换色")
check(u"+new" in diff.diff_text.get("1.0", "end-1c"),
      "内置差异窗口内容保留")

new_win = tk.Toplevel(app.root)
new_lbl = tk.Label(new_win, text=u"新窗口")
new_lbl.pack()
new_win.update()
check(same_color(new_lbl.cget("bg"), m.core.APP_BG)
      and same_color(new_lbl.cget("fg"), m.core.TEXT),
      "换肤后新开的辅助窗口自动继承（option 数据库）")

# 非法皮肤名：从青竹切“火星”应回退晴空
app._set_theme(u"火星")
app.root.update()
check(app.theme_name == u"晴空" and m.core.APP_BG == "#F2F6FA"
      and reloaded.settings["theme"] == u"晴空",
      "运行中传入非法皮肤名回退晴空并写回")

new_win.destroy()
diff.destroy()
win.destroy()

# ---------- 8. 重启恢复 ----------
saved_theme = app.theme_name
app.root.destroy()
again = m.ConfigStore(m.CONFIG_DIR)
again.load()
check(again.settings["theme"] == saved_theme,
      "重启后配置仍读取到上次皮肤: %r" % again.settings.get("theme"))
app2 = m.App(again, m.Hub(again))
app2.root.update()
check(app2.theme_name == u"晴空" and m.core.APP_BG == "#F2F6FA"
      and same_color(app2.root.cget("bg"), "#F2F6FA"),
      "重启窗口恢复上次选择的皮肤")
app2.root.destroy()

# 真正的“没有记录”场景：另一个干净配置目录 -> 晴空
fresh2 = m.ConfigStore(os.path.join(HOME, "cfg_fresh2"))
fresh2.load()
app3 = m.App(fresh2, m.Hub(fresh2))
app3.root.update()
check(app3.theme_name == u"晴空" and m.core.APP_BG == "#F2F6FA"
      and same_color(app3.root.cget("bg"), "#F2F6FA"),
      "全新配置启动默认晴空")
app3.root.destroy()

print("-" * 46)
print("通过 %d 项，失败 %d 项" % (COUNT[0] - len(FAILS), len(FAILS)))
for name in FAILS:
    print("  FAILED: %s" % name)
if FAILS:
    sys.exit(1)
print("theme: ALL PASS (%d)" % COUNT[0])
