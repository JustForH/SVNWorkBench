# -*- coding: utf-8 -*-
"""配置持久化：单文件 _settings.json（默认 ~/.config/SVNWorkBench/）。

v5 起配置离开程序目录：默认放用户主目录的 .config 应用专属文件夹
（XDG 规范），环境变量 SVNWB_CONFIG_DIR 可覆盖（测试指向 /tmp）。

旧版（v4 及以前）配置在程序同级 configs/_settings.json，字段结构相同，
首次启动由 _migrate() 一次性迁入新位置（只搬还没填过的字段，旧文件
原样保留，不主动删除用户数据）。写入是原子的（.tmp + os.replace）。
"""

import json
import os
from pathlib import Path

from .core import (LEGACY_SETTINGS, THEME_DEFAULT, clean_excludes,
                   decode_svn_url, normalize_recent_urls, normalize_theme)

# ============================================================
# 二、配置持久化（单文件 _settings.json）
# ============================================================

def default_settings():
    """配置初值：不预设项目，地址与目录留给用户填写或选工作副本反查。"""
    return {"svn_url": "", "dst": "", "excludes": [],
            "trust_server_cert": False, "diff_tool": "ask",
            "theme": THEME_DEFAULT, "recent_repo_urls": [],
            "migrated": False}


class ConfigStore:
    """单文件配置存储。

    目录结构（默认）：
      ~/.config/SVNWorkBench/
        _settings.json     工作副本、SVN 地址、排除清单、证书选项

    兼容旧版：首次加载把程序同级 configs/_settings.json 的字段并入
    新位置一次，搬完打 migrated 标记，此后不再读旧文件。
    """

    def __init__(self, config_dir):
        self.dir = Path(config_dir)
        self.settings_path = self.dir / "_settings.json"
        self.settings = default_settings()

    # ---- 内部 ----
    def _save_settings(self):
        tmp = self.settings_path.parent / (self.settings_path.name + ".tmp")
        tmp.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(str(tmp), str(self.settings_path))

    @staticmethod
    def _read_json(path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _normalize(self):
        st = self.settings
        diff_tool = str(st.get("diff_tool") or "ask").strip()
        if diff_tool not in ("ask", "meld", "builtin"):
            diff_tool = "ask"
        self.settings = {
            "svn_url": decode_svn_url(str(st.get("svn_url") or "").strip()),
            "dst": str(st.get("dst") or "").strip(),
            "excludes": clean_excludes(st.get("excludes") or []),
            "trust_server_cert": bool(st.get("trust_server_cert")),
            "diff_tool": diff_tool,
            "theme": normalize_theme(st.get("theme")),
            "recent_repo_urls": normalize_recent_urls(
                st.get("recent_repo_urls") or []),
            "migrated": bool(st.get("migrated")),
        }

    def _migrate(self):
        """一次性迁移：旧版程序同级 configs/_settings.json 并入新位置。

        只搬还没填过的字段；搬完打上 migrated 标记，此后不再读旧文件
        （旧文件原样保留，不主动删除用户数据）。字段结构与新版相同。
        """
        if self.settings.get("migrated"):
            return
        data = self._read_json(LEGACY_SETTINGS)
        if data:
            if not self.settings.get("svn_url"):
                self.settings["svn_url"] = decode_svn_url(
                    str(data.get("svn_url") or ""))
            if not self.settings.get("dst"):
                self.settings["dst"] = str(data.get("dst") or "")
            if not self.settings.get("excludes"):
                self.settings["excludes"] = clean_excludes(
                    data.get("excludes") or [])
            if data.get("trust_server_cert"):
                self.settings["trust_server_cert"] = True
        self.settings["migrated"] = True
        self._save_settings()

    # ---- 对外 ----
    def load(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        st = self._read_json(self.settings_path)
        if st:
            self.settings.update(st)
        self._normalize()
        self._migrate()
        self._normalize()
        return self

    def update_fields(self, svn_url, dst, excludes):
        """写回工作副本三项（检出/更新成功启动后调用）。"""
        self.settings["svn_url"] = decode_svn_url(str(svn_url or "").strip())
        self.settings["dst"] = str(dst or "").strip()
        self.settings["excludes"] = clean_excludes(excludes or [])
        self._save_settings()
        return dict(self.settings)

    def set_option(self, key, value):
        self.settings[key] = value
        self._save_settings()
