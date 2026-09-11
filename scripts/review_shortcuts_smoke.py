"""Exercise review keys through real Qt/WebEngine using a disposable collection."""

import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if package := os.environ.get("ANKI_BUILTIN_PACKAGE_ROOT"):
    sys.path.insert(0, str(Path(package) / "app_packages"))
else:
    sys.path[:0] = [str(ROOT / item) for item in ("qt", "pylib", "out/qt", "out/pylib")]
name = sys.argv[1]
assert name and Path(name).name == name and name not in (".", "..")
BASE = ROOT / "runtime" / name
PROFILE = BASE / "Shortcut-Test"
assert not BASE.exists(), "Use a fresh synthetic profile"
os.environ.pop("ANKIDEV", None)
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "shortcut-smoke-" + name
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
results = {"checks": {}, "errors": []}


def check(label, value):
    results["checks"][label] = bool(value)
    print("CHECK", label, bool(value), flush=True)
    assert value, label


def wait(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise TimeoutError(str(predicate))


def settle():
    deadline = time.monotonic() + 0.25
    wait(lambda: time.monotonic() >= deadline and not mw._background_op_count)


def js(web, code):
    values = []
    web.page().runJavaScript(code, values.append)
    wait(lambda: bool(values))
    return values[0]


def snapshot():
    return (
        mw.reviewer.card.id if mw.reviewer.card else None,
        mw.reviewer.state,
        mw.col.db.scalar("select count(*) from revlog"),
    )


def focus_card():
    mw.activateWindow()
    mw.web.setFocus()
    js(mw.web, "document.activeElement?.blur()")
    wait(lambda: js(mw.web, "ankiReviewShortcutAllowed()"))


def press(key):
    results["last_key"] = {
        "key": key.name,
        "available": mw.reviewer.shortcuts.available(),
        "focus": type(app.focusWidget()).__name__,
        "active": type(QApplication.activeWindow()).__name__,
        "pending": mw.reviewer.shortcuts.pending is not None,
        "snapshot": snapshot(),
    }
    QTest.keyClick(app.focusWidget() or mw, key)
    settle()


def show_answer():
    focus_card()
    press(Qt.Key.Key_Space)
    wait(
        lambda: (
            mw.reviewer.state == "answer"
            and js(mw.bottomWeb, "!!document.querySelector('button[data-ease]')")
        )
    )


def prepare():
    from anki.collection import Collection
    from anki.lang import set_lang
    from aqt.profiles import ProfileManager

    BASE.mkdir(parents=True)
    (BASE / ".builtin-test").write_text("synthetic data only")
    set_lang("en_US")
    pm = ProfileManager(str(BASE))
    pm.setupMeta()
    pm.meta.update(
        defaultLang="zh_CN", firstRun=False, updates=False, spacebar_rates_card=True
    )
    pm.create("Shortcut-Test")
    pm.load("Shortcut-Test")
    pm.profile.update(autoSync=False, syncKey=None, syncMedia=False)
    pm.save()
    pm.db.close()
    config = PROFILE / "SynapsePro_Data/addon_settings.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "onboarding_completed": True,
                "gamification_popups_enabled": False,
                "minimal_dashboard_enabled": False,
            }
        )
    )
    col = Collection(str(PROFILE / "collection.anki2"))
    did = col.decks.id("Shortcut synthetic cards")
    model = col.models.by_name("Basic")
    for index in range(16):
        note = col.new_note(model)
        content = f'<h2>Synthetic {index}</h2><input id="edit"><textarea id="area"></textarea><div contenteditable="true" id="rich">Edit</div><iframe id="frame" srcdoc="&lt;input id=inner&gt;"></iframe>'
        note["Front"] = content
        note["Back"] = "Answer" + content
        col.add_note(note, did)
    col.decks.select(did)
    col.close()


try:
    prepare()
    from PyQt6.QtTest import QTest

    import aqt
    from aqt.qt import (
        QApplication,
        QDialog,
        QInputMethodEvent,
        QKeyEvent,
        QKeySequence,
        QLineEdit,
        QMenu,
        QShortcut,
        Qt,
        QVBoxLayout,
    )

    app = aqt._run(
        ["anki", "-b", str(BASE), "-p", "Shortcut-Test", "--safemode", "-l", "zh_CN"],
        exec=False,
    )
    mw = aqt.mw
    wait(lambda: mw.col and mw.state == "deckBrowser" and mw.learning_workspace.store)
    wait(lambda: sys.modules["aqt.builtin_features.synapsepro"]._daily_maintenance_done)
    mw.activateWindow()
    mw.raise_()
    wait(
        lambda: (
            not mw._background_op_count
            and js(
                mw.web,
                """(()=>{
        const page = document.querySelector('.deck-workspace');
        const button = page?.querySelector('.deck-start');
        if (!button || page.dataset.ready !== 'true') return false;
        button.click();
        return true;
    })()""",
            )
        )
    )
    wait(
        lambda: (
            mw.reviewer.state == "question"
            and mw.reviewer._states_mutated
            and js(mw.web, "typeof ankiReviewShortcutAllowed === 'function'")
        )
    )
    w, pf = mw.learning_workspace, mw.passfail2
    before = snapshot()
    show_answer()
    check(
        "front space shows one answer without a review record",
        snapshot()[2] == before[2],
    )
    for key in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
        before = snapshot()
        press(key)
        check(
            f"answer {key.name} cannot rate even with the legacy preference enabled",
            snapshot() == before,
        )
    mw.bottomWeb.setFocus()
    js(mw.bottomWeb, "document.querySelector('button[data-ease]').focus()")
    before = snapshot()
    press(Qt.Key.Key_Space)
    press(Qt.Key.Key_Return)
    check(
        "focused rating button cannot be activated by space or enter",
        snapshot() == before,
    )
    w.finish_button.setFocus()
    press(Qt.Key.Key_Space)
    check(
        "space on native finish button does not end review",
        mw.state == "review" and snapshot() == before,
    )

    for enabled in (True, False, True, False):
        pf.save(pf.value | {"enabled": enabled})
        settle()
        keys = [shortcut.key().toString() for shortcut in mw.stateShortcuts]
        check(
            f"mode switch {enabled} registers each key once {len(results['checks'])}",
            len(keys) == len(set(keys)) and keys.count("1") == keys.count("2") == 1,
        )
        if enabled:
            check(
                "two-grade keys 3 and 4 are absent", "3" not in keys and "4" not in keys
            )
            hints = js(
                mw.bottomWeb,
                "Array.from(document.querySelectorAll('button[data-ease]')).map(b=>[b.dataset.ease,b.title])",
            )
            check(
                "two-grade button hints show 1 and 2",
                re.findall(r"\d+", hints[0][1]) == ["1"]
                and re.findall(r"\d+", hints[1][1]) == ["2"],
            )

    for enabled, keys in (
        (
            False,
            (
                (Qt.Key.Key_1, 1),
                (Qt.Key.Key_2, 2),
                (Qt.Key.Key_3, 3),
                (Qt.Key.Key_4, 4),
            ),
        ),
        (True, ((Qt.Key.Key_1, 1), (Qt.Key.Key_2, 3))),
    ):
        pf.save(pf.value | {"enabled": enabled})
        for key, rating in keys:
            if mw.reviewer.state == "question":
                show_answer()
            focus_card()
            before = snapshot()
            if enabled:
                press(Qt.Key.Key_3)
                press(Qt.Key.Key_4)
                check(
                    f"unused two-grade keys do not rate before {key.name}",
                    snapshot() == before,
                )
            press(key)
            wait(
                lambda: (
                    mw.reviewer.state == "question" and snapshot()[2] == before[2] + 1
                )
            )
            check(
                f"mode {enabled} key {key.name} records only rating {rating}",
                mw.col.db.scalar("select ease from revlog order by id desc limit 1")
                == rating,
            )

    show_answer()
    for style in ("colours", "advanced", "current"):
        tools = mw.review_tools
        tools.config.save("policy", tools.config.values["policy"] | {"style": style})
        tools.changed()
        settle()
        hints = js(
            mw.bottomWeb,
            "Array.from(document.querySelectorAll('button[data-ease]')).map(b=>[b.dataset.ease,b.title])",
        )
        check(
            f"{style} style preserves two-grade key hints",
            len(hints) == 2
            and re.findall(r"\d+", hints[0][1]) == ["1"]
            and re.findall(r"\d+", hints[1][1]) == ["2"],
        )
    focus_card()
    press(Qt.Key.Key_2)
    wait(lambda: mw.reviewer.state == "question")

    from unittest.mock import patch

    from aqt.preferences import Preferences

    pf.save(pf.value | {"enabled": False})
    preferences = Preferences(mw)
    preferences.show()
    wait(lambda: preferences.web._domDone)
    preferences.answer_key_edits[1].setText("Space")
    with patch("aqt.preferences.showWarning") as warning:
        preferences.accept()
        check(
            "conflicting preference is rejected without saving",
            warning.called and mw.pm.get_answer_key(1) == "1",
        )
    preferences.answer_key_edits[1].setText("8")
    preferences.accept()
    wait(lambda: not preferences.isVisible())
    show_answer()
    before = snapshot()
    press(Qt.Key.Key_1)
    check(
        "old four-grade key stops immediately after saving preferences",
        snapshot() == before,
    )
    press(Qt.Key.Key_8)
    wait(lambda: mw.reviewer.state == "question" and snapshot()[2] == before[2] + 1)
    check(
        "new four-grade key submits its intended rating immediately",
        mw.col.db.scalar("select ease from revlog order by id desc limit 1") == 1,
    )
    preferences = Preferences(mw)
    preferences.show()
    wait(lambda: preferences.web._domDone)
    preferences.answer_key_edits[1].setText("1")
    preferences.accept()
    wait(lambda: not preferences.isVisible())
    pf.save(pf.value | {"enabled": True})

    for selector in ("#edit", "#area", "#rich", "#frame"):
        focus_card()
        if selector == "#frame":
            js(
                mw.web,
                "document.querySelector('#frame').contentDocument.querySelector('input').focus()",
            )
        else:
            js(mw.web, f"document.querySelector('{selector}').focus()")
        before = snapshot()
        for key in (
            Qt.Key.Key_Space,
            Qt.Key.Key_Return,
            Qt.Key.Key_1,
            Qt.Key.Key_2,
            Qt.Key.Key_D,
        ):
            press(key)
        check(
            f"editor {selector} keeps input without review or navigation",
            mw.state == "review" and snapshot() == before,
        )

    focus_card()
    before = snapshot()
    js(mw.web, "document.dispatchEvent(new CompositionEvent('compositionstart'))")
    press(Qt.Key.Key_Space)
    press(Qt.Key.Key_Return)
    check("web IME composition cannot reveal or rate", snapshot() == before)
    js(mw.web, "document.dispatchEvent(new CompositionEvent('compositionend'))")
    event = QInputMethodEvent("拼音", [])
    QApplication.sendEvent(app.focusWidget(), event)
    press(Qt.Key.Key_Space)
    press(Qt.Key.Key_Return)
    check("Qt IME preedit cannot reveal or submit a review", snapshot() == before)
    QApplication.sendEvent(app.focusWidget(), QInputMethodEvent())

    dialog = QDialog(mw)
    layout = QVBoxLayout(dialog)
    edit = QLineEdit(dialog)
    layout.addWidget(edit)
    dialog.setModal(True)
    dialog.show()
    edit.setFocus()
    settle()
    for key in (Qt.Key.Key_1, Qt.Key.Key_Space, Qt.Key.Key_Return):
        press(key)
    check(
        "modal dialog input cannot operate the underlying review", snapshot() == before
    )
    dialog.reject()
    focus_card()
    menu = QMenu(mw)
    menu.addAction("Synthetic menu action")
    menu.popup(mw.mapToGlobal(mw.rect().center()))
    settle()
    press(Qt.Key.Key_2)
    check("popup menu owns rating keys", snapshot() == before)
    menu.close()
    focus_card()
    QTest.keyPress(app.focusWidget(), Qt.Key.Key_Space)
    settle()
    for _ in range(8):
        QApplication.sendEvent(
            app.focusWidget(),
            QKeyEvent(
                QKeyEvent.Type.KeyPress,
                Qt.Key.Key_Space,
                Qt.KeyboardModifier.NoModifier,
                " ",
                True,
                1,
            ),
        )
        settle()
    QTest.keyRelease(app.focusWidget(), Qt.Key.Key_Space)
    check(
        "held space reveals one answer and records no rating",
        mw.reviewer.state == "answer" and snapshot()[2] == before[2],
    )

    for index in range(4):
        before = snapshot()
        w.open(0)
        settle()
        press(Qt.Key.Key_Space)
        press(Qt.Key.Key_2)
        check(
            f"statistics page ignores review keys {index}",
            snapshot() == before and not mw.stateShortcuts,
        )
        w.show_review()
        settle()
        focus_card()
        check(f"resuming preserves the card and answer {index}", snapshot() == before)
    mw.grab().save(str(BASE / "review.png"))
    before_count = snapshot()[2]
    press(Qt.Key.Key_D)
    wait(lambda: mw.state == "deckBrowser")
    press(Qt.Key.Key_Space)
    press(Qt.Key.Key_2)
    check(
        "leaving review removes its shortcuts",
        mw.state == "deckBrowser"
        and mw.col.db.scalar("select count(*) from revlog") == before_count,
    )
    w.profile_close()
    mw.pm.save()
    mw.col.close()
    mw.col = None
except BaseException:
    results["errors"].append(traceback.format_exc())
    print(results["errors"][-1], flush=True)
    print("DIAGNOSTICS", json.dumps(results.get("last_key")), flush=True)
    if "mw" in globals() and mw:
        print("CURRENT", snapshot(), mw.reviewer.shortcuts.snapshot(), flush=True)
        print(
            "SHORTCUTS",
            [(s.key().toString(), s.isEnabled()) for s in mw.stateShortcuts],
            flush=True,
        )
        mw.grab().save(str(BASE / "failure.png"))
finally:
    results["passed"] = (
        bool(results["checks"])
        and all(results["checks"].values())
        and not results["errors"]
    )
    (BASE / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print("RESULT", results["passed"], len(results["checks"]), flush=True)
    os._exit(0 if results["passed"] else 1)
