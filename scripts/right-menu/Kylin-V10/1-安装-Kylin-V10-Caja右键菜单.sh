#!/bin/bash
# ============================================================
# 1-安装-Kylin-V10-Caja右键菜单
# 仅适用于 Kylin V10 / MATE 桌面（使用 Caja 文件管理器）。
#
# 在 ~/.config/caja/scripts/ 下写入菜单脚本"使用SVN_WB打开"，之后
# 文件管理器里 右键 -> 脚本 -> 使用SVN_WB打开 即启动程序：
#   - 选中目录：打开该目录（工作副本）；
#   - 选中文件：打开文件所在目录；
#   - 空白处右键：打开当前目录。
# 程序启动参数就是工作副本目录（见 README「文件管理器右键集成」）。
# 只写当前用户目录，不需要 sudo。
#
# 用法：
#   源码目录:
#     bash scripts/right-menu/Kylin-V10/1-安装-Kylin-V10-Caja右键菜单.sh [exe路径]
#   交付包（脚本在 dist/right-menu/Kylin-V10/）:
#     cd dist
#     bash right-menu/Kylin-V10/1-安装-Kylin-V10-Caja右键菜单.sh [exe路径]
#
# 不带参数时从脚本所在目录开始，逐级向上查找：
#   ① <目录>/SVNWorkBench          （脚本与 exe 放在一起）
#   ② <目录>/dist/SVNWorkBench     （源码目录 / 交付包上层目录）
# 例如 dist/right-menu/Kylin-V10/ 会找到 dist/SVNWorkBench；源码目录里的
# scripts/right-menu/Kylin-V10/ 会找到工程根目录/dist/SVNWorkBench。
# ============================================================

# 兼容用户用 sh 执行：自动切回 bash
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi
set -u

SCRIPT_PATH="$0"
if command -v readlink >/dev/null 2>&1; then
    SCRIPT_PATH=$(readlink -f "$0" 2>/dev/null || printf '%s' "$0")
fi
SCRIPT_DIR=$(cd "$(dirname "${SCRIPT_PATH}")" >/dev/null 2>&1 && pwd)

if [ -z "${HOME:-}" ]; then
    echo "错误：未设置 HOME，无法定位 Caja 脚本目录。" >&2
    exit 1
fi
CAJA_SCRIPTS_DIR="${HOME}/.config/caja/scripts"
MENU_SCRIPT="${CAJA_SCRIPTS_DIR}/使用SVN_WB打开"

# 防止在 UOS/deepin 等没有 Caja 的系统上误装（装进去也不会显示）
if ! command -v caja >/dev/null 2>&1; then
    echo "错误：未检测到 caja，本脚本仅适用于 Kylin V10 / MATE 桌面。" >&2
    echo "UOS / deepin 请使用对应系统的右键菜单脚本。" >&2
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

echo "==== Kylin V10 / Caja SVNWorkBench 右键菜单安装 ===="
echo "程序路径: ${APP_PATH:-未找到}"

if [ -z "${APP_PATH}" ] || [ ! -f "${APP_PATH}" ]; then
    echo "错误：未找到 SVNWorkBench 可执行文件" >&2
    echo "请在工程根目录执行本脚本，或显式指定：bash $0 /path/to/SVNWorkBench" >&2
    exit 1
fi
# 存成绝对路径，菜单脚本以后不依赖当前目录
APP_PATH=$(cd "$(dirname "${APP_PATH}")" && pwd)/$(basename "${APP_PATH}")
if ! chmod +x "${APP_PATH}" 2>/dev/null; then
    echo "错误：无法给 ${APP_PATH} 添加执行权限。" >&2
    exit 1
fi

if ! mkdir -p "${CAJA_SCRIPTS_DIR}" 2>/dev/null; then
    echo "错误：无法创建 Caja 脚本目录 ${CAJA_SCRIPTS_DIR}" >&2
    exit 1
fi
if [ ! -w "${CAJA_SCRIPTS_DIR}" ]; then
    echo "错误：Caja 脚本目录不可写：${CAJA_SCRIPTS_DIR}" >&2
    exit 1
fi

# 生成 Caja 菜单脚本：
#   - APP=... 用 printf %q 转义，路径含空格/引号也能正确执行；
#   - 静态部分用带引号的 heredoc，避免安装时提前展开运行时变量。
{
    printf '#!/bin/bash\n'
    printf '# Caja 右键脚本：使用SVN_WB打开（由安装脚本生成）\n'
    printf 'APP=%q\n' "${APP_PATH}"
    cat <<'EOF'

SELECTED="${CAJA_SCRIPT_SELECTED_FILE_PATHS:-}"
if [ -z "$SELECTED" ]; then
    # 空白处右键：Caja 只给出当前目录 URI（file:// 且百分号编码）
    CURRENT_URI="${CAJA_SCRIPT_CURRENT_URI:-}"
    case "$CURRENT_URI" in
        file://*) ;;
        *) exit 1 ;;
    esac
    CURRENT_DIR="${CURRENT_URI#file://}"
    printf -v CURRENT_DIR '%b' "${CURRENT_DIR//%/\\x}"
    SELECTED="$CURRENT_DIR"
fi

# 多选时 Caja 用换行分隔；程序一次只打开一个工作副本，取第一个
SELECTED="${SELECTED%%$'\n'*}"

if [ -d "$SELECTED" ]; then
    TARGET="$SELECTED"
elif [ -e "$SELECTED" ]; then
    # 选中普通文件：打开文件所在目录
    TARGET="$(dirname "$SELECTED")"
else
    exit 1
fi

exec "$APP" "$TARGET"
EOF
} > "${MENU_SCRIPT}" || {
    echo "错误：写入 ${MENU_SCRIPT} 失败。" >&2
    exit 1
}

if ! chmod 755 "${MENU_SCRIPT}" 2>/dev/null; then
    echo "错误：无法给 ${MENU_SCRIPT} 添加执行权限。" >&2
    exit 1
fi

# 重启 Caja 让"脚本"菜单立即刷新（优雅退出；桌面会话通常会重新拉起）
if command -v caja >/dev/null 2>&1; then
    caja -q >/dev/null 2>&1 || killall caja >/dev/null 2>&1 || true
fi

echo "完成！菜单项：右键 -> 脚本 -> 使用SVN_WB打开"
echo "（选中文件时会打开该文件所在目录）"
echo "卸载命令：bash ${SCRIPT_DIR}/2-卸载-Kylin-V10-Caja右键菜单.sh"
