# SynapsePro 插件说明

当前本地版本为 **1.6.0-local**：在原生卡片浏览器中增加三栏浏览，保留原生编辑器和标准布局。继续保留 1.5.1 的 DeepSeek API 支持及旧数据保护。插件源码位于同一 main 分支的 `addon/`；Anki 主程序目录保持独立。以下“来源与基线”记录原始 1.5.0，当前修改详情和验证见 [1.6.0 报告](docs/RELEASE-1.6.0.md)，此前修改见 [1.5.1 报告](docs/RELEASE-1.5.1.md)。

## 三栏卡片浏览

点击 Anki 顶部“浏览”，首次打开会进入三栏模式，并在屏幕允许时扩大窗口。工具栏或“视图”菜单中取消勾选“三栏浏览”，即可恢复标准布局、原生列设置和笔记模式。

- 左侧牌组目录直接读取 Anki 层级；支持查找、折叠、选中标记及长名称悬停提示。默认包含子牌组，可取消勾选“包含子牌组”。选择另一牌组会清空内容搜索；查找牌组只过滤目录。
- 中间按卡片显示问题摘要、卡片模板和到期信息。同一笔记的正反向卡片、不同挖空卡片分别列出。搜索支持 Anki 语法；排序下拉框支持排序字段、添加时间、到期、模板和牌组，箭头切换升降序。问题摘要本身不支持排序。
- 右侧“预览”使用 Anki 模板、媒体服务和原生播放器。“显示答案”只翻面，不评分，不修改调度。切换卡片回到正面；多选时提示选择一张卡片。“编辑”保留原生保存、模板/字段操作及撤销流程，切换牌组前保存未完成的编辑。
- 窗口尺寸、分栏宽度、目录显隐、折叠状态及排序保存在当前 profile 的本地设置中。窄窗口用工具栏“牌组目录／卡片列表／卡片预览”切换，不强制挤满三栏。原生布局的窗口尺寸和列宽分别保留。
- `F6` 在目录、列表、预览之间切换；`Ctrl+Alt+1/2/3` 分别聚焦这三个区域。目录用方向键展开、折叠及选择，列表用上下键选择；列表中的空格显示/切换预览，`R` 重播音频。编辑输入框不使用这些单键操作。原有“跳转”菜单也会转到当前可见区域。
- “全部筛选条件”显示原生侧栏的标签、状态、已保存搜索等；工具栏“牌组目录”可以返回目录。其他入口传入的搜索（例如困难卡片）保持原条件，并显示“自定义搜索范围”。

与原生预览一致，输入答案型卡片的输入框会隐藏。未对所有自定义 JavaScript 模板、第三方浏览器插件或所有主题组合做穷举验证。

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

原版作者 README / 代码要求 Anki Desktop **25.09.4+、Qt6 WebEngine**；原始下载时的 AnkiWeb 分支元数据限定 **25.09.4–26.05.0**。这份历史元数据不等同于当前本地修改版的验证范围。1.6.0 的三栏浏览分别在 **25.09.4** 与源码构建的 **26.08.1** 验证；升级到其他版本后仍需重新运行回归。

| 目录                           | 用途                                                           |
| ------------------------------ | -------------------------------------------------------------- |
| `addon/`                       | 后续修改的原版插件代码                                         |
| `original/236979321.ankiaddon` | 原始完整包，SHA256 可校验，不入 Git                            |
| `original/upstream/`           | 作者源码与 Git 历史，参考用，不嵌入本工作仓库                  |
| `.venv/`                       | 独立 Python 3.13.13、Anki/aqt 25.09.4、PyQt6 6.11.0、Qt 6.11.2 |
| `runtime/manual/`              | 已准备的手动测试配置与独立插件副本                             |
| `runtime/load-probe/`          | 自动加载探针配置、日志和 JSON 结果                             |
| `scripts/`                     | 准备、加载检查、源码检查、打包及启动脚本                       |
| `docs/`                        | 结构说明与准备报告                                             |

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

# 原版导入探针只供历史对照，不代表当前修改的验证
./.venv/Scripts/python.exe scripts/load_probe.py

# 将审核后的新增插件文件明确纳入 Git，再打包
./.venv/Scripts/python.exe scripts/package.py
```

打包输出 `dist/SynapsePro-1.6.0-local.ankiaddon`。包内 manifest 的 package 为 `SynapsePro1`，而通过 AnkiWeb ID 安装/测试复制使用 `236979321`；不要在同一配置中同时启用两份。已有 manual 配置使用 `scripts/deploy_test.py manual` 更新（必须先退出 Anki），脚本会完整备份 profile，再只替换插件安装副本并校验 profile 数据哈希。无需再手动安装第二份插件。不要用 AnkiWeb 更新覆盖本地修改版。

仅通过 pip 准备的测试环境可能缺少音频播放器。Windows 源码工作区可先执行 `just addon-audio-tools`，通过项目已锁定版本和 SHA-256 的构建配方准备 mpv。启动脚本会在本进程中使用 `out/extracted/mpv`；跨工作区时可传 `-AudioDirectory <播放器目录>`，也可通过 `-PythonPath <python.exe>` 指定隔离 Python。不会修改系统 PATH。

三栏功能的重复验证使用以下配方；`<run>` 必须是新的测试目录名：

```powershell
just addon-test <python.exe>
just addon-lint
just addon-browser-smoke <run> <python.exe>
just addon-browser-restart <run> <python.exe>
# 默认生成 1 万张性能卡片；10 万张验证前设置：
$env:SYNAPSE_BROWSER_TEST_COUNT = '100000'
```

源码 26.08.1 测试使用 `out/pyenv/Scripts/python.exe`，并在当前命令进程设置 `PYTHONPATH=pylib;qt;out/pylib;out/qt`；请勿把该值带入 25.09.4 的独立运行环境。插件原有功能另用 `just addon-prepare smoke-1.5.1 <python.exe>` 和 `just addon-smoke write/restart <python.exe>` 验证。`just check` 仍是主程序的完整检查入口，不能代替插件回归。

启动脚本始终传 `-b runtime/<name>`、`-p SynapsePro-Test` 和独立 `ANKI_SINGLE_INSTANCE_KEY`。不传 `--safemode`，因为它会禁用待测插件。测试配置不登录 AnkiWeb，已设置 `autoSync=False`、`syncMedia=False`、`syncKey=None`。基础测试配置初始只有一张 2+2 卡片；浏览验收脚本会另行生成专用样本和性能数据。不要把正式导出、媒体或 API key 放入这里。

首次引导需要本人审阅并决定是否同意条款；自动测试不会接受条款或发送引导统计。当前版本需验证主界面与主题、侧栏、番茄钟、复习与统计/XP、计划与截止日期、AI 和音乐。已移除功能不再作为可操作入口，但旧数据保留须校验。每项记录动作、预期、结果和日志，不能以窗口出现代替验收。

测试回滚：退出测试进程，重新从原始包建立新 `runtime/<name>`；原测试目录保留备查。后续数据兼容测试须备份完整测试 profile（含 collection、媒体、SynapsePro_Data、笔记数据库和 WebEngine 存储）。不对现有工作目录执行自动清理或强制还原。

详细结论见 [接手报告](docs/HANDOVER.md)，修改位置见 [结构说明](docs/SYNAPSEPRO-ARCHITECTURE.md)。

原版历史验证见 [1.5.0 冒烟记录](docs/SMOKE.md)。当前 `scripts/smoke_test.py` 已更新为 1.5.1 的验收范围，结果见 [本地版本报告](docs/RELEASE-1.5.1.md)，不要把原版失败记录当作当前验收结果。

## 使用 DeepSeek

运行 `./scripts/launch-test.ps1 -RunName manual`，打开侧栏 AI 助手 → 设置 → 服务商 **DeepSeek**，填入自己的 API Key，选择 `deepseek-flash` 或输入账户支持的模型 ID，然后保存。API Key 只存储到当前 profile 的 `SynapsePro_Data/ai_secrets.json`，不要提交或分享该文件。其他服务商仍可选择，各自密钥保留。

DeepSeek 使用普通聊天模式（`thinking.type=disabled`）和原有流式交互，无需增加 SDK。接口与默认模型依据 [DeepSeek 官方文档](https://api-docs.deepseek.com/)，模型名可手动调整。
