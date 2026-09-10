"""Real Qt workflow checks. Creates only runtime/<name> synthetic data.

Run via just addon-browser-smoke. No real credentials, sync, grading or user
profiles are involved. Qt/Anki APIs drive the test, not desktop input injection.
"""

import hashlib
import io
import json
import os
import subprocess
import sys
import time
import traceback
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
name = sys.argv[1]
assert name and Path(name).name == name and name not in (".", "..", "backups")
BASE = (ROOT / "runtime" / name).resolve()
assert BASE.is_relative_to(ROOT / "runtime") and not BASE.exists(), (
    "Use a fresh run name"
)
subprocess.run([sys.executable, str(ROOT / "scripts" / "prepare.py"), name], check=True)

from anki.collection import AddNoteRequest, Collection

col = Collection(str(BASE / "SynapsePro-Test" / "collection.anki2"))
parent = col.decks.id("目录验收")
child = col.decks.id("目录验收::子牌组")
empty = col.decks.id("空牌组")
large = col.decks.id("性能牌组")
paired = col.models.by_name("Basic (and reversed card)")
note = col.new_note(paired)
note["Front"], note["Back"] = "apple", "苹果"
col.add_note(note, parent)
pair_ids = [card.id for card in note.cards()]
pair_note = note.id
cloze = col.new_note(col.models.by_name("Cloze"))
cloze["Text"] = "{{c1::Paris}} is the capital of {{c2::France}}."
col.add_note(cloze, child)
cloze_ids = [card.id for card in cloze.cards()]
media_model = col.models.copy(col.models.by_name("Basic"))
media_model["css"] += "\n.fixture-label { color: rgb(17, 83, 149); font-weight: bold; }"
col.models.save(media_model)
audio = io.BytesIO()
with wave.open(audio, "wb") as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(8000)
    wav.writeframes(b"\x00\x00" * 800)
col.media.write_data("browser-test.wav", audio.getvalue())
col.media.write_data(
    "browser-test.svg",
    b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><rect width="40" height="40" fill="#115395"/></svg>',
)
media_note = col.new_note(media_model)
media_note["Front"] = (
    '<span class="fixture-label">Synthetic media</span><img src="browser-test.svg">[sound:browser-test.wav]'
)
media_note["Back"] = "Synthetic answer"
col.add_note(media_note, child)
media_id = media_note.cards()[0].id
large_count = int(os.environ.get("SYNAPSE_BROWSER_TEST_COUNT", "10000"))
assert 1 <= large_count <= 100000
for offset in range(0, large_count, 1000):
    requests = []
    for index in range(offset, min(offset + 1000, large_count)):
        n = col.new_note(col.models.by_name("Basic"))
        n["Front"], n["Back"] = f"Synthetic row {index:06d}", "Synthetic answer"
        requests.append(AddNoteRequest(note=n, deck_id=large))
    col.add_notes(requests)
col.decks.select(parent)
col.close()

os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "synapse-browser-" + name
os.environ["PYTHONUTF8"] = "1"
audio_bin = ROOT / "out" / "extracted" / "mpv"
if (audio_bin / "mpv.exe").exists():
    os.environ["PATH"] = str(audio_bin) + os.pathsep + os.environ.get("PATH", "")
from PyQt6.QtTest import QTest

import aqt
from aqt import gui_hooks
from aqt.qt import QApplication, Qt, QTimer

results = {"checks": {}, "errors": [], "card_count": large_count}
done = False
app = aqt._run(
    ["anki", "-b", str(BASE), "-p", "SynapsePro-Test", "-l", "zh_CN"], exec=False
)
mw = aqt.mw
browser = None
workspace = None
started = time.monotonic()


def check(name, condition):
    results["checks"][name] = bool(condition)
    print(f"BROWSER {name}: {bool(condition)}", flush=True)
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
    results["passed"] = (
        bool(results["checks"])
        and all(results["checks"].values())
        and not results["errors"]
    )
    (BASE / "browser-result.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)
    mw.unloadProfileAndExit()


def guard(fn):
    def wrapped(*args):
        if done:
            return
        try:
            return fn(*args)
        except Exception:
            finish(traceback.format_exc())

    return wrapped


def wait_for(predicate, callback, seconds=20):
    deadline = time.monotonic() + seconds

    @guard
    def poll():
        if predicate():
            callback()
        elif time.monotonic() > deadline:
            raise TimeoutError(callback.__name__)
        else:
            QTimer.singleShot(30, poll)

    poll()


def idle():
    return (
        workspace.enabled
        and not workspace.loading
        and not workspace.saving_scope
        and not workspace.inflight
        and not workspace.query_timer.isActive()
    )


def reject_onboarding():
    for widget in QApplication.topLevelWidgets():
        if widget.__class__.__name__ == "OnboardingDialog":
            widget.reject()


onboarding_timer = QTimer()
onboarding_timer.timeout.connect(reject_onboarding)
onboarding_timer.start(100)
audio_events = []
gui_hooks.av_player_will_play_tags.append(
    lambda tags, side, context: audio_events.append((side, len(tags)))
)
played_events = []
gui_hooks.av_player_did_begin_playing.append(
    lambda player, tag: played_events.append(type(player).__name__)
)


def open_browser():
    global browser, workspace
    browser = aqt.dialogs.open("Browser", mw)
    browser.resize(1320, 760)
    workspace = browser._synapse_workspace
    wait_for(lambda: workspace.enabled and idle(), initial)


def initial():
    check("parent_and_children", browser.table.len() == 5)
    check("cards_not_notes", not browser.table.is_notes_mode())
    check(
        "embedded_widget",
        workspace.preview.parentWidget() is not None
        and not workspace.preview.isWindow(),
    )
    check(
        "native_editor_retained",
        browser.editor.widget is not None
        if hasattr(browser.editor, "widget")
        else browser.editor is not None,
    )
    check("original_profile_isolated", Path(mw.pm.base).resolve() == BASE)
    results["revlog_before"] = mw.col.db.scalar("select count(*) from revlog")
    results["scheduling_before"] = scheduling_hash()
    workspace.include_children.setChecked(False)
    wait_for(lambda: idle() and browser.table.len() == 2, parent_only)


def parent_only():
    check("parent_only", set(browser.table._model._items) == set(pair_ids))
    browser.table.select_single_card(pair_ids[1])
    workspace.show_preview()
    wait_for(
        lambda: (
            workspace.preview._last_state is not None
            and workspace.preview.card().id == pair_ids[1]
        ),
        reverse_ready,
    )


def reverse_ready():
    workspace.preview._web.page().runJavaScript(
        "document.querySelector('#qa').innerText", guard(reverse_text)
    )


def reverse_text(text):
    check("distinct_reverse_card_rendered", "苹果" in text and "apple" not in text)
    workspace.preview.flip_button.click()
    wait_for(lambda: workspace.preview._last_state[0] == "answer", answer_ready)


def answer_ready():
    workspace.preview._web.page().runJavaScript(
        "document.querySelector('#qa').innerText", guard(answer_text)
    )


def answer_text(text):
    check("actual_template_answer", "apple" in text and "苹果" in text)
    check(
        "preview_has_no_grading",
        mw.col.db.scalar("select count(*) from revlog") == results["revlog_before"],
    )
    workspace.include_children.setChecked(True)
    wait_for(lambda: idle() and browser.table.len() == 5, media_select)


def media_select():
    browser.table.select_single_card(media_id)
    workspace.show_preview()
    results["media_deadline"] = time.monotonic() + 10
    wait_for(
        lambda: (
            workspace.preview._last_state is not None
            and workspace.preview._last_state[1] == media_id
        ),
        media_ready,
    )


def media_ready():
    workspace.preview._web.page().runJavaScript(
        "({text:document.querySelector('#qa').innerText, image:!!document.querySelector('#qa img')?.naturalWidth, color:document.querySelector('.fixture-label')?getComputedStyle(document.querySelector('.fixture-label')).color:null})",
        guard(media_result),
    )


def media_result(data):
    if (
        not data["image"] or "Synthetic media" not in data["text"]
    ) and time.monotonic() < results["media_deadline"]:
        QTimer.singleShot(50, guard(media_ready))
        return
    results["media_render"] = data
    check(
        "front_reset_after_card_switch",
        workspace.preview._state == "question"
        and "Synthetic answer" not in data["text"],
    )
    check("media_image_loaded", data["image"])
    check("template_css_preserved", data["color"] == "rgb(17, 83, 149)")
    check("native_audio_tags", any(count > 0 for _side, count in audio_events))
    workspace.preview.replay_button.click()
    check("native_audio_player_available", aqt.sound.mpvManager is not None)
    # A second native preview takes ownership of Anki's shared audio player.
    # Closing/hiding our embedded pane must not stop that other playback.
    from unittest.mock import patch

    from aqt.browser.previewer import BrowserPreviewer
    from aqt.sound import av_player

    other_preview = BrowserPreviewer(browser, mw, lambda: None)
    other_preview.open()
    with patch.object(
        av_player, "stop_and_clear_queue", wraps=av_player.stop_and_clear_queue
    ) as stop:
        workspace.preview.stop_audio()
        check("other_preview_audio_not_stopped", not stop.called)
    other_preview.close()
    workspace.tree.setCurrentItem(workspace.items[empty][0])
    wait_for(lambda: idle() and browser.table.len() == 0, empty_deck)


def empty_deck():
    check(
        "empty_deck_state",
        "没有卡片" in workspace.status.text() and workspace.tabs.isVisible(),
    )
    workspace.tree.setCurrentItem(workspace.items[parent][0])
    wait_for(lambda: idle() and browser.table.len() == 5, search_empty)


def search_empty():
    workspace.search_box.setText("absolutely-absent")
    workspace.search_scope()
    wait_for(lambda: idle() and browser.table.len() == 0, empty_search)


def empty_search():
    check("empty_search_state", "搜索条件" in workspace.status.text())
    workspace.search_box.setText("apple")
    workspace.search_scope()
    workspace.tree.setCurrentItem(workspace.items[child][0])
    wait_for(lambda: idle() and browser.table.len() == 3, latest_search)


def latest_search():
    check(
        "latest_search_wins",
        set(browser.table._model._items) == set(cloze_ids + [media_id]),
    )
    browser.search_for('"deck:目录验收" prop:lapses>=8')
    wait_for(lambda: idle() and browser.table.len() == 0, external_search)


def external_search():
    check(
        "external_search_preserved",
        workspace.scope_id is None and "prop:lapses>=8" in browser._lastSearchTxt,
    )
    workspace.tree.setCurrentItem(workspace.items[parent][0])
    wait_for(lambda: idle() and browser.table.len() == 5, edit_select)


def edit_select():
    browser.table.select_single_card(pair_ids[0])
    workspace.tabs.setCurrentIndex(1)
    results["editor_deadline"] = time.monotonic() + 10
    # Save through the actual editor bridge, as field editing does.
    wait_for(
        lambda: browser.editor.note is not None and browser.editor.note.id == pair_note,
        edit_note,
    )


def edit_note():
    browser.editor.web.page().runJavaScript(
        """(() => {
      function fields(root) {
        const found = [...root.querySelectorAll('[contenteditable=true]')];
        for (const el of root.querySelectorAll('*')) if (el.shadowRoot) found.push(...fields(el.shadowRoot));
        return found;
      }
      window.smokeFields = fields(document);
      return window.smokeFields.map(el => el.innerText);
    })()""",
        guard(editor_ready),
    )


def editor_ready(texts):
    if (
        not texts or len(texts) < 2 or "apple" not in texts[0]
    ) and time.monotonic() < results["editor_deadline"]:
        QTimer.singleShot(50, guard(edit_note))
        return
    check("editor_real_webview", texts and "apple" in texts[0])
    browser.editor.web.page().runJavaScript(
        """(() => {
      const field = window.smokeFields[1];
      field.focus(); field.innerHTML = '苹果（已编辑）';
      field.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:'苹果（已编辑）'}));
      return true;
    })()""",
        guard(navigate_without_manual_save),
    )


def navigate_without_manual_save(_result):
    workspace.tree.setCurrentItem(workspace.items[child][0])
    wait_for(
        lambda: (
            idle()
            and browser.table.len() == 3
            and "已编辑" in mw.col.get_note(pair_note)["Back"]
        ),
        navigation_saved,
    )


def navigation_saved():
    check(
        "deck_navigation_saves_editor_draft",
        "已编辑" in mw.col.get_note(pair_note)["Back"],
    )
    workspace.tree.setCurrentItem(workspace.items[parent][0])
    wait_for(idle, editing_saved)


def editing_saved():
    workspace.tabs.setCurrentIndex(0)
    browser.table.select_single_card(pair_ids[1])
    wait_for(
        lambda: (
            workspace.preview._last_state
            and workspace.preview._last_state[1] == pair_ids[1]
        ),
        edited_preview,
    )


def edited_preview():
    workspace.preview._web.page().runJavaScript(
        "document.querySelector('#qa').innerText", guard(edited_text)
    )


def edited_text(text):
    check("editor_update_reaches_preview", "已编辑" in text)
    browser.resize(620, 600)
    workspace.apply_responsive()
    workspace.show_list()
    check(
        "narrow_list",
        workspace.list_widget.isVisible() and not workspace.tabs.isVisible(),
    )
    workspace.show_preview()
    check(
        "narrow_preview",
        workspace.tabs.isVisible() and not workspace.list_widget.isVisible(),
    )
    browser.resize(1320, 760)
    workspace.apply_responsive()
    browser.form.splitter.setSizes([420, 550])
    workspace.remember_sizes()
    browser.grab().save(str(BASE / "browser-wide.png"))
    results["saved_widths"] = workspace.prefs.get("widths")
    workspace.mode_action.setChecked(False)
    wait_for(lambda: not workspace.enabled, standard_mode)


def standard_mode():
    check(
        "standard_editor_restored",
        browser.form.splitter.widget(1) is workspace.editor_widget,
    )
    check(
        "standard_sidebar_restored",
        browser.sidebarDockWidget.widget() is workspace.native_sidebar,
    )
    check(
        "standard_columns_restored",
        mw.col.load_browser_card_columns() == workspace.standard["card_columns"],
    )
    workspace.mode_action.setChecked(True)
    wait_for(idle, large_search)


def large_search():
    results["large_start"] = time.monotonic()
    workspace.tree.setCurrentItem(workspace.items[large][0])
    wait_for(lambda: idle() and browser.table.len() == large_count, large_ready, 60)


def large_ready():
    results["large_search_seconds"] = round(
        time.monotonic() - results.pop("large_start"), 3
    )
    check("large_card_count", browser.table.len() == large_count)
    browser.form.tableView.scrollToBottom()
    check("rows_cached_on_demand", len(browser.table._model._rows) < 200)
    check("scheduling_unchanged", scheduling_hash() == results.pop("scheduling_before"))
    check(
        "revlog_unchanged",
        mw.col.db.scalar("select count(*) from revlog") == results["revlog_before"],
    )
    check("native_audio_playback_started", bool(played_events))
    workspace.reverse_button.click()
    wait_for(idle, large_sorted)


def large_sorted():
    first = mw.col.get_card(browser.table._model._items[0]).note()["Front"]
    check("sort_descending", first == f"Synthetic row {large_count - 1:06d}")
    workspace.tree.setCurrentItem(workspace.items[parent][0])
    browser.table.select_single_card(pair_ids[1])
    wait_for(idle, deferred_selection)


def deferred_selection():
    check(
        "external_card_selection_survives_async_search",
        browser.table.get_single_selected_card().id == pair_ids[1],
    )
    workspace.focus_decks()
    QTest.keyClick(workspace.tree, Qt.Key.Key_Left)
    check(
        "tree_collapse_keeps_scope",
        workspace.scope_id == parent and browser.table.len() == 5,
    )
    QTest.keyClick(workspace.tree, Qt.Key.Key_Right)
    QTest.keyClick(workspace.tree, Qt.Key.Key_Down)
    wait_for(lambda: idle() and workspace.scope_id == child, keyboard_list)


def keyboard_list():
    check("keyboard_deck_selection", browser.table.len() == 3)
    workspace.show_list()
    old = browser.table.get_single_selected_card().id
    QTest.keyClick(browser.form.tableView, Qt.Key.Key_Down)
    check("keyboard_card_selection", browser.table.get_single_selected_card().id != old)
    browser.table.select_all()
    wait_for(lambda: workspace.preview.card() is None, multiple_selected)


def multiple_selected():
    check(
        "multiselect_does_not_preview_arbitrary_card",
        workspace.preview.card() is None and "请选择一张" in workspace.status.text(),
    )
    workspace.tree.setCurrentItem(workspace.items[parent][0])
    wait_for(idle, deletion)


def deletion():
    # This explicit collection mutation is separate from the read-only checks.
    browser.table.select_single_card(pair_ids[0])
    from aqt.operations.note import remove_notes

    remove_notes(parent=browser, note_ids=[pair_note]).run_in_background()
    wait_for(lambda: idle() and browser.table.len() == 3, deleted)


def deleted():
    card = workspace.preview.card()
    check("deleted_cards_removed", not set(pair_ids) & set(browser.table._model._items))
    check("deleted_preview_cleared", card is None or card.id not in pair_ids)
    workspace.mode_action.setChecked(False)
    wait_for(lambda: not workspace.enabled, switch_to_notes)


def switch_to_notes():
    browser._switch.setChecked(True)
    wait_for(browser.table.is_notes_mode, notes_mode)


def notes_mode():
    workspace.mode_action.setChecked(True)
    wait_for(idle, cards_mode_again)


def cards_mode_again():
    check("three_panes_force_cards", not browser.table.is_notes_mode())
    workspace.mode_action.setChecked(False)
    wait_for(
        lambda: not workspace.enabled and browser.table.is_notes_mode(), notes_restored
    )


def notes_restored():
    check("standard_notes_mode_restored", browser.table.is_notes_mode())
    workspace.mode_action.setChecked(True)
    wait_for(idle, close_browser)


def close_browser():
    results["before_close_widths"] = workspace.prefs.get("widths")
    browser.close()
    wait_for(lambda: browser._closeEventHasCleanedUp, reopen_browser)


def reopen_browser():
    global browser, workspace
    browser = aqt.dialogs.open("Browser", mw)
    workspace = browser._synapse_workspace
    wait_for(idle, reopened)


def reopened():
    results["reopened_widths"] = workspace.prefs.get("widths")
    check("reopen_enabled", workspace.enabled)
    check(
        "reopen_local_widths", workspace.prefs.get("widths") == results["saved_widths"]
    )
    check("reopen_data_persisted", len(mw.col.find_cards('"deck:目录验收"')) == 3)
    workspace.show_preview()
    QTest.keyClick(workspace.preview, Qt.Key.Key_Escape)
    wait_for(lambda: workspace.closed, escaped)


def escaped():
    check("escape_closes_browser_safely", browser._closeEventHasCleanedUp)
    finish()


def scheduling_hash():
    rows = mw.col.db.all(
        "select id, did, odid, type, queue, due, ivl, factor, reps, lapses, left, odue from cards order by id"
    )
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


QTimer.singleShot(
    100, guard(lambda: wait_for(lambda: mw.col is not None, open_browser))
)
QTimer.singleShot(120000, lambda: finish("120 second timeout"))
sys.excepthook = lambda kind, value, tb: finish(
    "".join(traceback.format_exception(kind, value, tb))
)
app.exec()
raise SystemExit(0 if results.get("passed") else 1)
