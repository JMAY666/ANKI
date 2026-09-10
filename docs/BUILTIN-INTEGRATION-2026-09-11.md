# 两组功能内置集成交付记录

日期：2026-09-11。交付内容是本仓库内同一份 Anki 26.08.1 的源码和完整可启动软件。

## 源码与启动

- 工程：`E:\AI项目\ANKI\ANKI`。
- 内置实现：`qt/aqt/builtin_features/synapsepro/` 与 `qt/aqt/builtin_features/fsrs_helper/`。
- 原生接入：`qt/aqt/main.py` 初始化；`builtin_features/storage.py` 管理旧配置兼容；`qt/aqt/mediasrv.py` 提供内置资源；`qt/aqt/addons.py` 阻止旧副本重复加载。
- 仓库内完整软件：`dist/Anki-built-in-26.8.1/Anki.exe`。目录含 Python、Qt 和同一源码构建的 Anki 核心/界面，不依赖开发环境或另装两个插件。
- 原生关于界面显示内置版本；Anki 的内部集合版本和协议未改动。

在本仓库继续启动同一份已验证配置：

```powershell
just builtin-run -b ./runtime/builtin-joint-01 -p Builtin-Test -l zh_CN
```

也可运行仓库里的完整软件，使用相同配置：

```powershell
& './dist/Anki-built-in-26.8.1/Anki.exe' -b './runtime/builtin-joint-01' -p Builtin-Test -l zh_CN
```

正常使用时直接启动 `Anki.exe`，沿用 Anki 默认数据位置。两个独立插件工程已退出活动工作目录，完整原件移至恢复备份；活动实现只在本工程中。

## 版本核实

SynapsePro 使用本工程已经改过的 1.6.0-local（基线 `d7b6c5e20`），保留 `4eed59734` 的 DeepSeek 和功能移除、`3310041dd` 的三栏浏览以及后续窗口边界修复。未使用正式环境里的旧 1.5.0 替代。

FSRS Helper 使用已接手工程 `85ad582` 的运行版本：26.05.08 / `c7219f5`。运行代码、翻译资源和固定 i18n 依赖一并迁入，保留其 MIT 许可。

## 冲突与兼容处理

- 两组功能由 Anki 主程序初始化，初始化函数可重复调用而不重复注册。
- 两个原 ID 和同 manifest package 的改名副本会在内置模块加载成功后跳过；无关外部插件仍正常加载。
- FSRS 菜单及设置接入主程序配置；SynapsePro 的账户数据路径、AI Key 位置、集合配置键保持兼容。迁移只复制缺失内容，不删除来源。
- 三栏浏览保留原生表格/编辑器/预览，同时展示和支持排序 Target R。修复表头布局恢复错误触发排序事件的问题。
- CSS 及图片改用内置资源路由；可修改主题位于账户数据目录。修复预览页面触发不允许的内联脚本，以及 AI 页未加载完成时调用尚未定义函数的问题；没有放宽 Anki 内容安全策略。
- 网页查看器、笔记本、思维导图保持移除，其数据库、恢复文件和存储目录保留。

## 共同运行的实际结果

同一个 `runtime/builtin-joint-01` 配置、同一个 Anki/Qt 实例同时运行两组功能。配置包含 24 张合成卡片、合成复习历史和故意会报错的旧插件副本。

- 完整软件包：32 项共同运行检查通过，错误列表为空。
- 同配置的新进程重启：16 项通过，排程、复习记录、SynapsePro/DeepSeek 和 FSRS 配置保持。
- 删除两个旧插件测试目录后的同配置重启：17 项通过，确认内置功能不依赖它们存在。
- 检查包括两个原生菜单各一个、初始化去重、旧插件不执行、无关插件照常加载、旧设置和退役数据保留。
- DeepSeek 本地聊天页面渲染、三栏模板预览、FSRS Target R 列及排序、反复恢复标准布局通过。
- FSRS 原生设置对话框保存小数阈值、菜单开关和配置重读通过。
- 延期、提前、重新排程、摊平、休假、分散兄弟卡均实际改变合成排程，并通过撤销恢复；统计 HTML 生成正常。
- 真实复习页面展示问题、答案和评分，评分一次恰好新增一条复习记录。
- 扩展浏览回归：47 项通过；新进程重启 7 项通过。覆盖搜索、编辑持久化、原生音频、模板图片、布局、笔记模式恢复和一万张卡片测试牌组。
- 回归与迁移测试 18 项通过，包含安装/恢复脚本的临时文件验收：恢复原程序、旧插件配置，以及完整恢复数据时保留安装后产生的文件。
- `just build`、`just wheels`、`just check` 通过。完整检查包含 Rust 629 项、Python 库 153 项及 Qt 117 项；其他检查按构建缓存执行。
- 实际启动仓库完整包和安装后的 `Anki.exe`，均正常退出（0）。诊断确认两个模块从该程序的 `app_packages/aqt/builtin_features/` 加载，两个菜单各一个，无旧插件模块，未开启开发模式。

本地证据位于 `out/builtin-*.log`、`runtime/builtin-joint-01/*-results.json`、`runtime/builtin-browser-01/browser-*.json`，界面截图也在相应测试目录。它们由 Git 排除，不包含在源码提交中。

## 已完成的安装与备份

按最初安装要求，已安装到 `D:\Users\PC\AppData\Local\Programs\Anki`，原快捷方式仍指向相同 `Anki.exe`。用户随后要求把后续工作集中在仓库内，因此没有继续检查系统安装信息或开展额外系统部署。

- 原程序保留在 `D:\Users\PC\AppData\Local\Programs\Anki.pre-builtin-20260911-063622`。
- 最新完整程序和用户数据备份：`E:\AI项目\ANKI\integration-backups\20260911-063440`，含 SHA-256 清单及安装记录。
- 实施前源码、Git 历史及初始程序/数据备份：`E:\AI项目\ANKI\integration-backups\20260911-060256`。最新备份的 `SOURCE-BACKUP.txt` 指向它。
- 安装前发现偏好数据库、集合元数据及备份文件与初始快照有变化；逐行比较时，笔记、卡片和复习记录均一致。未归因到某个进程；完整保留了两次快照，并以最新快照作为安装恢复基准。
- 最新快照共 13,565 个用户文件，复制及安装前均校验 SHA-256。安装和离线配置迁移之后，原有文件仅两个旧插件的 `meta.json` 改变（停用标记），其余原有文件逐字节不变；新增内置配置及主题副本不覆盖源数据。
- 按用户随后要求，验证通过后已删除两个旧插件加载目录；先复制并校验的完整副本保存在最新备份的 `retired-installed-addons/`。两个独立源码工程移至 `retired-plugin-workspaces/`，不再留在当前活动工作目录。上述变更仅涉及这两个插件，正式集合、媒体及账户数据不在删除范围内。
- 仓库内旧测试配置的插件目录及旧 `.ankiaddon` 包也已归档至 `retired-test-addons/`、`retired-packages/`。既有恢复备份不删除；`dist/` 仅保留最终的 `Anki-built-in-26.8.1` 完整软件目录。
- 正式账户启用了自动同步。本次未启动其同步或对其评分；可执行文件验收继续使用同一份合成配置。

恢复命令：

```powershell
./scripts/restore_builtin.ps1 -BackupPath 'E:\AI项目\ANKI\integration-backups\20260911-063440'
```

默认恢复原程序和旧插件启用状态，保留最新学习数据。仅在需要整体回到备份时刻时添加 `-RestoreUserData`；它会保留恢复前的数据副本。详细边界见 [内置功能说明](../BUILTIN-FEATURES.md)。

## 验证限制

没有使用真实 DeepSeek Key 发起付费请求；DeepSeek 的请求构造、流式解析、错误和 Key 隔离通过离线回归测试。没有验证真实 AnkiWeb/移动端同步、全部第三方插件组合，以及 Hard 批量纠正等未执行的操作。保留上游 Qt/MathJax/Waitress 非阻断警告。已执行检查中没有剩余失败项。
