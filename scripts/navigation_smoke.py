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
PROFILE = BASE / "Navigation-Test"
os.environ.pop("ANKIDEV", None)
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "navigation-smoke-" + name
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
    pm.create("Navigation-Test")
    pm.load("Navigation-Test")
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
    for addon in ("236979321", "759844606", "876946123"):
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


try:
    if mode == "write":
        prepare()
    assert (BASE / ".builtin-test").read_text() == "synthetic data only"
    from PyQt6.QtTest import QTest

    import aqt
    from aqt.builtin_features import initialize, replaces_addon
    from aqt.builtin_features.learning import metrics
    from aqt.builtin_features.passfail2 import SettingsDialog
    from aqt.deckoptions import DeckOptionsDialog
    from aqt.import_export.import_dialog import ImportDialog
    from aqt.progress import ProgressDialog
    from aqt.qt import QApplication, QComboBox, QLabel, Qt, QTimer

    app = aqt._run(
        ["anki", "-b", str(BASE), "-p", "Navigation-Test", "--safemode", "-l", "zh_CN"],
        exec=False,
    )
    mw = aqt.mw

    def dialog_guard():
        modal = QApplication.activeModalWidget()
        if modal and not isinstance(
            modal, (DeckOptionsDialog, SettingsDialog, ProgressDialog, ImportDialog)
        ):
            results["errors"].append(
                " | ".join(label.text() for label in modal.findChildren(QLabel))
            )
            modal.reject()

    guard = QTimer()
    guard.timeout.connect(dialog_guard)
    guard.start(500)
    wait(lambda: mw.col and mw.state == "deckBrowser" and mw.learning_workspace.store)
    synapse = sys.modules["aqt.builtin_features.synapsepro"]
    wait(lambda: synapse._daily_maintenance_done)
    mw.resize(1540, 940)
    col, w, pf = mw.col, mw.learning_workspace, mw.passfail2
    did, other = col.decks.id("病理::基础"), col.decks.id("生理::基础")
    results["source"] = sys.modules["aqt.builtin_features.passfail2"].__file__
    home(did)
    check(
        "all three built-ins share one main window",
        hasattr(mw, "gamification_manager")
        and pf.mw is mw
        and w.mw is mw
        and col.get_config("fsrs"),
    )
    initialize(mw)
    check(
        "single registration and legacy copies blocked",
        sum("Pass/Fail 2" in a.text() for a in mw.form.menuTools.actions()) == 1
        and all(
            replaces_addon(x, str(BASE / "addons21"))
            for x in ("236979321", "759844606", "876946123")
        ),
    )
    check(
        "one statistics navigation and top import",
        js(
            mw.toolbarWeb,
            "document.querySelectorAll('a#stats').length===1 && !document.querySelector('#learning-workspace') && !!document.querySelector('a#import')",
        ),
    )
    check(
        "three columns share selected deck",
        js(
            mw.web,
            "getComputedStyle(document.querySelector('.deck-workspace')).gridTemplateColumns.split(' ').length===3 && document.querySelector('.deck-main h1').textContent===document.querySelector('.deck-scope-info h3').textContent",
        ),
    )
    check(
        "only sidebar create and shared actions remain",
        js(
            mw.web,
            "document.querySelectorAll('.deck-directory-actions button').length===2 && !document.querySelector('[onclick*=\"import\"]')",
        ),
    )
    screenshot("deck-wide")
    if mode in ("restart", "restart-native"):
        expected = json.loads((BASE / "expected.json").read_text())
        check(
            "all mode and customization states persist on restart",
            pf.value == expected["passfail"]
            and col.db.scalar("SELECT COUNT(*) FROM revlog") == expected["reviews"],
        )
        check("selected deck remains saved", col.decks.selected() == did)
        if mode == "restart":
            dialog = SettingsDialog(pf)
            dialog.enabled.setChecked(False)
            dialog.custom.setChecked(False)
            dialog.save()
            expected["passfail"] = pf.value
            (BASE / "expected.json").write_text(json.dumps(expected))
        if mode == "restart-native":
            from aqt.theme import Theme, theme_manager

            synapse.addon_settings["minimal_dashboard_enabled"] = False
            synapse.addon_settings["theme_restart_warning_suppressed"] = True
            home(did)
            results["standard_layout"] = js(
                mw.web,
                "({width: innerWidth, scroll:document.documentElement.scrollWidth, overflow:Array.from(document.querySelectorAll('.deck-workspace *')).filter(e=>e.getBoundingClientRect().right>innerWidth+2).slice(0,20).map(e=>({tag:e.tagName,id:e.id,cls:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right}))})",
            )
            screenshot("deck-standard")
            check(
                "standard auxiliary widgets fit their column",
                js(
                    mw.web,
                    "document.documentElement.scrollWidth <= window.innerWidth + 2",
                ),
            )
            screenshot("deck-standard")
            mw.pm.set_theme(Theme.DARK)
            theme_manager.apply_style()
            home(did)
            check(
                "dark theme keeps the deck actions and auxiliary widgets usable",
                js(
                    mw.web,
                    "document.body.classList.contains('nightMode') && document.documentElement.scrollWidth <= window.innerWidth + 2",
                ),
            )
            screenshot("deck-dark")
    else:
        check(
            "new built-in retains original four-grade behavior by default",
            not pf.value["enabled"],
        )
        parent = col.decks.id("病理")
        old_collapse = js(
            mw.web, f"document.getElementById('{parent}').dataset.collapsed"
        )
        js(
            mw.web,
            f"document.getElementById('{parent}').querySelector('.collapse').click(); true",
        )
        wait(
            lambda: (
                js(mw.web, f"document.getElementById('{parent}')?.dataset.collapsed")
                == str(1 - int(old_collapse))
            )
        )
        check(
            "directory expand collapse preserves selection", col.decks.selected() == did
        )
        wait(
            lambda: (
                not mw._background_op_count
                and not mw.web.page().isLoading()
                and js(
                    mw.web,
                    "document.querySelector('.deck-workspace')?.dataset.ready === 'true'",
                )
            )
        )
        js(
            mw.web,
            "document.querySelector('#deck-search').value='基础'; document.querySelector('#deck-search').dispatchEvent(new Event('input')); true",
        )
        check(
            "large tree search disambiguates duplicate deck names",
            js(
                mw.web,
                "Array.from(document.querySelectorAll('tr.deck:not([hidden]) a.deck')).some(a=>a.textContent==='病理::基础') && Array.from(document.querySelectorAll('tr.deck:not([hidden]) a.deck')).some(a=>a.textContent==='生理::基础')",
            ),
        )
        js(
            mw.web,
            "document.querySelector('#deck-search').value=''; document.querySelector('#deck-search').dispatchEvent(new Event('input')); true",
        )
        home(other)
        check(
            "both content columns follow directory selection",
            js(
                mw.web,
                "document.querySelector('.deck-main h1').textContent==='生理::基础' && document.querySelector('.deck-scope-info h3').textContent==='生理::基础'",
            ),
        )
        home(did)
        mw.onStats()
        wait(lambda: w.snapshot is not None and not w.refreshing)
        check(
            "statistics independent from review with no duplicate review tab",
            [w.tabs.tabText(i) for i in range(w.tabs.count())]
            == ["概览统计", "AI 建议", "记录"]
            and w.snapshot["cards"]["total"] == 12
            and mw.state != "review",
        )
        w.deck.click()
        w.deck.search.setText("生理::基础")
        w.deck.select_first_match()
        wait(
            lambda: (
                w.snapshot
                and w.snapshot["scope"]["deck_id"] == other
                and not w.refreshing
            )
        )
        check(
            "tree picker selects exact scoped deck and shows shared preset",
            w.deck.currentData() == other
            and "共享" in w.preset_scope.text()
            and "病理::基础" in w.preset_scope.toolTip(),
        )
        w.deck_options_button.click()
        wait(
            lambda: any(
                isinstance(x, DeckOptionsDialog) for x in QApplication.topLevelWidgets()
            )
        )
        option = next(
            x
            for x in QApplication.topLevelWidgets()
            if isinstance(x, DeckOptionsDialog)
        )
        wait(lambda: option._ready)
        check("native settings open the selected deck", option._deck["id"] == other)
        option.require_close()
        w.deck.click()
        w.deck.search.setText("基础")
        screenshot("stats-tree")
        w.deck.popup.hide()
        home(did)
        mw.resize(650, 800)
        wait(lambda: js(mw.web, "window.innerWidth < 700"))
        check(
            "narrow window retains usable main controls",
            js(
                mw.web,
                "document.documentElement.scrollWidth <= window.innerWidth+2 && document.querySelector('.deck-start').getBoundingClientRect().width > 150",
            ),
        )
        screenshot("deck-narrow")
        mw.resize(1540, 940)
        for label in ("空牌组", "限额"):
            empty_id = col.decks.id(label)
            with patch("aqt.deckbrowser.showInfo") as notice:
                mw.deckBrowser.start_review(empty_id)
                wait(lambda: not mw.deckBrowser._starting_review)
                check(
                    label + " respects native scheduling and reports no review content",
                    mw.state == "deckBrowser"
                    and bool(notice.call_args)
                    and col.db.scalar("SELECT COUNT(*) FROM revlog") == 0,
                )
        home(did)
        with patch("aqt.operations.deck.getOnlyText", return_value="新建验证"):
            js(mw.web, "document.querySelector('[onclick*=\"create\"]').click(); true")
            wait(lambda: col.decks.by_name("新建验证") is not None)
        check(
            "sidebar create uses native deck creation",
            col.decks.by_name("新建验证") is not None,
        )
        with patch("aqt.deckbrowser.openLink") as shared:
            js(mw.web, "document.querySelector('[onclick*=\"shared\"]').click(); true")
            wait(lambda: shared.called)
            check(
                "get decks retains AnkiWeb target",
                shared.call_args.args[0] == "https://ankiweb.net/shared/decks/",
            )
        with patch(
            "aqt.import_export.importing.prompt_for_file_then_import"
        ) as importer:
            js(mw.toolbarWeb, "document.querySelector('#import').click(); true")
            wait(lambda: importer.called)
            check(
                "top import reaches unchanged native import flow",
                importer.call_args.args[0] is mw,
            )
        imported = BASE / "synthetic-import.tsv"
        imported.write_text(
            "#separator:tab\n#notetype:Basic\n#deck:导入验证\nSynthetic imported front\tSynthetic imported back\n",
            encoding="utf8",
        )
        count_before_import = col.card_count()
        with patch("aqt.import_export.importing.getFile", return_value=str(imported)):
            js(mw.toolbarWeb, "document.querySelector('#import').click(); true")
            wait(
                lambda: any(
                    isinstance(x, ImportDialog) for x in QApplication.topLevelWidgets()
                )
            )
        import_dialog = next(
            x for x in QApplication.topLevelWidgets() if isinstance(x, ImportDialog)
        )
        wait(lambda: js(import_dialog.web, "!!document.querySelector('.import')"))
        js(
            import_dialog.web,
            "document.querySelector('.import').closest('button').click(); true",
        )
        wait(
            lambda: (
                col.card_count() == count_before_import + 1
                and not mw._background_op_count
            )
        )
        check(
            "top import completes an actual synthetic file import",
            len(col.find_cards("deck:导入验证")) == 1,
        )
        import_dialog.reject()
        fresh = col.decks.id("新建验证")
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"], note["Back"] = "Fresh deck scope", "Synthetic only"
        col.add_note(note, fresh)
        home(fresh)
        js(mw.web, "document.querySelector('.deck-study-card').click(); true")
        wait(lambda: mw.state == "review" and mw.reviewer.state == "question")
        mw.onStats()
        wait(lambda: not w.refreshing and w.snapshot is not None)
        check(
            "statistics entered from a newly created deck retain that deck scope",
            w.deck.currentData() == fresh
            and w.snapshot["scope"]["deck_id"] == fresh
            and w.snapshot["cards"]["total"] == 1,
        )
        mw.toolbar._deckLinkHandler()
        home(did)
        js(mw.web, "document.querySelector('.deck-study-card').click(); true")
        wait(lambda: mw.state == "review" and mw.reviewer.state == "question")
        check(
            "deck card enters reviewer directly and preserves scope",
            not w.header.isVisible()
            and mw.reviewer.card.did == did
            and mw.reviewer.card.queue != -1,
        )
        mw.reviewer._showAnswer()
        wait(lambda: buttons() == [1, 2, 3, 4])
        selector = w.review_bar.findChild(QComboBox)
        original = (
            mw.reviewer.card.id,
            mw.reviewer.card.timer_started,
            col.db.all("SELECT * FROM cards ORDER BY id"),
        )
        for _ in range(3):
            selector.setCurrentIndex(1)
            wait(lambda: buttons() == [1, 3])
            selector.setCurrentIndex(0)
            wait(lambda: buttons() == [1, 2, 3, 4])
        check(
            "repeated mode switches preserve card face timer and scheduling data",
            (
                mw.reviewer.card.id,
                mw.reviewer.card.timer_started,
                col.db.all("SELECT * FROM cards ORDER BY id"),
            )
            == original
            and mw.reviewer.state == "answer"
            and col.db.scalar("SELECT COUNT(*) FROM revlog") == 0,
        )
        dialog = SettingsDialog(pf)
        dialog.enabled.setChecked(True)
        dialog.custom.setChecked(True)
        dialog.fields["again_button_name"].setText("忘记")
        dialog.fields["good_button_name"].setText("记住")
        dialog.fields["good_button_textcolor"].setText("#237544")
        dialog.preview()
        check(
            "original custom-name color switch and preview retained",
            dialog.previews[1].text() == "记住"
            and "#237544" in dialog.previews[1].styleSheet(),
        )
        dialog.save()
        wait(
            lambda: (
                buttons() == [1, 3]
                and "记住" in js(mw.bottomWeb, "document.body.innerText")
            )
        )
        canceled = SettingsDialog(pf)
        canceled.custom.setChecked(False)
        canceled.reject()
        check(
            "cancel leaves saved customization unchanged",
            pf.value["toggle_names_textcolors"] == "1",
        )
        screenshot("passfail-answer")
        before = col.db.scalar("SELECT COUNT(*) FROM revlog")
        for key in (Qt.Key.Key_2, Qt.Key.Key_2, Qt.Key.Key_2):
            if mw.reviewer.state == "question":
                mw.reviewer._showAnswer()
            wait(lambda: mw.reviewer.state == "answer" and buttons() == [1, 3])
            previous = col.db.scalar("SELECT COUNT(*) FROM revlog")
            mw.activateWindow()
            mw.web.setFocus()
            QTest.keyClick(mw, key)
            wait(
                lambda: (
                    col.db.scalar("SELECT COUNT(*) FROM revlog") == previous + 1
                    and mw.reviewer.state == "question"
                )
            )
        check(
            "three separate presses of key 2 each record native Good once in selected deck",
            col.db.list("SELECT ease FROM revlog ORDER BY id") == [3, 3, 3]
            and col.db.scalar(
                "SELECT COUNT(*) FROM revlog r JOIN cards c ON c.id=r.cid WHERE c.did!=?",
                did,
            )
            == 0,
        )
        check(
            "session ledger agrees with remapped ratings",
            metrics.session_summary(col, w.session["events"])["reviews"] == 3,
        )
        mw.undo()
        wait(lambda: col.db.scalar("SELECT COUNT(*) FROM revlog") == before + 2)
        check(
            "native undo remains available with PassFail",
            metrics.session_summary(col, w.session["events"])["reviews"] == 2,
        )
        wait(lambda: mw.reviewer.state in ("question", "answer"))
        for native, ease in ((True, 2), (True, 4), (False, 1)):
            selector.setCurrentIndex(0 if native else 1)
            if mw.reviewer.state == "question":
                mw.reviewer._showAnswer()
            wait(
                lambda: (
                    mw.reviewer.state == "answer"
                    and buttons() == ([1, 2, 3, 4] if native else [1, 3])
                )
            )
            count = col.db.scalar("SELECT COUNT(*) FROM revlog")
            js(
                mw.bottomWeb,
                f"document.querySelector('button[data-ease=\"{ease}\"]').click(); true",
            )
            wait(
                lambda: (
                    col.db.scalar("SELECT COUNT(*) FROM revlog") == count + 1
                    and mw.reviewer.state == "question"
                )
            )
            check(
                f"{'native' if native else 'PassFail'} button {ease} records the correct rating",
                col.db.scalar("SELECT ease FROM revlog ORDER BY id DESC LIMIT 1")
                == ease,
            )
        w.finish_button.click()
        wait(
            lambda: (
                mw.state == "deckBrowser"
                and js(
                    mw.web,
                    "document.querySelector('.deck-workspace')?.dataset.selectedDeck",
                )
                == str(did)
            )
        )
        check(
            "exit returns to original selected deck",
            col.decks.selected() == did and not w.header.isVisible(),
        )
        (BASE / "expected.json").write_text(
            json.dumps(
                {
                    "passfail": pf.value,
                    "reviews": col.db.scalar("SELECT COUNT(*) FROM revlog"),
                }
            )
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
    results["passed"] = bool(results["checks"]) and not results["errors"]
    (BASE / f"{mode}-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print("RESULT", results["passed"], len(results["checks"]), flush=True)
    os._exit(0 if results["passed"] else 1)
