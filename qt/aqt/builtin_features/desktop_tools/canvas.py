# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Mount upstream drawing tools without reloading or modifying the current card."""

import json
import re
from typing import Any

from anki import lang

from . import renderer
from .config import validate_pen

LABELS = {
    "Toggle visiblity (, comma)": "显示／隐藏笔迹（逗号）",
    "Pen 1": "画笔一",
    "Pen 2": "画笔二",
    "Highlighter": "荧光笔",
    "Eraser": "笔画橡皮",
    "Undo the last stroke (Alt + z)": "撤销笔画（Alt+Z）",
    "Redo the last stroke (Alt + Y)": "重做笔画（Alt+Y）",
    "Clean canvas (. dot)": "清空画布（句点，可撤销）",
    "Toggle fullscreen canvas(Alt + b)": "切换大／小画布（Alt+B）",
}


def mount_script(value: dict[str, Any], preserve: bool = True) -> str:
    validate_pen(value)
    for key, setting in value.items():
        setattr(renderer, key, setting)
    html = renderer.blackboard()
    markup, script = html.split("<script>", 1)
    script = script.rsplit("</script>", 1)[0]
    if lang.current_lang.startswith("zh"):
        for original, translated in LABELS.items():
            markup = markup.replace(original, translated)
    # No global functions, inline event handlers, body styles or unowned listeners.
    bindings: list[str] = []

    def bind(match: re.Match[str]) -> str:
        index = len(bindings)
        bindings.append(match[1])
        return f'data-pendown-action="{index}"'

    markup = re.sub(r'onclick="([^"]*)"', bind, markup)
    markup = markup.replace(":root {", "#pendown-root {")
    markup = markup.replace(
        "body {\n  overflow-x: hidden; /* Hide horizontal scrollbar */\n}", ""
    )
    markup = markup.replace(".nopointer", "#canvas_wrapper.nopointer")
    markup = markup.replace(".touch_disable", "#pencil_button_bar.touch_disable")
    markup = markup.replace(".color-button", ".pendown-color-button")
    markup = markup.replace('class="color-button', 'class="pendown-color-button')
    script = script.replace("'color-button'", "'pendown-color-button'")
    script = script.replace("document.getElementById(", "root.querySelector('#' + ")
    script = script.replace(
        "document.getElementsByClassName('pendown-color-button')",
        "root.getElementsByClassName('pendown-color-button')",
    )
    script = script.replace(
        "document.documentElement.style.setProperty", "root.style.setProperty"
    )
    script = script.replace(
        "getComputedStyle(document.documentElement)", "getComputedStyle(root)"
    )
    script = script.replace("canvas_wrapper.style", "wrapper.style")
    script = script.replace("event.preventDefault();", "e.preventDefault();")
    script = script.replace(
        "var line_width = 4;", f"var line_width = {json.dumps(value['ts_line_width'])};"
    )
    script = script.replace(
        "window.requestAnimationFrame(draw_last_line_segment);",
        "frame = requestAnimationFrame(draw_last_line_segment);",
    )
    script = script.replace(
        "function draw_last_line_segment() {",
        "function draw_last_line_segment() {\n    if (disposed) return;",
    )
    script = script.replace("window.setTimeout(resize, 100)", "return")
    for call in (
        'pen_canvas.addEventListener("pointerdown", pointerDownLine)',
        'pen_canvas.addEventListener("pointermove", pointerMoveLine)',
        'window.addEventListener("pointerup", pointerUpLine)',
        "window.addEventListener('resize', resize)",
        "window.addEventListener('load', resize)",
    ):
        script = script.replace(call, call[:-1] + ", {signal: events.signal})")
    script = script.replace(
        "document.addEventListener('keyup', function(e) {",
        "document.addEventListener('keyup', function(e) {\n    if (!root.isConnected || root.hidden || e.isComposing || e.defaultPrevented || e.ctrlKey || e.metaKey || e.target.closest('input,textarea,select,[contenteditable=true]')) return;",
    )
    # The final listener belongs to this canvas and is aborted on every unmount.
    script = script.rstrip().removesuffix("})") + "}, {signal: events.signal});\n"
    # Non-pen clicks and cancelled pointer streams must not leave drawing active.
    script = script.replace(
        "wrapper.classList.add('nopointer');",
        "if (e.button !== 0) return;\n    wrapper.classList.add('nopointer');",
    )
    extra_css = """
    #pendown-root {position:absolute; inset:0; pointer-events:none;}
    #pendown-root canvas, #pencil_button_bar {pointer-events:auto;}
    #pencil_button_bar {max-width:calc(100vw - 8px); max-height:calc(100vh - 8px); overflow:auto; flex-wrap:wrap;}
    #pencil_button_bar button {flex-shrink:0;}
    """
    bind_script = "\n".join(
        f"root.querySelector('[data-pendown-action=\"{index}\"]').addEventListener('click', function(){{ {body} }}, {{signal: events.signal}});"
        for index, body in enumerate(bindings)
    )
    return f"""(() => {{
    const previous = window.ankiPenDown?.snapshot();
    window.ankiPenDown?.dispose();
    const root = document.createElement('div'); root.id = 'pendown-root';
    root.innerHTML = {json.dumps(markup + "<style>" + extra_css + "</style>")};
    document.body.append(root);
    let disposed = false, frame = 0;
    const events = new AbortController();
    {script}
    {bind_script}
    window.addEventListener('pointercancel', () => {{stop_drawing(); wrapper.classList.remove('nopointer');}}, {{signal:events.signal}});
    const observer = new ResizeObserver(() => {{if (!disposed) resize();}});
    observer.observe(document.documentElement);
    window.ankiPenDown = {{
      snapshot: () => ({{strokes:strokes_data, redo:redo_stack, visible}}),
      clear: () => {{strokes_data=[]; redo_stack=[]; nextLine=0; nextPoint=0; stop_drawing(); resize();}},
      resize, undo:ts_undo, redo:ts_redo,
      dispose: () => {{disposed=true; cancelAnimationFrame(frame); events.abort(); observer.disconnect(); root.remove(); delete window.ankiPenDown;}},
    }};
    if ({str(preserve).lower()} && previous) {{
      strokes_data=previous.strokes; redo_stack=previous.redo;
      if (!previous.visible) switch_visibility();
    }}
    for (const button of root.querySelectorAll('button')) button.setAttribute('aria-label', button.title);
    resize();
    }})()"""
