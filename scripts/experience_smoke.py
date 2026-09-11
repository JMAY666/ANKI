"""Real Qt/WebEngine regression exercise using a disposable synthetic profile."""

import base64
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
if package := os.environ.get("ANKI_BUILTIN_PACKAGE_ROOT"):
    sys.path.insert(0, str(Path(package) / "app_packages"))
else:
    sys.path[:0] = [str(ROOT / p) for p in ("qt", "pylib", "out/qt", "out/pylib")]
name, mode = sys.argv[1], sys.argv[2]
assert Path(name).name == name and name not in (".", "..")
BASE = ROOT / "runtime" / name
os.environ.pop("ANKIDEV", None)
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "experience-" + name
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
results = {"checks": {}, "errors": [], "mode": mode}


def check(label, condition):
    results["checks"][label] = bool(condition)
    print("CHECK", label, bool(condition), flush=True)
    assert condition, label


def wait(predicate, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise TimeoutError(str(predicate))


def js(web, code):
    response = []
    web.page().runJavaScript(code, response.append)
    wait(lambda: bool(response))
    return response[0]


def settled():
    wait(lambda: not mw._background_op_count)
    until = time.monotonic() + 0.15
    wait(lambda: time.monotonic() > until)


def home(did):
    mw.moveToState("deckBrowser")
    mw.deckBrowser.set_current_deck(did)
    wait(
        lambda: (
            js(
                mw.web,
                "document.querySelector('.deck-workspace')?.dataset.selectedDeck",
            )
            == str(did)
        )
    )
    settled()
    wait(
        lambda: (
            not mw._background_op_count
            and not mw.web.page().isLoading()
            and js(
                mw.web,
                "document.querySelector('.deck-workspace')?.dataset.ready === 'true' && document.querySelector('.deck-workspace')?.dataset.renderRevision",
            )
            == str(mw.deckBrowser._render_revision)
        )
    )


def prepare():
    from anki.collection import Collection
    from anki.lang import set_lang
    from aqt.profiles import ProfileManager

    assert not BASE.exists()
    BASE.mkdir(parents=True)
    (BASE / ".builtin-test").write_text("synthetic data only")
    set_lang("en_US")
    pm = ProfileManager(str(BASE))
    pm.setupMeta()
    pm.meta.update(defaultLang="zh_CN", firstRun=False, updates=False)
    pm.create("Experience")
    pm.load("Experience")
    pm.profile.update(autoSync=False, syncKey=None, syncMedia=False)
    pm.save()
    pm.db.close()
    config = BASE / "Experience/SynapsePro_Data/addon_settings.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "onboarding_completed": True,
                "minimal_dashboard_enabled": True,
                "gamification_popups_enabled": False,
            }
        )
    )
    col = Collection(str(BASE / "Experience/collection.anki2"))
    did = col.decks.id("English::Words")
    model = col.models.by_name("Basic")
    data = io.BytesIO()
    with wave.open(data, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x10\x00\xf0" * 4000)
    col.media.write_data("synthetic.wav", data.getvalue())
    words = (
        "apple",
        "river",
        "window",
        "study",
        "paper",
        "flower",
        "garden",
        "orange",
        "book",
        "cloud",
        "water",
        "sun",
    )
    speech_dir = BASE / "speech"
    speech_dir.mkdir()
    speech_path = str(speech_dir).replace("'", "''")
    script = "Add-Type -AssemblyName System.Speech; $speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; $speaker.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet, [System.Speech.Synthesis.VoiceAge]::NotSet, 0, [System.Globalization.CultureInfo]::GetCultureInfo('en-US')); "
    script += f"$speechDir = '{speech_path}'; "
    script += (
        "foreach ($word in @("
        + ",".join(f"'{word}'" for word in words)
        + ")) { $speaker.SetOutputToWaveFile((Join-Path $speechDir ($word + '.wav'))); $speaker.Speak($word); $speaker.SetOutputToNull() }; $speaker.Dispose()"
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(script.encode("utf-16le")).decode(),
        ],
        capture_output=True,
        timeout=45,
    )
    spoken = completed.returncode == 0 and all(
        (speech_dir / f"{word}.wav").exists() for word in words
    )
    results["speech_fixture"] = (
        "Windows English TTS" if spoken else "synthetic tone fallback"
    )
    for word in words:
        note = col.new_note(model)
        filename = f"{word}.wav" if spoken else "synthetic.wav"
        if spoken:
            col.media.write_data(filename, (speech_dir / filename).read_bytes())
        note["Front"] = f"<h1>{word}</h1>[sound:{filename}]"
        note["Back"] = f"Answer for {word}"
        col.add_note(note, did)
    conf = col.decks.config_dict_for_deck_id(did)
    conf["new"]["order"] = 0
    conf["newSortOrder"] = 4
    col.decks.update_config(conf)
    col.decks.id("Other::Child")
    col.decks.select(did)
    col.close()


try:
    if mode == "write":
        prepare()
    assert (BASE / ".builtin-test").read_text() == "synthetic data only"
    from PyQt6.QtTest import QTest

    import aqt
    from aqt import gui_hooks
    from aqt.progress import ProgressDialog
    from aqt.qt import QApplication, QLabel, QPoint, Qt, QTimer

    app = aqt._run(
        ["anki", "-b", str(BASE), "-p", "Experience", "--safemode", "-l", "zh_CN"],
        exec=False,
    )
    mw = aqt.mw

    from aqt.builtin_features.synapsepro.quick_switches import (
        open_quick_switches,
        playlist_loop,
        save_setting,
    )

    def dismiss_error():
        modal = QApplication.activeModalWidget()
        if isinstance(modal, ProgressDialog):
            return
        if modal and modal.windowTitle() not in ("Anki", ""):
            return
        if modal:
            results["errors"].append(
                " | ".join(label.text() for label in modal.findChildren(QLabel))
            )
            modal.reject()

    guard = QTimer()
    guard.timeout.connect(dismiss_error)
    guard.start(500)
    wait(lambda: mw.col and mw.state == "deckBrowser" and mw.learning_workspace.store)
    synapse = sys.modules["aqt.builtin_features.synapsepro"]
    wait(lambda: synapse._daily_maintenance_done)
    col, workspace = mw.col, mw.learning_workspace
    did = col.decks.id(
        "Other::English::Words" if mode == "restart" else "English::Words"
    )
    other = col.decks.id("Other::Child")
    mw.resize(1400, 900)
    home(did)
    if mode == "restart":
        check(
            "toolbar preference survives restart",
            not workspace.review_toolbar_visible(),
        )
        check("playlist loop survives restart", playlist_loop())
        check(
            "deck hierarchy survives restart",
            col.decks.by_name("Other::English::Words") is not None,
        )
        check("card count preserved", col.db.scalar("select count(*) from cards") == 12)
    else:
        check(
            "small deck tree ready",
            js(mw.web, "document.querySelector('.deck-workspace').dataset.ready")
            == "true",
        )
        for i in range(240):
            col.decks.id(f"Many::{i:03}::Level::Leaf")
        mw.deckBrowser.refresh()
        wait(lambda: js(mw.web, "document.querySelectorAll('tr.deck').length") > 700)
        settled()
        js(
            mw.web,
            "window.directoryIdentity=document.querySelector('.deck-directory');window.widgetsIdentity=document.querySelector('.deck-global-widgets');",
        )
        start = time.monotonic()
        for i in range(30):
            mw.deckBrowser.set_current_deck(did if i % 2 else other)
        wait(
            lambda: (
                js(
                    mw.web,
                    "document.querySelector('.deck-workspace').dataset.selectedDeck",
                )
                == str(did)
            )
        )
        settled()
        results["rapid_selection_ms"] = round((time.monotonic() - start) * 1000)
        check(
            "three panels consistent after rapid selection",
            js(
                mw.web,
                "document.querySelector('.deck-main h1').textContent === document.querySelector('.deck-scope-info h3').textContent && document.querySelector('tr.current').id === document.querySelector('.deck-workspace').dataset.selectedDeck",
            ),
        )
        check(
            "selection preserves directory and account widgets",
            js(
                mw.web,
                "directoryIdentity===document.querySelector('.deck-directory') && widgetsIdentity===document.querySelector('.deck-global-widgets')",
            ),
        )
        parent = col.decks.id("Many")
        for i in range(8):
            mw.deckBrowser._collapse(parent)
        settled()
        check(
            "collapse does not reload page",
            js(mw.web, "directoryIdentity===document.querySelector('.deck-directory')"),
        )
        check(
            "collapse matches saved state",
            bool(col.decks.get(parent)["collapsed"])
            == bool(
                int(
                    js(mw.web, f"document.getElementById('{parent}').dataset.collapsed")
                )
            ),
        )
        col.decks.select(other)
        mw.deckBrowser._renderPage(selection_only=True)
        mw.deckBrowser._collapse(parent)
        wait(
            lambda: (
                js(
                    mw.web,
                    "document.querySelector('.deck-workspace')?.dataset.selectedDeck",
                )
                == str(other)
            )
        )
        check(
            "collapse cannot discard the selected deck update",
            js(mw.web, "document.querySelector('tr.current').id") == str(other),
        )
        home(did)
        for width in (1400, 950, 620):
            mw.resize(width, 800)
            settled()
            check(
                f"deck layout fits width {width}",
                js(mw.web, "document.documentElement.scrollWidth <= innerWidth + 2"),
            )
        mw.resize(1400, 900)

    if mode == "restart":
        did = col.decks.id("Other::English::Words")
        home(did)
    audio = []

    def on_audio(player, tag):
        event = {
            "card": mw.reviewer.card.id,
            "side": mw.reviewer.state,
            "time": time.monotonic(),
        }
        # Never spin an event loop inside the WebChannel's visible-ack callback.
        mw.web.page().runJavaScript(
            "({text:document.getElementById('qa')?.innerText,opacity:getComputedStyle(document.getElementById('qa')).opacity})",
            lambda dom: audio.append(event | {"dom": dom}),
        )

    gui_hooks.av_player_did_begin_playing.append(on_audio)
    mw.deckBrowser.start_review(did)
    wait(lambda: mw.state == "review" and mw.reviewer.card and audio)
    check(
        "first audio starts with visible matching card",
        audio[-1]["dom"]["opacity"] == "1"
        and mw.reviewer.card.note()["Front"].split("</h1>")[0].split(">")[-1]
        in audio[-1]["dom"]["text"],
    )
    for index in range(5 if mode == "write" else 1):
        reviewer = mw.reviewer
        previous = reviewer.card.id
        reviewer._showAnswer()
        settled()
        reviewer._answerCard(3)
        wait(
            lambda: (
                reviewer.card
                and reviewer.card.id != previous
                and audio[-1]["card"] == reviewer.card.id
            )
        )
        check(
            f"card {index} audio matches visible face",
            audio[-1]["side"] == "question"
            and audio[-1]["dom"]["opacity"] == "1"
            and reviewer.card.note()["Front"].split("</h1>")[0].split(">")[-1]
            in audio[-1]["dom"]["text"],
        )
    check(
        "review toolbar respects saved preference",
        workspace.review_bar.isVisible() == workspace.review_toolbar_visible(),
    )
    # Rapid redraws must never play the three obsolete audio requests.
    count = len(audio)
    for _ in range(4):
        mw.reviewer._showQuestion()
    wait(lambda: len(audio) > count)
    settled()
    check("rapid redraw plays only the newest audio request", len(audio) == count + 1)
    anchor = synapse.sidebar_widget_instance._quick_button
    open_quick_switches(mw, anchor)
    menu = mw._quick_switch_menu
    settled()
    menu.controls[0][0].click()
    check(
        "toolbar checkbox changes actual container",
        workspace.review_bar.isVisible() == menu.controls[0][0].isChecked(),
    )
    mw.grab().save(str(BASE / f"{mode}-quick-switches.png"))
    menu.grab().save(str(BASE / f"{mode}-popover.png"))
    open_quick_switches(mw, anchor)
    check(
        "second activation closes popover",
        not menu.isVisible() and not anchor.isChecked(),
    )
    open_quick_switches(mw, anchor)
    menu = mw._quick_switch_menu
    QTest.mouseClick(mw.web, Qt.MouseButton.LeftButton)
    settled()
    check("outside click closes popover", not menu.isVisible())
    for fullscreen in (False, True):
        mw.showFullScreen() if fullscreen else mw.showNormal()
        for zoom in (0.8, 1.0, 1.5):
            mw.web.setZoomFactor(zoom)
            workspace.set_review_toolbar_visible(False)
            settled()
            hidden_y = workspace.pages.y()
            open_quick_switches(mw, synapse.sidebar_widget_instance._quick_button)
            menu = mw._quick_switch_menu
            settled()
            check(
                f"popup inside window full={fullscreen} zoom={zoom}",
                mw.frameGeometry().contains(menu.frameGeometry()),
            )
            QTest.keyClick(menu, Qt.Key.Key_Escape)
            check(
                f"Escape closes popup full={fullscreen} zoom={zoom}",
                not menu.isVisible(),
            )
            workspace.set_review_toolbar_visible(True)
            settled()
            check(
                f"hidden toolbar releases height full={fullscreen} zoom={zoom}",
                workspace.pages.y() > hidden_y,
            )
    mw.showNormal()
    mw.web.setZoomFactor(1)
    workspace.set_review_toolbar_visible(False)
    save_setting("soundcloud_playlist_loop", True)
    mw.moveToState("deckBrowser")
    settled()
    if mode == "write":
        home(did)
        positions = js(
            mw.web,
            f"[{col.decks.id('English')},{col.decks.id('Other')}].map(id=>{{const r=document.getElementById(String(id)).getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]}})",
        )
        start, end = [QPoint(round(x), round(y)) for x, y in positions]
        target = mw.web.focusProxy()
        QTest.mousePress(target, Qt.MouseButton.LeftButton, pos=start)
        QTest.qWait(250)
        for part in range(1, 7):
            QTest.mouseMove(target, start + (end - start) * part / 6)
            QTest.qWait(40)
        QTest.mouseRelease(target, Qt.MouseButton.LeftButton, pos=end)
        wait(lambda: col.decks.by_name("Other::English::Words") is not None)
        settled()
        check(
            "reparent preserves cards and nested deck",
            col.decks.by_name("Other::English::Words") is not None
            and col.db.scalar("select count(*) from cards") == 12,
        )
    mw.grab().save(str(BASE / f"{mode}-home.png"))
    results["audio_events"] = audio
    workspace.profile_close()
    mw.pm.save()
    col.close()
    mw.col = None
except BaseException:
    results["errors"].append(traceback.format_exc())
    print(results["errors"][-1], flush=True)
    if "mw" in globals() and mw:
        mw.grab().save(str(BASE / f"{mode}-failure.png"))
finally:
    results["passed"] = bool(results["checks"]) and not results["errors"]
    (BASE / f"{mode}-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print("RESULT", results["passed"], len(results["checks"]), flush=True)
    os._exit(0 if results["passed"] else 1)
