"""Real Qt/Anki event-loop smoke test, exclusively against a synthetic profile.

Rejects onboarding (never accepts terms); no production code or completion
flags are patched. Uses application APIs, not native desktop automation.
"""
from pathlib import Path
import importlib
import json
import os
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "runtime" / "smoke-eventloop"
MODE = sys.argv[1] if len(sys.argv) > 1 else "write"
assert MODE in ("write", "restart")
assert (BASE / "prefs21.db").exists()
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "synapsepro-smoke-eventloop"
os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["PYTHONUTF8"] = "1"
import aqt
from aqt.qt import QTimer, QApplication

results = {"mode": MODE, "checks": {}, "errors": [], "onboarding_accepted": False}
done = False
started = time.monotonic()
app = aqt._run(["anki", "-b", str(BASE), "-p", "SynapsePro-Test", "-l", "en_US"], exec=False)
mw = aqt.mw
addon = importlib.import_module("236979321")
nb = importlib.import_module("236979321.notebook_sidebar")
pomo = importlib.import_module("236979321.pomodoro")
mm = importlib.import_module("236979321.mindmap_sidebar")
NOTE = [{"id": "smoke-note", "title": "Synthetic smoke note", "content": "<p>Smoke persistence 2+2=4</p>"}]
TODO = [{"id": "smoke-todo", "text": "Synthetic task", "completed": False}]

def check(name, condition):
    results["checks"][name] = bool(condition)
    print(f"SMOKE {name}: {bool(condition)}", flush=True)
    if not condition:
        raise AssertionError(name)

def finish(error=None):
    global done
    if done:
        return
    done = True
    if error:
        results["errors"].append(str(error))
    results["elapsed_seconds"] = round(time.monotonic() - started, 2)
    results["passed"] = bool(results["checks"]) and all(results["checks"].values()) and not results["errors"]
    (BASE / f"result-{MODE}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2), flush=True)
    mw.unloadProfileAndExit()

def guard(fn):
    def run(*args):
        if done:
            return
        try:
            fn(*args)
        except Exception:
            finish(traceback.format_exc())
    return run

def later(ms, fn):
    QTimer.singleShot(ms, guard(fn))

def wait_for(name, predicate, fn, attempts=100):
    if predicate():
        check(name, True)
        fn()
    elif attempts:
        later(100, lambda: wait_for(name, predicate, fn, attempts-1))
    else:
        check(name, False)

def reject_onboarding():
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, addon.onboarding_dialog.OnboardingWizard) and widget.isVisible():
            if not getattr(widget, "_smoke_observed", False):
                widget._smoke_observed = True
                if not hasattr(widget, "_smoke_started"):
                    widget._smoke_started = time.monotonic()
                widget.view.page().runJavaScript("document.body.innerText.length", guard(lambda n, w=widget: onboarding_ready(w, n)))

def onboarding_ready(widget, size):
    results["onboarding_dom_length"] = size
    if not isinstance(size, (int, float)) or size <= 20:
        if time.monotonic() - widget._smoke_started > 3:
            results["checks"]["onboarding_webview_rendered"] = False
            results["onboarding_diagnostics"] = {"url": widget.view.url().toString(), "body_length": size}
            widget.reject()
            results["onboarding_dismissed"] = True
            return
        widget._smoke_observed = False
        return
    check("onboarding_webview_rendered", isinstance(size, (int, float)) and size > 20)
    widget.reject()
    results["onboarding_dismissed"] = True

poll = QTimer()
poll.timeout.connect(guard(reject_onboarding))
poll.start(100)

def dashboard():
    check("modules_loaded", addon.modules_loaded)
    check("isolated_profile", Path(mw.pm.base).resolve() == BASE.resolve())
    check("no_sync_credentials", not mw.pm.profile.get("syncKey") and not mw.pm.profile.get("autoSync"))
    check("onboarding_not_completed", not addon.addon_settings.get("onboarding_completed"))
    check("managers_initialized", all((addon.gamification_manager, addon.learning_plan_manager, addon.deadline_manager)))
    mw.web.page().runJavaScript("document.body.innerText", guard(dashboard_loaded))

def dashboard_loaded(text):
    check("dashboard_deck_rendered", isinstance(text, str) and "SynapsePro-Synthetic-Test" in text)
    check("launcher_initialized", addon.launcher_dock_widget is not None)
    initial = addon.launcher_dock_widget.isVisible()
    addon.toggle_launcher_sidebar()
    check("launcher_toggled", addon.launcher_dock_widget.isVisible() != initial)
    addon.toggle_launcher_sidebar()
    check("launcher_restored", addon.launcher_dock_widget.isVisible() == initial)
    if MODE == "restart":
        check("notebook_restart_persistence", json.loads(nb.load_latest_note()) == NOTE)
        check("todo_restart_persistence", json.loads(nb.load_latest_todos()) == TODO)
        check("review_restart_persistence", mw.col.db.scalar("select count(*) from revlog") >= 1)
        finish()
        return
    check("notebook_write", nb.save_note(json.dumps(NOTE)))
    check("notebook_read", json.loads(nb.load_latest_note()) == NOTE)
    check("todo_write", nb.save_todos(json.dumps(TODO)))
    check("todo_read", json.loads(nb.load_latest_todos()) == TODO)
    pomo.reset_action()
    pomo.start_pause_action()
    check("pomodoro_started", pomo.pomodoro_timer.isActive())
    results["timer_start"] = pomo.time_remaining
    later(1400, timer_elapsed)

def timer_elapsed():
    check("pomodoro_real_tick", pomo.time_remaining < results["timer_start"])
    pomo.start_pause_action()
    check("pomodoro_paused", not pomo.pomodoro_timer.isActive())
    pomo.reset_action()
    check("pomodoro_reset", pomo.current_state == pomo.constants.STATE_IDLE)
    nb.toggle_notebook_dock()
    wait_for("notebook_page_loaded", lambda: nb._dock and nb._dock.widget()._page_ready, notebook_ready)

def notebook_ready():
    nb._dock.widget().web.page().runJavaScript("document.body.innerText", guard(notebook_dom))

def notebook_dom(text):
    check("notebook_dom_rendered", isinstance(text, str) and len(text) > 20)
    mm.toggle_mindmap_dock()
    later(4000, inspect_mindmap)

def inspect_mindmap():
    panel = mm.mindmap_dock.widget()
    results["mindmap_diagnostics"] = dict(visible=mm.mindmap_dock.isVisible(), initialized=panel.is_initialized, ready=panel._page_ready, url=panel.web_view.url().toString() if panel.web_view else None)
    results["checks"]["mindmap_page_loaded"] = panel._page_ready
    if not panel._page_ready:
        mm.toggle_mindmap_dock()
        later(300, lambda: (mm.toggle_mindmap_dock(), later(2000, inspect_mindmap_retry)))
        return
    mindmap_ready()

def inspect_mindmap_retry():
    panel = mm.mindmap_dock.widget()
    results["checks"]["mindmap_reopen_loaded"] = panel._page_ready
    if panel.web_view:
        mindmap_ready()
    else:
        mindmap_dom(None)

def mindmap_ready():
    mm.mindmap_dock.widget().web_view.page().runJavaScript("document.body.innerText", guard(mindmap_dom))

def mindmap_dom(text):
    results["mindmap_text"] = text[:200] if isinstance(text, str) else text
    results["checks"]["mindmap_dom_rendered"] = isinstance(text, str) and len(text) > 20
    mm.toggle_mindmap_dock()
    # Close notebook before restoring exact backend persistence fixture.
    nb._dock.widget().unload_content(guard(after_notebook_closed))

def after_notebook_closed(saved):
    check("notebook_flush_on_close", saved)
    check("notebook_fixture_saved", nb.save_note(json.dumps(NOTE)))
    nb._dock.hide()
    did = mw.col.decks.id_for_name("SynapsePro-Synthetic-Test")
    note = mw.col.new_note(mw.col.models.by_name("Basic"))
    note["Front"], note["Back"] = "Synthetic smoke review: 3 + 3?", "6"
    mw.col.add_note(note, did)
    mw.col.decks.select(did)
    results["revlog_before"] = mw.col.db.scalar("select count(*) from revlog")
    mw.moveToState("review")
    wait_for("review_question_ready", lambda: mw.reviewer.card is not None and mw.reviewer.state == "question", answer)

def answer():
    mw.reviewer._showAnswer()
    check("review_answer_shown", mw.reviewer.state == "answer")
    mw.reviewer._answerCard(3)
    wait_for("review_logged", lambda: mw.col.db.scalar("select count(*) from revlog") > results["revlog_before"], finish)

later(100, lambda: wait_for("profile_initialized", lambda: mw.col is not None and addon.launcher_dock_widget is not None, lambda: wait_for("onboarding_rejected_without_acceptance", lambda: results.get("onboarding_dismissed", False), lambda: later(1000, dashboard))))
later(60000, lambda: finish("60 second timeout"))
app.exec()
raise SystemExit(0 if results.get("passed") else 1)
