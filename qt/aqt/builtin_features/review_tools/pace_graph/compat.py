# Source integration: Ankitects Pty Ltd and contributors
"""Small Qt 5/6 and saved-configuration adapters; no OS dependencies."""
import math
import re


def local_position(event):
    return event.position() if hasattr(event, 'position') else event.localPos()


def global_position(event):
    return event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()


def execute_menu(menu, point):
    method = getattr(menu, 'exec', None) or menu.exec_
    return method(point)


def normalize_config(raw):
    raw = raw if isinstance(raw, dict) else {}
    result = dict(raw)
    for key, default, low, high in [
        ('goal', 10., 1, 300), ('window', 20, 5, 100), ('refresh', 1, 1, 10),
        ('transition', 4., .5, 15), ('background', 20, 0, 100),
        ('foreground', 65, 0, 100), ('graph_opacity', 55, 0, 100), ('number_size', 20, 16, 28),
        ('history_seconds', 60, 15, 120),
    ]:
        try:
            value = float(raw.get(key, default))
            result[key] = max(low, min(high, value)) if math.isfinite(value) else default
        except (TypeError, ValueError, OverflowError):
            result[key] = default
    for key in ('window', 'refresh', 'number_size', 'history_seconds'):
        result[key] = int(result[key])
    for key, choices, default in [
        ('view', ('minimal', 'compact', 'full'), 'minimal'),
        ('controls', ('hover', 'always', 'hidden'), 'hover'),
        ('palette', ('muted', 'bright', 'mono', 'custom'), 'muted'),
        ('theme', ('auto', 'light', 'dark'), 'auto'),
    ]:
        value = raw.get(key)
        result[key] = value if isinstance(value, str) and value in choices else default
    for key, default in [('window_shadow', False), ('locked', False), ('details', True), ('endpoint', True), ('goal_line', True)]:
        value = raw.get(key, default)
        result[key] = value if isinstance(value, bool) else default
    for key in ('position', 'size', 'compact_size', 'minimal_size'):
        value = raw.get(key)
        if not (isinstance(value, list) and len(value) == 2 and
                all(type(v) is int and abs(v) < 1000000 for v in value)):
            result.pop(key, None)
    for key, default in [('custom_ahead', '#21877b'), ('custom_behind', '#b16d32'), ('custom_text', '#34454d'), ('custom_background', '#f1f4f5')]:
        value = raw.get(key, default)
        result[key] = value if isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value) else default
    return result
