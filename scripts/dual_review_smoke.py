"""Native dual-review acceptance with an isolated, synthetic collection."""

import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if package := os.environ.get("ANKI_BUILTIN_PACKAGE_ROOT"):
    sys.path.insert(0, str(Path(package) / "app_packages"))
else:
    sys.path[:0] = [str(ROOT / part) for part in ("qt", "pylib", "out/qt", "out/pylib")]
name = sys.argv[1]
assert name and Path(name).name == name and name not in (".", "..")
BASE = ROOT / "runtime" / name
assert not BASE.exists(), "Use a fresh synthetic run name"
BASE.mkdir(parents=True)
(BASE / ".builtin-test").write_text("synthetic data only")
os.environ.pop("ANKIDEV", None)
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "dual-review-" + name
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
os.environ["QT_QPA_FONTDIR"] = str(
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
)
results = {"checks": {}, "errors": []}


def check(label, result):
    print("CHECK", label, bool(result), flush=True)
    results["checks"][label] = bool(result)
    assert result, label


def wait(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        if results["errors"]:
            raise AssertionError(results["errors"][-1])
        time.sleep(0.015)
    raise TimeoutError(str(predicate))


def js(web, source):
    received = []
    web.page().runJavaScript(source, received.append)
    wait(lambda: bool(received))
    return received[0]


def ready(panel):
    return (
        not panel.pending
        and panel.reviewer.card
        and panel.reviewer.state == "question"
        and panel.reviewer._states_mutated
        and js(panel.reviewer.web, "document.querySelector('#qa h2')?.textContent")
        == panel.reviewer.card.note()["Front"].split("<h2>", 1)[1].split("</h2>", 1)[0]
    )


try:
    from anki.collection import Collection
    from anki.lang import set_lang
    from aqt.profiles import ProfileManager

    set_lang("en_US")
    pm = ProfileManager(str(BASE))
    pm.setupMeta()
    pm.meta.update(defaultLang="zh_CN", firstRun=False, updates=False)
    pm.create("Dual-Review-Test")
    pm.load("Dual-Review-Test")
    pm.profile.update(autoSync=False, syncKey=None, syncMedia=False)
    pm.save()
    pm.db.close()
    profile = BASE / "Dual-Review-Test"
    settings = profile / "SynapsePro_Data/addon_settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "onboarding_completed": True,
                "gamification_popups_enabled": False,
                "minimal_dashboard_enabled": True,
            }
        )
    )
    col = Collection(str(profile / "collection.anki2"))
    col.set_config("cardStateCustomizer", "customData.good.scope = ctx.deckName;")
    model = col.models.by_name("Basic")
    decks = {
        key: col.decks.id("双栏测试::" + key) for key in ("记忆", "练习", "空牌组")
    }
    for key in ("记忆", "练习"):
        for index in range(8):
            note = col.new_note(model)
            note["Front"] = (
                f'<h2>{key} {index}</h2><input id="keep-input"><p>合成内容</p>'
                + "<p>独立滚动的长卡片。</p>" * 14
            )
            note["Back"] = f'<h2>{key} {index} 答案</h2><input id="keep-input">'
            col.add_note(note, decks[key])
    col.decks.select(decks["记忆"])
    col.close()

    import aqt
    from aqt.progress import ProgressDialog
    from aqt.qt import QApplication, QLabel, QTimer

    app = aqt._run(
        [
            "anki",
            "-b",
            str(BASE),
            "-p",
            "Dual-Review-Test",
            "--safemode",
            "-l",
            "zh_CN",
        ],
        exec=False,
    )
    mw = aqt.mw
    previous_excepthook = sys.excepthook

    def record_exception(kind, value, tb):
        results["errors"].append("".join(traceback.format_exception(kind, value, tb)))
        previous_excepthook(kind, value, tb)

    sys.excepthook = record_exception

    def dialog_guard():
        modal = QApplication.activeModalWidget()
        if modal and not isinstance(modal, ProgressDialog):
            results["errors"].append(
                " | ".join(label.text() for label in modal.findChildren(QLabel))
            )
            modal.reject()

    guard = QTimer()
    guard.timeout.connect(dialog_guard)
    guard.start(200)
    wait(lambda: mw.col and mw.state == "deckBrowser" and mw.learning_workspace.store)
    wait(lambda: sys.modules["aqt.builtin_features.synapsepro"]._daily_maintenance_done)
    mw.resize(1450, 950)
    mw.activateWindow()
    mw.moveToState("review")
    original = mw.reviewer
    wait(
        lambda: (
            original.card
            and original.state == "question"
            and original._states_mutated
            and js(original.web, "!!document.querySelector('#qa h2')")
        )
    )
    original._showAnswer()
    wait(
        lambda: (
            original.state == "answer"
            and js(original.web, "!!document.querySelector('#keep-input')")
        )
    )
    js(
        original.web,
        "window.dualSentinel=43;document.querySelector('#keep-input').value='preserved';",
    )
    left_id = original.card.id
    owner = mw.dual_review
    workspace = mw.learning_workspace
    page_order = [workspace.pages.widget(i) for i in range(workspace.pages.count())]
    from aqt.qt import QPushButton

    entry = mw.findChild(QPushButton, "dualReviewLauncher")
    check("sidebar entry is available", entry is not None)
    entry.click()
    left, right = owner.panels
    wait(lambda: not left.pending and left.token and not right.pending)
    check(
        "statistics page indices stay stable during dual review",
        all(
            workspace.pages.widget(i) is page
            for i, page in enumerate(page_order)
            if page is not workspace.native
        ),
    )
    check(
        "left renderer, card and answer survive entry",
        left.reviewer is original
        and original.card.id == left_id
        and original.state == "answer",
    )
    check(
        "left DOM and input survive entry",
        js(
            original.web,
            "window.dualSentinel===43 && document.querySelector('#keep-input').value==='preserved'",
        ),
    )
    right.deck.setCurrentIndex(right.deck.findData(decks["练习"]))
    wait(lambda: ready(right))
    check("different decks issue different cards", right.reviewer.card.id != left_id)
    mw.desktop_tools.set_enabled(True)
    wait(
        lambda: (
            js(original.web, "!!window.ankiPenDown")
            and js(right.reviewer.web, "!!window.ankiPenDown")
        )
    )
    js(original.web, "window.leftPenIdentity=window.ankiPenDown")
    check(
        "custom scheduling receives each pane's own context",
        json.loads(right.reviewer._v3.states.good.custom_data)["scope"].endswith(
            "::练习"
        )
        and json.loads(original._v3.states.good.custom_data)["scope"].endswith(
            "::记忆"
        ),
    )
    owner.activate(right, focus=True)
    right.reviewer._showAnswer()
    wait(lambda: right.reviewer.state == "answer")
    right_id = right.reviewer.card.id
    right.reviewer._answerCard(3)
    wait(
        lambda: (
            not owner.submitting and ready(right) and right.reviewer.card.id != right_id
        )
    )
    check(
        "right-first answer creates exactly one review",
        mw.col.db.scalar("select count(*) from revlog") == 1,
    )
    check(
        "custom scheduling data is saved on the answered card",
        json.loads(mw.col.get_card(right_id).custom_data)["scope"].endswith("::练习"),
    )
    check(
        "right answer leaves left state intact",
        original.card.id == left_id
        and original.state == "answer"
        and js(original.web, "window.dualSentinel===43"),
    )
    mw.undo()
    wait(
        lambda: (
            not right.pending
            and right.reviewer.card
            and right.reviewer.card.id == right_id
            and right.reviewer.state == "answer"
        )
    )
    check(
        "global undo restores right card and revlog",
        mw.col.db.scalar("select count(*) from revlog") == 0,
    )
    right.deck.setCurrentIndex(right.deck.findData(decks["记忆"]))
    wait(lambda: ready(right))
    check(
        "overlapping deck reservations exclude the left card",
        right.reviewer.card.id != left_id,
    )
    check(
        "right card change preserves the left handwriting canvas",
        js(original.web, "window.leftPenIdentity===window.ankiPenDown"),
    )
    mw.desktop_tools.set_enabled(False)
    from PyQt6.QtTest import QTest

    from aqt.qt import Qt

    mw.activateWindow()
    owner.activate(right, focus=True)
    wait(
        lambda: (
            QApplication.activeWindow() is mw and QApplication.focusWidget() is not None
        )
    )
    js(right.reviewer.web, "document.querySelector('#keep-input').focus()")
    QTest.keyClicks(QApplication.focusWidget(), "1 2 3 4")
    app.processEvents()
    wait(
        lambda: (
            js(right.reviewer.web, "document.querySelector('#keep-input').value")
            == "1 2 3 4"
        )
    )
    check(
        "typing cannot grade or flip",
        right.reviewer.state == "question"
        and mw.col.db.scalar("select count(*) from revlog") == 0,
    )
    check(
        "typing reaches the right input",
        js(right.reviewer.web, "document.querySelector('#keep-input').value")
        == "1 2 3 4",
    )
    js(right.reviewer.web, "document.activeElement.blur()")
    owner.activate(right, focus=True)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Space)
    wait(lambda: right.reviewer.state == "answer")
    check(
        "space flips only the active panel",
        original.state == "answer" and original.card.id == left_id,
    )
    mw.passfail2.save(mw.passfail2.value | {"enabled": True})
    wait(
        lambda: (
            js(
                right.reviewer.bottom.web,
                "document.querySelectorAll('button[data-ease]').length",
            )
            == 2
        )
    )
    check(
        "two-grade mode updates both panes",
        js(original.bottom.web, "document.querySelectorAll('button[data-ease]').length")
        == 2,
    )
    mw.passfail2.save(mw.passfail2.value | {"enabled": False})
    wait(
        lambda: (
            js(
                right.reviewer.bottom.web,
                "document.querySelectorAll('button[data-ease]').length",
            )
            == 4
        )
    )
    mw.onEditCurrent()
    editor = next(
        w
        for w in QApplication.topLevelWidgets()
        if hasattr(w, "editor")
        and getattr(w.editor, "card", None)
        and w.editor.card.id == right.reviewer.card.id
    )
    edited_card = editor.editor.card.id
    wait(lambda: js(editor.editor.web, "typeof saveNow === 'function'"))
    owner.activate(left)
    check(
        "editor target stays on its original pane",
        editor.editor.card.id == edited_card and edited_card != left_id,
    )
    closed = []
    editor.closeWithCallback(lambda: closed.append(True))
    wait(lambda: bool(closed))
    owner.activate(right)
    geometry = {}
    for panel in owner.panels:
        geometry[panel.name] = {
            "panel": [panel.x(), panel.y(), panel.width(), panel.height()],
            "card": [panel.reviewer.web.width(), panel.reviewer.web.height()],
            "parent": panel.native.parentWidget().metaObject().className(),
        }
    results["wide_geometry"] = geometry
    check(
        "both native card surfaces have usable area",
        all(
            p.reviewer.web.isVisible()
            and 280 <= p.reviewer.web.width() <= p.width()
            and p.reviewer.web.height() >= 180
            for p in owner.panels
        ),
    )
    mw.grab().save(str(BASE / "dual-review-wide.png"))
    from unittest.mock import patch

    owner.activate(left)
    original._pending_visible_audio = (
        original._audio_revision,
        original.card,
        original.state,
        ["synthetic-left-audio"],
    )
    right.reviewer._pending_visible_audio = (
        right.reviewer._audio_revision,
        right.reviewer.card,
        right.reviewer.state,
        ["synthetic-right-audio"],
    )
    with (
        patch("aqt.reviewer.av_player.play_tags") as play,
        patch("aqt.reviewer.av_player.stop_and_clear_queue") as stop,
    ):
        right.reviewer._play_visible_audio(str(right.reviewer._audio_revision))
        check("inactive pane cannot autoplay", play.call_count == 0)
        original._play_visible_audio(str(original._audio_revision))
        check(
            "visible active pane owns playback",
            play.call_count == 1 and owner.audio_owner is original,
        )
        right.reviewer._cancel_pending_audio()
        check("inactive refresh cannot stop active audio", stop.call_count == 0)
        owner.activate(right)
        check("focus change stops previous pane audio", stop.call_count == 1)
    right_face = right.reviewer.state
    js(
        right.reviewer.web,
        "window.rightSentinel=91;document.querySelector('#keep-input').value='right-resume';",
    )
    owner.toggle()
    owner.toggle()
    wait(lambda: not right.pending)
    check(
        "reopening preserves the right DOM, input and face",
        not right.stale
        and right.reviewer.state == right_face
        and js(
            right.reviewer.web,
            "window.rightSentinel===91 && document.querySelector('#keep-input').value==='right-resume'",
        ),
    )
    from aqt.operations import CollectionOp

    changed_note = mw.col.get_note(right.reviewer.card.nid)
    changed_note["Back"] += " changed-note-marker"
    saved = []
    CollectionOp(parent=mw, op=lambda col: col.update_note(changed_note)).success(
        lambda _: saved.append(True)
    ).run_in_background()
    wait(lambda: bool(saved) and right.stale)
    check(
        "changed note blocks stale grading without replacing the other pane",
        not right.can_act()
        and not left.stale
        and original.card.id == left_id
        and js(original.web, "window.dualSentinel===43"),
    )
    before_count = mw.col.db.scalar("select count(*) from revlog")
    right.reviewer._answerCard(3)
    check(
        "stale card cannot write a review",
        mw.col.db.scalar("select count(*) from revlog") == before_count,
    )
    right.refresh.click()
    wait(
        lambda: (
            not right.pending
            and not right.stale
            and right.reviewer._states_mutated
            and js(
                right.reviewer.web,
                "document.body.textContent.includes('changed-note-marker')",
            )
        )
    )
    check("refresh restores the updated answer", right.reviewer.state == "answer")
    right.deck.setCurrentIndex(right.deck.findData(decks["空牌组"]))
    wait(lambda: not right.pending and right.reviewer.card is None)
    check("empty right deck leaves left usable", not left.stale and left.can_act())
    owner.activate(left, focus=True)
    owner.toggle()
    wait(
        lambda: (
            not owner.enabled
            and mw.learning_workspace.pages.currentWidget()
            is mw.learning_workspace.native
        )
    )
    check(
        "exit restores original renderer and answer",
        mw.reviewer is original
        and original.card.id == left_id
        and original.state == "answer",
    )
    check(
        "exit keeps DOM and typed input",
        js(
            original.web,
            "window.dualSentinel===43 && document.querySelector('#keep-input').value==='preserved'",
        ),
    )
    check(
        "single layout restores the original page order",
        all(workspace.pages.widget(i) is page for i, page in enumerate(page_order)),
    )
    original._answerCard(3)
    wait(lambda: not owner.submitting and ready(left) and original.card.id != left_id)
    check(
        "single review remains schedulable after exit",
        mw.col.db.scalar("select count(*) from revlog") == 1,
    )
    owner.toggle()
    wait(lambda: not right.pending)
    mw.resize(650, 850)
    wait(lambda: owner.compact)
    owner.tabs.setCurrentIndex(1)
    check(
        "compact layout switches to right", owner.active is right and right.isVisible()
    )
    owner.tabs.setCurrentIndex(0)
    check(
        "compact layout retains left card",
        original.card is not None and left.isVisible(),
    )
    mw.grab().save(str(BASE / "dual-review.png"))
    owner.stop()
    mw.learning_workspace.profile_close()
    mw.col.close()
    mw.col = None
except BaseException:
    results["errors"].append(traceback.format_exc())
    print(results["errors"][-1], flush=True)
    if "mw" in globals() and mw:
        mw.grab().save(str(BASE / "failure.png"))
finally:
    results["passed"] = bool(results["checks"]) and not results["errors"]
    (BASE / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print("RESULT", results["passed"], len(results["checks"]), flush=True)
    os._exit(0 if results["passed"] else 1)
