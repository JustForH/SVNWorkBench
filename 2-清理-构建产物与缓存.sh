#!/bin/sh
# ============================================================
# 2-清理-构建产物与缓存
#
# 清理整个项目的构建产物与缓存：
#   build/          PyInstaller 工作目录（.spec、warn 清单、中间产物）
#   dist/           打包交付物（重新运行 1-构建脚本即可再生成）
#   __pycache__/    Python 字节码缓存（全项目扫描，含 svnwb/ 与 tests/）
#   *.pyc           散落的字节码文件
#
# 不会动：源码（SVNWorkBench.py / svnwb/ / tests/）、文档、
#         脚本正本（根目录 1/2 与 scripts/ 目录）、用户配置
#         （~/.config/SVNWorkBench/）与运行日志
#         （/tmp/SVNWorkBench-<用户名>/logs/，重启即清，不在项目内）。
#
# 脚本位置: 工程根目录/2-清理-构建产物与缓存.sh
# 用法（工程根目录）:
#   ./2-清理-构建产物与缓存.sh
#   （也可从任意目录执行，脚本会自动切到工程根目录）
# ============================================================
set -e
SCRIPT_DIR=$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd)
PROJECT_ROOT="$SCRIPT_DIR"
cd "$PROJECT_ROOT"

# 安全闸：确认当前目录确实是本工程，防止脚本被误拷到别处后乱删
if [ ! -f "SVNWorkBench.py" ] || [ ! -d "svnwb" ]; then
    echo "错误：当前目录不是 SVNWorkBench 工程（缺少 SVNWorkBench.py / svnwb/），拒绝清理" >&2
    exit 1
fi

found=""
for d in build dist; do
    if [ -e "$d" ]; then
        size=$(du -sk "$d" 2>/dev/null | cut -f1)
        rm -rf "$d"
        echo "已删除 ${d}/（${size:-?} KB）"
        found="yes"
    fi
done

# 字节码缓存：先删各层 __pycache__ 目录，再兜底清散落的 .pyc
find . -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -exec rm -f {} + 2>/dev/null || true
echo "已清除全部 __pycache__ / *.pyc"

if [ -z "$found" ]; then
    echo "（build/ 与 dist/ 本来就不存在，只清了字节码缓存）"
fi
echo "完成。如需重新产出交付物：./1-构建-打包绿色单文件.sh"
