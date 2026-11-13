#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SVNWorkBench —— 程序入口（薄壳）

功能与实现都在 svnwb/ 包里按职责拆分：
  svnwb/core.py          平台常量、排除规则与通用工具（含 APP_VERSION）
  svnwb/theme.py         平面化主题（ttk 样式 / 配色 / 内边距）
  svnwb/config_store.py  配置持久化（~/.config/SVNWorkBench/_settings.json）
  svnwb/runner.py        后台执行 svn 命令的线程
  svnwb/hub.py           单任务调度 + 事件队列
  svnwb/dialogs.py       通用弹窗与界面辅助
  svnwb/app.py           主窗口（工作副本页）与入口 main()
  svnwb/repo_browser.py  仓库浏览器 + 检出/更新勾选对话框（懒加载）
  svnwb/log_view.py      提交历史窗口（svn log + 版本对比，懒加载）

依赖: Python 3.5.2+ 标准库（tkinter 随 Python 附带）+ svn 命令行客户端。
      Debian/Ubuntu 若缺少 tkinter: sudo apt install python3-tk
运行: python3 SVNWorkBench.py [工作副本目录]
      带启动参数时自动把该目录填进工作副本并反查地址
      （供文件管理器右键"打开方式"集成使用，见 README）。

配置在 ~/.config/SVNWorkBench/，日志在 /tmp/SVNWorkBench-<用户名>/logs/，
都不在程序目录——程序目录只需本入口脚本与 svnwb/ 包。
"""

import sys
from pathlib import Path

from tkinter import filedialog, messagebox

from svnwb import dialogs, config_store, core  # noqa: F401  （供测试 monkeypatch）
from svnwb.app import App, main  # noqa: F401
from svnwb.config_store import ConfigStore  # noqa: F401
from svnwb.core import (  # noqa: F401
    ACCENT, ACCENT_ALT, ACCENT_HOVER, APP_BG, APP_NAME, APP_TITLE, APP_VERSION,
    BASE_DIR, BORDER, CONFIG_DIR, LEGACY_SETTINGS, CHECK_OFF,
    CHECK_ON, HOVER_BG, LOG_COLORS, ITEM_TAG, ITEM_TEXT, MODE_NAMES, MUTED,
    ON_ACCENT, PRESSED_BG, RECENT_URL_LIMIT, SURFACE, TEXT, THEMES,
    THEME_DEFAULT, THEME_ORDER, TREE_BG, TREE_COLORS,
    UP_CHECK_DELTA,
    UP_CUR_BG, UP_FILL, UP_FONT_DELTA, UP_HOVER_BG, UP_PATH_X, UP_REV_X,
    UP_TEXT_OFFSET,
    STATUS_SORT_ORDER, status_sort_key,
    ApiError, BusyError, RunCancelled,
    cached_credentials, clean_excludes, DIFF_MAX_LINES, diff_stats, fmt_date,
    is_excluded,
    join_url, list_credentials, log_dir, looks_like_collection_error,
    normalize_exclude, normalize_recent_urls, normalize_svn_url,
    decode_svn_url, parse_auth_fields, parse_info_url, push_recent_url,
    parse_log_xml, parse_repo_index, parse_status_xml, probe_wc_url,
    repo_path_to_url, resolve_dst, subversion_auth_dir,
    tail_msg,
    topmost_paths,
)
from svnwb import theme  # noqa: F401  （平面化主题，供测试参考）
from svnwb.hub import Hub  # noqa: F401
from svnwb.runner import Runner  # noqa: F401
from svnwb.dialogs import (  # noqa: F401
    ask_auth, ask_cert, ask_confirm, install_edit_shortcuts, open_with_system,
    show_diff_win, show_logs,
)

if __name__ == "__main__":
    sys.exit(main())
