# 事件循环冒烟测试 — 2026-09-11 补测

上一阶段仅做导入探针，不足以代表功能冒烟测试。本次运行真实 Anki 25.09.4 / PyQt6 6.11.0 / Qt 6.11.2、Windows Qt 平台和完整事件循环，使用 `runtime/smoke-eventloop/` 合成 profile。通过应用自身 Python 接口和 WebEngine DOM 回调断言，不依赖原生桌面自动点击，也不等同于人工视觉验收。

## 最终结果

写入/功能阶段 **27 项通过、3 项失败，退出码 1**。3 项失败属于同一个功能：思维导图首次页面加载、重新打开加载和 DOM 渲染。真实 profile 初始化、引导页面 DOM 渲染并取消、主界面牌组 DOM、侧栏开关/恢复、数据管理器初始化、番茄钟真实 QTimer tick/暂停/重置、笔记/待办持久化 API 读写、笔记 WebView 加载/DOM/关闭时保存、合成卡问答与复习日志写入均通过。

独立重启阶段 **15 项全部通过，退出码 0**，再次验证初始化、引导取消、主界面，以及上一次进程写入的笔记、待办和复习日志仍存在。笔记和待办的持久化操作使用插件存储接口；本次没有声称验证了键盘输入、所有编辑器按钮或思维导图编辑保存。

思维导图失败的观测状态：dock `visible=true`，panel `initialized=false`、`ready=false`，`web_view=None`，没有页面 URL。关闭后等待再打开仍未加载。此项在当前测试组合中可复现；根因尚未确认，不能直接推断所有官方 Anki 安装环境都会失败。本阶段依照只接手、不改行为的边界保留原版代码，没有修复或绕过该功能。

## 调试过程与限制

- 初始 offscreen 模式遇到 GPU context 错误，最终改用普通 Windows Qt 平台。
- 首版测试脚本读取引导 DOM 过早，且异步回调错误捕获循环变量；随后修正等待与绑定，最终引导页面渲染通过。不能将这些测试脚本错误当作插件缺陷。
- 引导始终调用 reject/cancel，没有接受条款、设置 onboarding_completed 或发送完成统计；没有注入假的成功标记、替换插件函数或改插件源码。
- 未测试云 AI、音乐服务、PDF 制卡、完整计划操作、思维导图保存、XP 数值正确性或全套主题外观。游戏管理器初始化不等于 XP 算法验证。
- 只有合成测试数据，无同步密钥，autoSync 关闭；未操作正式 Anki 数据。测试最终调用 Anki 的卸载 profile 和退出流程，不强制终止正式 Anki 进程。

## 复现

```powershell
# 当前 profile 已存在，首次重建时才执行；脚本拒绝覆盖已有目录
./.venv/Scripts/python.exe scripts/prepare.py smoke-eventloop

./.venv/Scripts/python.exe scripts/smoke_test.py write
./.venv/Scripts/python.exe scripts/smoke_test.py restart
```

write 可重复运行，会新增合成复习卡并作答。当前失败必须保持非零退出码，不能把 mindmap 失败转成忽略。原始日志位于 `runtime/smoke-eventloop/write.log`、`restart.log`；最终 JSON 证据另存于 `docs/smoke-write.json`、`docs/smoke-restart.json`。
