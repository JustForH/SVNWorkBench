#!/bin/sh
# ============================================================
# 1-构建-打包绿色单文件
#
# 产物: dist/ 目录 —— SVNWorkBench 主程序 + right-menu/<系统>/ 下的
#       右键菜单安装/卸载脚本，整个 dist/ 拷给客户即可：双击
#       SVNWorkBench 运行，再按目标系统执行对应目录里的 1-安装 脚本。
#       目标机只需系统自带的 svn 命令行（python3-tk 不再需要）。
#       例外：Kylin V10 SP1 的 Peony 右键插件在安装时现场编译，
#       执行该安装脚本的目标机需要有 libpeony-dev / qt5-qmake /
#       qtbase5-dev 等开发包；只运行主程序不需要。
#
# 脚本位置: 工程根目录/1-构建-打包绿色单文件.sh
# 用法（工程根目录）:
#   ./1-构建-打包绿色单文件.sh
#
# 构建机（跑本脚本的机器）需要 python3、python3-pip、python3-tk，
# 缺 pip / tkinter 时脚本自动 `sudo apt install`（会提示输密码）：
#   **python3-tk 必须装在构建机上**——tkinter 会被打进单文件；
#   构建机缺它时包"能打出来"，但一运行就报
#   ModuleNotFoundError: No module named 'tkinter'（实测踩过）。
#   目标机运行时不需要 python3-tk。
#
# 注意：PyInstaller 不支持交叉编译，每个架构要在对应架构的机器上
# 构建一次：x86 电脑上运行本脚本出 x86 包，ARM 设备上运行同一份
# 脚本出 ARM 包（脚本与架构无关，靠 Python 版本自动适配）。
#
# 国内网络可设镜像：PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
# ============================================================
set -e
SCRIPT_DIR=$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd)
PROJECT_ROOT="$SCRIPT_DIR"
cd "$PROJECT_ROOT"

# 按构建机的 Python 版本选 PyInstaller 版本：
#   3.5 -> 3.6（最后支持 3.5 的版本）
#   3.6 -> 4.10（4.x 源码用了 f-string，3.5 会 SyntaxError）
#   3.7 -> 5.x（6.x 最低要求 Python 3.8）
#   3.8 及以上 -> 6.x（pyinstaller<7）
# 20261111 实测：Python 3.8 必须走 pyinstaller<7；旧的 <6 分支会装
# 5.x，构建产物不可用。
# WANT_MAJOR 用来核对构建机已装的 PyInstaller 大版本，避免"缺了才装"
# 导致机器上原有的旧版本继续被使用。
PYVER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
case "$PYVER" in
    3.5)
        PKG="pyinstaller==3.6"
        WANT_MAJOR=3
        ;;
    3.6)
        PKG="pyinstaller==4.10"
        WANT_MAJOR=4
        ;;
    3.7)
        PKG="pyinstaller<6"
        WANT_MAJOR=5
        ;;
    *)
        PKG="pyinstaller<7"
        WANT_MAJOR=6
        ;;
esac

install_pkg() {
    echo "安装 $1 ..."
    if command -v sudo >/dev/null 2>&1; then
        sudo apt install -y "$1"
    else
        sudo apt-get install -y "$1" || {
            echo "错误：请用 root 手动安装: apt install $1" >&2
            exit 1
        }
    fi
}

# ① 构建机必须能 import tkinter —— 它会被打进单文件
if ! python3 -c "import tkinter" >/dev/null 2>&1; then
    echo "构建机缺少 python3-tk（需要打进单文件；目标机运行时不需要）..."
    install_pkg python3-tk
    if ! python3 -c "import tkinter" >/dev/null 2>&1; then
        echo "错误：仍无法 import tkinter，请手动执行: sudo apt install python3-tk" >&2
        exit 1
    fi
fi

# ② 检查 pyinstaller：没有、或大版本与当前 Python 要求不符时要重装。
#    只判断"有没有装"不够——构建机上遗留的旧 PyInstaller 会一直被用，
#    例如 Python 3.8 误装了 5.x 就会构建失败。
PI_VERSION=$(python3 -m PyInstaller --version 2>/dev/null || true)
NEED_PYINSTALLER=0
if [ -z "$PI_VERSION" ]; then
    NEED_PYINSTALLER=1
else
    PI_MAJOR=${PI_VERSION%%.*}
    case "$PI_MAJOR" in
        ''|*[!0-9]*) PI_MAJOR=0 ;;
    esac
    if [ "$PI_MAJOR" != "$WANT_MAJOR" ]; then
        echo "已安装 PyInstaller $PI_VERSION，与 Python $PYVER 要求的 $PKG 不符，准备重装..."
        NEED_PYINSTALLER=1
    fi
fi

if [ "$NEED_PYINSTALLER" = "1" ]; then
    if ! python3 -m pip --version >/dev/null 2>&1; then
        echo "构建机缺少 pip..."
        install_pkg python3-pip
    fi
    echo "安装 $PKG（Python $PYVER）..."
    if [ -n "${PYPI_MIRROR:-}" ]; then
        python3 -m pip install --user --upgrade -i "$PYPI_MIRROR" "$PKG" || \
            python3 -m pip install --user --upgrade "$PKG"
    else
        python3 -m pip install --user --upgrade "$PKG"
    fi

    PI_VERSION=$(python3 -m PyInstaller --version 2>/dev/null || true)
    if [ -z "$PI_VERSION" ]; then
        echo "错误：PyInstaller 安装后仍无法运行，请手动检查:" >&2
        echo "  python3 -m pip install --user --upgrade '$PKG'" >&2
        exit 1
    fi
    PI_MAJOR=${PI_VERSION%%.*}
    case "$PI_MAJOR" in
        ''|*[!0-9]*) PI_MAJOR=0 ;;
    esac
    if [ "$PI_MAJOR" != "$WANT_MAJOR" ]; then
        echo "错误：安装后 PyInstaller 仍是 $PI_VERSION（Python $PYVER 需要 $PKG）。" >&2
        echo "      可能有系统级版本优先级更高，请手动卸载旧版后重跑：" >&2
        echo "      python3 -m pip uninstall pyinstaller" >&2
        exit 1
    fi
fi
echo "使用 PyInstaller $PI_VERSION（Python $PYVER）"

# --clean 必须带：PyInstaller 有增量缓存，build/ 里留着上次的 TOC 时
# 重跑会"checking Analysis/PYZ/PKG/EXE"全部跳过、750ms 空跑退出 0，
# 旧 exe 与旧 warn 文件原封不动（装完 python3-tk 重跑也不会重建——）
# 20261014 实测踩过），产物仍是坏的。
python3 -m PyInstaller --clean --onefile --windowed --name SVNWorkBench \
    --distpath dist --workpath build --specpath build \
    --log-level WARN SVNWorkBench.py

# ③ 事后核对：tkinter 真的打进去了（防止构建机环境异常静默漏包，
#    漏包的产物一运行就报 No module named 'tkinter'）。
#    warn 文件不存在 = Analysis 压根没跑（--clean 后不该发生），同样报错。
WARNFILE="build/SVNWorkBench/warn-SVNWorkBench.txt"
if [ ! -f "$WARNFILE" ]; then
    echo "错误：未生成 $WARNFILE，构建疑似空跑，请检查上方输出。" >&2
    exit 1
fi
if grep -q "missing module named tkinter" "$WARNFILE"; then
    echo "错误：tkinter 未打进包，产物不可用。请检查构建机 python3-tk 后重跑。" >&2
    exit 1
fi

# ④ 右键菜单脚本随包交付：scripts/right-menu/<系统>/ 整个目录结构
#    原样拷进 dist/right-menu/<系统>/。保留分系统子目录，避免 UOS 与
#    Kylin 的 1-安装 / 2-卸载 编号混在一起；以后新增系统时只要在
#    scripts/right-menu/ 下加子目录，这里会自动带上，不需要改脚本。
MENU_SRC="${SCRIPT_DIR}/scripts/right-menu"
if [ ! -d "$MENU_SRC" ]; then
    echo "错误：缺少右键菜单脚本目录 $MENU_SRC" >&2
    exit 1
fi
# 清掉上次构建留下的旧布局（早期版本把脚本平铺在 dist/ 根目录）
rm -rf dist/right-menu
rm -f dist/0?-安装-*.sh dist/0?-卸载-*.sh \
      dist/install_SVNWorkBench_Right_Menu.sh \
      dist/uninstall_SVNWorkBench_Right_Menu.sh

COPIED_MENU=""
for OS_DIR in "$MENU_SRC"/*; do
    [ -d "$OS_DIR" ] || continue
    OS_NAME=$(basename "$OS_DIR")
    mkdir -p "dist/right-menu/$OS_NAME"
    for MENU_FILE in "$OS_DIR"/*.sh; do
        [ -f "$MENU_FILE" ] || continue
        MENU_NAME=$(basename "$MENU_FILE")
        cp -f "$MENU_FILE" "dist/right-menu/$OS_NAME/$MENU_NAME"
        chmod +x "dist/right-menu/$OS_NAME/$MENU_NAME"
        COPIED_MENU="$COPIED_MENU $OS_NAME/$MENU_NAME"
    done
done
if [ -z "$COPIED_MENU" ]; then
    echo "错误：$MENU_SRC 下没有可用的右键菜单脚本（*.sh）" >&2
    exit 1
fi

chmod +x dist/SVNWorkBench
echo ""
echo "完成: $(pwd)/dist/"
echo "架构: $(uname -m)   Python: $PYVER   PyInstaller: $PI_VERSION"
echo "已随包拷贝右键菜单脚本："
for MENU_ITEM in $COPIED_MENU; do
    echo "  dist/right-menu/$MENU_ITEM"
done
echo "把 dist/ 整个目录拷到目标目录即可交付："
echo "  双击 SVNWorkBench 运行，再进入 dist/ 执行对应系统的 1-安装 脚本："
echo "  UOS/deepin:            bash right-menu/UOS/1-安装-UOS文件管理器右键菜单.sh"
echo "  Kylin V10 (MATE/Caja): bash right-menu/Kylin-V10/1-安装-Kylin-V10-Caja右键菜单.sh"
echo "  Kylin V10 SP1 (Peony): bash right-menu/Kylin-V10-SP1/1-安装-Kylin-V10-SP1-Peony右键菜单.sh"
echo "  （SP1 安装右键菜单时需目标机有 libpeony-dev、qt5-qmake、qtbase5-dev）"
echo "（配置在 ~/.config/SVNWorkBench/，日志在 /tmp/SVNWorkBench-<用户名>/logs/）"
