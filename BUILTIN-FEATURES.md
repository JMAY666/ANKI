# Anki 内置学习工具

本工程把已修改的 SynapsePro 和已接手的 FSRS Helper 直接编入同一份 Anki 26.08.1。启动 Anki 后，两组功能由主程序加载，无需安装 `236979321` 或 `759844606`，不交付独立插件包。

## 源码与保留的版本

- Anki：本仓库 `qt/`、`pylib/`、`rslib/`、`ts/`，版本 26.08.1。
- SynapsePro：`qt/aqt/builtin_features/synapsepro/`，来自本仓库 `d7b6c5e20` 的 1.6.0-local。DeepSeek 和功能移除来自 `4eed59734`；三栏浏览来自 `3310041dd`，窗口边界修复来自 `d7b6c5e20`。没有重新下载原版替代。
- FSRS Helper：`qt/aqt/builtin_features/fsrs_helper/`，来自相邻已接手工程的 `85ad582`；运行源码基线是标签 26.05.08、提交 `c7219f5`。未升级到其他版本。
- FSRS 翻译依赖：已将固定的 `python_i18n` 子模块运行代码和许可证纳入主程序。来源提交 `4b7deea70b07b4286c96a59cc176abe14784b360`，不依赖用户另外安装 Python 包。
- 两组原始 MIT 许可证及 SynapsePro 第三方声明随源码和软件保留。迁入代码保留已有格式，核心接入层遵循主工程的格式和类型检查；迁入代码另有行为回归及真实 Anki/Qt 测试。

## 使用

打开原 Anki 快捷方式或安装目录中的 `Anki.exe`。

- 工具 → SynapsePro：主题、学习计划等设置；侧栏包含 AI、番茄钟、音乐等已保留功能。
- AI 的服务商下拉保留 DeepSeek。Key 仍保存在账户本地 `SynapsePro_Data/ai_secrets.json`，不放入软件包或 Git。
- 点击浏览进入原生三栏模式，列表同时显示 FSRS 的 Target R 列；可恢复标准布局。
- 工具 → FSRS Helper：排程工具及开关；“设置…”打开本机配置编辑器。原牌组齿轮入口、统计和复习回调保留。
- 关于界面显示两组内置功能的版本。网页查看器、笔记本、思维导图没有恢复。

## 配置与兼容

`aqt.main.AnkiQt.setupAddons()` 在外部插件加载前调用原生功能初始化。这里沿用既有生命周期入口的位置，但功能模块属于 `aqt` 软件包，不经过插件管理器导入。重复初始化不会再次注册菜单/事件。

`builtin_features/storage.py` 管理迁移和路径：

- FSRS 设置保存到 Anki 数据根目录的 `builtin_features/fsrs_helper.json`。首次合并旧插件 `config.json` 和 `meta.json.config`，保留未知字段。后续以原生配置为准，不重复覆盖。
- FSRS 的导出及 Hard 纠正记录迁入 `builtin_features/fsrs_helper/user_files/`，原文件保留。
- SynapsePro 继续使用各账户的 `SynapsePro_Data`、原有集合设置键和浏览器偏好。旧插件根目录设置仅在目标缺失时复制；既有 AI Key 不搬往新的位置。
- 可修改的 CSS 位于账户 `SynapsePro_Data/themes/`，不写入软件安装目录；内置资源经 Anki 自己的资源路由提供，代码、配置和 Key 不能从此路由读取。
- 旧笔记本、思维导图、音乐及其他用户数据均保留。停用功能不会删除其历史数据。
- 两个原插件 ID 以及保留这些 manifest package 标识的改名副本，会在内置模块成功初始化后跳过加载。用户手动重新启用旧插件，也不会重复执行这两组功能。其余插件沿用 Anki 正常加载流程。

## 构建与验证

沿用项目工具链，通过 `just` 执行：

```powershell
just build
just builtin-test
just builtin-smoke joint-test-001
just builtin-smoke joint-test-001 restart
just builtin-smoke joint-test-001 builtin-only
just check
```

同一 smoke 配置同时包含两组内置功能，并放入会报错的旧插件副本，检验旧副本未执行。测试覆盖配置迁移、菜单/事件去重、DeepSeek 本地页面、三栏浏览与 Target R、排程及撤销、复习和新进程持久化。测试不使用真实 API Key、同步账户或正式牌组。

保留更完整的三栏浏览回归脚本，现也使用本工程的同一内置软件，不安装独立插件：

```powershell
just builtin-browser-smoke browser-test-001
just builtin-browser-restart browser-test-001
```

使用已有 Windows Anki 26.8.1 运行时模板和本工程新构建的两个 wheel 组装完整软件：

```powershell
just builtin-package '原 Anki 程序备份目录' 'Anki-built-in-26.8.1'
```

产物包含 `Anki.exe`、Python/Qt、同一份核心和界面代码，位于 `dist/Anki-built-in-26.8.1/`。构建记录和 wheel 哈希位于其中的 `INTEGRATED-BUILD.json`。这一步复用既有 Python/Qt 启动器，并替换为本工程构建的 `anki`、`aqt` 和 `_aqt` 包；不是把两个插件复制进用户插件目录。

源码直接运行采用正常自动备份行为：

```powershell
just builtin-run -b '测试数据根目录' -p '测试账户名' -l zh_CN
```

原 `just run` 仍是上游开发模式；正常使用请选择安装后的 `Anki.exe` 或 `builtin-run`。`--safemode` 仅跳过外部插件及自动同步，两组内置功能仍运行。

## 安装与恢复

安装前关闭 Anki，完整备份原程序、用户数据和源码。先用同一个合成配置验证软件包及其 `Anki.exe`，再运行：

```powershell
./scripts/install_builtin.ps1 -ImagePath '完整软件目录' -InstallPath '实际 Anki 安装目录' -BackupPath '已校验的完整备份目录'
```

安装器先复制并校验文件，将原程序保留在原位置旁的 `.pre-builtin-时间戳` 目录，再替换正式目录；备份两个旧插件的完整 metadata 后将其停用，不删除插件代码和配置。`installation.json` 记录实际位置。

确认内置版本验证通过后，按用户要求移除旧插件加载目录。此命令先复制并逐文件校验恢复副本，再删除两个固定 ID 的旧插件目录：

```powershell
./scripts/remove_legacy_addons.ps1 -DataPath 'Anki 数据根目录' -BackupPath '已校验的完整备份目录'
```

本次已执行该清理；两个独立插件工程也已移到备份下的 `retired-plugin-workspaces/`，原插件完整副本位于 `retired-installed-addons/`。正常运行只使用本工程中的内置代码。`builtin-only` 验证会移除同一合成配置里的旧插件测试副本，然后检查两组功能仍可运行。

恢复原程序和旧插件启用状态，保留安装后学习数据：

```powershell
./scripts/restore_builtin.ps1 -BackupPath '完整备份目录'
```

只有需要回到备份时刻的整个数据目录时，才加 `-RestoreUserData`。该选项会先把当前数据移到 `.before-restore-时间戳`，然后复制备份，不直接丢弃安装后产生的数据。单纯恢复程序不会撤销已进行的 FSRS 排程；可使用 Anki 撤销，或恢复相应数据备份。

具体安装位置、备份和本次结果见 [交付记录](docs/BUILTIN-INTEGRATION-2026-09-11.md)。早期插件报告仅作为历史记录，不再代表当前交付方式。
