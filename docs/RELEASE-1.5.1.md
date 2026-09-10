# SynapsePro 1.5.1-local

2026-09-11，本地修改版；上游基线 1.5.0 保留在 `original/` 和 Git 标签 `baseline-1.5.0`。

## 修改

- AI 是本地 HTML + Python API，不是 AI 网站嵌入。沿用服务商下拉、Key、模型输入、帮助弹窗和流式回复，新增 DeepSeek，保留其余六种服务商。
- DeepSeek Key 独立存储于 profile 本地 secrets 文件；模型使用独立配置键，避免覆盖原服务商的模型设置。切换服务商时清除异家密钥，恢复该服务商已保存配置/本次编辑草稿，不硬编码真实 Key。
- 默认 `deepseek-flash`，支持任意模型 ID。请求发送到 `https://api.deepseek.com/chat/completions`，普通聊天模式 `thinking.type=disabled`，复用原流式 JSON/SSE 处理和 2048 输出 token 设置。
- 删除网页查看器、笔记本（含待办、PDF 制卡/查看器）、思维导图的导入、生命周期回调、侧栏按钮、设置项、快捷键分发和注册、网页资源导出。
- 删除四个专用 Python 模块：`website_sidebar.py`、`notebook_sidebar.py`、`mindmap_sidebar.py`、`embedded_window.py`；删除根 `index.html`、`web_notebook/` 的 HTML/PDF.js 及六个专用 SVG。embedded_window 只被三个被移除功能调用，AI 不依赖它。
- 保留 Qt WebEngine、AI `chat_ui.html`、音乐 WebView、主题/设置公共页面和牌组 wordcloud。移除 PDF.js 的专属许可段，保留 wordcloud 许可。
- 旧卡片 PDF 来源链接不改写；点击时提示查看器已移除、文件仍保留，不产生未知命令异常。不重新提供被移除功能入口。
- 旧数据、收藏、笔记数据库、PDF/媒体、WebEngine 存储和已存在的旧配置键不自动删除或迁移。

主要修改文件：`addon/ai_assistant.py`、`chat_ui.html`、`__init__.py`、`launcher_widget.py`、`constants.py`、`sidebar_shortcuts.py`、两种设置 Python 模块与 `settings_web/settings.html`、翻译/版本/隐私说明。专用删除清单可在 Git diff 中查看。

## 验证

环境：Windows，Anki 25.09.4，Python 3.13.13，PyQt6 6.11.0 / Qt 6.11.2。只用隔离 `runtime/smoke-1.5.1/` 和合成卡片、合成 Key。

- 7 个离线回归测试通过，含六种原服务商路由、DeepSeek 实际请求 URL/Auth/模型/stream 字段、流式解析、401 错误、缺 Key 不发送、独立 Key/模型保存、功能文件与快捷键移除。
- 36 项真实 Qt/Anki 事件循环检查通过：正常初始化、主界面、侧栏开关、菜单/工具入口移除、旧快捷键忽略、番茄钟真实计时/暂停/重置、AI WebView 七种服务商、界面保存 DeepSeek 设置、模拟 API 流式回复完整显示、原生设置/HTML 设置页无被移除控件、复习作答与 revlog、旧 PDF 链接安全提示。
- 16 项独立重启检查通过：DeepSeek 模型和 profile 本地 Key 保留、复习记录保留、旧笔记/思维导图等合成数据 SHA256 不变。
- Python AST、JSON、两个修改 HTML 的内联 JavaScript 语法检查通过；Git 变更空白检查通过。原版遗留 locales 转义及 Anki 弃用警告保留，不作为新功能失败。
- JSON 证据：`docs/release-smoke-write.json`、`docs/release-smoke-restart.json`。日志：`runtime/smoke-1.5.1/`、`runtime/unit-changes.log`。

API 验证使用合成 SSE 响应，真实 Python worker/Qt 信号/JS 渲染链路均运行。**没有真实 DeepSeek Key，所以未完成付费在线对话、真实账户模型权限或限流验证**；其他服务商也只验证旧路由保持，不宣称全部云端实测通过。主题完整视觉回归、音乐播放和所有学习计划/统计数值未逐项覆盖。未测试 Anki 26.08.1。

接口依据：[DeepSeek 官方首次调用](https://api-docs.deepseek.com/)、[思考模式说明](https://api-docs.deepseek.com/guides/thinking_mode/)，查阅于 2026-09-11。

## 运行与恢复

当前中文测试版入口仍为 `scripts/launch-test.ps1 -RunName manual`。更新工具 `scripts/deploy_test.py manual` 会先完整备份到 `runtime/backups/manual-时间戳/`，仅替换其 `addons21/236979321`，将旧安装目录保留到 profile 根部 `.addon-previous-时间戳/`，不会被 Anki 当作第二个插件加载。原来的额外插件数据文件保留，profile 数据更新前后做 SHA256 比较。

本次已实际更新 manual 配置。完整备份：`runtime/backups/manual-20260911-032947-658166/`；旧插件副本：`runtime/manual/.addon-previous-20260911-032947-658166/`。更新前后 50 个 profile/配置/数据文件 SHA256 完全相同；中文语言配置保持不变。没有启动或改动默认正式 Anki2，也没有推送 Git。

恢复时先退出测试 Anki；将当前安装目录移到另一个保留位置，再将上述旧安装目录移回 `addons21/236979321`。需要恢复整个测试状态时，从完整备份复制为新的独立测试目录，再显式用 `-b` 启动该目录；不要自动覆盖新的学习数据。默认正式 Anki2 不在此更新流程内。

重新准备合成测试：`scripts/prepare.py smoke-1.5.1`（已有目录时拒绝覆盖）；然后分别运行 `scripts/smoke_test.py write` 和 `scripts/smoke_test.py restart`。打包使用 `scripts/package.py`，输出 `dist/SynapsePro-1.5.1-local.ankiaddon`。
