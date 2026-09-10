"""Real Qt/Anki event-loop smoke test, exclusively against a synthetic profile.

Rejects onboarding (never accepts terms); no production code or completion
flags are patched. DeepSeek HTTP responses are synthetic; real API credentials
are never used. Uses application APIs, not native desktop automation.
"""
from pathlib import Path
import importlib
import json
import os
import sys
import time
import traceback
import hashlib
import io

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "runtime" / "smoke-1.5.1"
MODE = sys.argv[1] if len(sys.argv) > 1 else "write"
assert MODE in ("write", "restart")
assert (BASE / "prefs21.db").exists()
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "synapsepro-smoke-1.5.1"
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
ai = importlib.import_module("236979321.ai_assistant")
pomo = importlib.import_module("236979321.pomodoro")
retired = ("website_viewer_enabled", "notebook_enabled", "mindmap_enabled")
legacy_paths = [BASE / "SynapsePro-Test" / n for n in ("notebook.sqlite", "mindmap_recovery.json", "mindmap_web_data/synthetic", "website_web_data/synthetic")]
legacy_hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in legacy_paths}
real_urlopen = ai.urllib.request.urlopen

def synthetic_api(req, *args, **kwargs):
    if getattr(req, "full_url", "") == "https://api.deepseek.com/chat/completions":
        body = json.loads(req.data)
        assert req.get_header("Authorization") == "Bearer synthetic-deepseek-key"
        assert body["model"] == "synthetic-custom-model"
        assert body["thinking"] == {"type": "disabled"}
        results["api_request_verified"] = True
        return io.BytesIO(b'data: {"choices":[{"delta":{"content":"Synthetic DeepSeek reply"}}]}\n' + b'data: [DONE]\n')
    return real_urlopen(req, *args, **kwargs)

ai.urllib.request.urlopen = synthetic_api

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
    results["checks"]["legacy_data_unchanged"] = all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in legacy_hashes.items())
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
        check("deepseek_restart_settings", ai._load_settings()["provider"] == "deepseek" and ai._load_settings()["model"] == "synthetic-custom-model")
        check("deepseek_restart_key", ai._load_settings()["apiKey"] == "synthetic-deepseek-key")
        check("review_restart_persistence", mw.col.db.scalar("select count(*) from revlog") >= 1)
        finish()
        return
    check("removed_shortcuts", not set(retired) & set(addon.constants.SIDEBAR_SHORTCUT_KEYS))
    # Even migrated configurations containing old shortcuts must not register them.
    addon.sidebar_shortcuts.refresh(dict(addon.addon_settings, sidebar_shortcuts={key: "Ctrl+Alt+9" for key in retired}))
    check("legacy_shortcuts_ignored", not addon.sidebar_shortcuts._registered)
    check("removed_modules_not_loaded", all("236979321." + n not in sys.modules for n in ("website_sidebar", "notebook_sidebar", "mindmap_sidebar", "embedded_window")))
    from aqt.qt import QAction, QPushButton
    texts = [x.text() for x in mw.findChildren(QAction)] + [x.toolTip() for x in addon.sidebar_widget_instance.findChildren(QPushButton)]
    check("menus_and_launcher_entries_removed", not any(any(label in t for label in ("Mind Map", "Notebook", "Website Viewer", "Search in Sidebar")) for t in texts))
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
    ai.toggle_ai_assistant_dock()
    later(1200, ai_ready)


def ai_ready():
    ai._webview.page().runJavaScript("({ready:typeof _settingsProvider==='string',providers:Array.from(document.querySelectorAll('#s-provider option')).map(x=>x.value)})", guard(ai_options))


def ai_options(data):
    check("ai_webview_ready", data and data.get("ready"))
    check("all_ai_providers_present", set(data["providers"]) == {"openai", "gemini", "openrouter", "anthropic", "ollama", "llamaserver", "deepseek"})
    ai._webview.page().runJavaScript("document.getElementById('s-provider').value='openai';onProviderChange(false);document.getElementById('s-apikey').value='synthetic-other-key';document.getElementById('s-provider').value='deepseek';onProviderChange();document.getElementById('s-apikey').value", guard(provider_changed))


def provider_changed(value):
    check("provider_switch_clears_foreign_key", value == "")
    later(300, save_ai)


def save_ai():
    ai._webview.page().runJavaScript("document.getElementById('s-apikey').value='synthetic-deepseek-key';document.getElementById('s-model').value='synthetic-custom-model';saveSettings();", guard(lambda _: later(300, saved_ai)))


def saved_ai():
    check("ai_ui_settings_saved", ai._load_settings()["provider"] == "deepseek" and ai._load_settings()["model"] == "synthetic-custom-model")
    check("ai_key_not_in_collection", ai.CK_KEY_DEEPSEEK not in mw.col.conf)
    ai._webview.page().runJavaScript("document.getElementById('start-user-input').value='Synthetic test';trySendFromEmpty();", guard(lambda _: later(1200, stream_complete)))


def stream_complete():
    ai._webview.page().runJavaScript("({text:document.getElementById('chat').innerText,busy:busy})", guard(check_reply))


def check_reply(data):
    check("deepseek_request_payload", results.get("api_request_verified", False))
    check("deepseek_stream_in_ui", data and 'Synthetic DeepSeek reply' in data['text'] and not data['busy'])
    # Both native and HTML settings must omit removed tools.
    native = addon.settings_dialog.SettingsDialog(addon.addon_settings, mw)
    from aqt.qt import QCheckBox
    labels = [w.text() for w in native.findChildren(QCheckBox)]
    check("native_settings_removed", not any(x in labels for x in ('Mind Map','Notebook','Website Viewer')))
    native.reject(); native.deleteLater()
    from importlib import import_module
    web_settings = import_module('236979321.web_settings_dialog')
    check("settings_payload_removed", not set(retired) & set(web_settings._TOGGLE_KEYS))
    global settings_test_dialog
    settings_test_dialog = web_settings.WebSettingsDialog(addon.addon_settings, mw)
    settings_test_dialog.show()
    wait_for("web_settings_initialized", lambda: settings_test_dialog._injected, check_web_settings)


def check_web_settings():
    settings_test_dialog._view.page().runJavaScript("SIDE.map(x=>x[0])", guard(web_settings_result))


def web_settings_result(keys):
    check("web_settings_controls_removed", set(keys) == {"ai_assistant_enabled", "gamification_sidebar_enabled", "music_player_enabled", "pomodoro_enabled"})
    settings_test_dialog.reject()
    settings_test_dialog.deleteLater()
    ai.toggle_ai_assistant_dock()
    start_review()


def start_review():
    did = mw.col.decks.id_for_name("SynapsePro-Synthetic-Test")
    note = mw.col.new_note(mw.col.models.by_name("Basic"))
    note["Front"], note["Back"] = "Synthetic smoke review: 3 + 3?", "6"
    mw.col.add_note(note, did)
    mw.col.decks.select(did)
    results["revlog_before"] = mw.col.db.scalar("select count(*) from revlog")
    mw.moveToState("review")
    wait_for("review_question_ready", lambda: mw.reviewer.card is not None and mw.reviewer.state == "question", answer)

def answer():
    check("old_pdf_link_no_error", addon.webview_did_receive_js_message(False, "pycmd:synapsepro:pdf:synthetic", mw.reviewer) == (True, None))
    mw.reviewer._showAnswer()
    check("review_answer_shown", mw.reviewer.state == "answer")
    mw.reviewer._answerCard(3)
    wait_for("review_logged", lambda: mw.col.db.scalar("select count(*) from revlog") > results["revlog_before"], finish)

later(100, lambda: wait_for("profile_initialized", lambda: mw.col is not None and addon.launcher_dock_widget is not None, lambda: wait_for("onboarding_rejected_without_acceptance", lambda: results.get("onboarding_dismissed", False), lambda: later(1000, dashboard))))
later(60000, lambda: finish("60 second timeout"))
app.exec()
raise SystemExit(0 if results.get("passed") else 1)
