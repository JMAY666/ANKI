# Anki

[![Build Status](https://github.com/ankitects/anki/actions/workflows/ci.yml/badge.svg)](https://github.com/ankitects/anki/actions/workflows/ci.yml)
[![Documentation](https://img.shields.io/badge/docs-dev--docs.ankiweb.net-blue)](https://dev-docs.ankiweb.net)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=ankitects_anki&metric=coverage)](https://sonarcloud.io/summary/new_code?id=ankitects_anki)

This repo contains the source code for the computer version of
[Anki](https://apps.ankiweb.net).

## About

Anki is a spaced repetition program. Please see the [website](https://apps.ankiweb.net) to learn more.

## 内置 SynapsePro 与 FSRS Helper

本仓库把 SynapsePro 1.6.0-local 与 FSRS Helper 26.05.08 直接集成进 Anki 26.08.1 源码，交付同一个可启动软件，不需要用户安装两个插件。保留 DeepSeek、三栏浏览、学习计划、番茄钟等已确认功能；网页查看器、笔记本与思维导图保持移除，旧数据保留。

源码位于 `qt/aqt/builtin_features/`，由 Anki 初始化并管理配置；旧插件配置可迁入，重复加载会被拦截。三栏浏览同时提供 FSRS Target R，保留原生浏览与复习流程。

构建、启动、迁移和恢复见 [内置功能说明](BUILTIN-FEATURES.md)，本次安装与验证见 [交付记录](docs/BUILTIN-INTEGRATION-2026-09-11.md)。后续修改审核后统一推送 `main`。

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
for checks, Git review, and local commits. Local commits do not authorize a push;
review every outgoing commit, including files deleted later in that history,
before an authorized push. Keep relevant documentation in the same commit as the
change, and review the GitHub About description after a successful push.

#### Contributors

The following people have contributed to Anki: [CONTRIBUTORS](./CONTRIBUTORS)

### Anki Betas

If you'd like to try development builds of Anki but don't feel comfortable
building the code, please see [Anki betas](https://betas.ankiweb.net/).

## License

Anki's license: [LICENSE](./LICENSE)
