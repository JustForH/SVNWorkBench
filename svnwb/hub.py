# -*- coding: utf-8 -*-
"""服务层：Hub 单任务调度 + 事件队列。

同一时刻只允许一个任务（Hub.start 已有任务在跑时抛 BusyError，界面弹警告）；
Runner 线程的事件经 _pump 转发到 events，主线程在 App._poll 里取用。
"""

import queue
import threading
from datetime import datetime
from pathlib import Path

from .core import (ApiError, BusyError, clean_excludes, decode_svn_url,
                   log_dir, resolve_dst, safe_filename)
from .runner import Runner

# ============================================================
# 四、服务层：单任务执行 + 事件队列（供界面轮询）
# ============================================================

class Hub:
    """全局状态：单任务执行、事件队列。

    Runner 线程的事件经 _pump 转发到 self.events（queue.Queue），
    界面用 root.after 定时取用，避免在非主线程直接操作 Tk 控件。
    """

    def __init__(self, store):
        self.store = store
        self.events = queue.Queue()   # log / busy / ask_auth / ask_cert / done
        self.runner = None
        self.params = {}
        self.mode = None
        self.log_path = None
        self.ask_pending = False

    def busy(self):
        r = self.runner
        return r is not None and r.is_alive()

    def start(self, mode, params):
        if self.busy():
            raise BusyError(u"已有任务在运行，请先等待完成或取消")
        p = dict(params)
        # 日志头/文件名里的名字：取目标目录名（不再有“项目”概念）；
        # 提交历史按地址读取时没有本地目录，用地址最后一段
        p["target_name"] = Path(str(p.get("dst") or p.get("wc") or
                                     p.get("url") or
                                     p.get("file_url") or
                                     u"").strip() or "run").name or "run"
        p["trust_server_cert"] = bool(p.get("trust_server_cert",
                                             self.store.settings.get("trust_server_cert", False)))
        if mode == "download":
            p["url"] = decode_svn_url(str(p.get("url", "")).strip())
            p["dst"] = str(p.get("dst", "")).strip()
            p["excludes"] = clean_excludes(p.get("excludes") or [])
            # 重新勾选、需要从工作副本里拉回的目录（顶层化后交给 svn update）
            p["restore"] = clean_excludes(p.get("restore") or [])
            if not p["url"]:
                raise ApiError(u"请填写 SVN 地址")
            if not p["dst"]:
                raise ApiError(u"请填写本地目录")
            dst = resolve_dst(p["dst"])
            if dst.exists() and not dst.is_dir():
                raise ApiError(u"本地目录路径已被文件占用: %s" % dst)
        elif mode in ("status", "update"):
            p["wc"] = str(p.get("wc", "")).strip()
            if not p["wc"]:
                raise ApiError(u"请先填写工作副本路径")
        elif mode == "export":
            # 导出：地址 + 本地目标（目标已存在时由界面确认后带 force）
            p["url"] = decode_svn_url(str(p.get("url", "")).strip())
            p["dst"] = str(p.get("dst", "")).strip()
            p["force"] = bool(p.get("force"))
            if not p["url"]:
                raise ApiError(u"请先选择要导出的目录或文件")
            if not p["dst"]:
                raise ApiError(u"请选择导出到的本地文件夹")
        elif mode in ("log", "logdiff"):
            # 目标三选一：SVN 地址（整版本对比）、文件地址（单文件对比，
            # 提交历史按仓库根拼出，见 core.repo_path_to_url）、工作副本；
            # 空的项删掉，末尾的目录校验就不会拿空串去凑工作副本
            p["url"] = decode_svn_url(str(p.get("url", "")).strip())
            p["file_url"] = decode_svn_url(str(p.get("file_url", "")).strip())
            p["wc"] = str(p.get("wc", "")).strip()
            for key in ("url", "file_url", "wc"):
                if not p[key]:
                    p.pop(key, None)
            if not (p.get("url") or p.get("file_url") or p.get("wc")):
                raise ApiError(u"请先指定 SVN 地址或工作副本路径")
            if mode == "log":
                try:
                    p["limit"] = max(1, min(2000, int(p.get("limit") or 50)))
                except (TypeError, ValueError):
                    p["limit"] = 50
            else:
                p["rev"] = str(p.get("rev") or "").strip()
                if not p["rev"]:
                    raise ApiError(u"请先选中要对比的版本")
        elif mode in ("add", "revert", "delete"):
            p["paths"] = [str(x) for x in (p.get("paths") or [])]
            if not p["paths"]:
                raise ApiError(u"请先勾选要操作的条目")
        elif mode == "commit":
            p["message"] = str(p.get("message", "")).strip()
            if not p["message"]:
                raise ApiError(u"请填写提交说明")
            p["paths"] = [str(x) for x in (p.get("paths") or [])]
        elif mode == "diff":
            p["path"] = str(p.get("path") or "").strip() or None
        elif mode == "cat":
            p["path"] = str(p.get("path") or "").strip()
            if not p["path"]:
                raise ApiError(u"请选择要对比的条目")
            p["out"] = str(p.get("out") or "").strip()
            if not p["out"]:
                raise ApiError(u"缺少对比基线的输出路径")
        else:
            raise ApiError(u"未知模式: %s" % mode)
        if "wc" in p:
            wc = resolve_dst(p["wc"])
            if not wc.is_dir():
                raise ApiError(u"工作副本目录不存在: %s" % wc)

        logs_dir = log_dir()
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = logs_dir / ("%s_%s_%s.log"
                               % (ts, safe_filename(p["target_name"]), mode))
        q = queue.Queue()
        self.params = p
        self.mode = mode
        self.log_path = str(log_path)
        self.ask_pending = False
        self.runner = Runner(mode, q, log_path, **p)
        threading.Thread(target=self._pump, args=(q,), daemon=True).start()
        self.runner.start()
        self.events.put({"type": "busy", "busy": True, "mode": mode})

    def _pump(self, q):
        while True:
            ev = q.get()
            kind = ev[0]
            if kind == "log":
                self.events.put({"type": "log", "text": ev[1], "tag": ev[2]})
            elif kind in ("ask_auth", "ask_cert"):
                self.ask_pending = True
                self.events.put({"type": kind, "message": ev[1]})
            elif kind == "done":
                ok, detail, result, log_path = ev[1], ev[2], ev[3], ev[4]
                self.ask_pending = False
                # 等 runner 线程完全退出后再投递 done，
                # 保证界面收到 done 时已可接受下一个任务
                r = self.runner
                if r is not None:
                    r.join(timeout=5)
                self.events.put({"type": "done", "ok": ok, "mode": self.mode,
                                 "detail": detail, "result": result, "log": log_path,
                                 "dest": self.params.get("dest")})
                break

    def cancel(self):
        if self.runner is not None:
            self.runner.cancel()

    def respond(self, resp):
        if self.runner is not None and self.ask_pending:
            self.ask_pending = False
            self.runner.auth_q.put(resp)

