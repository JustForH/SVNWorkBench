# 脚本说明

## 目录结构

```text
工程根目录/
├── 1-构建-打包绿色单文件.sh           # 通用：打包
├── 2-清理-构建产物与缓存.sh           # 通用：清理
└── scripts/
    ├── README.md
    └── right-menu/
        ├── UOS/                       # UOS / deepin 专用
        │   ├── 1-安装-UOS文件管理器右键菜单.sh
        │   └── 2-卸载-UOS文件管理器右键菜单.sh
        ├── Kylin-V10/                 # Kylin V10 / MATE（Caja）专用
        │   ├── 1-安装-Kylin-V10-Caja右键菜单.sh
        │   └── 2-卸载-Kylin-V10-Caja右键菜单.sh
        └── Kylin-V10-SP1/             # Kylin V10 SP1（Peony）专用，与上面的 Caja 方案无关
            ├── 1-安装-Kylin-V10-SP1-Peony右键菜单.sh
            └── 2-卸载-Kylin-V10-SP1-Peony右键菜单.sh
```

## 脚本索引

| 编号 | 脚本 | 作用 | 适用环境 |
| --- | --- | --- | --- |
| 1 | `1-构建-打包绿色单文件.sh`（根目录） | 用 PyInstaller 打包 `dist/` 绿色单文件，并把各系统的右键菜单脚本拷入 `dist/right-menu/<系统>/` | 构建机（x86 / ARM 各自构建） |
| 2 | `2-清理-构建产物与缓存.sh`（根目录） | 删除 `build/`、`dist/`、`__pycache__/`、`*.pyc` | 构建机 |
| 1 | `right-menu/UOS/1-安装-UOS文件管理器右键菜单.sh` | 安装 UOS/deepin 系统级菜单（右键文件夹 + 右键空白处，两个 .desktop） | UOS / deepin |
| 2 | `right-menu/UOS/2-卸载-UOS文件管理器右键菜单.sh` | 卸载 UOS/deepin 系统级菜单 | UOS / deepin |
| 1 | `right-menu/Kylin-V10/1-安装-Kylin-V10-Caja右键菜单.sh` | 安装 Kylin V10 的 Caja 用户级菜单脚本（右键 -> 脚本） | Kylin V10 / MATE |
| 2 | `right-menu/Kylin-V10/2-卸载-Kylin-V10-Caja右键菜单.sh` | 卸载 Kylin V10 的 Caja 菜单脚本 | Kylin V10 / MATE |
| 1 | `right-menu/Kylin-V10-SP1/1-安装-Kylin-V10-SP1-Peony右键菜单.sh` | 现场编译并安装 Peony 原生 C++ 菜单插件 | Kylin V10 SP1 / Peony |
| 2 | `right-menu/Kylin-V10-SP1/2-卸载-Kylin-V10-SP1-Peony右键菜单.sh` | 删除 Peony 原生插件（按 multiarch 动态查找） | Kylin V10 SP1 / Peony |

## 编号与目录约定

- 通用构建/清理脚本直接放在工程根目录，常用命令更短。
- 按操作系统区分的脚本放在 `scripts/right-menu/<系统>/`，目录名保持
  系统本名：`UOS/`、`Kylin-V10/`、`Kylin-V10-SP1/`。**`Kylin-V10-SP1/`
  与 `Kylin-V10/` 是两套互不相干的方案，不能合并**（前者是 Peony 原生
  插件，后者是 MATE/Caja 脚本）。
- 编号在每个类别内从 `1` 开始，按使用顺序排列，**不补前导零**：
  - 根目录：`1-构建`、`2-清理`。
  - `right-menu/<系统>/`：`1-安装`、`2-卸载`。
- 文件名统一采用“编号-动作-对象/系统”的格式，让作用一眼可见。
- 安装/卸载脚本的正本放在 `scripts/right-menu/<系统>/`；打包时由根目录的
  `1-构建-打包绿色单文件.sh` **自动遍历** `scripts/right-menu/` 下的所有
  系统子目录，原样拷入 `dist/right-menu/<系统>/`。新增系统时只要新建
  子目录并放入编号脚本，不需要改打包脚本。

## 各系统说明

### UOS / deepin

- 使用 `dde-file-manager` 的系统级菜单扩展，写入
  `/usr/share/deepin/dde-file-manager/oem-menuextensions/`，需要 sudo。
- 安装两个 `.desktop`：`SVNWorkBench.desktop`（右键文件夹，`%F`）与
  `SVNWorkBenchEmpty.desktop`（右键空白处，`%p`）。dde-file-manager 6.x
  起空白处不展开 `%F`，两份缺一不可。
- 安装脚本会检测 `dde-file-manager`，在 Kylin 等没有该文件管理器的系统上
  直接报错退出，避免误装。

### Kylin V10 / MATE（Caja）

- 使用 Caja 的用户级“脚本”菜单，写入
  `~/.config/caja/scripts/使用SVN_WB打开`，不需要 sudo。
- 菜单入口：文件管理器里 **右键 -> 脚本 -> 使用SVN_WB打开**。
- 选中目录时打开该目录；选中普通文件时打开文件所在目录；空白处右键时
  打开当前目录。
- 安装脚本会检测 `caja`，在 UOS/deepin 等没有 Caja 的系统上直接报错退出。
- 卸载脚本只删除上面那一个菜单脚本，不影响 `~/.config/caja/` 里的其它
  脚本。

### Kylin V10 SP1（Peony 原生插件）

- **与 Kylin V10 / MATE（Caja）完全无关，两套脚本不要混用。** SP1 使用
  Peony（UKUI 桌面）的原生 C++ 菜单插件，不是 Caja 的“脚本”菜单。
- 安装脚本在目标机现场编译一个小型 Qt 插件，安装为
  `/usr/lib/<multiarch>/peony-extensions/libpeony-svnworkbench-plugin.so`
  （`<multiarch>` 由 `gcc -print-multiarch` / `dpkg-architecture` 计算，
  ARM 通常是 `aarch64-linux-gnu`，x86_64 是 `x86_64-linux-gnu`）。
- 安装依赖（包名以目标机软件源为准）：

  ```bash
  sudo apt install g++ make pkg-config qt5-qmake qtbase5-dev libpeony-dev
  ```

  关键检查：`qmake` 是 Qt5、`pkg-config --exists peony`、能通过
  `pkg-config --cflags peony` 找到 `menu-plugin-iface.h`。缺少时安装
  脚本会给出明确提示并退出，不会留下半装状态。
- **插件元数据版本必须与 Peony 的 `VERSION` 完全一致**，否则 Peony 的
  `PluginManager` 会静默跳过插件。脚本默认用
  `pkg-config --modversion peony` 生成 `common.json` 的 `version`
  （Kylin V10 SP1 当前为 `3.2.2`）；确需覆盖时用
  `SVNWB_PEONY_VERSION=3.2.2`。Peony 升级后要重新执行安装脚本编译。
- 菜单只挂在 `DirectoryView` 与 `DesktopWindow` 两种类型上，不往侧边栏
  等其它菜单加项；`menuActions` 里同时检查插件启用状态。选中目录时
  打开该目录，选中普通文件时打开文件所在目录，空白处右键时打开当前
  目录；多选时主程序目前只取第一个目录作为工作副本。
- **每次 `menuActions` 都必须新建 QAction（`parent=nullptr`），禁止复用
  成员 QAction 指针**：Peony 的 `DirectoryViewMenu` / `DesktopMenu` 会对
  插件返回的 action 执行 `setParent(menu)`，菜单关闭时 action 随
  `QMenu` 销毁。复用旧指针会在下一次右键时访问已释放对象，导致 Peony
  闪退（右键文件夹后再右键文件/空白处必现）。目标目录用值捕获进
  lambda，`connect` 以 action 自身为上下文。
- 卸载脚本**不再写死 `aarch64-linux-gnu`**：按 multiarch 动态计算，并
  兜底搜索 `/usr/lib/*/peony-extensions/` 与
  `/usr/local/lib/*/peony-extensions/`，x86_64 机器上也能删干净。只有
  真的删掉插件才重启 Peony。
- 可选环境变量（一般不需要）：
  - `SVNWB_PEONY_VERSION`：覆盖插件元数据版本；
  - `SVNWB_PEONY_TRIPLET`：覆盖 multiarch 目录名；
  - `SVNWB_PEONY_LIBDIR`：覆盖库根目录，仅调试/非标准安装使用，
    **普通用户不要设置**（Peony 只会从自己的插件目录加载）；
  - `SVNWB_KEEP_BUILD=1`：编译失败时保留临时目录，便于排查。
- 临时编译目录用 `mktemp -d` 创建，退出时自动清理；不再使用固定的
  `/tmp/peony-svnworkbench-plugin`，避免并发/符号链接风险。卸载脚本会
  顺带清理旧版脚本留下的这个固定目录（只删当前用户自己的）。
- 插件不随 `dist/` 提供预编译 `.so`：Peony 插件与架构、Qt/Peony 版本
  强相关，必须在目标机现场编译。

## 交付包中的位置

```text
dist/
├── SVNWorkBench
└── right-menu/
    ├── UOS/
    │   ├── 1-安装-UOS文件管理器右键菜单.sh
    │   └── 2-卸载-UOS文件管理器右键菜单.sh
    ├── Kylin-V10/
    │   ├── 1-安装-Kylin-V10-Caja右键菜单.sh
    │   └── 2-卸载-Kylin-V10-Caja右键菜单.sh
    └── Kylin-V10-SP1/
        ├── 1-安装-Kylin-V10-SP1-Peony右键菜单.sh
        └── 2-卸载-Kylin-V10-SP1-Peony右键菜单.sh
```

进入 `dist/` 后按目标系统执行对应的 `1-安装` 脚本即可；安装脚本会从
脚本所在目录逐级向上查找 `SVNWorkBench` / `dist/SVNWorkBench`，所以
脚本放在 `dist/right-menu/<系统>/` 里也能自动找到 exe，也支持显式指定：

```bash
bash right-menu/UOS/1-安装-UOS文件管理器右键菜单.sh /path/to/SVNWorkBench
bash right-menu/Kylin-V10/1-安装-Kylin-V10-Caja右键菜单.sh /path/to/SVNWorkBench
bash right-menu/Kylin-V10-SP1/1-安装-Kylin-V10-SP1-Peony右键菜单.sh /path/to/SVNWorkBench
```
