# 截图向 AI 提问

## 使用

1. 在单栏或双栏复习底部点击「截图提问」。拖动框选 Anki 窗口内的区域；Esc 或右键取消。
2. 在预览窗口输入问题，点击「发送」。右侧 AI 对话栏会自动展开，显示图片、问题及回复。只发送图片也可以，程序会附上「请解释这张图片」。
3. 在预览窗口点击「默认 AI…」可以把截图及文字转入右侧草稿并打开设置。保存服务商、模型及自己的 API Key 后再发送。

右侧聊天输入框下方也有「添加图片」「截图提问」「默认 AI…」。支持选择 PNG、JPEG、WebP，以及在输入框内粘贴图片。缩略图的 × 可删除附件。中文输入法组合文字时，Enter 不会误发送；Shift+Enter 换行。

普通提问和截图提问共用保存的默认服务商与模型。各服务商的自定义模型分别记忆，旧的已选服务商及 API Key 保留。模型是否支持图片由实际服务商决定；可选自定义模型，接口拒绝时显示错误并保留重试所需内容。DeepSeek 已知文字模型会在发送前提示改选识图模型。

## 图片与聊天

- 每条问题最多 4 张图片；单个导入文件不超过 20 MiB、4000 万像素。超大或损坏文件会拒绝，动态图片不支持。
- 图片长边最多保留 2048 像素；优先 PNG，较大附件改用 JPEG，单张编码前数据上限为 2 MiB。原文件不改动，不复制图片元数据。
- 图片和问题通过同一次请求发送。后续追问可使用最近的图文上下文；请求历史有单独的文字及图片大小上限，超出时移除较早的对话。
- 截图和聊天仅驻留内存，不写入牌组媒体或聊天文件。取消框选不发送，清空聊天或关闭账户释放图片和上下文。截图预览点击取消会丢弃本次新截图，已有聊天草稿保留。
- 普通输入框发送失败后，原文字及附件继续留在输入框中。底栏截图发送失败会在该条消息旁保留「重试」，已有聊天草稿不受影响。
- 评分、撤销、卡片调度及同步契约保持原样。截图按钮位于原底栏，不给卡片左右另加占位。

## 接口依据

2026-09-15 核对官方接口：

- [DeepSeek 图像理解](https://api-docs.deepseek.com/guides/vision/)：`deepseek-flash` 接受文字与 `image_url` 图片块；同一结构用于现有 OpenAI 兼容路由。
- [Gemini 图像理解](https://ai.google.dev/gemini-api/docs/image-understanding)：图片转为 `inlineData`。
- [Claude 图像输入](https://platform.claude.com/docs/en/build-with-claude/vision)：图片转为带 `media_type` 的 base64 `image` 块。
- [Ollama Vision](https://docs.ollama.com/capabilities/vision)：图片放入消息的 base64 `images` 数组；需使用支持图片的本地模型。

## 验证

通过项目配方运行：

```text
just ai-images-test
just ai-images-smoke <新的合成测试名>
just ai-images-native-smoke <新的合成测试名>
just check
```

单元测试验证七种路由的实际请求体、图片像素、错误与取消、默认模型兼容和不同缩放比例下的裁剪。WebEngine 集成测试使用独立合成账户验证完整入口、预览、删除、粘贴、失败重试、侧栏重建、双栏入口、窄窗及调度不变；网络服务在边界替换为合成回复。离屏测试替换窗口截图来源；Windows 原生测试使用真实窗口截图。所有记录仅在忽略的 `runtime/` 中。

真实云服务的识图回答质量、账户额度与网络状态需要使用用户自己的服务验证，自动化测试不调用个人 API Key。

### 2026-09-15 验证与交付记录

- `just ai-images-test`：27 项图片回归测试及 7 项原有 AI／兼容测试通过；包含四类流式错误事件的失败保留及长对话裁剪回归。
- 打包后的 Windows 原生界面检查 19 项通过；验证实际截图像素、高级底栏、双栏、窄窗、失败重试及已有草稿保留。当前使用目录更新后，19 项原生及 19 项离屏集成检查通过。
- `just builtin-package` 成功，完整便携包位于 `dist/Anki-ai-images-26.8.1/`。7 个功能文件已更新到原使用目录 `dist/Anki-dual-review-26.8.1/`，逐文件 SHA-256 一致；重启 Anki 生效。
- 原文件与校验清单位于 `runtime/ai-images-delivery-20260915/`。回退时先退出 Anki，按 `delivery.json` 恢复 `program-before` 中的文件，并移除清单中 `before` 为 null 的本次新增文件；无需恢复学习数据库。程序、备份、合成账户和测试截图继续由现有排除规则留在本机。
- 完整 `just check` 初次停在贡献者登记；随后使用项目已有的 `CONTRIBUTORS_BYPASS_EMAILS` 本地作者参数继续检查。Rust 639、Python 库 153、前端 78、Qt 220 项测试通过，mypy 与 Svelte 检查通过。唯一失败测试为 `test_installer.py::test_build_and_package`：Briefcase 无法解包本机 WiX MSI，退出码 200。最后一轮还记录了音频测试收尾时主窗口为空的异步回调异常。完整检查不能记为全绿；功能验证及便携包交付已单独通过。

详细记录：`runtime/ai-images-unit-final.log`、`runtime/ai-images-check-complete.log`、`runtime/ai-images-package-20260915-final/results.json`、`runtime/ai-images-installed-20260915-verified/results.json`、`runtime/ai-images-installed-20260915-complete/results.json`。
