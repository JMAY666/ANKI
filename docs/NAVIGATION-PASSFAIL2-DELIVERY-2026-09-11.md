# 统计导航、牌组三栏与 Pass/Fail 2 交付记录

## 实际运行版本

已更新并重新启动原运行目录中的 `dist/Anki-learning-workspace-26.8.1/Anki.exe`。实际账户的启动诊断确认：集合已打开、三个内置模块就绪、SynapsePro 和 FSRS Helper 菜单各一份、旧插件模块未加载。Pass/Fail 2 的代码来自此运行目录中的 `app_packages/aqt/builtin_features/passfail2/`。没有更换用户的数据目录。

软件仍为 Anki 26.08.1，内置 SynapsePro 1.6.0-local、FSRS Helper 26.05.08 和 Pass/Fail 2 0.3.0。`INTEGRATED-BUILD.json` 记录了组件来源及两个 wheel 的 SHA-256。

## 已完成的行为

- 顶部统一为「统计」，不再重复显示「学习」；统计页仅保留概览、AI 建议和记录。查看报告不启动复习。
- 牌组页为左侧目录、中间当前牌组、右侧辅助信息。原有全账户面板明确标记为全部牌组，不改变旧统计公式。普通和简洁仪表盘、窄窗和深色主题均保留。
- 卡片入口与开始学习直接进入所选牌组的原生队列，保留子牌组范围、到期时间、每日限额、暂停和搁置规则。没有可学习内容时明确提示；结束后返回原选中牌组。
- 统计中的牌组树选择支持搜索、折叠、展开、完整路径区分同名牌组和限定高度滚动。附近的牌组选项按实际选中 ID 打开，显示共享预设影响范围；新建牌组后复习中打开统计也保留该牌组范围。小齿轮其他操作保留。
- 创建／获取在左栏；顶部导入可实际完成文件导入，底部重复入口移除。
- 复习栏可切换原生四档／Pass-Fail 两档；工具 → 复习按钮 · Pass/Fail 2 保留原名称、文字颜色开关、颜色选择、预览、保存和取消。模式切换不重置当前卡片或排程状态。
- 原包没有二档／四档切换，本次补上；原包实际存在的自定义总开关完整保留。新配置默认保留四档；旧插件配置按启用状态迁入，改名但保留原 manifest 的副本也能识别。

## 实际验证

| 检查 | 结果 |
| --- | --- |
| `just check` | 通过：Rust 629、Python 库 153、Qt 117、前端 61；Svelte 0 错误／0 警告，相关类型、格式及 lint 通过 |
| `just navigation-check` | 相关 16 个源码文件类型检查与 Ruff 通过 |
| `just builtin-test` | 45 项通过，包含安装与恢复、已有内置功能及新增回归 |
| `just navigation-test` | 最终 10 项通过；含真实鼠标展开箭头测试，确认不会误选牌组或关闭弹层 |
| 最终软件包：导航与 Pass/Fail | 31 项通过，涵盖直接复习、限额／空牌组、树选择、设置对象、反复切换、按键和按钮评分、撤销、创建／获取以及顶部实际导入合成文件 |
| 最终软件包：两次重启 | 7 项及 9 项通过；验证四档／两档、自定义开关两种状态的保存，以及普通辅助面板和深色主题 |
| 原统计／AI／复习流程 | 17 项及重启 7 项通过；模拟 API 的确认应用与撤销、实际统计口径、图表、模板、媒体、隐藏复习保护和会话记录 |
| SynapsePro 与 FSRS Helper 联合回归 | 33 项及重启 18 项通过；包括 DeepSeek 页面、原生／三栏卡片浏览切换、Target R、排程与复习 |
| `Anki.exe` | 软件包使用合成账户正常启动并退出 0；更新后原路径的真实使用实例再次确认三个模块就绪 |

完整检查使用 [已有 Windows 检查配置](local-startup-validation.md)：`PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`、指定 Briefcase 缓存，以及项目提供的本地贡献者名单白名单入口。首次裸环境检查遇到格式、贡献者登记和编码问题，修复格式并采用文档环境后通过。旧安装恢复测试最初被正在运行的 Anki 保护检查阻止，正常关闭应用后已通过。

所有评分／导入／迁移验收只操作合成账户；未给正式牌组批量改分、改调度、导入或删除。真实 DeepSeek 付费调用、多设备同步和长期学习效果未验证。本次仍有原项目的非阻断 Qt/GPU 回退、旧 Qt API 和 Sass 提示。

## 备份与恢复

恢复目录为 `runtime/integration-20260911/`，受 Git 排除规则保护：

- `source-before.zip`：修改前源码，提交 `de285a28b5e207069535faf718b6bf46984f46a1`。
- `program-before/`：修改前完整程序，4,909 个文件。
- `Anki2/`：正常关闭软件后复制的完整用户数据，共 12,946 个文件，全部与源文件逐一核对 SHA-256。
- `sha256-manifest.json`：源码、程序与用户数据的校验记录。
- `installation.json`：实际安装、前一程序及恢复位置；安装器保留替换时的原程序。
- `startup-diagnostics-updated.json`：实际使用版本启动确认，不含密钥或卡片内容。

恢复原程序并保留更新后产生的学习记录：

```powershell
pwsh -NoProfile -File .\scripts\restore_builtin.ps1 -BackupPath .\runtime\integration-20260911
```

运行恢复前先正常关闭 Anki。只有明确需要回到备份时刻的整份用户数据时才使用原脚本的 `-RestoreUserData`；它会另存当前数据。单纯关闭 Pass/Fail 两档无需恢复程序，在复习栏选择原生四档即可。

## 证据与版本管理

详细日志和截图位于 `out/navigation-*.log`、`runtime/navigation-final-acceptance/`、`runtime/learning-package-navigation/`、`runtime/builtin-package-navigation/`。测试快照、源码来源原始包、完整软件和所有个人备份均未纳入 Git；排除规则无需改变。仅提交相关源码、测试、构建配方、许可和使用文档。
