# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from pathlib import Path

import pytest

from aqt.builtin_features.desktop_tools.config import (
    PEN_DEFAULTS,
    pen_settings,
    tray_settings,
    validate_pen,
)
from aqt.builtin_features.storage import FeatureStorage, read_object, write_object


def test_partial_profile_keeps_existing_custom_colors() -> None:
    source = {"ts_pen1_color": "#abcdef", "unrelated": "keep"}
    result = pen_settings(source)
    assert result["ts_pen1_color"] == "#abcdef"
    assert result["ts_pen2_color"] == "#ff0000"
    assert source == {"ts_pen1_color": "#abcdef", "unrelated": "keep"}


@pytest.mark.parametrize(
    "key,value",
    [
        ("ts_pen1_color", "';alert(1)//"),
        ("ts_line_width", float("nan")),
        ("ts_line_width", 0),
        ("ts_location", 1.5),
        ("ts_small_width", -1),
        ("ts_state_on", "false"),
    ],
)
def test_invalid_legacy_settings_are_rejected(key: str, value: object) -> None:
    with pytest.raises(ValueError):
        validate_pen({**PEN_DEFAULTS, key: value})


def test_tray_migration_preserves_source_and_unknown_fields(tmp_path: Path) -> None:
    old = tmp_path / "addons21/85158043"
    write_object(old / "config.json", {"hide_on_startup": True, "extra": "keep"})
    write_object(old / "meta.json", {"config": {"debug": True}})
    storage = FeatureStorage(tmp_path)
    value = tray_settings(storage)
    assert value == {
        "enabled": False,
        "hide_on_startup": True,
        "debug": True,
        "extra": "keep",
    }
    assert read_object(old / "config.json") == {
        "hide_on_startup": True,
        "extra": "keep",
    }
    write_object(old / "config.json", {"hide_on_startup": False})
    assert tray_settings(storage) == value


def test_conflicting_legacy_copies_do_not_create_config(tmp_path: Path) -> None:
    for name, hidden in (("85158043", True), ("renamed", False)):
        old = tmp_path / "addons21" / name
        write_object(old / "manifest.json", {"package": "85158043"})
        write_object(old / "config.json", {"hide_on_startup": hidden})
    storage = FeatureStorage(tmp_path)
    with pytest.raises(ValueError):
        tray_settings(storage)
    assert not (storage.root / "minimize_to_tray.json").exists()


def test_corrupt_native_config_is_not_overwritten(tmp_path: Path) -> None:
    storage = FeatureStorage(tmp_path)
    path = storage.root / "minimize_to_tray.json"
    path.parent.mkdir(parents=True)
    path.write_text("broken", encoding="utf8")
    with pytest.raises(ValueError):
        tray_settings(storage)
    assert path.read_text() == "broken"
