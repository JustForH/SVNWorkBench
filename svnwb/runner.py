# -*- coding: utf-8 -*-
"""后台执行引擎：Runner 线程按模式跑 svn 命令序列。

所有 svn 调用统一走 _run -> _decorate（附加 --non-interactive、证书信任与
凭据参数）；输出解析优先用 --xml。事件只进队列，绝不直接碰 Tk 控件。
"""

import os
import queue
import re
import subprocess
import threading
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from .core import (AUTH_HINTS, CERT_HINTS, RunCancelled,
                   _contains_any, cmd_str, decode_diff_output,
                   decode_svn_url, diff_stats, has_exclude_child, is_excluded,
                   normalize_svn_url,
                   parse_info_repo, parse_log_xml,
                   parse_status_xml,
                   resolve_dst, topmost_paths)

# ============================================================
# 三、执行引擎（与桌面版一致，含凭据/证书交互重试）
# ============================================================

class Runner(threading.Thread):
    """后台执行线程。mode: download/status/update/add/revert/delete/commit/
    diff/cat/log/logdiff/export。

    事件通过 out_q 上报: ("log", text, tag) / ("ask_auth", text) /
    ("ask_cert", text) / ("done", ok, detail, result, log_path)。
    认证/证书弹窗答复通过 auth_q 传回。
    """

    def __init__(self, mode, out_q, log_path, **params):
        super().__init__(daemon=True)
        self.mode = mode
        self.q = out_q
        self.log_path = Path(log_path)
        self.params = params
        self.target_name = params.get("target_name", "")
        self.cancel_flag = False
        self.proc = None
        self.creds = None
        self.trust_cert = bool(params.get("trust_server_cert"))
        self.auth_q = queue.Queue()
        self._ask_count = 0
        self._buffer = None
        self._raw_out = None         # sink="bytes" 时的原始输出
        self._sink_file = None       # sink="file" 时的输出路径
        self._trust_flags_cached = None
        self._log_file = None

    def log(self, text, tag="info"):
        self.q.put(("log", text, tag))
        try:
            if self._log_file is None:
                self._log_file = open(str(self.log_path), "w", encoding="utf-8")
                self._log_file.write("# 目标: %s  模式: %s  时间: %s\n" % (
                    self.target_name, self.mode,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            self._log_file.write(text + "\n")
            self._log_file.flush()
        except OSError:
            pass

    def cancel(self):
        self.cancel_flag = True
        p = self.proc
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass

    def run(self):
        try:
            fn = {"download": self._do_download,
                  "status": self._do_status, "update": self._do_update,
                  "add": self._do_add, "revert": self._do_revert,
                  "delete": self._do_delete,
                  "commit": self._do_commit,
                  "diff": self._do_diff, "cat": self._do_cat,
                  "log": self._do_log, "logdiff": self._do_logdiff,
                  "export": self._do_export}[self.mode]
            result = fn()
            self.q.put(("done", True, self.mode, result, str(self.log_path)))
        except RunCancelled:
            self.q.put(("done", False, "__cancelled__", None, str(self.log_path)))
        except Exception as e:
            self.log("错误: %s" % e, "err")
            try:
                self.log(traceback.format_exc(), "err")
            except Exception:
                pass
            self.q.put(("done", False, str(e), None, str(self.log_path)))
        finally:
            if self._log_file is not None:
                try:
                    self._log_file.close()
                except OSError:
                    pass
                self._log_file = None

    # ---------- 子进程执行（含凭据/证书重试） ----------
    def _decorate(self, cmd):
        if len(cmd) < 2 or cmd[0] != "svn":
            return list(cmd)
        real = ["svn"] + self._get_trust_flags() + ["--non-interactive"]
        if self.creds:
            u, p, remember = self.creds
            real += ["--username", u]
            if p:
                real += ["--password", p]
            if not remember:
                real += ["--no-auth-cache"]
            else:
                # 新版 svn 默认禁止明文存储密码，--non-interactive 下无法
                # 询问会静默放弃缓存，导致"勾了记住仍每次提示"；
                # 显式放行本次缓存（凭据明文存于 ~/.subversion/auth）。
                # --config-option 必须是 分类:小节:选项 三段式，
                # servers 的全局小节是 global，写成 servers:选项 会被
                # svn 以 E205000"参数 --config-option 的语法无效"拒绝
                real += ["--config-option",
                         "servers:global:store-plaintext-passwords=yes"]
        real += cmd[1:]
        return real

    def _get_trust_flags(self):
        if self._trust_flags_cached is not None:
            return self._trust_flags_cached
        flags = []
        if self.trust_cert:
            try:
                pr = subprocess.Popen(["svn", "help", "checkout"],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    h = pr.communicate(timeout=15)[0].decode("utf-8", "replace")
                except subprocess.TimeoutExpired:
                    pr.kill()
                    h = pr.communicate()[0].decode("utf-8", "replace")
                if "--trust-server-cert-failures" in h:
                    flags = ["--trust-server-cert-failures=unknown-ca,cn-mismatch,"
                             "expired,not-yet-valid,other"]
                else:
                    flags = ["--trust-server-cert"]
            except Exception:
                flags = ["--trust-server-cert"]
        self._trust_flags_cached = flags
        return flags

    def _ask(self, kind, text):
        self._ask_count += 1
        if self._ask_count > 3:
            raise RuntimeError("多次验证未通过，已中止本次操作")
        self.q.put((kind, text))
        try:
            resp = self.auth_q.get(timeout=1800)
        except queue.Empty:
            raise RunCancelled
        if not resp or not resp.get("ok"):
            raise RunCancelled
        if kind == "ask_auth":
            self.creds = (resp.get("username", ""), resp.get("password", ""),
                          bool(resp.get("remember")))
        else:
            self.trust_cert = True
            self._trust_flags_cached = None

    def _exec_stream(self, cmd, cwd, sink):
        """以字节模式读取子进程输出并按行解码（兼容 3.5：
        Popen 无 text/encoding 参数，universal_newlines 使用本地编码，不可控）。

        sink="log"    逐行解码写进运行日志（默认，stderr 并入 stdout）
        sink="buffer" 逐行解码暂存 self._buffer（供 --xml 解析）
        sink="bytes"  原始字节暂存 self._raw_out（查看内容用：文本编码要
                      在拿到原始字节后判断，先按 UTF-8 解码会丢信息）
        sink="file"   stdout 按原始字节写入 self._sink_file（svn cat 导出
                      基线文件时用，二进制保真，绝不进日志）
        """
        try:
            if sink == "log":
                proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT)
            else:
                proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
        except FileNotFoundError:
            raise RuntimeError("未找到 svn 命令，请先安装 Subversion 客户端")
        self.proc = proc
        out, err = [], []
        self._raw_out = bytearray() if sink == "bytes" else None

        def drain(stream, acc):
            try:
                for raw in iter(stream.readline, b""):
                    acc.append(raw.decode("utf-8", "replace").rstrip("\r\n"))
            except Exception:
                pass

        te = None
        if sink != "log":
            te = threading.Thread(target=drain, args=(proc.stderr, err), daemon=True)
            te.start()
        if sink == "file":
            self._copy_out(proc)
        else:
            for raw in iter(proc.stdout.readline, b""):
                if sink == "bytes":
                    self._raw_out.extend(raw)
                    # 只留最后几行给失败摘要用，正文不再多占一份解码文本；
                    # 原始字节留给界面按实际编码解码（见 repo_browser.cat_display）
                    out.append(raw[:4096].decode("utf-8", "replace").rstrip("\r\n"))
                    if len(out) > 8:
                        del out[:-8]
                else:
                    ln = raw.decode("utf-8", "replace").rstrip("\r\n")
                    out.append(ln)
                    if sink == "buffer":
                        if self._buffer is not None:
                            self._buffer.append(ln)
                    else:
                        self.log(ln)
                if self.cancel_flag:
                    break
        rc = proc.wait()
        if te is not None:
            te.join(timeout=2)
        self.proc = None
        if sink != "log":
            for ln in err:
                if ln.strip():
                    self.log(ln, "warn")
        if self.cancel_flag:
            raise RunCancelled
        return rc, out, err

    def _copy_out(self, proc):
        """把子进程 stdout 原样写进 self._sink_file（二进制，可中断）。"""
        path = self._sink_file
        if not path:
            raise RuntimeError("缺少输出文件路径")
        fh = open(path, "wb")
        try:
            while True:
                if self.cancel_flag:
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    break
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                fh.write(chunk)
        finally:
            fh.close()

    def _run(self, cmd, cwd=None, sink="log"):
        last_rc, last_tail = 1, []
        for attempt in range(4):
            real = self._decorate(cmd)
            label = "$ " + cmd_str(real)
            if attempt:
                label += "    # 第 %d 次重试" % (attempt + 1)
            self.log(label, "cmd")
            rc, out_lines, err_lines = self._exec_stream(real, cwd, sink)
            if rc == 0:
                if sink == "bytes":
                    return bytes(self._raw_out or b"")
                return out_lines
            last_rc = rc
            last_tail = out_lines[-8:] + err_lines[-4:]
            text = "\n".join(out_lines + err_lines)
            if self.cancel_flag:
                raise RunCancelled
            if _contains_any(text, CERT_HINTS) and not self._get_trust_flags():
                self._ask("ask_cert", text)
                continue
            if _contains_any(text, AUTH_HINTS):
                self._ask("ask_auth", text)
                continue
            break
        tail = "\n".join(last_tail).strip()
        raise RuntimeError("svn 命令失败（退出码 %d）%s" % (last_rc, ("\n" + tail) if tail else ""))

    @staticmethod
    def _local_dirs(root, rel):
        """列出 base 下的子目录名（os.listdir + os.path.isdir，兼容 3.5）。"""
        base = root if not rel else root / rel
        bs = str(base)
        try:
            names = os.listdir(bs)
        except OSError:
            return []
        out = []
        for n in names:
            if n.startswith("."):
                continue
            try:
                if os.path.isdir(os.path.join(bs, n)):
                    out.append(n)
            except OSError:
                pass
        return sorted(out)

    # ---------- 各模式 ----------
    @staticmethod
    def _probe_wc_url(dst):
        """读取目录对应的工作副本来源 URL；非工作副本返回 None（svn info）。"""
        if not dst.is_dir():
            return None
        try:
            pr = subprocess.Popen(["svn", "info", "--xml", "--non-interactive",
                                   str(dst)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, _err = pr.communicate()
        except OSError:
            return None
        if pr.returncode != 0:
            return None
        try:
            el = ET.fromstring(out.decode("utf-8", "replace")).find("entry/url")
            return el.text if el is not None else None
        except Exception:
            return None

    def _enforce_excludes(self, dst, excludes):
        """把本地仍存在、但当前规则要求排除的目录/文件重新排除。

        `--set-depth=exclude` 对文件同样有效（实测 svn 1.10：被排除的
        文件从工作副本移除、不再出现在 status 输出里），所以勾选树里
        取消勾选的单个文件也能真正排除；已排除的条目本地不存在，
        直接跳过（不会重复执行命令）。
        """
        for pat in excludes or []:
            rel = str(pat or "").strip().strip("/")
            if not rel:
                continue
            p = dst / rel
            if p.is_dir() or p.is_file():
                self.log("[EXCLUDE] %s" % rel, "warn")
                self._run(["svn", "update", "--set-depth=exclude", rel],
                          cwd=str(dst))

    def _restore_excludes(self, dst, restore):
        """把此前被排除、本次重新勾选的目录/文件拉回（--set-depth=infinity）。

        顺序必须在 _enforce_excludes 之前：上层目录恢复时会连带拉回它的
        子孙，其中仍属排除的由随后的 exclude 步骤重新排掉。文件同样支持
        `--set-depth=infinity`（实测 svn 1.10）。
        """
        rels = topmost_paths(restore)
        for rel in rels:
            self.log("[恢复] %s" % rel, "warn")
            self._run(["svn", "update", "--set-depth=infinity", rel],
                      cwd=str(dst))

    def _do_download(self):
        dst = resolve_dst(self.params["dst"])
        if dst.exists() and not dst.is_dir():
            raise RuntimeError("本地目录路径已被文件占用: %s" % dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        self.log("============ SVN 下载 ============", "phase")
        self.log("目标: %s" % dst, "info")
        url = self.params["url"]
        wc_url = self._probe_wc_url(dst)
        if wc_url is not None:
            if normalize_svn_url(wc_url) != normalize_svn_url(url):
                raise RuntimeError(
                    "目标目录已是其他来源的工作副本，不能重复下载：\n"
                    "  现有来源: %s\n  本次来源: %s\n"
                    "请更换本地目录，或确认后删除该目录再试。" % (wc_url, url))
            self.log("目标已是同一来源的工作副本，改为增量更新（svn update）", "info")
            self._run(["svn", "update", str(dst)], cwd=str(dst.parent))
            self._restore_excludes(dst, self.params.get("restore"))
            self._enforce_excludes(dst, self.params["excludes"])
            self.log("======== 增量更新完成 ========", "phase")
            return "updated"
        self._run(["svn", "checkout", "--depth=immediates", url, str(dst)],
                  cwd=str(dst.parent))
        excludes = self.params["excludes"]

        def walk(rel):
            if self.cancel_flag:
                raise RunCancelled
            if is_excluded(rel, excludes):
                self.log("[EXCLUDE] %s" % rel, "warn")
                self._run(["svn", "update", "--set-depth=exclude", rel], cwd=str(dst))
                return
            if has_exclude_child(rel, excludes):
                self._run(["svn", "update", "--set-depth=immediates", rel], cwd=str(dst))
                for name in self._local_dirs(dst, rel):
                    walk(rel + "/" + name)
                return
            self._run(["svn", "update", "--set-depth=infinity", rel], cwd=str(dst))

        for name in self._local_dirs(dst, ""):
            walk(name)
        # 逐层算法只处理目录；排除清单里的**单个文件**（勾选树可以精确到
        # 文件）在这里补一刀：已下载的按 set-depth=exclude 移除，
        # 未下载的（上层目录已排除）本地不存在、自动跳过
        self._enforce_excludes(dst, excludes)
        self.log("======== 下载完成 ========", "ok")

    def _wc(self):
        wc = resolve_dst(self.params["wc"])
        if not wc.is_dir():
            raise RuntimeError("工作副本目录不存在: %s" % wc)
        return wc

    def _do_status(self):
        """读取本地改动（不带 -u：范围固定为本地未提交改动，不联网）。

        带 `--no-ignore`：**任何文件都不隐藏**，被 svn 忽略规则
        （默认 global-ignores 命中 *.so、*.a、*.pyc 等）的文件也列出来
        （状态 I 忽略），用户才能重新勾选加入版本控制（用户要求）。
        """
        wc = self._wc()
        self.log("读取状态: %s" % wc, "phase")
        self._buffer = []
        self._run(["svn", "status", "--xml", "--no-ignore"], cwd=str(wc),
                  sink="buffer")
        xml_text = "\n".join(self._buffer)
        self._buffer = None
        return parse_status_xml(xml_text)

    def _do_update(self):
        """更新整个工作副本（svn update），完成后由界面刷新改动列表。"""
        wc = self._wc()
        self.log("更新工作副本: %s" % wc, "phase")
        self._run(["svn", "update"], cwd=str(wc))
        return True

    def _do_export(self):
        """导出仓库目录 / 文件到本地（svn export，不含 .svn 元数据的干净副本）。

        与检出（download）的区别：**不建工作副本、不写配置**，一次性
        拷贝。目标已存在时 svn 默认拒绝（E155000），界面确认后带
        `--force`（只覆盖同名文件，目标里的其他文件不动，实测 1.10）。
        """
        url = str(self.params.get("url") or "").strip()
        dst = resolve_dst(self.params.get("dst"))
        self.log("============ SVN 导出 ============", "phase")
        self.log("地址: %s" % url, "info")
        self.log("目标: %s" % dst, "info")
        cmd = ["svn", "export"]
        if self.params.get("force"):
            cmd.append("--force")
        cmd += [url, str(dst)]
        self._run(cmd)
        self.log("======== 导出完成 ========", "ok")
        return str(dst)

    def _do_add(self):
        wc = self._wc()
        paths = list(self.params["paths"])
        self.log("加入版本控制: %d 项" % len(paths), "phase")
        self._run(["svn", "add", "--force", "--parents"] + paths, cwd=str(wc))
        return True

    def _do_revert(self):
        """恢复所选（svn revert）。

        `--depth=empty` 只恢复节点本身，普通修改（含目录属性改动）用它，
        免得顺手丢掉没勾选的子条目修改；但新增/替换/删除/缺失这类
        “整棵树形状变化”的目录，svn 不允许只恢复父节点而不恢复孩子
        （E155038），必须 `--depth=infinity` 连同子条目一起恢复，否则
        “添加目录后还原”整条命令报错、什么都没恢复。深恢复清单由界面
        按条目状态算好放进 deep（见 core.REVERT_TREE_ITEMS）。
        """
        wc = self._wc()
        paths = list(self.params["paths"])
        deep = set(self.params.get("deep") or [])
        shallow = [p for p in paths if p not in deep]
        roots = topmost_paths([p for p in paths if p in deep])
        self.log("恢复所选（丢弃本地修改）: %d 项" % len(paths), "phase")
        # 先恢复子/普通条目再整棵恢复：新增父目录不允许先于孩子恢复，
        # 深恢复顶层化后已经覆盖其下勾选的子孙
        if shallow:
            self._run(["svn", "revert", "--depth=empty"] + shallow,
                      cwd=str(wc))
        if roots:
            self._run(["svn", "revert", "--depth=infinity"] + roots,
                      cwd=str(wc))
        return True

    def _do_delete(self):
        """删除所选条目（svn delete --force）。

        --force 让四种情况都能一条命令走通（实测 svn 1.10）：
        未版本控制/忽略的文件直接从磁盘删除；已修改的版本控制文件照常
        标记删除（本地文件移除，提交后从仓库删除）；本地已缺失的条目
        补记删除。不带 --force 时前三种都会报错。
        """
        wc = self._wc()
        paths = list(self.params["paths"])
        self.log("删除所选: %d 项" % len(paths), "phase")
        self._run(["svn", "delete", "--force"] + paths, cwd=str(wc))
        return True

    def _do_commit(self):
        wc = self._wc()
        msg = self.params.get("message", "")
        paths = list(self.params.get("paths") or [])
        self.log("提交: %s" % (paths if paths else "整个工作副本"), "phase")
        cmd = ["svn", "commit", "-m", msg] + paths
        lines = self._run(cmd, cwd=str(wc))
        rev = None
        for ln in lines:
            m = re.search(r"Committed revision (\d+)\.", ln)
            if not m:
                # 中文语言环境的 svn 输出: "提交后的版本为 2。"
                m = re.search(r"提交后的版本为\s*(\d+)", ln)
            if m:
                rev = m.group(1)
        if rev:
            self.log("======== 提交完成，新版本 r%s ========" % rev, "ok")
        else:
            self.log("没有需要提交的改动。", "ok")
        return rev

    def _do_diff(self):
        """生成差异：只看本地未提交改动（供内置差异窗口使用）。"""
        wc = self._wc()
        path = self.params.get("path")
        self.log("生成差异: %s（本地未提交）" % wc, "phase")
        cmd = ["svn", "diff", "--internal-diff"]
        if path:
            cmd.append(path)
        # 原始字节交给 core 按文件实际编码解码：svn 的 hunk 正文原样携带
        # 文件内容（GBK 旧文件常见），先按 UTF-8 解码会整段变成乱码
        raw = self._run(cmd, cwd=str(wc), sink="bytes")
        lines = decode_diff_output(raw)
        return {"lines": lines, "stats": diff_stats(lines)}

    def _do_log(self):
        """读取提交历史（svn log -v --xml）+ 目标的地址信息。

        目标二选一：params["url"]（仓库浏览器右键“查看提交记录”，整个
        命令以地址为对象，cwd 不需要）或 params["wc"]（主界面“提交历史”）。
        必须显式 `-r HEAD:1`：①对工作副本 svn log 的默认范围是
        BASE+1..HEAD——工作副本已是最新时会返回空列表；②范围方向决定
        排列顺序，HEAD:1 才是最新的在最上面。地址目标的默认范围是
        1:HEAD（最旧在前），所以同样要显式给出方向。

        返回 {"entries", "wc_url", "root"}：地址信息来自同一目标的
        `svn info --xml`（地址模式查地址，工作副本模式查本地——Runner
        线程里跑可以正常走凭据/证书重试），LogView 用它把 log 给出的
        仓库路径换算成对比目标（工作副本相对路径 / 文件地址），logdiff
        就不用再查一次。info 失败不致命——换算降级为整版本对比。
        """
        url = str(self.params.get("url") or "").strip()
        limit = int(self.params.get("limit") or 50)
        if url:
            target, cwd = url, None
        else:
            wc = self._wc()
            target, cwd = str(wc), str(wc)
        self.log("读取提交历史: %s（最近 %d 条）" % (target, limit), "phase")
        cmd = ["svn", "log", "--xml", "-v", "-l", str(limit), "-r", "HEAD:1"]
        if url:
            cmd.append(url)
        self._buffer = []
        self._run(cmd, cwd=cwd, sink="buffer")
        xml_text = "\n".join(self._buffer)
        self._buffer = []
        wc_url, root = u"", u""
        try:
            self._run(["svn", "info", "--xml", target], cwd=cwd, sink="buffer")
            wc_url, root = parse_info_repo("\n".join(self._buffer))
        except RunCancelled:
            raise
        except Exception:
            pass                       # info 拿不到只是换算降级，别拖垮日志
        finally:
            self._buffer = None
        return {"entries": parse_log_xml(xml_text),
                "wc_url": decode_svn_url(wc_url),
                "root": decode_svn_url(root)}

    def _do_logdiff(self):
        """某个提交版本的差异（svn diff -c N），供 meld/内置窗口查看。

        **`-c N` 就是 N-1 -> N：本次提交与上一个版本之间的差异**，不含
        本地未提交改动——这是提交历史双击对比的语义，勿改成 `-r N`
        （那是“该版本与工作副本”对比）。

        目标三种：
          - params["file_url"] + params["pair"]：单文件的两版原始内容，
            分别 `svn cat -r N-1 <url>@N-1` / `svn cat -r N <url>@N` 写进
            left/right 临时文件（路径在该版本不存在的一侧——本版本新增的
            左侧 / 删除的右侧——写成空文件），交给 meld 左右两版对比；
          - params["file_url"]：单文件的统一差异 `svn diff -c N <url>`。
            **必须用地址**：文件在本版本新增/删除、或被排除出工作副本时
            本地没有节点，用工作副本相对路径会报 E155010"找不到节点"；
            地址形式对新增/删除/普通三种情况实测都直接成功（peg 取 HEAD
            即可，不需要重试）；
          - params["url"]（地址整版本）或 params["wc"]（工作副本整版本）。
        """
        rev = str(self.params.get("rev") or "").strip()
        title = str(self.params.get("title") or "")
        file_url = str(self.params.get("file_url") or "").strip()
        if file_url and self.params.get("pair"):
            left = str(self.params.get("left") or "")
            right = str(self.params.get("right") or "")
            try:
                prev = str(int(rev) - 1)
            except ValueError:
                prev = "0"
            self.log("生成两版内容: r%s -> r%s  %s" % (prev, rev, file_url),
                     "phase")
            self._cat_to(file_url, prev, left)
            self._cat_to(file_url, rev, right)
            return {"rev": rev, "title": title, "kind": "pair",
                    "left": left, "right": right}
        url = str(self.params.get("url") or "").strip()
        if file_url:
            target, cwd = file_url, None
        elif url:
            target, cwd = url, None
        else:
            wc = self._wc()
            target, cwd = str(wc), str(wc)
        self.log("生成版本差异: r%s（本次提交与上一版本）-> %s"
                 % (rev, target), "phase")
        cmd = ["svn", "diff", "--internal-diff", "-c", rev]
        if cwd is None:
            cmd.append(target)
        # 同 _do_diff：原始字节按文件实际编码解码，GBK 文件不能先按 UTF-8
        raw = self._run(cmd, cwd=cwd, sink="bytes")
        lines = decode_diff_output(raw)
        return {"rev": rev, "title": title,
                "lines": lines, "stats": diff_stats(lines)}

    def _cat_to(self, url, rev, out):
        """导出某地址某版本的原始内容到临时文件（按原始字节）。

        路径在该版本不存在时（对比“上一版本”遇到本版本新增的文件、
        对比“本版本”遇到本版本删除的文件）svn 返回 W160013/E200009
        并退出码 1——这不是错误，写成空文件让两版对比照常进行；
        其它错误（认证/网络/地址错）照常抛出。
        """
        self._sink_file = out
        try:
            self._run(["svn", "cat", "-r", rev, "%s@%s" % (url, rev)],
                      cwd=None, sink="file")
        except RunCancelled:
            raise
        except Exception as e:
            msg = str(e)
            if "160013" not in msg and "E200009" not in msg:
                raise
            with open(out, "wb"):
                pass                      # 该版本没有这个路径 -> 空文件
        finally:
            self._sink_file = None

    def _do_cat(self):
        """导出某路径的 BASE 版本到临时文件（外部对比工具的左侧内容）。"""
        wc = self._wc()
        path = self.params.get("path") or ""
        out = self.params.get("out") or ""
        self.log("导出对比基线: %s" % path, "phase")
        self._sink_file = out
        try:
            self._run(["svn", "cat", "-r", "BASE", path], cwd=str(wc),
                      sink="file")
        except Exception:
            try:
                os.unlink(out)
            except OSError:
                pass
            raise
        finally:
            self._sink_file = None
        return out

