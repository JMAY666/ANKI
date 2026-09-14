"""Previous-card acceptance in a real WebEngine UI with synthetic data only."""

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
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "review-undo-" + name
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


def ready(reviewer, card_id=None):
    return (
        not mw._background_op_count
        and reviewer.card
        and (card_id is None or reviewer.card.id == card_id)
        and reviewer.state in ("question", "answer")
        and reviewer._states_mutated
        and js(reviewer.web, "document.querySelector('#qa h2')?.textContent")
        == reviewer.card.note()["Front"].split("<h2>", 1)[1].split("</h2>", 1)[0]
        and js(reviewer.bottom.web, "!!document.getElementById('previous-card')")
    )


def grade(reviewer, ease):
    wait(lambda: ready(reviewer))
    card_id = reviewer.card.id
    if reviewer.state == "question":
        reviewer._showAnswer()
    reviewer._answerCard(ease)
    wait(lambda: ready(reviewer) and reviewer.card.id != card_id)
    return card_id


def previous(reviewer, card_id, double=False):
    mw.activateWindow()
    reviewer.bottom.web.setFocus()
    wait(
        lambda: QApplication.focusWidget() and QApplication.focusWidget().window() is mw
    )
    wait(
        lambda: js(
            reviewer.bottom.web,
            "document.getElementById('previous-card')?.disabled === false",
        )
    )
    if reviewer.web is mw.web:
        button = mw.learning_workspace.native.previous_button
        wait(lambda: button.isEnabled())
        button.click()
        if double:
            button.click()
        wait(lambda: ready(reviewer, card_id))
        return
    js(
        reviewer.bottom.web,
        "{ const button=document.getElementById('previous-card');"
        "const token=button.dataset.undoStep; button.click();"
        + ("pycmd('reviewPrevious:'+token);" if double else "")
        + "}",
    )
    wait(lambda: ready(reviewer, card_id))


def schedule():
    return mw.col.db.all(
        "select id,did,type,queue,due,ivl,factor,reps,lapses,left,odue,odid,data "
        "from cards order by id"
    )


try:
    from anki.collection import Collection
    from anki.lang import set_lang
    from aqt.profiles import ProfileManager

    set_lang("en_US")
    pm = ProfileManager(str(BASE))
    pm.setupMeta()
    pm.meta.update(defaultLang="zh_CN", firstRun=False, updates=False)
    pm.create("Review-Undo-Test")
    pm.load("Review-Undo-Test")
    pm.profile.update(autoSync=False, syncKey=None, syncMedia=False)
    pm.save()
    pm.db.close()
    profile = BASE / "Review-Undo-Test"
    settings = profile / "SynapsePro_Data/addon_settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"onboarding_completed": True, "gamification_popups_enabled": False})
    )
    col = Collection(str(profile / "collection.anki2"))
    model = col.models.by_name("Basic")
    decks = [col.decks.id("返回测试::" + side) for side in ("左", "右")]
    for deck in decks:
        for index in range(5):
            note = col.new_note(model)
            note["Front"] = f"<h2>合成卡片 {index + 1}</h2>测试误评分后返回。"
            note["Back"] = f"<p>合成答案 {index + 1}</p>"
            col.add_note(note, deck)
    col.decks.select(decks[0])
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
            "Review-Undo-Test",
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
    mw.resize(1200, 850)
    mw.activateWindow()
    mw.moveToState("review")
    reviewer = mw.reviewer
    wait(lambda: ready(reviewer))
    before = schedule()
    native = mw.learning_workspace.native
    check(
        "previous control is left of the card and vertically centered",
        native.previous_button.geometry().right() < native.viewport.geometry().left()
        and abs(
            native.previous_button.geometry().center().y()
            - native.viewport.geometry().center().y()
        )
        <= 1,
    )
    reviewer._showAnswer()
    wait(lambda: js(reviewer.bottom.web, "!!document.getElementById('defease')"))
    check(
        "rating group is centered in the review area",
        js(
            reviewer.bottom.web,
            "{const r=document.getElementById('middle').getBoundingClientRect(); Math.abs((r.left+r.right)/2-innerWidth/2)<2}",
        ),
    )
    mw.grab().save(str(BASE / "side-layout.png"))
    check(
        "first card has a disabled previous button",
        js(reviewer.bottom.web, "document.getElementById('previous-card').disabled"),
    )
    first = grade(reviewer, 3)
    second = grade(reviewer, 4)
    previous(reviewer, second, double=True)
    check(
        "double click returns one card and removes exactly one rating",
        mw.col.db.scalar("select count(*) from revlog") == 1,
    )
    previous(reviewer, first)
    check("consecutive undo restores original scheduling", schedule() == before)
    check(
        "consecutive undo removes old ratings",
        not mw.col.db.scalar("select count(*) from revlog"),
    )
    grade(reviewer, 3)
    previous(reviewer, first)
    grade(reviewer, 4)
    check(
        "regrading records only the corrected result",
        mw.col.db.all("select cid,ease from revlog") == [[first, 4]],
    )

    from aqt.operations.note import update_note

    note = reviewer.card.note()
    note["Back"] = "保留这次编辑"
    update_note(parent=mw, note=note).run_in_background()
    wait(lambda: not mw._background_op_count)
    wait(
        lambda: js(
            reviewer.bottom.web, "document.getElementById('previous-card').disabled"
        )
    )
    reviewer._undo_previous_card(str(mw.col.undo_status().last_step))
    check(
        "previous cannot discard an intervening edit",
        mw.col.get_note(note.id)["Back"] == "保留这次编辑",
    )
    mw.undo()
    wait(
        lambda: (
            not mw._background_op_count and reviewer._previous_card_step() is not None
        )
    )
    previous(reviewer, first)

    mw.passfail2.save(mw.passfail2.value | {"enabled": True})
    wait(lambda: ready(reviewer))
    grade(reviewer, 3)
    previous(reviewer, first)
    check("two-grade mode also restores scheduling", schedule() == before)
    mw.passfail2.save(mw.passfail2.value | {"enabled": False})

    from aqt.builtin_features.review_tools.config import get_config

    policy = get_config("policy")
    old_style = policy["style"]
    mw.review_tools.config.save("policy", policy | {"style": "advanced"})
    mw.review_tools.changed()
    wait(lambda: not reviewer.bottom.web.page().isLoading())
    wait(lambda: ready(reviewer))
    check(
        "advanced toolbar has the same previous control",
        js(reviewer.bottom.web, "document.querySelectorAll('#previous-card').length")
        == 1,
    )
    grade(reviewer, 3)
    previous(reviewer, first)
    check("advanced toolbar restores scheduling", schedule() == before)
    mw.grab().save(str(BASE / "advanced.png"))
    mw.review_tools.config.save("policy", policy | {"style": old_style})
    mw.review_tools.changed()
    wait(lambda: not reviewer.bottom.web.page().isLoading())

    owner = mw.dual_review
    owner.toggle()
    left, right = owner.panels
    wait(lambda: not left.pending and not right.pending)
    right.deck.setCurrentIndex(right.deck.findData(decks[1]))
    wait(lambda: not right.pending and ready(right.reviewer))
    owner.activate(right, focus=True)
    right_id = grade(right.reviewer, 3)
    owner.activate(left, focus=True)
    previous(left.reviewer, first)
    wait(lambda: not right.pending and ready(right.reviewer, right_id))
    check(
        "left previous button restores latest right rating in its original pane",
        owner.active is right and schedule() == before,
    )
    check(
        "dual previous removes the actual latest review",
        mw.col.db.scalar("select count(*) from revlog") == 0,
    )
    mw.grab().save(str(BASE / "dual.png"))
    owner.toggle()
    wait(lambda: not owner.enabled)
    mw.resize(560, 750)
    wait(lambda: ready(mw.reviewer))
    wait(
        lambda: js(
            mw.reviewer.bottom.web,
            "[...document.querySelectorAll('#innertable button')].every(b => b.getBoundingClientRect().right <= innerWidth + 1)",
        )
    )
    check(
        "previous button remains visible in a narrow window",
        native.previous_button.isVisible()
        and native.viewport.geometry().right() <= native.width(),
    )
    mw.grab().save(str(BASE / "narrow.png"))
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
