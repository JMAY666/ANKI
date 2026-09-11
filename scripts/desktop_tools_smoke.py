"""Joint desktop acceptance using synthetic cards and a real Qt/WebEngine instance."""

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
    sys.path[:0] = [str(ROOT / p) for p in ("qt", "pylib", "out/qt", "out/pylib")]
name, mode = sys.argv[1:3]
assert Path(name).name == name and name not in (".", "..")
BASE = ROOT / "runtime" / name
os.environ.pop("ANKIDEV", None)
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "desktop-tools-" + name
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
results = {"checks": {}, "errors": []}


def check(label, value):
    results["checks"][label] = bool(value)
    print("CHECK", label, bool(value), flush=True)
    assert value, label


def wait(predicate, timeout=25):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise TimeoutError(str(predicate))


def js(code):
    response = []
    mw.reviewer.web.page().runJavaScript(code, response.append)
    wait(lambda: bool(response))
    return response[0]


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
    pm.create("Desktop")
    pm.load("Desktop")
    pm.profile.update(
        autoSync=False, syncKey=None, syncMedia=False, ts_pen1_color="#1256ab"
    )
    pm.save()
    pm.db.close()
    config = BASE / "Desktop/SynapsePro_Data/addon_settings.json"
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
    col = Collection(str(BASE / "Desktop/collection.anki2"))
    did = col.decks.id("中文合成测试")
    for index in range(12):
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"] = (
            f"<h1>手写测试 {index}</h1><input id='test-input'><div style='height:500px'>绘画与复习</div>"
        )
        note["Back"] = "<h2>合成答案</h2>"
        col.add_note(note, did)
    col.decks.select(did)
    col.close()
    for addon in ("85158043", "812527193"):
        folder = BASE / "addons21" / addon
        folder.mkdir(parents=True)
        (folder / "__init__.py").write_text(
            "raise RuntimeError('legacy must not execute')"
        )


try:
    if mode == "write":
        prepare()
    assert (BASE / ".builtin-test").read_text() == "synthetic data only"
    from PyQt6.QtTest import QTest

    import aqt
    from aqt.builtin_features import initialize, replaces_addon
    from aqt.builtin_features.desktop_tools.settings import Settings
    from aqt.qt import (
        QApplication,
        QDialog,
        QDialogButtonBox,
        QLabel,
        QPoint,
        Qt,
        QTimer,
    )

    app = aqt._run(
        ["anki", "-b", str(BASE), "-p", "Desktop", "-l", "zh_CN"], exec=False
    )
    mw = aqt.mw

    def errors():
        modal = QApplication.activeModalWidget()
        if modal and modal.windowTitle() in ("Anki", "错误"):
            results["errors"].append(
                " | ".join(label.text() for label in modal.findChildren(QLabel))
            )
            modal.reject()

    guard = QTimer()
    guard.timeout.connect(errors)
    guard.start(500)
    wait(lambda: mw.col and mw.state == "deckBrowser" and mw.learning_workspace.store)
    wait(lambda: sys.modules["aqt.builtin_features.synapsepro"]._daily_maintenance_done)
    owner, col = mw.desktop_tools, mw.col
    initialize(mw)
    check(
        "no duplicate Tools menu entry",
        sum(a.text() == "托盘与手写" for a in mw.form.menuTools.actions()) == 0,
    )
    check(
        "legacy copies blocked",
        all(
            replaces_addon(key, str(BASE / "addons21")) and key not in sys.modules
            for key in ("85158043", "812527193")
        ),
    )
    check(
        "existing integrated tools loaded",
        bool(
            mw.learning_workspace
            and mw.passfail2
            and sys.modules.get("aqt.builtin_features.fsrs_helper")
        ),
    )
    check(
        "old partial profile color preserved",
        owner.pen_value["ts_pen1_color"] == "#1256ab",
    )
    if mode == "restart":
        check("handwriting enabled survives restart", owner.pen_value["ts_state_on"])
        check("tray setting survives restart", owner.tray_value["enabled"])
        if owner.tray_value["hide_on_startup"]:
            check("startup hides to tray", not mw.isVisible())
            owner.tray.restore()
        check("review persisted", col.db.scalar("select count(*) from revlog") >= 1)
    else:
        check("tray default preserves normal exit", not owner.tray_value["enabled"])
    mw.resize(1050, 800)
    sidebar = sys.modules["aqt.builtin_features.synapsepro"].sidebar_widget_instance
    anchor = sidebar._desktop_tools_button
    check("sidebar icon available", anchor.isVisible() and not anchor.icon().isNull())
    QTest.mouseClick(anchor, Qt.MouseButton.LeftButton)
    wait(lambda: owner.menu.isVisible())
    check(
        "sidebar opens all desktop tools",
        [action.text() for action in owner.menu.actions()]
        == ["启用卡片手写", "设置…", "使用说明"],
    )
    mw.grab().save(str(BASE / f"{mode}-sidebar.png"))
    owner.menu.grab().save(str(BASE / f"{mode}-sidebar-menu.png"))
    QTest.keyClick(owner.menu, Qt.Key.Key_Escape)
    check("Escape closes sidebar menu", not owner.menu.isVisible())
    owner.set_enabled(True)
    mw.moveToState("review")
    wait(lambda: mw.reviewer.card and js("!!window.ankiPenDown"))
    card_id = mw.reviewer.card.id
    before = col.db.scalar("select count(*) from revlog")
    check("single canvas", js("document.querySelectorAll('#pendown-root').length") == 1)
    check(
        "Chinese canvas controls",
        js("document.querySelector('#ts_pen1_button').title") == "画笔一",
    )
    target = mw.reviewer.web.focusProxy()
    QTest.mousePress(target, Qt.MouseButton.LeftButton, pos=QPoint(150, 150))
    for x in range(160, 261, 10):
        QTest.mouseMove(target, QPoint(x, 170))
        QTest.qWait(20)
    QTest.mouseRelease(target, Qt.MouseButton.LeftButton, pos=QPoint(270, 180))
    wait(lambda: js("window.ankiPenDown.snapshot().strokes.length") == 1)
    check(
        "real mouse stroke has points",
        js("window.ankiPenDown.snapshot().strokes[0].points.length") > 2,
    )
    js("window.ankiPenDown.undo()")
    check(
        "undo removes stroke", js("window.ankiPenDown.snapshot().strokes.length") == 0
    )
    js("window.ankiPenDown.redo()")
    check(
        "redo restores stroke", js("window.ankiPenDown.snapshot().strokes.length") == 1
    )

    def draw(tool, points):
        js(f"document.getElementById('{tool}').click()")
        target = mw.reviewer.web.focusProxy()
        QTest.mousePress(target, Qt.MouseButton.LeftButton, pos=QPoint(*points[0]))
        for point in points[1:-1]:
            QTest.mouseMove(target, QPoint(*point))
            QTest.qWait(30)
        QTest.mouseRelease(target, Qt.MouseButton.LeftButton, pos=QPoint(*points[-1]))
        QTest.qWait(60)

    draw("ts_pen2_button", [(300, 150), (310, 160), (320, 170), (330, 180)])
    check(
        "second pen uses configured color",
        js("window.ankiPenDown.snapshot().strokes.at(-1).color") == "#ff0000",
    )
    js("window.ankiPenDown.undo()")
    draw("ts_highlighter_button", [(300, 210), (310, 220), (320, 230), (330, 240)])
    check(
        "highlighter uses translucent stroke",
        js("window.ankiPenDown.snapshot().strokes.at(-1).opacity") == 0.4,
    )
    js("window.ankiPenDown.undo()")
    draw("ts_eraser_button", [(220, 120), (220, 150), (220, 170), (220, 210)])
    check(
        "eraser removes intersecting whole stroke",
        js("window.ankiPenDown.snapshot().strokes[0].visible") is False,
    )
    js("window.ankiPenDown.undo()")
    check(
        "undo eraser restores stroke",
        js("window.ankiPenDown.snapshot().strokes[0].visible") is True,
    )
    js(
        "document.getElementById('ts_visibility_button').click(); document.getElementById('test-input').focus()"
    )
    QTest.keyClick(mw.reviewer.web.focusProxy(), Qt.Key.Key_Period)
    check(
        "text input does not clear ink",
        js("window.ankiPenDown.snapshot().strokes.length") == 1,
    )
    js(
        "document.getElementById('test-input').blur(); document.getElementById('ts_visibility_button').click()"
    )
    owner.save({**owner.pen_value, "ts_compact_toolbar": True}, dict(owner.tray_value))
    wait(lambda: js("!!window.ankiPenDown"))
    check(
        "settings preserve ink and current card",
        js("window.ankiPenDown.snapshot().strokes.length") == 1
        and mw.reviewer.card.id == card_id
        and col.db.scalar("select count(*) from revlog") == before,
    )
    mw.reviewer._showAnswer()
    wait(lambda: mw.reviewer.state == "answer")
    check(
        "flipping preserves ink",
        js("window.ankiPenDown.snapshot().strokes.length") == 1,
    )
    dialog = Settings(owner)
    dialog.show()
    QTest.qWait(200)
    dialog.grab().save(str(BASE / f"{mode}-settings.png"))
    dialog.controls["ts_zen_mode"].setChecked(True)
    dialog.controls["ts_x_offset"].setValue(100)
    dialog.reset_layout()
    check(
        "layout reset preserves pen color",
        dialog.controls["ts_x_offset"].value() == 2
        and dialog.controls["ts_pen1_color"].text() == "#1256ab",
    )
    dialog.reject()
    check("cancel does not save settings", not owner.pen_value["ts_zen_mode"])
    saved = Settings(owner)
    saved.show()
    saved.controls["ts_line_width"].setValue(6.5)
    button = saved.findChild(QDialogButtonBox).button(
        QDialogButtonBox.StandardButton.Save
    )
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    check(
        "settings Save applies without changing card",
        owner.pen_value["ts_line_width"] == 6.5 and mw.reviewer.card.id == card_id,
    )
    mw.resize(620, 650)
    QTest.qWait(200)
    narrow = Settings(owner)
    narrow.resize(400, 480)
    narrow.show()
    QTest.qWait(150)
    narrow.grab().save(str(BASE / f"{mode}-settings-narrow.png"))
    check("narrow settings fit window", narrow.width() <= 620)
    narrow.reject()
    mw.resize(1050, 800)
    for full in (False, True):
        (mw.showFullScreen if full else mw.showNormal)()
        for zoom in (0.8, 1, 1.5):
            mw.reviewer.web.setZoomFactor(zoom)
            QTest.qWait(150)
            check(
                f"toolbar bounded full={full} zoom={zoom}",
                js(
                    "(()=>{const r=document.getElementById('pencil_button_bar').getBoundingClientRect();return r.width>0 && r.right<=innerWidth+1 && r.bottom<=innerHeight+1 && r.top>=0 && r.left>=0})()"
                ),
            )
            mw.grab().save(str(BASE / f"{mode}-full-{full}-zoom-{zoom}.png"))
    mw.showNormal()
    mw.reviewer.web.setZoomFactor(1)
    owner.save(dict(owner.pen_value), {**owner.tray_value, "enabled": True})
    child = QDialog(mw)
    child.setWindowTitle("合成子窗口")
    child.show()
    closed = QDialog(mw)
    closed.setWindowTitle("不应恢复的窗口")
    check("system tray available", owner.tray.available())
    owner.tray.hide()
    check("tray hides visible windows", not mw.isVisible() and not child.isVisible())
    owner.tray.restore()
    check(
        "tray restores only previously visible windows",
        mw.isVisible() and child.isVisible() and not closed.isVisible(),
    )
    child.close()
    mw.showFullScreen()
    mw.close()
    check(
        "close hides without closing collection", not mw.isVisible() and mw.col is col
    )
    owner.tray.restore()
    check("tray preserves fullscreen state", mw.isFullScreen())
    mw.showNormal()
    owner.set_enabled(False)
    wait(lambda: js("!window.ankiPenDown"))
    check(
        "disable does not reset answer",
        mw.reviewer.card.id == card_id and mw.reviewer.state == "answer",
    )
    owner.set_enabled(True)
    wait(lambda: js("!!window.ankiPenDown"))
    mw.reviewer._answerCard(3)
    wait(lambda: col.db.scalar("select count(*) from revlog") > before)
    wait(lambda: mw.reviewer.card.id != card_id and js("!!window.ankiPenDown"))
    check(
        "next card clears ink", js("window.ankiPenDown.snapshot().strokes.length") == 0
    )
    mw.moveToState("deckBrowser")
    wait(lambda: mw.state == "deckBrowser")
    check("no card writes", col.db.scalar("select count(*) from cards") == 12)
    owner.save(dict(owner.pen_value), {**owner.tray_value, "hide_on_startup": True})
    mw.pm.save()
    mw.form.actionExit.trigger()
    wait(lambda: mw.col is None)
    check("normal exit closes collection", mw.col is None)
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
