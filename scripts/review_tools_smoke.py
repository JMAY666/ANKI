"""One real Anki instance, all built-ins, synthetic data, no paid API calls."""

import json
import os
import sys
import time
import traceback
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if package := os.environ.get("ANKI_BUILTIN_PACKAGE_ROOT"):
    sys.path.insert(0, str(Path(package) / "app_packages"))
else:
    sys.path[:0] = [str(ROOT / item) for item in ("qt", "pylib", "out/qt", "out/pylib")]
name = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else "write"
assert name and Path(name).name == name and name not in (".", "..")
BASE = ROOT / "runtime" / name
PROFILE = BASE / "Review-Tools-Test"
os.environ.pop("ANKIDEV", None)
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "review-tools-smoke-" + name
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
results = {"checks": {}, "errors": [], "mode": mode}


def check(label, value):
    results["checks"][label] = bool(value)
    print("CHECK", label, bool(value), flush=True)
    assert value, label


def prepare():
    from anki.collection import Collection
    from anki.lang import set_lang
    from aqt.profiles import ProfileManager

    assert not BASE.exists(), "Use a fresh synthetic run name"
    BASE.mkdir(parents=True)
    (BASE / ".builtin-test").write_text("synthetic data only")
    set_lang("en_US")
    pm = ProfileManager(str(BASE))
    pm.setupMeta()
    pm.meta.update(defaultLang="zh_CN", firstRun=False, updates=False)
    pm.create("Review-Tools-Test")
    pm.load("Review-Tools-Test")
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
                "minimal_dashboard_enabled": True,
            }
        )
    )
    # No additional add-on is installed: these inert fixtures detect double loading.
    for addon in (
        "236979321",
        "759844606",
        "876946123",
        "1323545382",
        "2494384865",
        "1613056169",
        "1136455830",
        "2060144143",
        "1659223841",
    ):
        legacy = BASE / "addons21" / addon
        legacy.mkdir(parents=True)
        (legacy / "__init__.py").write_text(
            "raise RuntimeError('legacy duplicate loaded')"
        )
        (legacy / "meta.json").write_text(
            json.dumps({"disabled": addon == "876946123"})
        )
    col = Collection(str(PROFILE / "collection.anki2"))
    col.set_config("fsrs", True)
    model = col.models.by_name("Basic")
    for label in ("病理::基础", "生理::基础", "限额"):
        did = col.decks.id(label)
        for index in range(12):
            note = col.new_note(model)
            note["Front"] = f"Synthetic {label} {index}"
            note["Back"] = "Synthetic answer"
            col.add_note(note, did)
            card = note.cards()[0]
            if label != "限额":
                card.type = card.queue = 2
                card.ivl, card.reps, card.due = 20, 14, col.sched.today
                if index == 10:
                    card.queue = -1
                elif index == 11:
                    card.due += 5
                col.update_card(card)
        if label == "限额":
            deck = col.decks.get(did)
            deck["newLimit"] = 0
            col.decks.update_dict(deck)
    for index, cid in enumerate(col.find_cards('deck:"生理::基础" -is:suspended')[:4]):
        for days, ease, duration in (
            (9, 3, 1000),
            (7, 1, 10000),
            (5, 3, 10000),
            (3, 3, 10000),
        ):
            col.db.execute(
                "insert into revlog values (?,?,?,?,?,?,?,?,?)",
                col.sched.day_cutoff * 1000 - days * 86400000 + index,
                cid,
                -1,
                ease,
                20,
                10,
                2500,
                duration,
                1,
            )
    for index in range(160):
        col.decks.id(f"大量牌组::{index:03}::基础")
    col.decks.id("空牌组")
    col.decks.select(col.decks.id("病理::基础"))
    col.close()


def wait(predicate, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.02)
    raise TimeoutError(str(predicate))


def js(web, code):
    answer = []
    wait(lambda: web._domDone and not web.page().isLoading())
    web.page().runJavaScript(code, answer.append)
    wait(lambda: bool(answer))
    return answer[0]


def screenshot(label):
    wait(lambda: not mw._background_op_count)
    # QWebEngine DOM callbacks precede compositor painting; allow a frame to land.
    until = time.monotonic() + 0.35
    wait(lambda: time.monotonic() >= until)
    mw.grab().save(str(BASE / f"{mode}-{label}.png"))
    popup = QApplication.activePopupWidget()
    if popup:
        popup.grab().save(str(BASE / f"{mode}-{label}-popup.png"))


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


def buttons():
    return js(
        mw.bottomWeb,
        "Array.from(document.querySelectorAll('button[data-ease]')).map(b=>Number(b.dataset.ease))",
    )


def snapshot():
    return {
        table: col.db.all(f"select * from {table} order by id")
        for table in ("cards", "notes", "revlog")
    }


def switch_style(style):
    tools.config.save("policy", tools.config.values["policy"] | {"style": style})
    tools.changed()
    wait(lambda: not mw.bottomWeb.page().isLoading() and buttons())


try:
    if mode == "write":
        prepare()
    assert (BASE / ".builtin-test").read_text() == "synthetic data only"
    from PyQt6.QtTest import QSignalSpy, QTest

    import aqt
    from aqt.builtin_features import initialize, replaces_addon
    from aqt.builtin_features.review_tools.config import FEATURES
    from aqt.builtin_features.review_tools.settings import ToolSettings
    from aqt.progress import ProgressDialog
    from aqt.qt import QApplication, QLabel, Qt, QTextBrowser, QTimer

    app = aqt._run(
        ["anki", "-b", str(BASE), "-p", "Review-Tools-Test", "-l", "zh_CN"], exec=False
    )
    mw = aqt.mw

    def dialog_guard():
        modal = QApplication.activeModalWidget()
        if modal and not isinstance(modal, (ProgressDialog, ToolSettings)):
            results["errors"].append(
                " | ".join(label.text() for label in modal.findChildren(QLabel))
            )
            print(
                "DIALOG",
                list(results["checks"])[-1:],
                results["errors"][-1],
                flush=True,
            )
            modal.reject()

    guard = QTimer()
    guard.timeout.connect(dialog_guard)
    guard.start(500)
    wait(lambda: mw.col and mw.state == "deckBrowser" and mw.learning_workspace.store)
    wait(lambda: sys.modules["aqt.builtin_features.synapsepro"]._daily_maintenance_done)
    col, w, pf, tools = mw.col, mw.learning_workspace, mw.passfail2, mw.review_tools
    mw.resize(1380, 850)
    mw.activateWindow()
    did = col.decks.id("病理::基础")
    results["source"] = sys.modules["aqt.builtin_features.review_tools"].__file__
    home(did)
    initialize(mw)
    check(
        "all six tools are source-integrated with the existing three",
        all(key in tools.config.values for key in FEATURES)
        and pf is not None
        and "aqt.builtin_features.fsrs_helper" in sys.modules,
    )
    check(
        "one integration menu after reinitialization",
        sum(a.text() == "复习与统计扩展" for a in mw.form.menuTools.actions()) == 1,
    )
    check(
        "all old copies skipped in the same process",
        all(
            replaces_addon(key, str(BASE / "addons21")) and key not in sys.modules
            for ids in FEATURES.values()
            for key in ids
        ),
    )
    if mode == "restart":
        expected = json.loads((BASE / "expected-tools.json").read_text())
        check(
            "all saved feature configurations survive new process",
            tools.config.values == expected["config"],
        )
        check(
            "review record count persists",
            col.db.scalar("select count(*) from revlog") == expected["reviews"],
        )
        check(
            "no overlays on home after restart",
            not tools.feedback.label.isVisible()
            and not tools.pace.overlay.isVisible()
            and not mw.bottomWeb.isVisible(),
        )
    else:
        check(
            "approved defaults preserve current buttons and silence feedback",
            tools.config.values["policy"]["style"] == "current"
            and tools.config.values["policy"]["feedback"] == "off"
            and not tools.config.values["advanced_review"]["Button_   Skip Button"],
        )
        js(mw.web, "document.querySelector('.deck-study-card').click()")
        wait(
            lambda: (
                mw.state == "review"
                and mw.reviewer.state == "question"
                and js(mw.bottomWeb, "!!document.getElementById('ansbut')")
            )
        )
        wait(tools.pace.overlay.isVisible)
        check(
            "pace graph appears with native review",
            tools.pace.model.current is not None,
        )
        tools.pace.toggle_pause()
        check("pace pause works", tools.pace.model.paused)
        tools.pace.toggle_pause()
        tools.pace.hide_temporarily()
        check("temporary graph hide works", not tools.pace.overlay.isVisible())
        tools.pace.toggle_visible()
        tools.pace.config["position"] = [-999999, -999999]
        tools.pace.restore_position()
        check(
            "pace offscreen position recovers",
            any(
                screen.availableGeometry().contains(tools.pace.overlay.geometry())
                for screen in QApplication.screens()
            ),
        )
        tools.pace.configure()
        wait(lambda: tools.pace.dialog is not None)
        pace_original = dict(tools.pace.config)
        tools.pace.dialog.reject()
        check(
            "pace settings cancel restores model and appearance",
            tools.pace.config == pace_original,
        )
        from aqt.qt import QDoubleSpinBox, QPushButton

        tools.pace.configure()
        tools.pace.dialog.findChildren(QDoubleSpinBox)[0].setValue(13.0)
        for button in tools.pace.dialog.findChildren(QPushButton):
            if button.text() == "保存设置":
                button.click()
                break
        check(
            "pace settings save updates goal and persists",
            tools.pace.model.goal == 13.0
            and tools.config.values["pace_graph"]["goal"] == 13.0,
        )
        mw.reviewer._showAnswer()
        wait(lambda: buttons() == [1, 2, 3, 4])
        baseline = snapshot()
        cid = mw.reviewer.card.id
        js(mw.web, "window.__keepReviewTools='card-state-kept'")
        for style in ("colours", "advanced", "current", "advanced"):
            switch_style(style)
            check(
                f"{style} preserves four ratings and current card",
                buttons() == [1, 2, 3, 4] and mw.reviewer.card.id == cid,
            )
            check(
                f"{style} preserves card document",
                js(mw.web, "window.__keepReviewTools") == "card-state-kept",
            )
        config = tools.config.values["advanced_review"]
        for style in range(8):
            tools.config.save(
                "advanced_review", config | {" Review_ Buttons Style": style}
            )
            tools.changed()
            wait(lambda: buttons() == [1, 2, 3, 4])
        check(
            "all eight original Advanced button designs render", not results["errors"]
        )
        mw.resize(780, 560)
        wait(lambda: mw.width() <= 850)
        check(
            "narrow Advanced buttons are present and fit",
            js(
                mw.bottomWeb,
                "[...document.querySelectorAll('button[data-ease]')].every(b=>{const r=b.getBoundingClientRect();return r.width>0&&r.right<=innerWidth+1&&r.bottom<=document.body.scrollHeight+1})",
            ),
        )
        mw.on_toggle_full_screen()
        wait(mw.isFullScreen)
        check(
            "fullscreen keeps active Advanced ratings",
            buttons() == [1, 2, 3, 4] and mw.bottomWeb.review_controls_active(),
        )
        mw.on_toggle_full_screen()
        wait(lambda: not mw.isFullScreen())
        mw.resize(1380, 850)
        pf.save(
            pf.value
            | {
                "enabled": True,
                "toggle_names_textcolors": "1",
                "again_button_name": "失败测试",
                "good_button_name": "通过测试",
                "again_button_textcolor": "#123456",
                "good_button_textcolor": "#654321",
            }
        )
        for style in ("colours", "advanced", "current"):
            switch_style(style)
            wait(lambda: buttons() == [1, 3])
            check(
                f"PassFail names and colors win in {style}",
                "通过测试" in js(mw.bottomWeb, "document.body.innerText")
                and "#654321" in js(mw.bottomWeb, "document.body.innerHTML"),
            )
        check(
            "mode and layout changes do not modify collection data",
            snapshot() == baseline,
        )
        settings = ToolSettings(tools)
        before = json.dumps(tools.config.values, sort_keys=True)
        settings.fields[("policy", "feedback")].setCurrentIndex(1)
        settings.reject()
        check(
            "settings cancel does not write",
            json.dumps(tools.config.values, sort_keys=True) == before,
        )
        settings = ToolSettings(tools)
        settings.fields[("policy", "feedback")].setCurrentIndex(1)
        settings.fields[("answer_feedback", "hide_duration_ms")].setValue(6000)
        settings.grab().save(str(BASE / "tool-settings.png"))
        settings.save()
        check(
            "native settings save succeeds",
            not settings.error.text()
            and tools.config.values["policy"]["feedback"] == "badge",
        )
        wait(lambda: buttons() == [1, 3])
        count = col.db.scalar("select count(*) from revlog")
        js(mw.bottomWeb, "document.querySelector('button[data-ease=\"3\"]').click()")
        wait(
            lambda: (
                col.db.scalar("select count(*) from revlog") == count + 1
                and mw.reviewer.state == "question"
            )
        )
        check(
            "one click creates exactly one native rating",
            col.db.scalar("select ease from revlog order by id desc limit 1") == 3,
        )
        check(
            "rating badge reports actual PassFail result",
            tools.feedback.label.isVisible()
            and tools.feedback.label.text() == "通过测试",
        )
        check(
            "pace receives exactly one completed answer",
            len(tools.pace.model.answers) == 1,
        )
        tools.sidebar.toggle()
        check(
            "Advanced card info sidebar renders current card",
            tools.sidebar.dock.isVisible()
            and "记忆稳定性" in tools.sidebar.text.toPlainText(),
        )
        screenshot("badge-and-sidebar")
        w.open(0)
        wait(lambda: not mw.bottomWeb.review_controls_active())
        check(
            "statistics hides all review overlays",
            not tools.feedback.label.isVisible()
            and not tools.pace.overlay.isVisible()
            and not tools.sidebar.dock.isVisible(),
        )
        mw.resize(1100, 720)
        mw.on_toggle_full_screen()
        wait(mw.isFullScreen)
        check(
            "fullscreen statistics does not revive footer", not mw.bottomWeb.isVisible()
        )
        mw.on_toggle_full_screen()
        loaded = QSignalSpy(w.graph_web.loadFinished)
        w.show_graphs()
        wait(lambda: len(loaded) > 0)
        wait(lambda: js(w.graph_web, "!!window.__builtinSearchStatsReady"))
        wait(
            lambda: (
                "搜索与扩展统计" in js(w.graph_web, "document.body.innerText")
                or "搜索与扩展统计" in js(w.graph_web, "document.body.innerText")
            )
        )
        check(
            "original Search Stats Extended renders in existing detailed stats",
            js(w.graph_web, "!!window.__builtinSearchStatsReady"),
        )
        from anki.stats_pb2 import GraphsRequest

        seen_graphs = []
        original_graphs = col._backend.graphs_raw

        def observe_graphs(data):
            request = GraphsRequest()
            request.ParseFromString(data)
            result = original_graphs(data)
            seen_graphs.append(request.search)
            return result

        query = "cid:" + str(col.find_cards('deck:"病理::基础"')[0])
        with patch.object(col._backend, "graphs_raw", side_effect=observe_graphs):
            js(
                w.graph_web,
                "(()=>{let input=document.querySelector('.sse-root input[placeholder=\"搜索条件\"]');input.value="
                + json.dumps(query)
                + ";input.dispatchEvent(new Event('input',{bubbles:true}));return true})()",
            )
            wait(lambda: any(query in search for search in seen_graphs))
            check(
                "custom search UI reaches the real statistics backend",
                any(query in search for search in seen_graphs),
            )
        loaded = QSignalSpy(w.graph_web.loadFinished)
        tools.config.save(
            "policy", tools.config.values["policy"] | {"search_stats_enabled": False}
        )
        tools.changed()
        wait(lambda: len(loaded) > 0)
        check(
            "settings change synchronizes the visible statistics switch",
            not w.extended_stats.isChecked()
            and not js(w.graph_web, "!!window.__builtinSearchStatsReady"),
        )
        loaded = QSignalSpy(w.graph_web.loadFinished)
        tools.config.save(
            "policy",
            tools.config.values["policy"]
            | {"search_stats_enabled": True, "style": "advanced"},
        )
        tools.changed()
        wait(
            lambda: (
                len(loaded) > 0
                and js(w.graph_web, "!!window.__builtinSearchStatsReady")
            )
        )
        check(
            "settings can restore extended statistics in place",
            w.extended_stats.isChecked(),
        )
        screenshot("search-stats")
        check(
            "extended statistics has no runtime errors",
            not js(w.graph_web, "window.__builtinStatsErrors"),
        )
        (BASE / "search-controls.json").write_text(
            json.dumps(
                js(
                    w.graph_web,
                    "[...document.querySelectorAll('.sse-root input')].map(e=>({type:e.type,placeholder:e.placeholder,value:e.value,outer:e.outerHTML.slice(0,220)}))",
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf8",
        )
        loaded = QSignalSpy(w.graph_web.loadFinished)
        w.show_graphs()
        wait(lambda: len(loaded) > 0)
        wait(lambda: js(w.graph_web, "!!window.__builtinSearchStatsReady"))
        wait(
            lambda: (
                js(w.graph_web, "document.querySelectorAll('.sse-root').length") == 1
            )
        )
        check(
            "reloading statistics mounts one extension",
            js(w.graph_web, "document.querySelectorAll('.sse-root').length") == 1,
        )
        w.extended_stats.setChecked(False)
        wait(
            lambda: (
                not w.graph_web.page().isLoading()
                and not js(w.graph_web, "!!window.__builtinSearchStatsReady")
            )
        )
        check(
            "Search Stats switch restores native graphs",
            not js(w.graph_web, "!!window.__builtinSearchStatsReady"),
        )
        w.extended_stats.setChecked(True)
        wait(lambda: js(w.graph_web, "!!window.__builtinSearchStatsReady"))
        w.open(0)
        w.show_review()
        wait(mw.bottomWeb.review_controls_active)
        wait(
            lambda: js(
                mw.bottomWeb,
                "!!document.querySelector("
                + json.dumps("button[onclick*=card_info]")
                + ")",
            )
        )
        check(
            "style changes made in statistics apply on resume", not tools.controls_dirty
        )
        tools.config.save(
            "policy",
            tools.config.values["policy"]
            | {"style": "advanced", "feedback": "advanced"},
        )
        tools.config.save(
            "advanced_review",
            tools.config.values["advanced_review"]
            | {
                "Tooltip Timer": 6000,
                "Tooltip Style": 1,
                "Tooltip Position": [0, -100],
            },
        )
        tools.changed()
        mw.reviewer._showAnswer()
        wait(lambda: buttons() == [1, 3])
        count = col.db.scalar("select count(*) from revlog")
        QTest.keyClick(mw.web, Qt.Key.Key_2)
        wait(lambda: col.db.scalar("select count(*) from revlog") == count + 1)
        check(
            "numeric rating obeys PassFail with Advanced feedback",
            col.db.scalar("select ease from revlog order by id desc limit 1") == 3
            and tools.feedback.label.text() == "通过测试",
        )
        check(
            "feedback remains a single label",
            len(mw.findChildren(QLabel, "builtinRatingFeedback")) == 1,
        )
        wait(lambda: mw.reviewer.state == "question")
        skipped = mw.reviewer.card.id
        unrelated = col.find_cards("is:suspended")[0]
        tools.skip(False)
        wait(lambda: skipped in tools.skipped and col.get_card(skipped).queue == -3)
        check("skip only buries selected card", col.get_card(unrelated).queue == -1)
        tools.restore_skipped()
        wait(lambda: skipped not in tools.skipped and col.get_card(skipped).queue >= 0)
        check(
            "restore only touches this tool's skipped cards",
            col.get_card(unrelated).queue == -1,
        )
        wait(lambda: mw.reviewer.state == "question")
        suspended = mw.reviewer.card.id
        tools.skip(True)
        wait(lambda: suspended in tools.skipped and col.get_card(suspended).queue == -1)
        tools.restore_skipped()
        wait(
            lambda: (
                suspended not in tools.skipped and col.get_card(suspended).queue >= 0
            )
        )
        check(
            "suspend and restore preserve other suspended cards",
            col.get_card(unrelated).queue == -1,
        )
        mw.undo()
        wait(
            lambda: col.get_card(suspended).queue == -1 and not mw._background_op_count
        )
        check(
            "native undo is still available after tool operations",
            col.get_card(unrelated).queue == -1,
        )
        home(did)
        from aqt.builtin_features.review_tools import confidence
        from aqt.builtin_features.review_tools.info import overview_metrics

        report_cards, report_summary = confidence._scan(confidence._conf())
        check(
            "confidence analysis finds the synthetic fast-then-failed pattern",
            len(report_cards) >= 4 and bool(report_summary),
        )
        report_before = snapshot()
        guard.stop()

        def inspect_report():
            modal = QApplication.activeModalWidget()
            if modal:
                text = " ".join(
                    view.toPlainText() for view in modal.findChildren(QTextBrowser)
                )
                results["checks"]["confidence report actually renders"] = (
                    "快速作答后遗忘" in text and "生理" in text
                )
                modal.grab().save(str(BASE / "confidence-report.png"))
                modal.reject()

        QTimer.singleShot(300, inspect_report)
        tools.show_confidence()
        guard.start(500)
        check(
            "confidence report is read only",
            snapshot() == report_before
            and results["checks"].get("confidence report actually renders"),
        )
        tools.browse_confidence()
        browser = aqt.dialogs.open("Browser", mw)
        wait(lambda: browser.form.tableView.model().rowCount() >= 4)
        check(
            "confidence opens matching cards in existing browser",
            browser.form.tableView.model().rowCount() >= 4,
        )
        wait(
            lambda: (
                browser.editor.web._domDone
                and js(browser.editor.web, "typeof saveNow === 'function'")
            )
        )
        browser_closed = []
        browser.closeWithCallback(lambda: browser_closed.append(True))
        wait(lambda: bool(browser_closed))
        for variant in (1, 2):
            data = overview_metrics(col, did, variant)
            check(
                f"Advanced overview mode {variant} computes real data",
                data["total"] >= 12,
            )
        check("both Advanced overview modes are read only", snapshot() == report_before)
        mw.resize(1024, 768)
        wait(lambda: not mw.bottomWeb.isVisible())
        check(
            "home remains free of review controls and graph",
            not tools.pace.overlay.isVisible() and not tools.feedback.label.isVisible(),
        )
        tools.config.save(
            "policy",
            tools.config.values["policy"] | {"style": "current", "feedback": "off"},
        )
        screenshot("home")
        (BASE / "expected-tools.json").write_text(
            json.dumps(
                {
                    "config": tools.config.values,
                    "reviews": col.db.scalar("select count(*) from revlog"),
                }
            ),
            encoding="utf8",
        )
    w.profile_close()
    mw.pm.save()
    col.close()
    mw.col = None
except BaseException:
    results["errors"].append(traceback.format_exc())
    print(results["errors"][-1], flush=True)
    if "mw" in globals() and mw:
        mw.grab().save(str(BASE / f"{mode}-failure.png"))
finally:
    results["passed"] = (
        bool(results["checks"])
        and all(results["checks"].values())
        and not results["errors"]
    )
    (BASE / f"{mode}-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print("RESULT", results["passed"], len(results["checks"]), flush=True)
    os._exit(0 if results["passed"] else 1)
