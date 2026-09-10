# SynapsePro 接手工作区

本阶段仅获取、梳理和准备环境，未修改插件行为。后续修改目标为 `addon/`，不是同级 Anki 主程序仓库。

隔离测试启动器默认使用简体中文（`zh_CN`）。现有 manual 配置中的 SynapsePro 语言已设为中文（`zh`）；后续新配置使用插件的自动跟随 Anki 语言设置。

## 来源与基线

- 插件：SynapsePro，AnkiWeb 名称 SynapsePro - The Ultimate Anki Workspace，ID `236979321`。
- 发布包内部版本：`1.5.0`；`manifest.json`、`constants.py`、`config.json` 一致。
- [AnkiWeb](https://ankiweb.net/shared/info/236979321)：页面文本抓取只返回 JavaScript required，浏览器访问超时；实际发布包通过 Anki 客户端同款下载接口成功获取。
- 下载请求：`https://ankiweb.net/shared/download/236979321?v=2.1&p=260801`。
- 返回地址：`https://ankiweb.net/svc/shared/download-addon/236979321?t=1786729966&minpt=250904&maxpt=260500&bidx=0`。
- 下载时间：2026-09-11（北京时间）；大小 34,221,077 字节。
- SHA256：`6fadd925440a512babcad14ad70301439d03a87df7ff6eb14fd9b6b42e16bef7`。
- [作者仓库](https://github.com/mobesamedia/SynapsePro)，已克隆完整历史至 `original/upstream/`。HEAD `d9db156b8a0845c0e7344e4e33b871eedbe39b7a`，提交标题 Update-1.5.0。
- 发布包 287 个有效文件与本地 `addon/` 逐字节一致。与作者 checkout 对比，85 个文本文件仅存在换行差异；规范化 CRLF/LF 后，发布包文件内容全部匹配。作者仓库另有 README 等开发说明。
- 原始 ZIP 保留 macOS 元数据；工作目录同样保留，但 Git、打包和测试复制排除 `__MACOSX`、`.DS_Store`。未改动源码。

## 兼容版本与目录

作者 README / 代码要求 Anki Desktop **25.09.4+、Qt6 WebEngine**；AnkiWeb 当前分支元数据限定 **25.09.4–26.05.0**。这是两个不同来源的约束，不能据最低版本检查认定所有更新版本兼容。原有 `../ANKI/` 为 26.08.1，本阶段未用它做兼容性结论，也未修改该仓库。

| 目录 | 用途 |
|---|---|
| `addon/` | 后续修改的原版插件代码 |
| `original/236979321.ankiaddon` | 原始完整包，SHA256 可校验，不入 Git |
| `original/upstream/` | 作者源码与 Git 历史，参考用，不嵌入本工作仓库 |
| `.venv/` | 独立 Python 3.13.13、Anki/aqt 25.09.4、PyQt6 6.11.0、Qt 6.11.2 |
| `runtime/manual/` | 已准备的手动测试配置与独立插件副本 |
| `runtime/load-probe/` | 自动加载探针配置、日志和 JSON 结果 |
| `scripts/` | 准备、加载检查、源码检查、打包及启动脚本 |
| `docs/` | 结构说明与准备报告 |

## 开发与安装验证

在本工作区执行 PowerShell 命令；脚本不会安装到默认 Anki2。

```powershell
# 重建环境时使用；本机已完成
uv venv --python 3.13.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.lock.txt

# 已存在的 manual 配置直接启动，不要重复创建
./scripts/launch-test.ps1 -RunName manual

# 修改后复制到全新测试配置；原测试配置及数据不覆盖
./.venv/Scripts/python.exe scripts/prepare.py change-001
./scripts/launch-test.ps1 -RunName change-001

# 检查原版一致性（有意修改 addon 后，该检查预期不再全部通过）
./.venv/Scripts/python.exe scripts/inspect_source.py
uv pip check --python .venv/Scripts/python.exe

# 首次加载探针已准备过，无需重建 load-probe
./.venv/Scripts/python.exe scripts/load_probe.py

# 将审核后的新增插件文件明确纳入 Git，再打包
./.venv/Scripts/python.exe scripts/package.py
```

打包输出 `dist/SynapsePro-1.5.0-local.ankiaddon`。可在**隔离测试 Anki**的 Tools → Add-ons → Install from file 中选择它，然后重启。包内 manifest 的 package 为 `SynapsePro1`，而通过 AnkiWeb ID 安装/测试复制使用 `236979321`；不要在同一配置中同时启用两份。验证手动安装包时创建不含复制插件的另一独立配置，或先在隔离插件管理器禁用 ID 副本。

启动脚本始终传 `-b runtime/<name>`、`-p SynapsePro-Test` 和独立 `ANKI_SINGLE_INSTANCE_KEY`。不传 `--safemode`，因为它会禁用待测插件。测试配置不登录 AnkiWeb，已设置 `autoSync=False`、`syncMedia=False`、`syncKey=None`，只有合成测试牌组和一张 2+2 卡片。不要把正式导出、媒体或 API key 放入这里。

首次引导需要本人审阅并决定是否同意条款；本阶段没有接受条款或发送引导统计。完成引导后依次验证：主界面与主题、侧栏开关、番茄钟、笔记/待办保存重启、思维导图保存重启、测试卡复习与统计/XP、计划与截止日期、PDF 合成文件制卡；最后按需验证联网 AI、网页、音乐。每项记录动作、预期、结果和日志，不能以窗口出现代替验收。

测试回滚：退出测试进程，重新从原始包建立新 `runtime/<name>`；原测试目录保留备查。后续数据兼容测试须备份完整测试 profile（含 collection、媒体、SynapsePro_Data、笔记数据库和 WebEngine 存储）。不对现有工作目录执行自动清理或强制还原。

详细结论见 [接手报告](docs/HANDOVER.md)，修改位置见 [结构说明](docs/ARCHITECTURE.md)。

后续已补做 [真实事件循环冒烟测试](docs/SMOKE.md)：主界面、计时、笔记/待办存储、复习及重启持久化通过；思维导图页面初始化失败，整组测试保持失败状态，未修改原版功能。复现脚本为 `scripts/smoke_test.py`。
