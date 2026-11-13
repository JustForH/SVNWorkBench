# -*- coding: utf-8 -*-
"""browse_dir 三分支测试：假 zenity 成功 / zenity 取消 / 无 zenity 回退 Tk。"""
import os
import sys
from _testtmp import TMP  # noqa: E402
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import SVNWorkBench as m   # noqa: E402

BINDIR = TMP + "/fakebin"
FAILS = []
PASSED = [0]


def check(cond, msg):
    if cond:
        PASSED[0] += 1
        print("PASS: %s" % msg)
    else:
        FAILS.append(msg)
        print("FAIL: %s" % msg)


def make_fake_zenity(script_body):
    shutil.rmtree(BINDIR, ignore_errors=True)
    os.makedirs(BINDIR)
    path = os.path.join(BINDIR, "zenity")
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + script_body)
    os.chmod(path, 0o755)


old_path = os.environ.get("PATH", "")

try:
    # 1) zenity 正常返回路径
    make_fake_zenity("echo " + TMP + "/fake_dir\n")
    os.environ["PATH"] = BINDIR + ":" + old_path
    p = m.App.browse_dir(None, "../SP_PISA2_0")
    check(p == TMP + "/fake_dir", "zenity 返回所选路径: %r" % p)

    # 2) 用户取消（rc!=0，无输出）
    make_fake_zenity("exit 1\n")
    os.environ["PATH"] = BINDIR + ":" + old_path
    p = m.App.browse_dir(None, "")
    check(p is None, "取消时返回 None: %r" % p)

    # 3) zenity 不可用 -> 回退 Tk 对话框
    os.environ["PATH"] = "/nonexistent-empty"
    m.filedialog.askdirectory = lambda **kw: "/tmp/from_tk_chooser"
    p = m.App.browse_dir(None, "/tmp")
    check(p == "/tmp/from_tk_chooser", "回退 Tk 选择框: %r" % p)

    # 4) 初始目录推导：相对路径不存在 -> 用其父目录
    os.environ["PATH"] = BINDIR + ":" + old_path
    seen = {}

    def fake_zenity_kw(**kw):
        seen.update(kw)
        return ""

    make_fake_zenity("exit 0\n")  # 空输出 -> 取消，但会经过 --filename 参数
    import subprocess
    real_popen = subprocess.Popen

    class SpyPopen(object):
        def __init__(self, *a, **kw):
            seen["argv"] = a[0]
            self._p = real_popen(*a, **kw)

        def communicate(self, *a, **kw):
            return self._p.communicate(*a, **kw)

        def __getattr__(self, k):
            return getattr(self._p, k)

    subprocess.Popen = SpyPopen
    try:
        m.App.browse_dir(None, "../SP_PISA2_0")
    finally:
        subprocess.Popen = real_popen
    argv = seen.get("argv") or []
    fn = [x for x in argv if x.startswith("--filename=")]
    expected_dir = os.path.dirname(str(m.BASE_DIR)).rstrip("/") + "/"
    check(bool(fn) and fn[0] == "--filename=" + expected_dir,
          "由相对路径推导 zenity 初始目录: %r" % (fn[0] if fn else None))
finally:
    os.environ["PATH"] = old_path
    shutil.rmtree(BINDIR, ignore_errors=True)

print("-" * 46)
print("通过 %d 项，失败 %d 项" % (PASSED[0], len(FAILS)))
for f in FAILS:
    print("  FAILED: %s" % f)
sys.exit(1 if FAILS else 0)
