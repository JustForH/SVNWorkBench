#!/bin/bash
# ============================================================
# 1-安装-UOS文件管理器右键菜单
# 仅适用于 UOS / deepin（Debian 系，使用 dde-file-manager）。
#
# 往系统菜单扩展目录写入两个 SVNWorkBench*.desktop，之后文件管理器里
# 右键文件夹 / 右键空白处 ->"使用SVN_WB打开"即启动程序并打开对应目录
# （程序的"工作副本目录"启动参数，见 README「文件管理器右键集成」）。
#
# 为什么是两个文件（dde-file-manager 6.x 实测结论）：
#   ① SVNWorkBench.desktop      X-DFM-MenuTypes=SingleDir，Exec 用 %F
#                               （右键文件夹：选中的目录路径）
#   ② SVNWorkBenchEmpty.desktop X-DFM-MenuTypes=EmptyArea，Exec 用 %p
#                               （右键空白处：当前所在目录路径）
#   6.x 起 EmptyArea 不再展开 %F（空白处没有选中项、%F 为空），
#   5.x 时 %F 在 EmptyArea 正常；只有拆成两个文件才能两种场景都正常。
#
# 用法：
#   源码目录:
#     bash scripts/right-menu/UOS/1-安装-UOS文件管理器右键菜单.sh [exe路径]
#   交付包（脚本在 dist/right-menu/UOS/）:
#     cd dist
#     bash right-menu/UOS/1-安装-UOS文件管理器右键菜单.sh [exe路径]
#
# 不带参数时从脚本所在目录开始，逐级向上查找：
#   ① <目录>/SVNWorkBench          （脚本与 exe 放在一起）
#   ② <目录>/dist/SVNWorkBench     （源码目录 / 交付包上层目录）
# 例如 dist/right-menu/UOS/ 会找到 dist/SVNWorkBench；源码目录里的
# scripts/right-menu/UOS/ 会找到工程根目录/dist/SVNWorkBench。
# 写入 .desktop 需要 sudo（会提示输密码）。
# ============================================================

# 兼容用户用 sh 执行：自动切回 bash
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi
set -u

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)
# 系统菜单目录；SVNWB_UOS_MENU_DIR 仅供调试/测试或非标准安装使用
DESK_DIR="${SVNWB_UOS_MENU_DIR:-/usr/share/deepin/dde-file-manager/oem-menuextensions}"
DESK_FILE="${DESK_DIR}/SVNWorkBench.desktop"
DESK_FILE_EMPTY="${DESK_DIR}/SVNWorkBenchEmpty.desktop"

# 防止在 Kylin 等没有 dde-file-manager 的系统上误装（写进去也不会显示）
if ! command -v dde-file-manager >/dev/null 2>&1; then
    echo "错误：未检测到 dde-file-manager，本脚本仅适用于 UOS / deepin。" >&2
    echo "Kylin V10 / MATE（Caja）请使用对应系统的右键菜单脚本。" >&2
    exit 1
fi
if ! command -v sudo >/dev/null 2>&1; then
    echo "错误：写入 ${DESK_DIR} 需要 sudo。" >&2
    exit 1
fi

APP_PATH="${1:-}"
if [ -z "${APP_PATH}" ]; then
    SEARCH_DIR="$SCRIPT_DIR"
    LEVEL=0
    while [ "$LEVEL" -le 5 ]; do
        if [ -f "${SEARCH_DIR}/SVNWorkBench" ]; then
            APP_PATH="${SEARCH_DIR}/SVNWorkBench"
            break
        fi
        if [ -f "${SEARCH_DIR}/dist/SVNWorkBench" ]; then
            APP_PATH="${SEARCH_DIR}/dist/SVNWorkBench"
            break
        fi
        PARENT_DIR=$(dirname "${SEARCH_DIR}")
        [ "${PARENT_DIR}" = "${SEARCH_DIR}" ] && break
        SEARCH_DIR="$PARENT_DIR"
        LEVEL=$((LEVEL + 1))
    done
fi

echo "==== UOS SVNWorkBench 右键菜单安装 ===="
echo "程序路径: ${APP_PATH:-未找到}"

if [ -z "${APP_PATH}" ] || [ ! -f "${APP_PATH}" ]; then
    echo "错误：未找到 SVNWorkBench 可执行文件" >&2
    echo "请在工程根目录执行本脚本，或显式指定：bash $0 /path/to/SVNWorkBench" >&2
    exit 1
fi
# 存成绝对路径，脚本/程序日后挪动位置前都指向这里
APP_PATH=$(cd "$(dirname "${APP_PATH}")" && pwd)/$(basename "${APP_PATH}")
if ! chmod +x "${APP_PATH}" 2>/dev/null; then
    echo "错误：无法给 ${APP_PATH} 添加执行权限。" >&2
    exit 1
fi

# .desktop 的 Exec 路径加引号并转义反斜杠/双引号，路径含空格也能用
APP_EXEC=${APP_PATH//\\/\\\\}
APP_EXEC=${APP_EXEC//\"/\\\"}

if ! sudo mkdir -p "${DESK_DIR}" 2>/dev/null; then
    echo "错误：无法创建 ${DESK_DIR}（sudo 失败？）" >&2
    exit 1
fi

if ! sudo tee "${DESK_FILE}" >/dev/null <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=使用SVN_WB打开
Name[zh_CN]=使用SVN_WB打开
X-Deepin-Vendor=user-custom
X-DFM-MenuTypes=SingleDir
Exec="${APP_EXEC}" %F
EOF
then
    echo "错误：写入 ${DESK_FILE} 失败。" >&2
    exit 1
fi

# EmptyArea（右键空白处）：6.x 不展开 %F，必须用 %p 取当前目录，
# 所以单独一个 .desktop——与上面的 SingleDir 文件分开才两种都正常。
# 注意：%p 是 dde-file-manager 的扩展字段码，desktop-file-validate
# 会报 invalid field code，属预期行为，不要改成标准 %f/%F（空白处为空）。
if ! sudo tee "${DESK_FILE_EMPTY}" >/dev/null <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=使用SVN_WB打开
Name[zh_CN]=使用SVN_WB打开
X-Deepin-Vendor=user-custom
X-DFM-MenuTypes=EmptyArea
Exec="${APP_EXEC}" %p
EOF
then
    echo "错误：写入 ${DESK_FILE_EMPTY} 失败。" >&2
    exit 1
fi

if command -v killall >/dev/null 2>&1; then
    killall dde-file-manager 2>/dev/null || true
fi

echo "完成！已写入两个菜单项（右键文件夹 / 右键空白处），重启文件管理器后生效"
echo "卸载命令：bash ${SCRIPT_DIR}/2-卸载-UOS文件管理器右键菜单.sh"
