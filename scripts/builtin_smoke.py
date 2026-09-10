"""Both built-in toolsets in one real Anki/Qt process and one synthetic profile."""

import faulthandler
import importlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if package_root := os.environ.get("ANKI_BUILTIN_PACKAGE_ROOT"):
    sys.path.insert(0, str(Path(package_root) / "app_packages"))
else:
    sys.path[:0] = [str(ROOT / p) for p in ("qt", "pylib", "out/qt", "out/pylib")]
name = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else "write"
restart_only = mode in ("restart", "builtin-only")
assert name and Path(name).name == name and name not in (".", "..")
BASE = ROOT / "runtime" / name
PROFILE = BASE / "Builtin-Test"
os.environ.pop("ANKIDEV", None)
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "anki-builtin-" + name
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
results = {"checks": {}, "errors": [], "profile": str(BASE), "mode": mode}
faulthandler.dump_traceback_later(60)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf8")


def check(label, value):
    results["checks"][label] = bool(value)
    print("CHECK", label, bool(value), flush=True)
    assert value, label


def prepare():
    assert not BASE.exists(), "Choose a fresh run name"
    from anki.collection import Collection
    from anki.lang import set_lang
    from aqt.profiles import ProfileManager

    BASE.mkdir(parents=True)
    (BASE / ".builtin-test").write_text("synthetic data only", encoding="utf8")
    set_lang("en_US")
    pm = ProfileManager(str(BASE))
    pm.setupMeta()
    pm.meta.update(defaultLang="zh_CN", firstRun=False, updates=False)
    pm.create("Builtin-Test")
    pm.load("Builtin-Test")
    pm.profile.update(autoSync=False, syncKey=None, syncMedia=False)
    pm.save()
    pm.db.close()
    PROFILE.mkdir(exist_ok=True)
    for addon in ("236979321", "759844606"):
        folder = BASE / "addons21" / addon
        folder.mkdir(parents=True)
        (folder / "__init__.py").write_text(
            "raise RuntimeError('legacy copy executed')", encoding="utf8"
        )
        write_json(
            folder / "meta.json",
            {
                "disabled": False,
                "config": {"days_to_reschedule": 9} if addon == "759844606" else {},
            },
        )
    unrelated = BASE / "addons21/unrelated"
    unrelated.mkdir()
    (unrelated / "__init__.py").write_text("loaded = True", encoding="utf8")
    write_json(
        BASE / "addons21/236979321/addon_settings.json",
        {
            "onboarding_completed": True,
            "gamification_popups_enabled": False,
            "custom_bg_light": "#eaf3ef",
        },
    )
    (PROFILE / "notebook.sqlite").write_bytes(b"Retired notebook preserved")
    (PROFILE / "mindmap_recovery.json").write_text(
        '{"preserved": true}', encoding="utf8"
    )
    col = Collection(str(PROFILE / "collection.anki2"))
    col.set_config("fsrs", True)
    did = col.decks.id("共同验证")
    paired = col.models.by_name("Basic (and reversed card)")
    for index in range(12):
        note = col.new_note(paired)
        note["Front"], note["Back"] = (
            f"Synthetic question {index}",
            f"Synthetic answer {index}",
        )
        col.add_note(note, did)
    for index, cid in enumerate(col.find_cards("")):
        card = col.get_card(cid)
        card.type = card.queue = 2
        card.ivl = 20
        card.due = col.sched.today + (0 if index < 8 else 5)
        card.reps = 3
        col.update_card(card)
        col.db.execute(
            "update cards set data=? where id=?",
            json.dumps({"s": 20.0, "d": 5.0, "dr": 0.9}),
            cid,
        )
        for step, elapsed in enumerate((60, 35, 20)):
            rid = int((col.sched.day_cutoff - 86400 * elapsed - 3600) * 1000) + index
            col.db.execute(
                "insert into revlog values (?,?,?,?,?,?,?,?,?)",
                rid,
                cid,
                -1,
                3,
                (10, 15, 20)[step],
                (5, 10, 15)[step],
                2500,
                1000,
                1,
            )
    col.decks.select(did)
    col.close()


def wait(predicate, timeout=35):
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


def snapshot():
    return [
        [cid, due, ivl, json.loads(data or "{}")]
        for cid, due, ivl, data in col.db.all(
            "select id,due,ivl,data from cards order by id"
        )
    ]


def schedule_test(module, method, *args, **kwargs):
    before = snapshot()
    result = getattr(
        importlib.import_module("aqt.builtin_features.fsrs_helper.schedule." + module),
        method,
    )(*args, **kwargs)
    if hasattr(result, "done"):
        wait(result.done)
        result.result(timeout=1)
    app.processEvents()
    mw.progress.finish()
    check(module + " changes scheduling", snapshot() != before)
    col.undo()
    check(module + " undo restores cards", snapshot() == before)
    mw.reset()


try:
    if mode == "write":
        prepare()
    assert (PROFILE / "collection.anki2").exists()
    if mode == "builtin-only":
        assert (BASE / ".builtin-test").is_file()
        for addon in ("236979321", "759844606"):
            source = BASE / "addons21" / addon
            destination = BASE / "retired-legacy-fixtures" / addon
            if source.exists():
                destination.parent.mkdir(exist_ok=True)
                source.rename(destination)
    import anki
    import aqt
    from aqt import builtin_features, gui_hooks

    app = aqt._run(
        ["anki", "-b", str(BASE), "-p", "Builtin-Test", "-l", "zh_CN"], exec=False
    )
    mw = aqt.mw
    from aqt.qt import QApplication, QLabel, QTimer

    def reject_unexpected_dialog():
        modal = QApplication.activeModalWidget()
        if modal is not None:
            details = (
                modal.windowTitle()
                + ": "
                + " | ".join(label.text() for label in modal.findChildren(QLabel))
            )
            print("UNEXPECTED DIALOG", details, flush=True)
            results["errors"].append(details)
            modal.grab().save(str(BASE / "unexpected-dialog.png"))
            modal.reject()

    dialog_guard = QTimer()
    dialog_guard.timeout.connect(reject_unexpected_dialog)
    dialog_guard.start(500)
    wait(lambda: mw.col is not None and mw.state == "deckBrowser")
    col = mw.col
    syn = importlib.import_module("aqt.builtin_features.synapsepro")
    fsrs = importlib.import_module("aqt.builtin_features.fsrs_helper")
    ai = importlib.import_module("aqt.builtin_features.synapsepro.ai_assistant")
    results["anki"] = anki.version
    results["sources"] = [syn.__file__, fsrs.__file__]
    check(
        "both built in without add-on import",
        builtin_features.instance().ready
        and "236979321" not in sys.modules
        and "759844606" not in sys.modules,
    )
    check("unrelated add-on still loads", sys.modules["unrelated"].loaded)
    check(
        "one SynapsePro and one FSRS menu",
        sum(a.text() == "SynapsePro" for a in mw.form.menuTools.actions()) == 1
        and sum(a.menu() == fsrs.menu_for_helper for a in mw.form.menuTools.actions())
        == 1,
    )
    before_hooks = len(gui_hooks.profile_did_open._hooks)
    builtin_features.initialize(mw)
    check(
        "repeat init does not duplicate hooks",
        len(gui_hooks.profile_did_open._hooks) == before_hooks,
    )
    check(
        "normal backup mode and isolated data",
        not os.environ.get("ANKIDEV")
        and Path(mw.pm.base).resolve() == BASE.resolve()
        and not mw.pm.profile.get("syncKey"),
    )
    legacy_base = BASE / (
        "retired-legacy-fixtures" if mode == "builtin-only" else "addons21"
    )
    if mode == "builtin-only":
        check(
            "both legacy plugin directories absent",
            all(
                not (BASE / "addons21" / n).exists() for n in ("236979321", "759844606")
            ),
        )
    check(
        "legacy originals preserved",
        (legacy_base / "236979321/addon_settings.json").exists()
        and not json.loads((legacy_base / "759844606/meta.json").read_text())[
            "disabled"
        ]
        and (PROFILE / "notebook.sqlite").read_bytes() == b"Retired notebook preserved",
    )
    check(
        "retired features absent",
        all(
            not (Path(syn.__file__).parent / (n + ".py")).exists()
            for n in (
                "website_sidebar",
                "notebook_sidebar",
                "mindmap_sidebar",
                "embedded_window",
            )
        ),
    )
    if mode in ("restart", "exercise", "builtin-only"):
        expected = json.loads((BASE / "expected.json").read_text(encoding="utf8"))
        check(
            "scheduling and review persist after restart",
            snapshot() == expected["cards"]
            and col.db.scalar("select count(*) from revlog") == expected["reviews"],
        )
        check(
            "both configs persist after restart",
            fsrs.config.days_to_reschedule == 12
            and syn.addon_settings["custom_bg_light"] == "#dfeeed"
            and ai._load_settings()["provider"] == "deepseek",
        )
        if restart_only and "fsrs_config" in expected:
            check(
                "FSRS menu settings persist",
                fsrs.config.data == expected["fsrs_config"],
            )
    else:
        check(
            "legacy FSRS and Synapse settings migrated",
            fsrs.config.days_to_reschedule == 9
            and syn.addon_settings["custom_bg_light"] == "#eaf3ef",
        )
        fsrs.config.days_to_reschedule = 12
        syn.addon_settings["custom_bg_light"] = "#dfeeed"
        syn.save_addon_settings()
        ai._save_settings_dict(
            {
                "provider": "deepseek",
                "model": "deepseek-flash",
                "apiKey": "",
                "language": "English",
            }
        )
    ai.toggle_ai_assistant_dock()
    wait(
        lambda: (
            ai._webview is not None
            and js(
                ai._webview,
                "!!document.querySelector('#s-provider option[value=deepseek]')",
            )
        )
    )
    check(
        "DeepSeek local chat UI renders",
        js(
            ai._webview,
            "document.querySelector('#s-provider option[value=deepseek]').textContent",
        )
        == "DeepSeek",
    )
    mw.grab().save(str(BASE / (mode + "-main.png")))
    browser = aqt.dialogs.open("Browser", mw)
    workspace = browser._synapse_workspace
    wait(
        lambda: (
            workspace.enabled
            and not workspace.loading
            and not workspace.inflight
            and browser.table.len() > 0
        )
    )
    columns = {}
    gui_hooks.browser_did_fetch_columns(columns)
    check(
        "three pane browser and FSRS Target R coexist",
        workspace.enabled and "target_retrievability" in columns,
    )
    workspace._set_columns(["question", "template", "cardDue", "target_retrievability"])
    browser.table.select_single_card(col.find_cards("")[0])
    workspace.show_preview()
    wait(
        lambda: (
            workspace.preview.card() is not None
            and workspace.preview._last_state is not None
        )
    )
    wait(
        lambda: (
            "Synthetic"
            in (
                js(workspace.preview._web, "document.querySelector('#qa')?.innerText")
                or ""
            )
        )
    )
    check(
        "embedded native template preview renders",
        "Synthetic"
        in js(workspace.preview._web, "document.querySelector('#qa').innerText"),
    )
    custom = importlib.import_module(
        "aqt.builtin_features.fsrs_helper.browser.browser"
    ).custom_columns[0]
    check(
        "FSRS browser value available",
        "%" in custom._display_value(col.get_card(col.find_cards("")[0])),
    )
    from aqt.qt import Qt

    browser.table._on_sort_column_changed(3, Qt.SortOrder.DescendingOrder)
    wait(lambda: not workspace.loading and not workspace.inflight)
    check(
        "Target R sorting works in three pane browser",
        browser.table._state.sort_column == "target_retrievability",
    )
    browser.grab().save(str(BASE / (mode + "-browser.png")))
    for _ in range(2):
        workspace.set_enabled(False)
        wait(lambda: not workspace.enabled)
        workspace.set_enabled(True)
        wait(
            lambda: (
                workspace.enabled and not workspace.loading and not workspace.inflight
            )
        )
    check("standard and three pane layouts can alternate", not results["errors"])
    browser.close()
    app.processEvents()
    ai.toggle_ai_assistant_dock()
    if not restart_only:
        from aqt.qt import QDialogButtonBox, QPlainTextEdit

        previous_threshold = fsrs.config.reschedule_threshold

        def save_native_settings():
            dialog = QApplication.activeModalWidget()
            editor = dialog.findChild(QPlainTextEdit)
            value = json.loads(editor.toPlainText())
            value["reschedule_threshold"] = 0.15
            editor.setPlainText(json.dumps(value))
            dialog.findChild(QDialogButtonBox).button(
                QDialogButtonBox.StandardButton.Save
            ).click()

        dialog_guard.stop()
        QTimer.singleShot(100, save_native_settings)
        builtin_features.show_fsrs_settings()
        dialog_guard.start(500)
        check(
            "native FSRS settings dialog saves fractional threshold",
            fsrs.config.reschedule_threshold == 0.15,
        )
        fsrs.config.reschedule_threshold = previous_threshold
        previous_display = fsrs.config.display_memory_state
        fsrs.menu_display_memory_state.trigger()
        check(
            "FSRS menu switch saves through native config",
            fsrs.config.display_memory_state != previous_display,
        )
        did = col.decks.id("共同验证")
        postpone = importlib.import_module(
            "aqt.builtin_features.fsrs_helper.schedule.postpone"
        )
        postpone.get_desired_postpone_cnt_with_response = lambda *a: (2, True)
        schedule_test("postpone", "postpone", did)
        advance = importlib.import_module(
            "aqt.builtin_features.fsrs_helper.schedule.advance"
        )
        advance.get_desired_advance_cnt_with_response = lambda *a: (2, True)
        schedule_test("advance", "advance", did)
        schedule_test("reschedule", "reschedule", did)
        schedule_test("flatten", "flatten_background", did, 2)
        schedule_test("schedule_break", "_schedule_break_background", did, 3, 4)
        schedule_test("disperse_siblings", "disperse_siblings", did)
        from anki.stats import CollectionStats

        check("FSRS statistics render", len(CollectionStats(col).todayStats()) > 100)
        # Let each operation's queued success callback/reset finish before
        # changing screens; a Future finishing precedes its Qt UI callback.
        settle_until = time.monotonic() + 2
        wait(lambda: time.monotonic() >= settle_until)
        col.decks.select(did)
        mw.moveToState("review")
        wait(
            lambda: (
                mw.state == "review"
                and mw.reviewer.card is not None
                and mw.reviewer.state == "question"
            )
        )
        wait(
            lambda: (
                "Synthetic"
                in (js(mw.web, "document.querySelector('#qa')?.innerText") or "")
            )
        )
        check("native reviewer question renders", True)
        mw.reviewer._showAnswer()
        wait(lambda: mw.reviewer.state == "answer")
        wait(
            lambda: (
                "Synthetic answer"
                in (js(mw.web, "document.querySelector('#qa')?.innerText") or "")
            )
        )
        mw.grab().save(str(BASE / "review-answer.png"))
        count = col.db.scalar("select count(*) from revlog")
        mw.reviewer._answerCard(3)
        wait(lambda: col.db.scalar("select count(*) from revlog") == count + 1)
        check(
            "one grade writes exactly one review",
            col.db.scalar("select count(*) from revlog") == count + 1,
        )
        mw.moveToState("deckBrowser")
        write_json(
            BASE / "expected.json",
            {
                "cards": snapshot(),
                "reviews": col.db.scalar("select count(*) from revlog"),
                "fsrs_config": fsrs.config.data,
            },
        )
    syn.on_profile_close()
    mw.pm.save()
    col.close()
    mw.col = None
except BaseException:
    results["errors"].append(traceback.format_exc())
    print(results["errors"][-1], flush=True)
    if "mw" in globals() and mw is not None:
        mw.grab().save(str(BASE / "failure-main.png"))
        print("FAILURE STATE", mw.state, flush=True)
        print("FAILURE PAGE", js(mw.web, "document.body.innerText"), flush=True)
finally:
    results["passed"] = bool(results["checks"]) and not results["errors"]
    write_json(BASE / (mode + "-results.json"), results)
    print("RESULT", results["passed"], len(results["checks"]), flush=True)
    os._exit(0 if results["passed"] else 1)
