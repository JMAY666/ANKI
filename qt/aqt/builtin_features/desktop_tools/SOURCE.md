# 固定来源与许可

2026-09-12 从 Anki 主程序使用的 AnkiWeb 下载接口获取实际代码包。未使用网页介绍推测实现。

## Minimize to Tray 2 0.2

- 原页面：https://ankiweb.net/shared/info/85158043
- 代码包更新时刻（服务器）：2025-11-16T19:38:52+00:00
- SHA-256：`498feb8b3f8d5b68e52b4beda08a243850bfc2bc11cd495da81fe2a03d72e7a8`
- 服务器兼容元数据：minpt=231000，maxpt=250705；不作为当前 Anki 兼容性证明。

## AnkiPenDown 1.1

- 原页面：https://ankiweb.net/shared/info/812527193
- 代码包更新时刻（服务器）：2025-09-10T00:12:39+00:00
- SHA-256：`f514b11d7a48f30dc9ca11ccec356d136e3f8dee7acb90f62ffa798452d8e47b`
- 服务器兼容元数据：minpt=0，maxpt=0；不作为当前 Anki 兼容性证明。

## 代码与依赖

- 托盘：源码头标注 0.2。原作者 Simone Gaiarin，GNU GPL v3 or later。保留显示窗口、关闭隐藏、启动隐藏、诊断及窗口快照能力；由主程序关闭流程直接调用，不替换主窗口方法、不改全局退出策略。仅依赖已有 Qt。
- 手写：源码 `__version__ = "1.1"`。原作者 Michal Krassowski、Rytis Petronis、Vijay；GPL v3 or later，完整许可见 LICENSE。renderer.py 提取原来的 HTML/CSS、绘画、压感、荧光笔、整笔擦除、撤销及重做实现；canvas.py 对其进行事件隔离、资源清理和本地化适配。仅使用内置 Qt WebEngine 与浏览器 Canvas API，无新增联网服务或 Python 依赖。
- 原始包与未修改源码保留在本地恢复基线 runtime/tray-pendown-20260912/sources/，不作为独立扩展加载。
- 托盘新版需验证 Anki 26.08.1 生命周期；手写原代码在设置后重新进入复习，当前适配改为局部更新画布。配置键、颜色值和用户卡片内容不翻译。
- 现有 Anki、SynapsePro 1.6.0-local、FSRS Helper 26.05.08、Pass/Fail 与六项复习工具保持原版本。
