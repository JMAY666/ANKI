"""Verify persisted browsing preferences in a second Anki process."""

import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ("qt", "pylib", "out/qt", "out/pylib")]
name = sys.argv[1]
assert name and Path(name).name == name and name not in (".", "..", "backups")
BASE = (ROOT / "runtime" / name).resolve()
assert BASE.is_relative_to(ROOT / "runtime")
previous = json.loads((BASE / "browser-result.json").read_text(encoding="utf-8"))
assert previous["passed"], "Only reopen a verified synthetic fixture"
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "synapse-browser-restart-" + name
audio_bin = ROOT / "out" / "extracted" / "mpv"
if (audio_bin / "mpv.exe").exists():
    os.environ["PATH"] = str(audio_bin) + os.pathsep + os.environ.get("PATH", "")

import aqt
from anki.collection import Config
from aqt.qt import QApplication, QTimer

app = aqt._run(
    ["anki", "-b", str(BASE), "-p", "SynapsePro-Test", "-l", "zh_CN"], exec=False
)
mw = aqt.mw
results = {"checks": {}, "errors": []}
finished = False
deadline = time.monotonic() + 30
browser = None


def finish(error=None):
    global finished
    if finished:
        return
    finished = True
    if error:
        results["errors"].append(str(error))
    results["passed"] = (
        bool(results["checks"])
        and all(results["checks"].values())
        and not results["errors"]
    )
    (BASE / "browser-restart-result.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)
    mw.unloadProfileAndExit()


def check(name, value):
    results["checks"][name] = bool(value)
    assert value, name


def poll():
    global browser
    if finished:
        return
    try:
        for widget in QApplication.topLevelWidgets():
            if widget.__class__.__name__ == "OnboardingDialog":
                widget.reject()
        if time.monotonic() > deadline:
            raise TimeoutError("restarting card browser")
        if mw.col is None:
            QTimer.singleShot(50, poll)
            return
        if browser is None:
            results["original_notes_mode"] = mw.col.get_config_bool(
                Config.Bool.BROWSER_TABLE_SHOW_NOTES_MODE
            )
            results["original_revlog"] = mw.col.db.scalar("select count(*) from revlog")
            browser = aqt.dialogs.open("Browser", mw)
        workspace = browser._synapse_workspace
        if (
            not workspace.enabled
            or workspace.loading
            or workspace.inflight
            or workspace.saving_scope
        ):
            QTimer.singleShot(50, poll)
            return
        check("profile_isolated", Path(mw.pm.base).resolve() == BASE)
        check("mode_persisted_across_processes", workspace.enabled)
        check(
            "widths_persisted_across_processes",
            workspace.prefs["widths"] == previous["saved_widths"],
        )
        check("card_mode", not browser.table.is_notes_mode())
        check("collection_data_persisted", browser.table.len() == 3)
        check(
            "no_review_added",
            mw.col.db.scalar("select count(*) from revlog")
            == results["original_revlog"],
        )
        browser.close()
        QTimer.singleShot(50, closed)
    except Exception:
        finish(traceback.format_exc())


def closed():
    if finished:
        return
    try:
        if not browser._closeEventHasCleanedUp:
            if time.monotonic() > deadline:
                raise TimeoutError("closing restarted browser")
            QTimer.singleShot(50, closed)
            return
        check(
            "native_notes_mode_preserved",
            mw.col.get_config_bool(Config.Bool.BROWSER_TABLE_SHOW_NOTES_MODE)
            == results["original_notes_mode"],
        )
        finish()
    except Exception:
        finish(traceback.format_exc())


sys.excepthook = lambda kind, value, tb: finish(
    "".join(traceback.format_exception(kind, value, tb))
)
QTimer.singleShot(100, poll)
app.exec()
raise SystemExit(0 if results.get("passed") else 1)
