# Windows 本地启动验证

验证日期：2026-09-10。源码版本：Anki 26.08.1。

## 环境与安装

已使用 Windows 11 x64、Visual Studio MSVC 14.51 和 Windows SDK 10.0.26100.0
构建本地源码。安装了 just 1.58.0、Ninja 1.13.2、MSYS2/rsync 3.5.0，
并按仓库锁定配置准备 Rust 1.97.1、Python 3.13.13、Node.js 22.17.0、
Yarn 4.11.0 和 Qt 6.11.1。四个子模块均检出到主仓库指定的提交。

H 盘通过 USB 连接，首次写入前端依赖中的大量小文件非常慢。
本机将生成的 `node_modules` 放在 `%USERPROFILE%\.cache\anki-source\h-anki\node_modules`，
项目根目录通过 Windows 目录连接访问它。保留此缓存和目录连接后，仍可使用正常的
`just` 命令。源码、Rust 构建结果和测试配置仍在项目目录中。
之前的部分依赖文件保留在 `out/startup-validation/node-modules-partial/`。

## 已处理的问题

- 开发文档中的 `uv tool install just` 会安装同名 Python 包；已更正为
  `uv tool install rust-just`，README 同时提供官方 winget 安装命令。
- Windows 下，Protobuf 编译器无法正确处理中文项目路径中的绝对输出路径。
  生成步骤改为传入相对路径，保留原有生成文件位置；补充路径回归测试及生成器依赖声明。
- 初次移动依赖缓存时，Windows 应用缓存映射使前端工具得到不同的真实路径，导致
  Vite manifest 匹配失败。改用普通用户缓存目录并核对路径解析结果后，构建成功。
- Windows 默认编码导致安装器子进程的输出无法被 pytest 按 UTF-8 解码。
  在检查环境中设置 `PYTHONUTF8=1` 和 `PYTHONIOENCODING=utf-8` 后，相关错误消失。
- 安装包测试中，Windows Installer 无法访问映射后的 WiX 缓存路径，返回 1619。
  下载文件的 SHA-256 与 Briefcase 固定值一致；将 `BRIEFCASE_HOME` 指向普通用户
  缓存目录后，工具安装和安装包测试通过。

## 实际界面操作

通过 `just run` 启动源码构建出的 PyQt 程序，并检查真实 Windows 窗口：

1. 中文主界面正常显示牌组、工具栏和底部按钮。
2. 使用“创建牌组”建立“启动验证牌组”，主界面正常显示新牌组。
3. 使用“添加”窗口输入正面“启动验证：2 + 2 等于多少？”、背面“4”，保存后提示
   “已添加 1 条笔记”。
4. 牌组总览显示 1 张未学习卡片；点击“开始学习”后，题面正常显示。
5. 点击“显示答案”后显示“4”，并出现重来、困难、良好、简单四个评分按钮。
6. 选择“简单”后显示学习完成页面；正常退出后，以只读方式核对数据库，确认
   1 条笔记、1 张卡片和 1 条学习记录已保存，评分为 4，下次间隔为 4 天。

## 数据隔离

测试使用 `out/startup-validation/profile/`，配置名为自动创建的“账户 1”。
同时传入 `--safemode` 并使用独立 `ANKI_SINGLE_INSTANCE_KEY`。
未登录同步账户，没有导入正式牌组。

已核对默认 Anki 数据目录：验证前后的 6,459 个文件清单、大小和修改时间一致，
其中两个数据库的 SHA-256 一致。该检查覆盖已发现的默认目录，并非全盘数据审计。
测试数据库、日志、校验清单、依赖和构建结果均由现有排除规则排除，不纳入 Git。

## 检查结果

`just build`、`just fix-fmt` 和 `just check` 均已通过。检查结果包括：

- Rust：629 项通过、0 跳过，包含新增的 3 项路径回归测试。
- Python：工具测试 23 项、库测试 153 项、Qt 测试 111 项全部通过。
- 前端：61 项测试通过，Svelte 检查为 0 错误、0 警告。
- 格式、类型、Clippy、Ruff、ESLint、生成文档和仓库规范检查通过。

完整检查使用以下本地环境配置；首次检查发现的编码和安装器缓存问题已在此配置下解决。
本地分支作者尚未登记上游贡献者名册，使用项目已有的作者白名单入口，不修改上游名册。
未配置这些环境变量时，不应将检查视为已经验证通过。

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:BRIEFCASE_HOME = Join-Path $env:USERPROFILE '.cache\anki-source\briefcase'
New-Item -ItemType Directory -Path $env:BRIEFCASE_HOME -Force | Out-Null
$env:CONTRIBUTORS_BYPASS_EMAILS = (git log -1 --format=%ae).Trim()
just check
```

安装器自动测试使用仓库内置的虚拟 wheel 样本。同步、插件、音视频、牌组导入导出，
以及正式 Anki 安装包的安装与运行，没有纳入本次基本操作验证。
正常退出后的数据已核对；由于用户停止了界面控制，重启后的窗口复测未执行。

## 后续启动

在新开的 PowerShell 7 中进入项目根目录，然后执行：

```powershell
$env:ANKI_SINGLE_INSTANCE_KEY = 'anki-source-startup-validation'
just run -b ./out/startup-validation/profile --safemode -l zh_CN
```

该命令继续使用测试配置。开发启动会关闭自动备份，且 `out/` 是构建输出目录，
因此这份配置只用于测试。安装和其他开发命令见根目录 README。
