"""Exercise the real SoundCloud iframe in an existing synthetic profile only."""

import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ("qt", "pylib", "out/qt", "out/pylib")]
name = sys.argv[1]
assert Path(name).name == name and name not in (".", "..")
BASE = ROOT / "runtime" / name
assert (BASE / ".builtin-test").read_text() == "synthetic data only"
os.environ.pop("ANKIDEV", None)
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "experience-sc-" + name
report = {"checks": {}, "errors": []}


def wait(predicate, seconds=25):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.02)
    raise TimeoutError(
        "SoundCloud live widget did not reach the requested state within the timeout"
    )


def js(code):
    output = []
    player.sc_view.page().runJavaScript(code, output.append)
    wait(lambda: bool(output), 5)
    return output[0]


try:
    import aqt

    app = aqt._run(
        ["anki", "-b", str(BASE), "-p", "Experience", "--safemode", "-l", "zh_CN"],
        exec=False,
    )
    mw = aqt.mw
    wait(lambda: mw.col and mw.state == "deckBrowser")
    from aqt.builtin_features.synapsepro.background_music import _ensure_window
    from aqt.builtin_features.synapsepro.quick_switches import save_setting

    player = _ensure_window()
    player.show()
    player._set_mode("soundcloud")
    wait(lambda: js("!!window._widgetReady"))
    js("widget.getSounds(s=>window.liveSounds=s);")
    wait(lambda: js("window.liveSounds && liveSounds.length > 1"))
    from PyQt6.QtTest import QTest

    from aqt.qt import QPoint, Qt

    QTest.mouseClick(
        player.sc_view.focusProxy(), Qt.MouseButton.LeftButton, pos=QPoint(32, 38)
    )
    wait(lambda: js("window._scStatus?.playing"))
    report["tracks"] = js("liveSounds.length")
    for loop in (True, False):
        save_setting("soundcloud_playlist_loop", loop)
        js("widget.skip(liveSounds.length-1);scPlay();")
        wait(lambda: js("window._scStatus?.playing"))
        js("window.liveDuration=0;")

        def duration_ready():
            js("widget.getDuration(d=>window.liveDuration=d);")
            return js("window.liveDuration > 0")

        wait(duration_ready)
        js("widget.seekTo(Math.max(0,liveDuration-1500));")

        def terminal():
            js("widget.getCurrentSoundIndex(i=>window.liveIndex=i);")
            return js(
                "liveIndex===0 && _scStatus.playing"
                if loop
                else "liveIndex===liveSounds.length-1 && !_scStatus.playing"
            )

        wait(terminal, 15)
        report["checks"][
            "loop returns to first" if loop else "loop off stops at last"
        ] = True
        js("scPause();")
    save_setting("soundcloud_playlist_loop", True)
except BaseException:
    report["errors"].append(traceback.format_exc())
    if "player" in globals() and player:
        report["status"] = js("JSON.stringify(window._scStatus || {})")
        player.grab().save(str(BASE / "soundcloud-live.png"))
finally:
    (BASE / "soundcloud-live.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)
    os._exit(0 if len(report["checks"]) == 2 else 1)
