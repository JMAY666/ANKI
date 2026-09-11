# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Chinese presentation labels; persisted add-on keys remain unchanged."""

import re

TEXT = {
    "Again": "重来",
    "Hard": "困难",
    "Good": "良好",
    "Easy": "简单",
    "Pass": "通过",
    "Fail": "失败",
    "Study Now": "开始学习",
    "Edit": "编辑",
    "Show Answer": "显示答案",
    "More": "更多",
    "Info": "信息",
    "Skip": "跳过",
    "Show Skipped": "恢复本次跳过",
    "Undo": "撤销",
    "Undo Review": "撤销评分",
    "Review Buttons": "评分按钮",
    "All Bottombar Buttons": "全部底栏按钮",
    "Text": "文字配色",
    "Background": "背景配色",
    "Wide text": "宽版文字配色",
    "Wide background": "宽版背景配色",
    "Neon 1": "霓虹样式一",
    "Neon 2": "霓虹样式二",
    "Fill 1": "填充样式一",
    "Fill 2": "填充样式二",
    "Default": "默认",
    "Coloured": "按评分着色",
    "Inside button": "显示在按钮内",
    "left": "左侧",
    "middle left": "中部左侧",
    "middle right": "中部右侧",
    "right": "右侧",
    "Created": "创建时间",
    "Edited": "修改时间",
    "First Review": "首次复习",
    "Latest Review": "最近复习",
    "Due": "到期时间",
    "FSRS Stability": "记忆稳定性",
    "FSRS Difficulty": "记忆难度",
    "FSRS Retrievability": "回忆概率",
    "Interval": "复习间隔",
    "Ease": "卡片易度",
    "Reviews": "复习次数",
    "Lapses": "遗忘次数",
    "Correct Percent": "正确率",
    "Fastest Review": "最快作答",
    "Slowest Review": "最慢作答",
    "Average Time": "平均耗时",
    "Total Time": "累计耗时",
    "Card Type": "卡片类型",
    "Note Type": "笔记类型",
    "Deck": "牌组",
    "Tags": "标签",
    "Note ID": "笔记编号",
    "Card ID": "卡片编号",
    "Sort Field": "排序字段",
    "Current Review Count": "本轮评分次数",
    "Font": "字体",
    "Auto Open": "复习时自动打开",
    "warning note": "显示记录截断提示",
    "theme": "显示主题",
    "Hide Current Card": "隐藏当前卡片信息",
    "Number of previous cards to show": "历史卡片数量（原值 2～4 显示 1～3 张）",
    "number of reviews to show for a card": "每张卡显示的复习记录数（0 为全部）",
    "Button Colors": "启用评分按钮样式",
    "Hide Easy if not in Learning": "非学习阶段隐藏简单按钮",
    "More Overview Stats": "附加牌组统计",
    "Skip Method": "跳过方式",
    "Active Button Indicator": "默认评分按钮提示",
    "Hover Effect": "悬停效果",
    "Buttons Style": "评分按钮样式",
    "Bottombar Buttons Style": "通用底栏按钮样式",
    "Custom Colors": "启用自定义配色",
    "Custom Review Button Text Color": "自定义评分按钮文字颜色",
    "Custom Active Indicator Color": "自定义默认按钮提示颜色",
    "Cursor Style": "鼠标指针样式",
    "Button Transition Time": "按钮动画时长（毫秒）",
    "Button Border Radius": "按钮圆角（像素）",
    "Wide Button Percent": "宽版按钮占比（百分比）",
    "Interval Style": "预计间隔显示方式",
    "Custom Button Sizes": "启用自定义按钮尺寸",
    "Text Size": "文字大小（像素）",
    "Font Weight": "字重（0 最细，8 最粗）",
    "General Text Color": "通用文字颜色",
    "Bottombar Button Text Color": "底栏按钮文字颜色",
    "Bottombar Button Border Color": "底栏按钮边框颜色",
    "Custom Bottombar Button Text Color": "自定义底栏文字颜色",
    "Custom Bottombar Button Border Color": "自定义底栏边框颜色",
    "Tooltip": "启用浮动评分提示",
    "Tooltip Height": "提示高度（像素）",
    "Tooltip Width": "提示宽度（像素）",
    "Tooltip Timer": "提示时长（毫秒）",
    "Tooltip Text Color": "提示文字颜色",
    "Tooltip Style": "提示位置模式",
    "Tooltip Position": "提示固定位置",
    "Tooltip Offset": "提示位置微调",
    "ShowAnswer Border Color Style": "显示答案按钮的边框配色方式",
    "language": "评分标签语言",
    "debug_always_show": "调试时持续显示标签",
    "hide_duration_ms": "标签显示时长（毫秒）",
    "custom_labels": "自定义评分标签",
    "colours": "浅色模式配色",
    "colours-dark": "深色模式配色",
    "fast_factor": "快速作答阈值（牌组中位耗时的倍数）",
    "lookback_days": "回看天数",
    "min_gap_hours": "两次复习的最小间隔（小时）",
    "max_rows": "最多显示卡片数",
    "preview_chars": "卡片预览字数",
    "loadDelayMs": "图表加载延迟（毫秒）",
    "autoMemorisedStats": "自动计算记忆状态图表",
    "autoRevlogStats": "自动计算复习记录图表",
    "barWidth": "图表宽度（像素）",
    "barHeight": "图表高度（像素）",
    "piePercentages": "饼图显示百分比",
    "warnings": "显示图表提示",
    "trends": "显示趋势线",
    "forceLang": "统计界面语言",
    "graphMode": "默认图表类型",
    "categories": "图表分类显示状态",
    "categoryOrder": "图表顺序（可拖动调整）",
    "alwaysAllTime": "扩展图表始终使用全部历史",
    "graphOrder": "图表排序",
    "about": "关于",
    "due": "到期情况",
    "misc": "综合统计",
    "interval": "间隔",
    "lapse": "遗忘",
    "repetition": "重复次数",
    "time": "耗时",
    "fsrs": "记忆状态",
    "rating": "评分",
    "load": "工作量",
    "introduced": "引入卡片",
    "timeMachine": "历史回溯",
    "forgettingCurve": "遗忘曲线",
    "bad": "评分习惯",
    "New": "新卡",
    "Learning": "学习中",
    "Review": "复习",
    "Suspended": "暂停",
    "Buried": "搁置",
    "Mature": "成熟卡片",
    "Young": "年轻卡片",
    "Young / learning": "年轻卡片与学习中",
    "Unseen": "未学习",
    "Suspended / buried": "暂停与搁置",
    "Total": "总计",
    "Learned": "已学习",
    "Unlearned": "未完成学习",
    "New today": "今天可学新卡",
    "Learning today": "今天可学学习卡",
    "Review today": "今天可学复习卡",
    "pace_graph": "速度图",
    "button_colours": "评分配色",
    "advanced_review": "高级复习栏",
    "search_stats": "扩展统计",
    "answer_feedback": "评分提示",
    "confident_wrong": "快速作答后遗忘分析",
}


def tr(text: str) -> str:
    return TEXT.get(text, text)


def caption(key: str) -> str:
    plain = re.sub(r"[_\s]+", " ", key).strip()
    if translated := TEXT.get(key) or TEXT.get(plain):
        return translated
    if plain.lower().startswith("card info sidebar "):
        return "卡片信息 · " + tr(plain[18:])
    if plain.startswith("Review "):
        return tr(plain[7:])
    if plain.startswith("Button Label "):
        return tr(plain[13:]) + "按钮文字"
    if plain.startswith("Button "):
        rest = plain[7:]
        for prefix, suffix in (
            ("Shortcut ", "快捷键"),
            ("Position ", "位置"),
            ("Width ", "宽度（像素）"),
            ("Height ", "高度（像素）"),
        ):
            if rest.startswith(prefix):
                return tr(rest[len(prefix) :].removesuffix(" Button")) + suffix
        if rest.startswith("Hide "):
            return "隐藏" + tr(rest[5:]) + "按钮"
        return tr(rest.removesuffix(" Button"))
    if plain.startswith("Color "):
        rest = plain[6:]
        return tr(rest.removesuffix(" on hover")) + (
            "悬停颜色" if rest.endswith(" on hover") else "颜色"
        )
    if match := re.fullmatch(r"ShowAnswer Ease([1-4])( Color)?", plain):
        return f"卡片易度阈值 {match[1]}" + (" 的颜色" if match[2] else "（百分比）")
    return plain
