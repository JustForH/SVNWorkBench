# -*- coding: utf-8 -*-
"""测试用临时目录。

默认每次运行创建独立目录（/tmp/SVNWorkBench-tests-XXXX），退出时清理；
可用环境变量 SVNWB_TEST_TMP 指定固定目录，便于排查失败现场。
"""
import atexit
import os
import shutil
import tempfile

_base = os.environ.get("SVNWB_TEST_TMP")
if _base:
    TMP = os.path.abspath(_base)
    if not os.path.isdir(TMP):
        os.makedirs(TMP)
else:
    TMP = tempfile.mkdtemp(prefix="SVNWorkBench-tests-")
    atexit.register(shutil.rmtree, TMP, True)
