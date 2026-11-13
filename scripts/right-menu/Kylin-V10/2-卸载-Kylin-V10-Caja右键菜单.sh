#!/bin/bash
# ============================================================
# 2-卸载-Kylin-V10-Caja右键菜单
# 仅适用于 Kylin V10 / MATE 桌面（使用 Caja 文件管理器）。
#
# 与 1-安装-Kylin-V10-Caja右键菜单.sh 配套，移除写入
# ~/.config/caja/scripts/ 的"使用SVN_WB打开"菜单脚本，并重启 Caja。
# 只操作当前用户目录，不需要 sudo。
#
# 用法：
#   源码目录:
#     bash scripts/right-menu/Kylin-V10/2-卸载-Kylin-V10-Caja右键菜单.sh
#   交付包（脚本在 dist/right-menu/Kylin-V10/）:
#     cd dist
#     bash right-menu/Kylin-V10/2-卸载-Kylin-V10-Caja右键菜单.sh
# ============================================================

# 兼容用户用 sh 执行：自动切回 bash
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi
set -u

if [ -z "${HOME:-}" ]; then
    echo "错误：未设置 HOME，无法定位 Caja 脚本目录。" >&2
    exit 1
fi
CAJA_SCRIPTS_DIR="${HOME}/.config/caja/scripts"
MENU_SCRIPT="${CAJA_SCRIPTS_DIR}/使用SVN_WB打开"

if [ -f "${MENU_SCRIPT}" ]; then
    if ! rm -f "${MENU_SCRIPT}"; then
        echo "错误：删除 ${MENU_SCRIPT} 失败。" >&2
        exit 1
    fi
    echo "SVNWorkBench 右键菜单已移除"
else
    echo "未找到 SVNWorkBench 右键菜单（可能尚未安装）：${MENU_SCRIPT}"
fi

if command -v caja >/dev/null 2>&1; then
    caja -q >/dev/null 2>&1 || killall caja >/dev/null 2>&1 || true
fi
