# Anki

[![Build Status](https://github.com/ankitects/anki/actions/workflows/ci.yml/badge.svg)](https://github.com/ankitects/anki/actions/workflows/ci.yml)
[![Documentation](https://img.shields.io/badge/docs-dev--docs.ankiweb.net-blue)](https://dev-docs.ankiweb.net)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=ankitects_anki&metric=coverage)](https://sonarcloud.io/summary/new_code?id=ankitects_anki)

This repo contains the source code for the computer version of
[Anki](https://apps.ankiweb.net).

## About

Anki is a spaced repetition program. Please see the [website](https://apps.ankiweb.net) to learn more.

## 内置 SynapsePro、FSRS Helper 与 Pass/Fail 2

本仓库把 SynapsePro 1.6.0-local 与 FSRS Helper 26.05.08 直接集成进 Anki 26.08.1 源码，交付同一个可启动软件，不需要用户安装两个插件。保留 DeepSeek、三栏浏览、学习计划、番茄钟等已确认功能；网页查看器、笔记本与思维导图保持移除，旧数据保留。

Pass/Fail 2 0.3.0 也已内置：复习栏可随时选择原生四档或 Fail／Pass 两档；工具 → 复习按钮提供原插件的名称、文字颜色开关、颜色选择与预览。新用户默认保留四档；旧插件配置和启用状态仅在首次读取时迁入，原件保留。版本来源与所有切换规则见 [Pass/Fail 2 集成说明](docs/PASSFAIL2-INTEGRATION.md)。

另已在同一源码中接入 Pace Graph、Button Colours、Search Stats Extended、Advanced Review Bottom Bar 3.6.1、Show Answer Button Pressed 和 Confident But Wrong。工具 → 复习与统计扩展管理设置；扩展图表位于统计 → 详细统计。默认保留当前评分外观，评分提示关闭、跳过按钮隐藏；原生／Pass-Fail 评分语义保持不变。新增菜单、设置、提示与报告使用中文。各项入口、固定来源、用户确认的冲突处理、验证和回退见 [六项内置功能说明](docs/SIX-ADDON-INTEGRATION.md)。

源码位于 `qt/aqt/builtin_features/`，由 Anki 初始化并管理配置；旧插件配置可迁入，重复加载会被拦截。三栏浏览同时提供 FSRS Target R，保留原生浏览与复习流程。

构建、启动、迁移和恢复见 [内置功能说明](BUILTIN-FEATURES.md)，此前两项功能的合并与安装见 [早期交付记录](docs/BUILTIN-INTEGRATION-2026-09-11.md)。后续修改审核后统一推送 `main`。

顶部统一使用「统计」，集中展示概览、每日 DeepSeek 建议和应用记录。牌组页面分为目录、当前牌组内容和辅助信息三栏；从中间的卡片入口直接进入原生复习，结束后返回原选中牌组。统计中的牌组选择支持层级搜索，并在附近提供对应牌组选项和共享预设范围。获取、创建牌组位于左栏，导入位于顶部。每日分析需在账户内配置并授权汇总数据；默认关闭，参数仅在确认后应用。Key 在 Windows 保存时使用当前用户加密。使用、口径、边界与验证见 [统计与每日建议说明](docs/LEARNING-WORKSPACE.md)。

本机实际使用版本：`dist/Anki-learning-workspace-26.8.1/Anki.exe`。无需单独安装插件；从牌组直接学习，从顶部「统计」查看数据与报告。

复习时，空格／Enter 只在正面显示答案；答案面用明确评分键继续。两档固定为 1 失败、2 通过，3／4 不评分；四档默认仍为 1／2／3／4。输入、输入法组合、弹窗以及非复习页面不接管复习键。详细映射、配置与验证边界见 [复习快捷键说明](docs/REVIEW-SHORTCUTS.md)。

导航、牌组三栏、Pass/Fail 切换以及对应软件更新的验证与恢复位置见 [导航与评分交付记录](docs/NAVIGATION-PASSFAIL2-DELIVERY-2026-09-11.md)。

复习时可拖动卡片区域左右边缘调整宽度，拖动下边缘调整高度；同一账户会记住布局。顶部「恢复布局」或双击边缘可恢复默认大小。全屏切换会同步调整铺满卡片的旧式内嵌页面，底部按钮栏按实际内容收紧，窄窗中的编辑／更多换行保留。复习栏仅在当前复习页面显示；返回主页面会移除旧按钮与占位，切换到统计时会暂停显示，窗口或分辨率变化不会将其重新打开。复习期间顶部导航的外层背景与窗口连通，卡片背景不会在导航后形成整条色带。使用与验证见 [复习布局说明](docs/REVIEW-LAYOUT.md)。

## Getting Started

### Contributing

Want to contribute to Anki? Check out the [Contribution Guidelines](./docs/contributing.md).

For more information on building and developing, please see [Development](./docs/development.md).

### Windows 本地构建与隔离启动

本仓库按 [CLAUDE.md](./CLAUDE.md) 使用 `just` 配方构建、运行和检查。
需要 64 位 Windows、PowerShell 7 (`pwsh`)、Git、Rustup、MSVC C++ 编译工具、
Windows SDK、Ninja（或 N2），以及 MSYS2 的 `rsync`。将 `C:\msys64\usr\bin`
加入 PATH，并保留 Git for Windows 在它之前。安装命令运行后，重新打开 PowerShell。

`just` 和 Ninja 可使用以下命令安装：

```powershell
winget install --id Casey.Just --exact
winget install --id Ninja-build.Ninja --exact
```

也可用 `uv tool install rust-just` 安装命令运行器；PyPI 的 `just` 是另一个包。
在项目根目录执行：

```powershell
git submodule update --init --recursive
just build
$env:ANKI_SINGLE_INSTANCE_KEY = 'anki-source-startup-validation'
just run -b ./out/startup-validation/profile --safemode -l zh_CN
```

构建系统按仓库配置自动准备 Rust、Python、Node.js、Qt 和其他依赖。
版本以 `rust-toolchain.toml`、`.python-version`、`build/ninja_gen/src/node.rs`
及锁定文件为准；首次构建需要联网，后续启动会复用 `out/` 中的构建结果。

上述启动命令把配置、牌组、卡片和媒体保存在 `out/startup-validation/profile/`，
与已安装 Anki 的默认数据目录独立；`--safemode` 禁用插件及自动同步。
独立的 `ANKI_SINGLE_INSTANCE_KEY` 防止启动请求被已运行的正式 Anki 实例接收。
第一次启动会在该目录创建独立配置。再次执行同一命令会保留测试数据。
此目录位于可重新生成的 `out/` 下，仅用于测试，不应用来保存正式学习数据。

`just run` 会启用开发模式并关闭自动备份，因此不要省略 `-b` 后直接打开已有学习配置。
完成修改后运行 `just check`；查看其他配方使用 `just --list`。

本机的启动操作、数据隔离与检查结果见 [Windows 启动验证记录](./docs/local-startup-validation.md)。

#### Repository workflow

Follow [AGENTS.md](./AGENTS.md) and the existing [CLAUDE.md](./CLAUDE.md) instructions
for checks, Git review, and local commits. The recorded authorization covers pushes
to `origin/main`; review every outgoing commit, including files deleted later in
that history, before pushing. Keep relevant documentation in the same commit as the
change, and review the GitHub About description after a successful push.

#### Contributors

The following people have contributed to Anki: [CONTRIBUTORS](./CONTRIBUTORS)

### Anki Betas

If you'd like to try development builds of Anki but don't feel comfortable
building the code, please see [Anki betas](https://betas.ankiweb.net/).

## License

Anki's license: [LICENSE](./LICENSE)
