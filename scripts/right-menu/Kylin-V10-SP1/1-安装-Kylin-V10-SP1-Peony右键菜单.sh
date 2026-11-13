#!/bin/bash
# ============================================================
# 1-安装-Kylin-V10-SP1-Peony右键菜单
# 仅适用于 Kylin V10 SP1（Peony 文件管理器，UKUI 桌面）。
#
# 与 scripts/right-menu/Kylin-V10/（MATE / Caja 的“脚本”菜单）完全
# 无关，两套方案不要混用：
#   - Kylin-V10/        Caja 用户级脚本，无需编译；
#   - Kylin-V10-SP1/    本脚本，编译 Peony 原生 C++ 菜单插件。
#
# 本脚本在安装时现场编译一个小型 Qt 插件，安装到
#   <前缀>/lib/<multiarch>/peony-extensions/libpeony-svnworkbench-plugin.so
# 之后 Peony 的右键菜单里会出现“使用SVN_WB打开”：
#   - 选中目录：打开该目录（工作副本）；
#   - 选中文件：打开文件所在目录；
#   - 空白处右键：打开当前目录。
# 程序启动参数就是工作副本目录（见 README「文件管理器右键集成」）。
#
# 安装需要管理员权限（内部调用 sudo make install），并且目标机要有
# Peony 开发包与 Qt5 开发工具：
#   sudo apt install g++ make pkg-config qt5-qmake qtbase5-dev libpeony-dev
# 包名以目标机软件源为准；关键是要有 peony.pc 和 menu-plugin-iface.h。
#
# 用法：
#   源码目录:
#     bash scripts/right-menu/Kylin-V10-SP1/1-安装-Kylin-V10-SP1-Peony右键菜单.sh [exe路径]
#   交付包（脚本在 dist/right-menu/Kylin-V10-SP1/）:
#     cd dist
#     bash right-menu/Kylin-V10-SP1/1-安装-Kylin-V10-SP1-Peony右键菜单.sh [exe路径]
#
# 不带参数时从脚本所在目录开始，逐级向上查找：
#   ① <目录>/SVNWorkBench
#   ② <目录>/dist/SVNWorkBench
#   ③ <目录>/../../SVNWorkBench
#   ④ <工程根>/dist/SVNWorkBench
# 例如 dist/right-menu/Kylin-V10-SP1/ 会找到 dist/SVNWorkBench；源码目录
# 里的 scripts/right-menu/Kylin-V10-SP1/ 会找到工程根目录/dist/SVNWorkBench。
#
# 可选环境变量（一般不需要）：
#   SVNWB_PEONY_VERSION   覆盖插件元数据版本（默认取 pkg-config --modversion peony，
#                         必须与目标机 Peony 的 VERSION 完全一致）
#   SVNWB_PEONY_TRIPLET   覆盖 multiarch 目录名（默认由 gcc / dpkg-architecture 计算）
#   SVNWB_PEONY_LIBDIR    覆盖库根目录（默认 /usr/lib/<triplet>；仅调试/非标准安装，
#                         Peony 只会从它自己的插件目录加载，普通用户不要设置）
#   SVNWB_KEEP_BUILD=1    编译失败时保留临时目录，便于排查
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

# ---------- 1. 环境检查 ----------
if ! have peony; then
    die "未检测到 peony 文件管理器。本脚本仅适用于 Kylin V10 SP1（Peony）；
      Kylin V10 / MATE（Caja）请使用 right-menu/Kylin-V10/ 下的脚本。"
fi

MISSING=""
for TOOL in qmake make g++ gcc pkg-config; do
    have "$TOOL" || MISSING="${MISSING} ${TOOL}"
done
if [ -n "$MISSING" ]; then
    cat >&2 <<EOF
错误：缺少编译工具：${MISSING}
请先安装（Kylin V10 SP1 / Debian 系，包名以软件源为准）：
  sudo apt install g++ make pkg-config qt5-qmake qtbase5-dev libpeony-dev
EOF
    exit 1
fi

if [ "$(id -u)" -ne 0 ] && ! have sudo; then
    die "安装插件需要管理员权限，但未找到 sudo。请用 root 运行，或先安装 sudo。"
fi

QT_VERSION=$(qmake -query QT_VERSION 2>/dev/null || true)
case "$QT_VERSION" in
    5.*) : ;;
    *)
        die "当前 qmake 不是 Qt5（QT_VERSION=${QT_VERSION:-未知}）。Peony 使用 Qt5，
      请安装 qt5-qmake / qtbase5-dev 后重试。"
        ;;
esac

if ! pkg-config --exists peony; then
    cat >&2 <<'EOF'
错误：pkg-config 找不到 peony（缺少 peony.pc 或 Peony 开发包）。
请先安装目标机对应的 Peony 开发包，例如：
  sudo apt install libpeony-dev
安装后可用下面命令确认：
  pkg-config --modversion peony
  pkg-config --cflags peony
EOF
    exit 1
fi

PEONY_VERSION="${SVNWB_PEONY_VERSION:-$(pkg-config --modversion peony 2>/dev/null || true)}"
if ! [[ "$PEONY_VERSION" =~ ^[0-9]+(\.[0-9]+)+$ ]]; then
    die "无法确定 Peony 版本（得到：${PEONY_VERSION:-空}）。
      Peony 插件的 common.json 版本必须与 Peony 的 VERSION 完全一致，
      请用 SVNWB_PEONY_VERSION=3.2.2 这类形式显式指定。"
fi

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
[ -n "$TRIPLET" ] || die "无法确定系统库目录（multiarch triplet）。
      请用 SVNWB_PEONY_TRIPLET=aarch64-linux-gnu 或 x86_64-linux-gnu 显式指定。"
case "$TRIPLET" in
    */*|*..*) die "非法的 multiarch 目录名：$TRIPLET" ;;
esac

LIBDIR="${SVNWB_PEONY_LIBDIR:-/usr/lib/$TRIPLET}"
case "$LIBDIR" in
    /*) : ;;
    *) die "SVNWB_PEONY_LIBDIR 必须是绝对路径：$LIBDIR" ;;
esac
case "$LIBDIR" in
    *[[:space:]]*) die "SVNWB_PEONY_LIBDIR 不能包含空白字符：$LIBDIR" ;;
esac
INSTALL_DIR="${LIBDIR}/peony-extensions"
SO_NAME="libpeony-svnworkbench-plugin.so"
INSTALLED_SO="${INSTALL_DIR}/${SO_NAME}"

if [ -n "${SVNWB_PEONY_LIBDIR:-}" ]; then
    echo "注意：已用 SVNWB_PEONY_LIBDIR 覆盖安装目录（仅调试/非标准安装）："
    echo "      $INSTALL_DIR"
    echo "      Peony 默认只会从 /usr/lib/<multiarch>/peony-extensions 加载插件。"
fi

# ---------- 2. 定位主程序 ----------
SCRIPT_PATH="$0"
if have readlink; then
    SCRIPT_PATH=$(readlink -f "$0" 2>/dev/null || printf '%s' "$0")
fi
SCRIPT_DIR=$(cd "$(dirname "${SCRIPT_PATH}")" >/dev/null 2>&1 && pwd || true)
PROJECT_ROOT=$(cd "${SCRIPT_DIR}/../../.." >/dev/null 2>&1 && pwd || true)

APP_PATH="${1:-}"
if [ -z "$APP_PATH" ]; then
    for CANDIDATE in \
        "${SCRIPT_DIR}/SVNWorkBench" \
        "${SCRIPT_DIR}/dist/SVNWorkBench" \
        "${SCRIPT_DIR}/../../SVNWorkBench" \
        "${PROJECT_ROOT}/dist/SVNWorkBench" \
        "${PROJECT_ROOT}/SVNWorkBench/dist/SVNWorkBench"
    do
        if [ -f "$CANDIDATE" ]; then
            APP_PATH="$CANDIDATE"
            break
        fi
    done
fi

[ -n "$APP_PATH" ] || die "未找到 SVNWorkBench 可执行文件。
      请把本脚本放在 dist/ 里执行，或用第一个参数显式指定程序路径。"
[ -f "$APP_PATH" ] || die "SVNWorkBench 不存在：$APP_PATH"
APP_DIR=$(cd "$(dirname "$APP_PATH")" >/dev/null 2>&1 && pwd || true)
[ -n "$APP_DIR" ] || die "无法解析程序所在目录：$APP_PATH"
APP_PATH="${APP_DIR}/$(basename "$APP_PATH")"
if [ ! -x "$APP_PATH" ]; then
    chmod +x "$APP_PATH" 2>/dev/null || true
fi
[ -x "$APP_PATH" ] || die "程序不可执行：$APP_PATH"
case "$APP_PATH" in
    *$'\n'*) die "程序路径包含换行符，无法写入插件源码：$APP_PATH" ;;
esac

echo "==== Kylin V10 SP1（Peony）右键菜单安装 ===="
echo "程序路径: $APP_PATH"
echo "Peony 版本: $PEONY_VERSION"
echo "插件目录: $INSTALL_DIR"

# 把程序路径安全地嵌进 C++ 字符串字面量（只转义反斜杠和双引号）
APP_PATH_CPP=${APP_PATH//\\/\\\\}
APP_PATH_CPP=${APP_PATH_CPP//\"/\\\"}

# ---------- 3. 准备临时编译目录 ----------
BUILD_DIR=$(mktemp -d "${TMPDIR:-/tmp}/svnworkbench-peony-plugin.XXXXXXXX") \
    || die "无法创建临时编译目录"
KEEP_BUILD=0

cleanup() {
    if [ "$KEEP_BUILD" != "1" ]; then
        rm -rf -- "$BUILD_DIR"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

# 编译阶段（qmake 或 make）失败时统一调用：设置 SVNWB_KEEP_BUILD=1
# 才保留临时目录，否则只提示如何保留。
keep_build_on_failure() {
    if [ "${SVNWB_KEEP_BUILD:-0}" = "1" ]; then
        KEEP_BUILD=1
        echo "临时编译目录已保留：$BUILD_DIR" >&2
        echo "排查完请手动删除：rm -rf -- \"$BUILD_DIR\"" >&2
    else
        echo "如需保留临时目录排查，请设置 SVNWB_KEEP_BUILD=1 后重跑。" >&2
    fi
}

cd "$BUILD_DIR" || die "无法进入临时编译目录：$BUILD_DIR"

# ---------- 4. 生成 qmake 工程 ----------
cat > svnworkbench_plugin.pro <<'PRO_EOF'
TEMPLATE = lib
TARGET = peony-svnworkbench-plugin
CONFIG += plugin c++11
QT += core gui widgets

PKGCONFIG += peony
CONFIG += link_pkgconfig

HEADERS += svnworkbench_plugin.h
SOURCES += svnworkbench_plugin.cpp
DISTFILES += common.json

isEmpty(PREFIX): PREFIX = /usr
isEmpty(LIBDIR): LIBDIR = $$PREFIX/lib/$$ARCH_TRIPLET
isEmpty(ARCH_TRIPLET) {
    error("ARCH_TRIPLET is empty")
}
target.path = $$LIBDIR/peony-extensions/
INSTALLS += target
PRO_EOF

# ---------- 5. 生成插件头文件 ----------
cat > svnworkbench_plugin.h <<'HEADER_EOF'
#ifndef SVNWORKBENCH_PLUGIN_H
#define SVNWORKBENCH_PLUGIN_H

#include <QObject>
#include <QAction>
#include <QIcon>
#include <QStringList>

#include <menu-plugin-iface.h>

class SVNWorkBenchMenuPlugin : public QObject, public Peony::MenuPluginInterface
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID "org.ukui.peony-qt.plugin-iface.MenuPluginInterface" FILE "common.json")
    Q_INTERFACES(Peony::MenuPluginInterface)

public:
    explicit SVNWorkBenchMenuPlugin(QObject *parent = nullptr);
    ~SVNWorkBenchMenuPlugin() override;

    QList<QAction *> menuActions(Peony::MenuPluginInterface::Types types,
                                 const QString &uri,
                                 const QStringList &selectionUris) override;

    Peony::PluginInterface::PluginType pluginType() override;
    const QString name() override;
    const QString description() override;
    const QIcon icon() override;
    void setEnable(bool enable) override;
    bool isEnable() override;
    QString testPlugin() override;

private:
    bool m_enable;
};

#endif // SVNWORKBENCH_PLUGIN_H
HEADER_EOF

# ---------- 6. 生成插件元数据 ----------
# 版本必须与目标机 Peony 的 VERSION 完全一致，否则 PluginManager 会跳过插件。
cat > common.json <<EOF
{
    "name": "SVNWorkBench",
    "version": "${PEONY_VERSION}",
    "description": "Right-click menu for SVNWorkBench"
}
EOF

# ---------- 7. 生成插件实现 ----------
{
cat <<'CPP_HEAD'
#include "svnworkbench_plugin.h"

#include <QDebug>
#include <QFileInfo>
#include <QProcess>
#include <QUrl>

namespace {

// 把 Peony 传来的 URI 换算成要打开的工作副本目录：
//   目录 -> 目录本身；普通文件 -> 文件所在目录；
//   非本地 URI（trash://、smb:// 等）或已不存在的路径 -> 空。
QString localDirectoryForUri(const QString &uri)
{
    const QUrl url(uri);
    if (!url.isLocalFile()) {
        return QString();
    }

    const QString path = url.toLocalFile();
    if (path.isEmpty()) {
        return QString();
    }

    const QFileInfo info(path);
    if (info.isDir()) {
        return info.absoluteFilePath();
    }
    if (info.isFile()) {
        return info.absolutePath();
    }
    return QString();
}

} // namespace
CPP_HEAD

printf 'static const char kSvnWorkBenchAppPath[] = "%s";\n' "$APP_PATH_CPP"
cat <<'CPP_TAIL'

SVNWorkBenchMenuPlugin::SVNWorkBenchMenuPlugin(QObject *parent)
    : QObject(parent), m_enable(true)
{
}

SVNWorkBenchMenuPlugin::~SVNWorkBenchMenuPlugin()
{
}

QList<QAction *> SVNWorkBenchMenuPlugin::menuActions(
        Peony::MenuPluginInterface::Types types,
        const QString &uri,
        const QStringList &selectionUris)
{
    QList<QAction *> actions;

    if (!m_enable) {
        return actions;
    }

    // 只处理文件/文件夹视图和桌面，不往侧边栏等其它菜单里加项。
    // 菜单可能同时带多个类型标志，返回一次即可，避免重复菜单项。
    if (!types.testFlag(Peony::MenuPluginInterface::DirectoryView)
            && !types.testFlag(Peony::MenuPluginInterface::DesktopWindow)) {
        return actions;
    }

    QString target;

    if (!selectionUris.isEmpty()) {
        // 主程序只取第一个启动参数作为工作副本：取第一个能换算成
        // 本地目录的选中项。全是非本地 URI 时不要退回当前目录，
        // 否则会打开一个与用户所选内容无关的路径。
        for (const QString &selectedUri : selectionUris) {
            const QString dir = localDirectoryForUri(selectedUri);
            if (!dir.isEmpty()) {
                target = dir;
                break;
            }
        }
        if (target.isEmpty()) {
            return actions;
        }
    } else {
        // 空白处右键：uri 是当前目录。
        target = localDirectoryForUri(uri);
        if (target.isEmpty()) {
            return actions;
        }
    }

    // 关键：每次都必须新建 QAction，不能复用成员指针。
    // Peony 的 DirectoryViewMenu / DesktopMenu 会对插件返回的 action
    // 执行 setParent(menu)，菜单关闭时随 QMenu 一起销毁；复用旧指针
    // 会在下一次右键时访问已释放对象，导致 Peony 直接闪退。
    // parent 必须为 nullptr，交给 Peony 接管所有权。
    QAction *action = new QAction(QStringLiteral("使用SVN_WB打开"), nullptr);
    action->setIcon(QIcon::fromTheme(QStringLiteral("utilities-terminal")));

    const QString appPath = QString::fromUtf8(kSvnWorkBenchAppPath);
    QObject::connect(action, &QAction::triggered, action,
                     [appPath, target]() {
        if (!QProcess::startDetached(appPath, QStringList() << target)) {
            qWarning() << "SVNWorkBench: failed to start" << appPath;
        }
    });

    actions << action;
    return actions;
}

Peony::PluginInterface::PluginType SVNWorkBenchMenuPlugin::pluginType()
{
    return Peony::PluginInterface::MenuPlugin;
}

const QString SVNWorkBenchMenuPlugin::name()
{
    return QStringLiteral("SVNWorkBench Menu");
}

const QString SVNWorkBenchMenuPlugin::description()
{
    return QStringLiteral("Add SVNWorkBench to context menu");
}

const QIcon SVNWorkBenchMenuPlugin::icon()
{
    return QIcon::fromTheme(QStringLiteral("utilities-terminal"));
}

void SVNWorkBenchMenuPlugin::setEnable(bool enable)
{
    m_enable = enable;
}

bool SVNWorkBenchMenuPlugin::isEnable()
{
    return m_enable;
}

QString SVNWorkBenchMenuPlugin::testPlugin()
{
    return QStringLiteral("ok");
}
CPP_TAIL
} > svnworkbench_plugin.cpp

# ---------- 8. 编译 ----------
JOBS=$(getconf _NPROCESSORS_ONLN 2>/dev/null || true)
case "$JOBS" in
    ''|*[!0-9]*) JOBS=1 ;;
esac

echo "正在生成构建文件..."
if ! qmake "LIBDIR=$LIBDIR" "ARCH_TRIPLET=$TRIPLET" > qmake.log 2>&1; then
    cat qmake.log >&2
    echo "错误：qmake 失败。请确认 qt5-qmake / qtbase5-dev / libpeony-dev 已安装，" >&2
    echo "      并且 g++ 能正常编译（qmake 会调用编译器做探测）。" >&2
    keep_build_on_failure
    exit 1
fi

echo "正在编译插件（并行 ${JOBS} 个任务）..."
if ! make -j"$JOBS"; then
    echo "" >&2
    echo "编译失败。常见原因：" >&2
    echo "  1) 缺少 Peony 开发包头文件 menu-plugin-iface.h（libpeony-dev）" >&2
    echo "  2) Qt5 开发包不完整（qtbase5-dev / qt5-qmake）" >&2
    echo "  3) Peony 版本与插件元数据不一致（当前 ${PEONY_VERSION}）" >&2
    keep_build_on_failure
    exit 1
fi

if [ ! -f "$BUILD_DIR/$SO_NAME" ]; then
    echo "错误：编译结束但未生成 $SO_NAME，请检查 qmake 输出。" >&2
    keep_build_on_failure
    exit 1
fi
file "$BUILD_DIR/$SO_NAME" 2>/dev/null || true

# ---------- 9. 安装 ----------
echo "正在安装插件（需要管理员权限）..."
if [ "$(id -u)" -eq 0 ]; then
    make install || die "make install 失败。"
else
    sudo make install || die "make install 失败（sudo 被取消或没有权限？）。"
fi

[ -f "$INSTALLED_SO" ] || die "安装后未找到插件文件：$INSTALLED_SO
      请检查 make install 的输出与目录权限。"
ls -l "$INSTALLED_SO"

# ---------- 10. 重启 Peony ----------
restart_peony() {
    if ! have peony; then
        echo "提示：未找到 peony，跳过自动重启。请注销后重新登录使插件生效。"
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

restart_peony

echo ""
echo "✅ 安装完成。"
echo "   插件：$INSTALLED_SO"
echo "   用法：右键文件或文件夹 ->“使用SVN_WB打开”"
echo "   卸载：bash \"$(dirname "$0")/2-卸载-Kylin-V10-SP1-Peony右键菜单.sh\""
