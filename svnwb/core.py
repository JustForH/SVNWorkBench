# -*- coding: utf-8 -*-
"""平台常量、排除规则与通用工具，以及界面文案/配色常量。

本模块不依赖 tkinter，供主界面（svnwb.app）与仓库浏览器（svnwb.repo_browser）
共同复用；界面用到的纯字符串常量（文案、颜色、列位）也放在这里，
以免两个界面模块互相导入形成循环。
"""

import getpass
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

APP_NAME = "SVNWorkBench"
APP_TITLE = APP_NAME
APP_VERSION = "5.0"

# 全局主题库：一行一套皮肤，8 个键对应界面语义色（见下方“平面化主题配色”）。
# 这是唯一数据源，不要在别处再抄一份；键名/值由用户给定，保持原样。
THEMES = {
    "青野": {"bg": "#EDEDED", "panel": "#F7F7F7", "primary": "#07C160", "primary_active": "#06AD56", "accent": "#10AEFF", "text": "#191919", "text_dim": "#888888", "border": "#D6D6D6"},
    "晴空": {"bg": "#F2F6FA", "panel": "#FFFFFF", "primary": "#0099FF", "primary_active": "#0088E6", "accent": "#12B7F5", "text": "#000000", "text_dim": "#666666", "border": "#D6E4F0"},
    "深空": {"bg": "#1C1C1E", "panel": "#2C2C2E", "primary": "#5E5CE6", "primary_active": "#4B49CC", "accent": "#32D74B", "text": "#F2F2F7", "text_dim": "#8E8E93", "border": "#38383A"},
    "暖阳": {"bg": "#FDF6E3", "panel": "#EEE8D5", "primary": "#268BD2", "primary_active": "#1E6EA8", "accent": "#2AA198", "text": "#657B83", "text_dim": "#93A1A1", "border": "#E4D8B0"},
    "素纸": {"bg": "#FFFFFF", "panel": "#F7F7F5", "primary": "#2383E2", "primary_active": "#1B6DBF", "accent": "#0F7B6C", "text": "#37352F", "text_dim": "#9B9A97", "border": "#E9E9E7"},
    "极光": {"bg": "#0F172A", "panel": "#1E293B", "primary": "#38BDF8", "primary_active": "#0EA5E9", "accent": "#818CF8", "text": "#F8FAFC", "text_dim": "#94A3B8", "border": "#334155"},
    "原木": {"bg": "#FDFCF8", "panel": "#FFFFFF", "primary": "#D97757", "primary_active": "#C4643F", "accent": "#5F7A61", "text": "#333333", "text_dim": "#777777", "border": "#E8E4D9"},
    "青竹": {"bg": "#C7EDCC", "panel": "#E5F4E8", "primary": "#3F8F51", "primary_active": "#327342", "accent": "#256B3A", "text": "#1A331E", "text_dim": "#4A6A52", "border": "#A8D8B0"},
    "雾灰": {"bg": "#F0F4F8", "panel": "#FFFFFF", "primary": "#7F9EB2", "primary_active": "#6A8B9E", "accent": "#9CA8B8", "text": "#2C3A47", "text_dim": "#7A8997", "border": "#D6E0E8"},
    "暗金": {"bg": "#121212", "panel": "#1E1E1E", "primary": "#D4AF37", "primary_active": "#B5952F", "accent": "#F3E5AB", "text": "#E0E0E0", "text_dim": "#888888", "border": "#2C2C2C"}
}
THEME_DEFAULT = u"晴空"
# Python 3.5 的 dict 不保证顺序，菜单/测试顺序一律用这个元组（与上方一致）
THEME_ORDER = (u"青野", u"晴空", u"深空", u"暖阳", u"素纸",
               u"极光", u"原木", u"青竹", u"雾灰", u"暗金")


def _base_dir():
    """程序目录：源码运行 = 包上一级；PyInstaller 单文件 = 可执行文件旁。

    单文件模式下 `__file__` 指向临时解压目录（sys._MEIPASS，退出即消失），
    程序目录必须落到 exe 实际所在目录（sys.executable，实测指向用户
    双击的那个文件）。只用于定位“旧版配置迁移源”等程序旁资源——
    **配置与日志不再放程序目录**，见 CONFIG_DIR / log_dir()。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _user_name():
    """当前用户名（/tmp 下按用户隔离日志目录用）。"""
    try:
        return getpass.getuser() or "user"
    except Exception:
        return "user"


def default_config_dir():
    """配置默认目录：~/.config/SVNWorkBench（尊重 XDG_CONFIG_HOME）。"""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def default_log_dir():
    """日志默认目录：/tmp/SVNWorkBench-<用户名>/logs。

    /tmp 是全系统共享的，按用户名分子目录避免多用户互相踩权限；
    重启即清（运行日志本来就是短期排障数据）。
    """
    return Path(tempfile.gettempdir()) / ("%s-%s" % (APP_NAME, _user_name())) \
        / "logs"


BASE_DIR = _base_dir()
# 配置：用户主目录下的应用专属目录（环境变量可覆盖，测试指向 /tmp）。
# 旧版（v4 及以前）配置在程序同级 configs/_settings.json，字段结构相同，
# 首次启动由 LEGACY_SETTINGS 一次性迁入新位置（config_store._migrate）。
CONFIG_DIR = Path(os.environ.get("SVNWB_CONFIG_DIR", default_config_dir()))
LEGACY_SETTINGS = Path(os.environ.get("SVNWB_LEGACY_SETTINGS",
                                      BASE_DIR / "configs" / "_settings.json"))

AUTH_HINTS = ("E170001", "E215004", "Authentication error", "authorization failed",
              "Authentication failed", "No more credentials", "password for")
CERT_HINTS = ("E230001", "certificate verification failed", "Server SSL certificate")

# ============================================================
# 一、排除规则与通用工具（与桌面版一致）
# ============================================================

def normalize_exclude(p):
    p = (p or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    while "//" in p:
        p = p.replace("//", "/")
    return p.strip("/")


def clean_excludes(items):
    out, seen = [], set()
    for it in items or []:
        n = normalize_exclude(it)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def topmost_paths(rels):
    """相对路径集合 -> 互不包含的最上层集合（浅者优先，同深度按字典序）。

    排除清单与恢复清单共用：上层目录的 set-depth 命令已经覆盖其子孙，
    子孙没有必要重复列出。
    """
    out = []
    for rel in sorted(set([normalize_exclude(r) for r in rels or []]),
                      key=lambda s: (s.count("/"), s)):
        if not rel or any(rel == e or rel.startswith(e + "/") for e in out):
            continue
        out.append(rel)
    return out


def is_excluded(rel, excludes):
    return any(rel == e or rel.startswith(e + "/") for e in excludes)


def has_exclude_child(rel, excludes):
    return any(e.startswith(rel + "/") for e in excludes)


def safe_filename(name):
    return re.sub(r'[^\w\u4e00-\u9fff.-]+', '_', name or "run").strip("_") or "run"


def log_dir():
    """运行日志目录：默认 /tmp/SVNWorkBench-<用户名>/logs（见 default_log_dir）。

    SVNWB_LOG_DIR 可覆盖（测试把日志指向临时目录，不污染真实路径）。
    配置在 ~/.config/SVNWorkBench，日志在 /tmp——两者必须分开存放。
    """
    return Path(os.environ.get("SVNWB_LOG_DIR", default_log_dir()))


# ============================================================
# svn 本地登录凭据（~/.subversion/auth/svn.simple）
# ============================================================
# svn 把“记住密码”的凭据缓存到 ~/.subversion/auth/svn.simple/ 下的散列
# 文件名里（每个文件一条凭据，内容是 K <长度>/V <长度> 的字段块）。
# 删除某个文件 = svn 忘掉该凭据，下次连接重新询问用户名/密码。
# 主界面“账号管理”窗口列出并删除它们（删除前必须展示名称让用户确认）。

def subversion_auth_dir():
    """svn 凭据缓存目录（svn.simple，即用户名/密码那类）。

    SVNWB_SUBVERSION_DIR 可覆盖 .subversion 根目录（测试指向 /tmp，
    不碰真实用户凭据）。
    """
    base = os.environ.get("SVNWB_SUBVERSION_DIR") or str(
        Path.home() / ".subversion")
    return Path(base) / "auth" / "svn.simple"


def parse_auth_fields(text):
    """解析 svn 凭据文件（K/V 长度前缀格式）-> {字段名: 值}。"""
    lines = (text or "").splitlines()
    out = {}
    i = 0
    while i < len(lines):
        if lines[i].startswith("K ") and i + 1 < len(lines):
            key = lines[i + 1]
            i += 2
            if i < len(lines) and lines[i].startswith("V ") and i + 1 < len(lines):
                out[key] = lines[i + 1]
                i += 2
        else:
            i += 1
    return out


def list_credentials(auth_dir=None):
    """列出本地缓存的 svn 登录凭据。

    返回 [{"path", "file", "realm", "username", "name"}]：realm 是 svn 的
    “认证域”字符串（一般含服务器地址与用户名），name 是界面显示名
    （realm 为空时退回用户名/文件名）。目录不存在返回空列表。
    """
    d = Path(auth_dir) if auth_dir else subversion_auth_dir()
    try:
        files = sorted(p for p in d.iterdir() if p.is_file())
    except OSError:
        return []
    out = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fields = parse_auth_fields(text)
        realm = (fields.get("svn:realmstring") or "").strip()
        user = (fields.get("username") or "").strip()
        out.append({"path": str(f), "file": f.name, "realm": realm,
                    "username": user,
                    "name": realm or user or f.name})
    return out


def _realm_url(realm):
    """从 svn 认证域里取出服务器地址（取第一个 http(s) URL）。"""
    m = re.search(r"(https?://[^\s<>]+)", str(realm or ""))
    return m.group(1).rstrip(".,;") if m else u""


def cached_credentials(url, auth_dir=None):
    """从 svn 凭据缓存中找与 url 同源的登录凭据（供 HTTP 索引读取）。

    返回 {"username", "password", "realm"} 或 None。只使用 svn.simple 里
    真正的明文密码；没有密码（例如交给系统密钥环）时返回 None，由调用方
    弹登录框。密码只用于 HTTP Basic 认证，绝不写日志或界面。
    """
    target = urllib.parse.urlsplit(str(url or ""))
    host = (target.hostname or "").lower()
    if not host:
        return None
    try:
        target_port = target.port or (443 if target.scheme.lower() == "https" else 80)
    except ValueError:
        return None
    d = Path(auth_dir) if auth_dir else subversion_auth_dir()
    try:
        files = sorted(p for p in d.iterdir() if p.is_file())
    except OSError:
        return None
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fields = parse_auth_fields(text)
        realm = (fields.get("svn:realmstring") or "").strip()
        user = (fields.get("username") or "").strip()
        password = fields.get("password") or ""
        if not user or not password:
            continue
        realm_url = _realm_url(realm)
        if not realm_url:
            continue
        ru = urllib.parse.urlsplit(realm_url)
        rhost = (ru.hostname or "").lower()
        if not rhost or rhost != host:
            continue
        if (ru.scheme or "").lower() != (target.scheme or "").lower():
            continue
        try:
            rport = ru.port or (443 if ru.scheme.lower() == "https" else 80)
        except ValueError:
            continue
        if rport != target_port:
            continue
        return {"username": user, "password": password, "realm": realm}
    return None


def resolve_dst(dst):
    """解析本地目录。相对路径以程序所在目录为基准，
    因此 ../SP_PISA2_0 指向程序文件夹的上一层（与代码同级）。"""
    s = os.path.expanduser(str(dst).strip())
    p = Path(s)
    if p.is_absolute():
        return p
    return Path(os.path.normpath(str(BASE_DIR / p)))


_PCT_RE = re.compile(r"%[0-9A-Fa-f]{2}")

# 仓库浏览器地址栏的“最近浏览”上限（最新在前；配置字段 recent_repo_urls）
RECENT_URL_LIMIT = 10


def normalize_svn_url(u):
    """比较用 URL 归一化：解码百分号编码并去掉尾部斜杠。"""
    return decode_svn_url(str(u or "").rstrip("/"))


def normalize_recent_urls(values, limit=RECENT_URL_LIMIT):
    """整理最近浏览地址：去空、解码百分号、去尾部斜杠、按地址去重。

    只接受列表/元组（配置文件被手改成别的类型时按空处理），顺序保持不变
    （调用方约定最新在前），最多保留 limit 条。
    """
    out = []
    seen = set()
    if not isinstance(values, (list, tuple)):
        return out
    for raw in values:
        url = normalize_svn_url(raw)
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
        if limit and len(out) >= limit:
            break
    return out


def push_recent_url(values, url, limit=RECENT_URL_LIMIT):
    """把一次成功浏览的地址放到最前；重复地址只保留最新一条。"""
    current = normalize_recent_urls(values, limit)
    url = normalize_svn_url(url)
    if not url:
        return current
    return normalize_recent_urls([url] + current, limit)


def decode_svn_url(url):
    """SVN 地址含百分号编码时自动解码为可读文本。"""
    u = str(url or "").strip()
    if not _PCT_RE.search(u):
        return u
    try:
        d = urllib.parse.unquote(u, encoding="utf-8", errors="strict")
        return d if d else u
    except (UnicodeDecodeError, ValueError):
        return u


def _xml_local_name(tag):
    """XML 标签名去掉命名空间（集合索引一般无命名空间，兼容带前缀的）。"""
    return str(tag or "").rsplit("}", 1)[-1]


def parse_repo_index(data, base_url):
    """解析 Subversion 集合根索引（mod_dav_svn 的 <svn><index>）。

    返回 [{"kind":"dir", "name", "url", "rev", "author", "date", "size"}]；
    不是集合根（具体仓库页面、HTML、坏 XML）返回 None。
    `index` 带 base 属性时是具体仓库页面，不是集合根，也返回 None。
    只依赖标准库，地址全部按 base_url + href 计算（去掉尾部斜杠，与
    手输地址/树节点 iid 保持一致），不绑定任何服务器。
    """
    if not base_url:
        return None
    if not isinstance(data, bytes):
        try:
            data = str(data or "").encode("utf-8")
        except (TypeError, UnicodeError):
            return None
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError, TypeError):
        return None
    if _xml_local_name(root.tag) != "svn":
        return None
    index = None
    for child in list(root):
        if _xml_local_name(child.tag) == "index":
            index = child
            break
    if index is None or (index.get("base") or "").strip():
        return None
    base = str(base_url).rstrip("/") + "/"
    out = []
    seen = set()
    for child in list(index):
        if _xml_local_name(child.tag) != "dir":
            continue
        name = (child.get("name") or "").strip()
        href = (child.get("href") or "").strip()
        if not name or not href:
            continue
        url = urllib.parse.urljoin(base, href).rstrip("/")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"kind": "dir", "name": name, "url": url,
                    "rev": "", "author": "", "date": "", "size": ""})
    return out


def looks_like_collection_error(text):
    """svn list 对“仓库集合根”的典型报错（不是具体仓库）。"""
    t = str(text or "")
    return ("E175009" in t or "E130003" in t or "190001" in t
            or "does not contain the name of a repository" in t.lower())


def cmd_str(cmd):
    """命令转显示文本；--password 的值打码，避免密码进入界面/日志。"""
    out = []
    i = 0
    while i < len(cmd):
        a = cmd[i]
        if a == "--password" and i + 1 < len(cmd):
            out += [a, "******"]
            i += 2
            continue
        out.append(a)
        i += 1
    return " ".join(shlex.quote(c) for c in out)


def _contains_any(text, hints):
    return any(h.lower() in text.lower() for h in hints)


def join_url(url, rel):
    base = url.rstrip("/")
    if not rel:
        return base
    return "%s/%s" % (base, urllib.parse.quote(rel, safe="/"))


# 改动列表默认排序：版本控制内的改动按状态分组（冲突/缺失等异常在前，
# 常规修改/新增/删除随后），**未版本控制（?）与忽略（I）排在最后**
# （用户要求“默认将未版本控制的放到最后”）。同组内按路径字典序。
STATUS_SORT_ORDER = ("conflicted", "missing", "obstructed", "incomplete",
                     "modified", "replaced", "added", "deleted", "external",
                     "normal", "none", "ignored", "unversioned")


def status_sort_key(it):
    """改动列表排序键：(状态分组, 路径)。未版本控制在最后一组。"""
    it = it or {}
    item = it.get("item") or ""
    try:
        rank = STATUS_SORT_ORDER.index(item)
    except ValueError:
        rank = len(STATUS_SORT_ORDER)
    return (rank, it.get("path") or "")


def parse_status_xml(text):
    try:
        root = ET.fromstring((text or "").strip() or "<status/>")
    except ET.ParseError:
        raise RuntimeError("svn status 输出解析失败（可能不是工作副本目录）")
    items = []
    for entry in root.iter("entry"):
        wc = entry.find("wc-status")
        if wc is None:
            continue
        repos = entry.find("repos-status")
        items.append({
            "path": entry.get("path", ""),
            "item": wc.get("item", "none"),
            "rev": wc.get("revision", "") or "",
            "repos_item": (repos.get("item", "") if repos is not None else "") or "",
        })
    items.sort(key=status_sort_key)
    return items


def parse_info_url(text):
    """`svn info --xml` 输出 -> 工作副本来源地址（解析不出返回空串）。"""
    try:
        root = ET.fromstring((text or "").strip() or "<info/>")
    except ET.ParseError:
        return u""
    el = root.find("entry/url")
    return (el.text or "").strip() if el is not None else u""


def fmt_date(s):
    """svn 的 ISO 时间 -> “YYYY-MM-DD HH:MM”。"""
    s = (s or "").strip()
    if not s:
        return ""
    try:
        return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").strftime(
            "%Y-%m-%d %H:%M")
    except ValueError:
        return s[:16].replace("T", " ") if len(s) >= 16 else s


def parse_log_xml(text):
    """`svn log --xml -v` 输出 -> 提交列表（含每个版本改动的文件）。

    每项: {"rev", "author", "date", "msg", "paths"}，paths 是该版本改动的
    [{"action", "kind", "path"}]（action: A 添加 / M 修改 / D 删除 …，
    path 是**仓库根**相对的路径）。解析失败返回 []。
    """
    try:
        root = ET.fromstring((text or "").strip() or "<log/>")
    except ET.ParseError:
        return []
    out = []
    for lg in root.findall("logentry"):
        paths = []
        for p in lg.findall("paths/path"):
            paths.append({"action": p.get("action") or "",
                          "kind": p.get("kind") or "",
                          "path": (p.text or "")})
        paths.sort(key=lambda x: x["path"])
        out.append({
            "rev": lg.get("revision") or "",
            "author": (lg.findtext("author") or "").strip(),
            "date": (lg.findtext("date") or "").strip(),
            "msg": (lg.findtext("msg") or "").strip(),
            "paths": paths,
        })
    return out


def repo_path_to_url(repo_root, repo_path):
    """仓库根地址 + `svn log -v` 给出的仓库路径 -> 该文件的完整地址。

    地址目标（仓库浏览器右键“查看提交记录”）没有工作副本可换算，
    单文件对比直接用仓库根地址拼出文件地址即可；两边都是“解码后”的
    形态（地址走 decode_svn_url，log 的 XML 文本本身就是 UTF-8 明文），
    直接拼接。解析不出（缺根地址或路径）返回空串，调用方降级为整版本
    对比。
    """
    root = decode_svn_url(repo_root or "").rstrip("/")
    p = (repo_path or "").strip()
    if not root or not p:
        return u""
    return root + "/" + p.lstrip("/")


def _svn_info_xml(path):
    """跑 `svn info --xml <path>`（只读本地 .svn，不联网）。

    返回 (rc, stdout 文本, 错误说明)；rc 为 0 表示成功。
    """
    p = str(path or "")
    if not p:
        return 1, u"", u"请先填写工作副本路径"
    if not os.path.isdir(p):
        return 1, u"", u"目录不存在: %s" % p
    try:
        pr = subprocess.Popen(["svn", "info", "--xml", "--non-interactive", p],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return 1, u"", u"未找到 svn 命令行工具"
    try:
        out, err = pr.communicate(timeout=30)
    except Exception:
        try:
            pr.kill()
            pr.communicate()
        except Exception:
            pass
        return 1, u"", u"读取工作副本信息超时"
    text = out.decode("utf-8", "replace")
    if pr.returncode != 0:
        msg = (err or b"").decode("utf-8", "replace").strip()
        msg = [l for l in msg.split("\n") if l.strip()][-1:] or [u""]
        return pr.returncode, text, (u"该目录不是 SVN 工作副本%s"
                                     % (u"（%s）" % msg[0] if msg[0] else u""))
    return 0, text, u""


def probe_wc_url(path):
    """按工作副本目录反查 SVN 地址。

    `svn info` 只读本地 .svn 目录，不联网、不需要凭据，可在界面里直接调。
    返回 (地址, 错误说明)：地址非空表示成功，否则错误说明给出原因。
    """
    rc, text, err = _svn_info_xml(path)
    if rc != 0:
        return u"", err
    url = parse_info_url(text)
    if not url:
        return u"", u"无法从工作副本解析出 SVN 地址"
    return decode_svn_url(url), u""


def parse_info_repo(text):
    """`svn info --xml` 输出 -> (来源地址, 仓库根地址)；解析不出为空串。"""
    try:
        doc = ET.fromstring((text or "").strip() or "<info/>")
    except ET.ParseError:
        return u"", u""
    entry = doc.find("entry")
    if entry is None:
        return u"", u""
    url_el = entry.find("url")
    rep = entry.find("repository")
    root_el = rep.find("root") if rep is not None else None
    return ((url_el.text or "").strip() if url_el is not None else u"",
            (root_el.text or "").strip() if root_el is not None else u"")


def diff_stats(lines):
    add = rem = hunk = 0
    for ln in lines:
        if ln.startswith("+++") or ln.startswith("---"):
            continue
        if ln.startswith("+"):
            add += 1
        elif ln.startswith("-"):
            rem += 1
        elif ln.startswith("@@"):
            hunk += 1
    return add, rem, hunk


class RunCancelled(Exception):
    pass


class ApiError(RuntimeError):
    pass


class BusyError(RuntimeError):
    pass


# ============================================================
# 界面文案与配色（纯数据：主界面与仓库浏览器共用，不放 app 模块以免循环导入）
# ============================================================
MODE_NAMES = {"download": u"下载", "status": u"读取状态", "update": u"更新",
              "add": u"加入版本控制", "revert": u"恢复", "commit": u"提交",
              "delete": u"删除", "diff": u"生成差异", "cat": u"准备对比",
              "log": u"读取提交历史", "logdiff": u"生成版本差异",
              "export": u"导出"}

# 改动状态 -> 显示文本 / 颜色标签（与旧版一致）
ITEM_TEXT = {
    "modified": u"M 修改", "added": u"A 新增", "deleted": u"D 删除",
    "replaced": u"R 替换", "conflicted": u"C 冲突", "unversioned": u"? 未版本控制",
    "missing": u"! 缺失", "obstructed": u"~ 阻碍", "ignored": u"I 忽略",
    "external": u"X 外部", "incomplete": u"= 不完整", "none": u"无改动",
    "normal": u"无改动",
}
ITEM_TAG = {
    "modified": "mod", "added": "add", "replaced": "add", "deleted": "del",
    "conflicted": "conf", "missing": "conf", "obstructed": "conf",
    "incomplete": "conf", "unversioned": "gray", "ignored": "gray",
    "external": "gray", "none": "gray", "normal": "gray",
}
# 勾选标记（挑勾式）。改动列表与仓库浏览器共用这两个常量，测试也按常量断言；
# 列表里字号由 chk 标签放大（见 UP_CHECK_DELTA），所以这里用细笔画的字形也够醒目
CHECK_ON = u"\u2611"   # ☑ 已勾选
CHECK_OFF = u"\u2610"  # ☐ 未勾选

# ---------------- 平面化主题配色（见 svnwb/theme.py） ----------------
# core 不 import tkinter，这里只放纯字符串，供 app/dialogs/repo_browser 共用。
# **颜色不再写死**：THEMES 是唯一数据源，apply_palette() 按当前皮肤算出
# 下面这组语义色常量；切换皮肤时 theme.recolor() 再把已有控件的旧色映射成
# 新色（不重建控件）。模块导入时默认套“晴空”，所以没有配置记录时就是晴空。
APP_BG = THEMES[THEME_DEFAULT]["bg"]        # 页面底色（Frame/Label 默认取它）
SURFACE = THEMES[THEME_DEFAULT]["panel"]    # 面板：输入框、日志、列表、树的底色
BORDER = THEMES[THEME_DEFAULT]["border"]    # 1px 细边框（替代 Tk 默认的立体凹陷）
TEXT = THEMES[THEME_DEFAULT]["text"]        # 正文
ACCENT = THEMES[THEME_DEFAULT]["primary"]   # 主色：主按钮、选中行、输入焦点框
ACCENT_HOVER = THEMES[THEME_DEFAULT]["primary_active"]  # 主色悬停（更深一档）
ACCENT_ALT = THEMES[THEME_DEFAULT]["accent"]  # 次级强调：info 提示、日志 info
MUTED = THEMES[THEME_DEFAULT]["text_dim"]   # 次要文字

# 下面这些由 apply_palette() 按皮肤推导，先给一组安全初值（导入后立即覆盖）
HOVER_BG = "#f0f0f0"         # 次要按钮悬停底色
PRESSED_BG = "#dbdbdb"       # 次要按钮按下底色
ACCENT_DIM = "#85c9f9"       # 主色按钮禁用态
HEAD_BG = "#f2f2f2"          # 表头底色
TAB_BG = "#e4ecf5"           # 未选中页签
TAB_HOVER_BG = "#dbe0e5"     # 页签/表头悬停
SCROLL_BG = "#b9c6d4"        # 滚动条滑块
SCROLL_HOVER_BG = "#666666"  # 滚动条滑块悬停
DISABLED_FG = "#a3a7ab"      # 禁用态文字
ON_ACCENT = "#ffffff"        # 主色上的文字色（白字对比度不足时自动换深色）
ON_ACCENT_DISABLED = "#d4ebfc"  # 主色禁用按钮上的文字

# 状态配色。改动列表用 tk.Text 逐行着色：本机 Tk 的 ttk.Treeview 行标签
# （foreground/background）完全不生效（样式级配色才有效），Text 标签没问题。
# **状态色保持语义**（修改蓝/新增绿/删除红/冲突橙），不跟随皮肤主色；
# 深色皮肤下由 ensure_contrast() 自动提亮，保证看得清。
LOG_COLORS = {"cmd": "#008ae6", "ok": "#15803d", "err": "#dc2626",
              "warn": "#b45309", "info": "#0e8bb8"}
TREE_COLORS = {"mod": "#1d4ed8", "add": "#15803d", "del": "#dc2626",
               "conf": "#b45309", "gray": "#666666"}
TREE_BG = {"mod": "#e8edfb", "add": "#e8f2ea", "del": "#fbe9e9",
           "conf": "#fbf0e6", "gray": "#f3f3f3"}


# ---- 配色计算（纯 Python，不依赖 tkinter；只用标准库） ----
def _hex_rgb(value):
    """#RRGGBB -> (r, g, b)；非法值按黑色处理（只用于配色计算）。"""
    s = str(value or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return (0, 0, 0)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def _rgb_hex(rgb):
    return "#%02x%02x%02x" % (
        max(0, min(255, int(round(rgb[0])))),
        max(0, min(255, int(round(rgb[1])))),
        max(0, min(255, int(round(rgb[2])))))


def mix(color1, color2, amount):
    """把 color1 按 amount（0~1）混向 color2。"""
    a = max(0.0, min(1.0, float(amount)))
    r1, g1, b1 = _hex_rgb(color1)
    r2, g2, b2 = _hex_rgb(color2)
    return _rgb_hex((r1 + (r2 - r1) * a,
                     g1 + (g2 - g1) * a,
                     b1 + (b2 - b1) * a))


def _channel_lum(value):
    c = value / 255.0
    if c <= 0.03928:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def luminance(color):
    r, g, b = _hex_rgb(color)
    return (0.2126 * _channel_lum(r) + 0.7152 * _channel_lum(g)
            + 0.0722 * _channel_lum(b))


def contrast_ratio(color1, color2):
    l1, l2 = luminance(color1), luminance(color2)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def is_dark(color):
    """深色背景判定：亮度低于 0.45（深空/极光/暗金都算深色）。"""
    return luminance(color) < 0.45


def readable_on(bg, light="#ffffff", dark="#111111"):
    """主色上的文字色：优先白字，白字对比度不足 2.8 时换深色字。

    晴空白字对比度约 3.0，保留白字（与旧版观感一致）；青野/极光/暗金
    这类亮主色白字只有 2.1~2.4，自动换深色字，避免“看不清”。
    """
    if contrast_ratio(light, bg) >= 2.8:
        return light
    return dark


def ensure_contrast(color, bg, minimum=3.0):
    """保证 color 在 bg 上至少达到 minimum 对比度；不够就朝黑/白方向调。"""
    if contrast_ratio(color, bg) >= minimum:
        return color
    target = "#ffffff" if is_dark(bg) else "#000000"
    for step in range(1, 11):
        cand = mix(color, target, step / 10.0)
        if contrast_ratio(cand, bg) >= minimum:
            return cand
    return target


def _tint_for_text(panel, accent, text, amount, minimum=2.5):
    """按指定色给面板染色，保证与正文至少 minimum 的对比度（暖阳正文偏灰）。"""
    for step in range(10, 0, -1):
        cand = mix(panel, accent, amount * step / 10.0)
        if contrast_ratio(cand, text) >= minimum:
            return cand
    return panel


def normalize_theme(name):
    """配置里的皮肤名 -> 合法皮肤名；缺失/未知一律回退晴空。"""
    name = str(name or "").strip()
    return name if name in THEMES else THEME_DEFAULT


def palette_for(name):
    """按皮肤名算出一整套语义色；键名与 core 里的常量一一对应。"""
    th = THEMES[normalize_theme(name)]
    bg = th["bg"]
    panel = th["panel"]
    border = th["border"]
    text = th["text"]
    muted = th["text_dim"]
    accent = th["primary"]
    accent_active = th["primary_active"]
    accent_alt = th["accent"]

    # 状态色保持语义，只按面板明暗调对比度；深色皮肤下自动提亮
    status_mod = ensure_contrast("#1d4ed8", panel, 3.5)
    status_add = ensure_contrast("#15803d", panel, 3.5)
    status_del = ensure_contrast("#dc2626", panel, 3.5)
    status_conf = ensure_contrast("#b45309", panel, 3.5)
    status_gray = ensure_contrast(muted, panel, 3.0)

    dark = is_dark(panel)
    tint = 0.28 if dark else 0.18
    tree_bg = {
        "mod": mix(panel, status_mod, tint),
        "add": mix(panel, status_add, tint),
        "del": mix(panel, status_del, tint),
        "conf": mix(panel, status_conf, tint),
        "gray": mix(panel, status_gray, 0.18 if dark else 0.10),
    }
    # 当前行用固定的“选中蓝”，不跟皮肤主色走：青野/暖阳/原木/深空/极光的
    # accent 本身偏绿，若用它调底色，当前行会与“新增（绿）/修改（蓝）”的
    # 状态底色撞色。选中蓝只按面板明暗调深浅，保证醒目且不与状态语义混淆。
    cur_amount = 0.55 if dark else 0.45

    return {
        "APP_BG": bg,
        "SURFACE": panel,
        "BORDER": border,
        "TEXT": text,
        "MUTED": muted,
        "ACCENT": accent,
        "ACCENT_HOVER": accent_active,
        "ACCENT_ALT": accent_alt,
        "ACCENT_DIM": mix(accent, bg, 0.55),
        "HOVER_BG": mix(panel, text, 0.06),
        "PRESSED_BG": mix(panel, text, 0.14),
        "HEAD_BG": mix(panel, text, 0.05),
        "TAB_BG": mix(bg, border, 0.50),
        "TAB_HOVER_BG": mix(bg, text, 0.08),
        "SCROLL_BG": mix(border, muted, 0.35),
        "SCROLL_HOVER_BG": muted,
        "DISABLED_FG": mix(muted, bg, 0.45),
        "UP_HOVER_BG": mix(panel, accent, 0.10),
        "UP_CUR_BG": _tint_for_text(panel, "#3b82f6", text, cur_amount,
                                    2.2),
        "ON_ACCENT": readable_on(accent),
        "ON_ACCENT_DISABLED": mix(readable_on(accent),
                                  mix(accent, bg, 0.55), 0.35),
        "LOG_COLORS": {
            "cmd": ensure_contrast(accent, panel, 3.5),
            "ok": status_add,
            "err": status_del,
            "warn": status_conf,
            "info": ensure_contrast(accent_alt, panel, 3.0),
        },
        "TREE_COLORS": {
            "mod": status_mod,
            "add": status_add,
            "del": status_del,
            "conf": status_conf,
            "gray": status_gray,
        },
        "TREE_BG": tree_bg,
    }


# 色板里允许整体替换的键（顺序无所谓，切换时按这批键做旧色 -> 新色映射）
_PALETTE_KEYS = ("APP_BG", "SURFACE", "BORDER", "TEXT", "MUTED", "ACCENT",
                 "ACCENT_HOVER", "ACCENT_ALT", "ACCENT_DIM", "HOVER_BG",
                 "PRESSED_BG", "HEAD_BG", "TAB_BG", "TAB_HOVER_BG",
                 "SCROLL_BG", "SCROLL_HOVER_BG", "DISABLED_FG",
                 "UP_HOVER_BG", "UP_CUR_BG", "ON_ACCENT",
                 "ON_ACCENT_DISABLED", "LOG_COLORS", "TREE_COLORS", "TREE_BG")


def apply_palette(name):
    """把指定皮肤写入 core 的模块级颜色常量，并返回完整色板。"""
    pal = palette_for(name)
    for key in _PALETTE_KEYS:
        globals()[key] = pal[key]
    return pal


def current_palette():
    """当前色板快照（切换时用于旧色 -> 新色映射；字典做浅拷贝）。"""
    pal = {}
    for key in _PALETTE_KEYS:
        value = globals().get(key)
        pal[key] = dict(value) if isinstance(value, dict) else value
    return pal


# 改动列表的列位（像素）：勾选/状态 | 修订 | 路径。
# 列表是 tk.Text（见 _up_paint 的注释），列位靠制表位对齐，与表头标签一致
UP_REV_X, UP_PATH_X = 150, 215
UP_FILL = 160            # 行尾补空格：让整行着色盖满可视宽度
# 行底色由 apply_palette 按皮肤写入 UP_HOVER_BG / UP_CUR_BG，
# 三个标签按创建顺序排优先级：状态色 < 悬停 < 当前行，
# 所以当前行的高亮不会被悬停盖住，悬停会盖住行状态底色
apply_palette(THEME_DEFAULT)   # 导入即晴空：没有配置记录时默认就是它
UP_FONT_DELTA = 1        # 列表正文字号比 TkFixedFont 大一号
UP_CHECK_DELTA = 8       # 勾选框字号（TkFixedFont 10 + 8 = 18 号加粗，约 22px 宽；
                         # 改前的 ☐ 只有 8px）。**它同时决定行高**：Text 行高取行内
                         # 最大字号的 linespace，18 号时行高约 36px、一屏少看几行，
                         # 再往下调之前先开窗口数数一屏能放几行
UP_TEXT_OFFSET = 3       # 列表正文的垂直微调（像素，Tk 文本标签 offset 选项，
                         # **正值上移**）。勾选框字形大、ascent 也大，正文与它
                         # 共用一条基线，视觉上正文偏低——本机（Noto Sans Mono
                         # CJK SC、base 10）按截图量墨水范围：正文中心比勾选框
                         # 墨心低 3px，上移 3px 后两者对齐（用户要求“文字垂直
                         # 居中”）。改动列表与检出勾选列表的正文段统一挂 "txt"
                         # 标签套这个值；**别改成只挪勾选框**（往下挪会把行高
                         # 撑高，大字号 linespace 再涨一截）

# 内置差异窗口一次最多显示的行数：整版本差异可能上万行，全部塞进 tk.Text
# 会把界面卡死，超了就截断并在末尾写明（见 log_view.open_diff）
DIFF_MAX_LINES = 20000


def tail_msg(msg):
    """取 svn 输出的最后几行作为弹窗内容。"""
    lines = [l for l in str(msg or "").split("\n") if l.strip()]
    return "\n".join(lines[-6:]) or u"（svn 未返回详细信息）"
