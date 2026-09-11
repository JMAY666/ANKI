# Pass/Fail 2 内置集成

## 版本与原代码确认

实际获取并检查了 [AnkiWeb 876946123](https://ankiweb.net/shared/info/876946123) 的代码包，包内版本为 **0.3.0**，服务端更新时间为 2024-06-04。旧包声明的兼容区间不能直接证明适配 Anki 26.8.1；本次使用当前复习事件接口完成源码适配。完整来源、哈希和作者许可记录在 [SOURCE.md](../qt/aqt/builtin_features/passfail2/SOURCE.md)。

原代码的切换功能只有「启用自定义按钮名称和文字颜色」：关闭时显示 Fail／Pass，开启后使用保存的两个名称和文字颜色；支持颜色选择、刷新预览、保存和取消。名称沿用原代码的少于 15 字符限制，颜色为 `#RRGGBB`。原帮助段落提及第二个复选框，但实际代码没有背景色或二档／四档开关。本次未据此虚构原功能。

## 使用与切换

- 在牌组页面的中间区域点击卡片入口或「开始学习」，直接进入当前牌组的原生复习。
- 复习栏提供「原生四档评分／Pass-Fail 两档评分」，可以反复切换。切换只重新绘制评分控件，保留当前卡片、正反面、计时和原生排程状态。
- 工具 → **复习按钮 · Pass/Fail 2…** 同时提供模式选择及全部原有自定义功能。名称与颜色只有保存后才写入，取消不写入。
- 原生四档默认用 1／2／3／4 提交重来、困难、良好、简单，可在首选项中配置无冲突的评分键。两档固定用 1 提交失败、2 提交通过，3／4 不评分；通过在调度器中仍为原生默认评分（当前 Anki 为良好），不会改为“困难”。两种模式的空格／Enter 都只在正面显示答案，答案面不评分。按钮提示显示实际生效的按键，详见 [复习快捷键](REVIEW-SHORTCUTS.md)。
- 新配置默认使用原生四档，用户自行开启两档；迁入旧插件时保留原启用／停用状态。
- 「自定义」开关关闭时保留已保存的名称和颜色，再开启即可恢复。模式和保存的开关均在重启后保留，设置作用于同一本机 Anki 数据根目录内的所有账户，与原插件一致。

两档改变的是用户提交的评分选项，不重写 FSRS 算法、旧评分、牌组、媒体或卡片状态。用户实际提交的评分仍由 Anki 正常记录和排程；原生撤销保持可用。

## 与已有功能共存

入口通过 Anki 初始化内置模块注册一次。识别并拦截旧 `876946123`、`PassFail2` 以及 manifest package 为这些标识的副本，防止重复评分映射。保留 SynapsePro 1.6.0-local 的 DeepSeek、三栏卡片浏览、主题与已确认的移除；FSRS Helper 保持 26.05.08。

导航统一为「统计」，复习不经过报告。统计、分析报告与记录可单独查看；牌组选项在统计的牌组树选择旁，对应当前所选 ID，明确显示共享预设的牌组数量和完整路径提示。牌组三栏及左侧创建／获取、顶部导入使用同一软件中的原生操作。

## 配置与恢复

内置配置保存到 Anki 数据根目录的 `builtin_features/passfail2.json`。首次优先读取旧插件的 `config.json` 与 `meta.json.config`，后者优先，未知字段保留；目标已存在时不重复迁入或覆盖。损坏配置会报错，不用默认值覆盖。旧插件文件和元数据不修改、不删除。

本次修改前的源码压缩包和完整程序位于 Git 排除的 `runtime/integration-20260911/`，其中 `source-before.zip` 对应提交 `de285a28b5e207069535faf718b6bf46984f46a1`，`program-before/` 为旧实际使用版本。正式替换前正常关闭软件，并在该目录下完整备份 `Anki2/`，逐文件校验。程序仍运行于 `dist/Anki-learning-workspace-26.8.1/`；测试数据位于标记为合成数据的 `runtime/navigation-*` 和 `runtime/learning-*`，不写正式牌组或学习记录。

恢复时正常关闭软件，用保存的旧程序恢复原运行目录即可回到旧功能。原数据目录保持原样；若只想停用两档，选择原生四档即可。若要重新迁入旧插件配置，先备份当前 `builtin_features/passfail2.json` 再移走该文件；旧元数据保持可用。程序恢复不撤销期间已完成的真实复习。

## 验证命令

```powershell
just navigation-check
just navigation-test
just navigation-smoke navigation-test-001
just navigation-smoke navigation-test-001 restart
just navigation-smoke navigation-test-001 restart-native
just learning-smoke learning-test-001
just learning-smoke learning-test-001 restart
just builtin-test
just check
```

验收使用同一 Anki 实例加载三个内置模块，所有牌组、评分和配置均为合成数据；API 不使用真实密钥。软件包组装与实际入口沿用 `dist/Anki-learning-workspace-26.8.1/Anki.exe`，不另行交付插件或测试软件。最终执行结果见 [本次交付记录](NAVIGATION-PASSFAIL2-DELIVERY-2026-09-11.md)。
