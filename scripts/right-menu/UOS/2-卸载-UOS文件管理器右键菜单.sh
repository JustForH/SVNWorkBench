#!/bin/bash
# ============================================================
# 2-卸载-UOS文件管理器右键菜单
# 仅适用于 UOS / deepin（Debian 系，使用 dde-file-manager）。
#
# 与 1-安装-UOS文件管理器右键菜单.sh 配套，移除它写入的两个
# 系统菜单扩展 .desktop（右键文件夹 / 右键空白处）并重启文件管理器。
# 需要 sudo（会提示输密码）。
#
# 用法：
#   源码目录:
#     bash scripts/right-menu/UOS/2-卸载-UOS文件管理器右键菜单.sh
#   交付包（脚本在 dist/right-menu/UOS/）:
#     cd dist
#     bash right-menu/UOS/2-卸载-UOS文件管理器右键菜单.sh
# ============================================================

# 兼容用户用 sh 执行：自动切回 bash
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi
set -u

# 系统菜单目录；SVNWB_UOS_MENU_DIR 仅供调试/测试或非标准安装使用
DESK_DIR="${SVNWB_UOS_MENU_DIR:-/usr/share/deepin/dde-file-manager/oem-menuextensions}"

if ! command -v sudo >/dev/null 2>&1; then
    echo "错误：删除 ${DESK_DIR} 下的菜单文件需要 sudo。" >&2
    exit 1
fi

if [ -e "${DESK_DIR}/SVNWorkBench.desktop" ] || \
   [ -e "${DESK_DIR}/SVNWorkBenchEmpty.desktop" ]; then
    if ! sudo rm -f "${DESK_DIR}/SVNWorkBench.desktop" \
                    "${DESK_DIR}/SVNWorkBenchEmpty.desktop"; then
        echo "错误：删除菜单文件失败。" >&2
        exit 1
    fi
    echo "SVNWorkBench 右键菜单已移除"
else
    echo "未找到 SVNWorkBench 右键菜单（可能尚未安装）"
fi

if command -v killall >/dev/null 2>&1; then
    killall dde-file-manager 2>/dev/null || true
fi
