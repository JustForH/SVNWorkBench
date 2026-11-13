#!/bin/bash
# ============================================================
# 2-卸载-Kylin-V10-SP1-Peony右键菜单
# 仅适用于 Kylin V10 SP1（Peony 文件管理器，UKUI 桌面）。
#
# 与 scripts/right-menu/Kylin-V10/（MATE / Caja）完全无关，不要混用。
#
# 删除安装脚本编译并安装的 Peony 原生插件：
#   <前缀>/lib/<multiarch>/peony-extensions/libpeony-svnworkbench-plugin.so
# 不按固定 aarch64 路径删除：x86_64 机器上那会漏删；这里会自动计算
# multiarch 目录，并兜底搜索 /usr/lib/*/peony-extensions 与
# /usr/local/lib/*/peony-extensions。
#
# 如果安装时设置过 SVNWB_PEONY_LIBDIR / SVNWB_PEONY_TRIPLET，
# 卸载时请设置同样的值，否则可能找不到非标准目录里的插件。
#
# 用法：
#   源码目录:
#     bash scripts/right-menu/Kylin-V10-SP1/2-卸载-Kylin-V10-SP1-Peony右键菜单.sh
#   交付包（脚本在 dist/right-menu/Kylin-V10-SP1/）:
#     cd dist
#     bash right-menu/Kylin-V10-SP1/2-卸载-Kylin-V10-SP1-Peony右键菜单.sh
# ============================================================

# 兼容用户用 sh 执行：自动切回 bash
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi
set -u

die() {
    echo "错误：$*" >&2
    exit 1
}

have() {
    command -v "$1" >/dev/null 2>&1
}

SO_NAME="libpeony-svnworkbench-plugin.so"
CANDIDATES=()

if [ -n "${SVNWB_PEONY_LIBDIR:-}" ]; then
    case "${SVNWB_PEONY_LIBDIR}" in
        /*) : ;;
        *) die "SVNWB_PEONY_LIBDIR 必须是绝对路径：${SVNWB_PEONY_LIBDIR}" ;;
    esac
    CANDIDATES+=("${SVNWB_PEONY_LIBDIR}/peony-extensions/${SO_NAME}")
else
    # multiarch 目录：优先用户指定，其次 gcc，其次 dpkg-architecture，
    # 最后在 /usr/lib 下找唯一的 *-linux-gnu 目录。
    TRIPLET="${SVNWB_PEONY_TRIPLET:-}"
    if [ -z "$TRIPLET" ]; then
        TRIPLET=$(gcc -print-multiarch 2>/dev/null || true)
    fi
    if [ -z "$TRIPLET" ] && have dpkg-architecture; then
        TRIPLET=$(dpkg-architecture -qDEB_HOST_MULTIARCH 2>/dev/null || true)
    fi
    if [ -z "$TRIPLET" ]; then
        TRIPLET_CANDIDATES=(/usr/lib/*-linux-gnu)
        if [ "${#TRIPLET_CANDIDATES[@]}" -eq 1 ] && [ -d "${TRIPLET_CANDIDATES[0]}" ]; then
            TRIPLET=$(basename "${TRIPLET_CANDIDATES[0]}")
        fi
    fi
    case "$TRIPLET" in
        */*|*..*) die "非法的 multiarch 目录名：$TRIPLET" ;;
    esac

    # 标准安装路径（安装脚本默认写入这里）
    if [ -n "$TRIPLET" ]; then
        CANDIDATES+=("/usr/lib/${TRIPLET}/peony-extensions/${SO_NAME}")
        CANDIDATES+=("/usr/local/lib/${TRIPLET}/peony-extensions/${SO_NAME}")
    fi
    # 非 multiarch / 其它历史路径兜底
    CANDIDATES+=("/usr/lib/peony-extensions/${SO_NAME}")
    CANDIDATES+=("/usr/local/lib/peony-extensions/${SO_NAME}")
    CANDIDATES+=("/usr/lib64/peony-extensions/${SO_NAME}")

    # 再兜底扫描一遍 multiarch 子目录（覆盖旧脚本可能装错/装到别的 triplet
    # 的情况，例如旧卸载脚本写死 aarch64 但实际装在 x86_64 目录）。
    shopt -s nullglob
    for FILE in /usr/lib/*/peony-extensions/"${SO_NAME}" \
                /usr/local/lib/*/peony-extensions/"${SO_NAME}"
    do
        CANDIDATES+=("$FILE")
    done
    shopt -u nullglob
fi

# 去重后只保留真实存在的文件
FOUND=()
for CANDIDATE in "${CANDIDATES[@]}"; do
    [ -f "$CANDIDATE" ] || continue
    DUPLICATE=0
    if [ "${#FOUND[@]}" -gt 0 ]; then
        for EXISTING in "${FOUND[@]}"; do
            if [ "$EXISTING" = "$CANDIDATE" ]; then
                DUPLICATE=1
                break
            fi
        done
    fi
    if [ "$DUPLICATE" -eq 0 ]; then
        FOUND+=("$CANDIDATE")
    fi
done

if [ "${#FOUND[@]}" -eq 0 ]; then
    echo "未找到已安装的 SVNWorkBench Peony 插件（可能已经卸载）。"
else
    if [ "$(id -u)" -ne 0 ] && ! have sudo; then
        die "删除系统插件需要管理员权限，但未找到 sudo。请用 root 运行，或先安装 sudo。"
    fi

    echo "==== Kylin V10 SP1（Peony）右键菜单卸载 ===="
    for FILE in "${FOUND[@]}"; do
        echo "正在删除：$FILE"
        if [ "$(id -u)" -eq 0 ]; then
            rm -f -- "$FILE" || die "删除失败：$FILE"
        else
            sudo rm -f -- "$FILE" || die "删除失败：$FILE"
        fi
        [ ! -e "$FILE" ] || die "删除后文件仍然存在：$FILE"
    done
fi

# 清理旧版安装脚本留下的固定临时编译目录。只删当前用户自己的目录，
# 避免误删别人的东西；符号链接只删链接本身。
LEGACY_BUILD="/tmp/peony-svnworkbench-plugin"
if [ -L "$LEGACY_BUILD" ]; then
    rm -f -- "$LEGACY_BUILD" 2>/dev/null || true
    echo "已清理旧版临时编译目录（符号链接）：$LEGACY_BUILD"
elif [ -d "$LEGACY_BUILD" ]; then
    LEGACY_OWNER=$(stat -c '%U' "$LEGACY_BUILD" 2>/dev/null || true)
    CURRENT_USER=$(id -un 2>/dev/null || true)
    if [ -n "$LEGACY_OWNER" ] && [ "$LEGACY_OWNER" = "$CURRENT_USER" ]; then
        rm -rf -- "$LEGACY_BUILD" 2>/dev/null || true
        echo "已清理旧版临时编译目录：$LEGACY_BUILD"
    else
        echo "提示：旧版临时目录 $LEGACY_BUILD 不属于当前用户，未自动删除。"
    fi
fi

# 只有真的删掉了插件才重启 Peony。
restart_peony() {
    if ! have peony; then
        echo "提示：未找到 peony，跳过自动重启。请注销后重新登录。"
        return
    fi
    if [ -z "${DISPLAY:-}" ]; then
        echo "提示：当前没有图形会话（DISPLAY 未设置），跳过自动重启。"
        echo "      请在桌面会话里执行：peony -q; peony"
        return
    fi
    if [ "$(id -u)" -eq 0 ]; then
        echo "提示：当前以 root 运行，未自动重启 Peony（避免以 root 拉起桌面）。"
        echo "      请回到桌面用户后执行：peony -q; peony"
        return
    fi

    echo "正在重启 Peony 文件管理器..."
    if have killall; then
        killall peony >/dev/null 2>&1 || true
    else
        peony -q >/dev/null 2>&1 || true
    fi
    sleep 1
    if have pgrep && pgrep -x peony >/dev/null 2>&1; then
        # 桌面环境可能已经自动拉起了 Peony。
        :
    else
        nohup peony >/dev/null 2>&1 &
    fi
}

if [ "${#FOUND[@]}" -gt 0 ]; then
    restart_peony
    echo ""
    echo "✅ 插件已移除，右键菜单已消失。"
else
    echo "没有需要删除的插件文件。"
fi
