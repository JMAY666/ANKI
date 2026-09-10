# 代码结构与修改定位

以下基于实际 1.5.0 源码阅读与 AST 导入扫描，不是宣传页推测。共 38 个 Python 文件，3 个 JSON 文件，287 个有效发布文件。没有独立前端构建配置或上游自动测试套件，HTML/CSS/JS 直接随插件发布。

| 职责 | 主要位置 | 后续修改边界 |
|---|---|---|
| 入口、配置、生命周期、主界面渲染 | `addon/__init__.py` | `get_default_settings`、`on_profile_open`、`on_profile_close`、JS 命令路由、主题注入与 hook 注册 |
| 侧栏按钮、停靠与快捷键 | `launcher_widget.py`、`embedded_window.py`、`sidebar_shortcuts.py` | 侧栏工具开关、位置、浮动窗口、快捷键 |
| 主题、背景、精简面板 | `theme.py`、`custom_background.py`、`theme_editor_dialog.py`、`minimal_dashboard.py`、`theme/user_files/` | Python 色板 + 注入 CSS，注意现有 Anki 页面的样式范围 |
| 设置与新手引导 | `settings_dialog.py`、`web_settings_dialog.py`、`settings_web/`、`onboarding_dialog.py`、`onboarding/`、`onboarding_terms.py` | Qt/WebView 双层交互、配置持久化、条款和一次性上报 |
| 统计、牌组总览、每日小组件 | `statistics_widget.py`、`statistics_settings_dialog.py`、`deck_overview.py`、`daily_widgets.py` | 读取 collection / revlog，缓存失效与渲染 |
| XP/等级/挑战 | `gamification.py`、`gamification_popup.py`、`sidebar.py`、`gamification_web/sidebar.html` | 计算、collection 配置、profile JSON 恢复副本 |
| 计划、截止日期 | `learning_plan.py`、`configuration.py`、`study_plan_trigger.py`、`deadline_bar.py` | 日期与 Anki rollover、计划状态、计时及配置 |
| 番茄钟、音乐 | `pomodoro.py`、`background_music.py`、`music_player.html`、`soundcloud_player.html` | QTimer、QtMultimedia、WebEngine 与 SoundCloud |
| AI | `ai_assistant.py`、`chat_ui.html` | Python 请求/错误处理、聊天桥接、provider、profile 密钥；界面能力未做联网验证 |
| 网页侧栏 | `website_sidebar.py` | QWebEngineView、profile cookies、书签/历史、选中文字搜索 |
| 笔记、待办、PDF 制卡 | `notebook_sidebar.py`、`web_notebook/` | SQLite、CollectionOp/AddNoteRequest、PDF.js、媒体和引用 |
| 思维导图 | `mindmap_sidebar.py`、根 `index.html` | `mindmap://` 导航桥接、WebEngine localStorage 与 JSON 恢复 |
| 翻译与元信息 | `locales.py`、`web_i18n.py`、`web_translations.py`、`constants.py`、`manifest.json`、`changelog.py` | Python/Web 翻译同步、版本与最低版本 |

## Anki 交互

入口通过 `aqt.mw` 访问主窗口、profile、collection 和任务管理器。注册 `profile_did_open` / `profile_will_close`、`deck_browser_will_render_content`、`webview_did_receive_js_message`、`state_did_change`、`webview_will_set_content`，以及版本可用时的工具栏/主题/同步 hooks。Qt dock、QTimer 与 WebView 页面通过 JS 消息和自定义 URL 联系 Python。统计直接读取 Anki 数据，笔记制卡通过 CollectionOp 和 AddNoteRequest 写测试 collection；不是浏览器扩展，也不是独立 Electron 应用。

## 依赖和数据

主要外部 Python 依赖为 Anki/aqt 与 PyQt6（Widgets、WebEngine、Multimedia、Svg），另用标准库 sqlite3、urllib、threading、json 等；没有发现必须额外 pip 安装的插件专属库。完整导入清单在 `source-inspection.json`。PDF.js 等网页依赖已随包提供，第三方许可见 `addon/THIRD_PARTY_NOTICES.md`。

`on_profile_open` 将旧插件目录中的配置迁移到 `<profile>/SynapsePro_Data/`；这也是测试必须复制代码并使用新 profile 的原因。设置、计划、AI secrets、游戏恢复 JSON 等位于 profile。笔记用 profile 内 SQLite；思维导图/网页还有 WebEngine 存储和恢复文件。游戏、截止日期、部分音乐和 AI 非密钥偏好进入 collection config，可能随 Anki 同步。主题可能生成插件目录内 CSS。修改持久化逻辑时必须同时考虑旧路径迁移、原子写入、恢复与同步边界。

首次引导完成会向 Supabase 发送选择的语言、分类、来源、主题和版本；设置窗口还会请求作者新闻横幅。AI、网页、SoundCloud 按功能连接对应服务。本阶段未提供密钥或触发引导完成上报。`analytics_config.py` 自带作者的 public anon key，为原版发布内容，不是用户凭据；保留原始代码，不在文档或输出重复其值。
