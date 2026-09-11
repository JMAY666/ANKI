"""Real Anki/Qt acceptance using a marked synthetic profile and a fake API boundary."""

import base64
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
    sys.path[:0] = [str(ROOT / item) for item in ("qt", "pylib", "out/qt", "out/pylib")]
name = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else "write"
assert name and Path(name).name == name and name not in (".", "..")
BASE = ROOT / "runtime" / name
PROFILE = BASE / "Learning-Test"
os.environ.pop("ANKIDEV", None)
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "learning-smoke-" + name
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
results = {"checks": {}, "errors": [], "mode": mode}


def check(label, value):
    results["checks"][label] = bool(value)
    print("CHECK", label, bool(value), flush=True)
    assert value, label


def prepare():
    assert not BASE.exists(), "Use a new synthetic run name"
    from anki.collection import Collection
    from anki.lang import set_lang
    from aqt.profiles import ProfileManager

    BASE.mkdir(parents=True)
    (BASE / ".builtin-test").write_text("synthetic data only")
    set_lang("en_US")
    pm = ProfileManager(str(BASE))
    pm.setupMeta()
    pm.meta.update(defaultLang="zh_CN", firstRun=False, updates=False)
    pm.create("Learning-Test")
    pm.load("Learning-Test")
    pm.profile.update(autoSync=False, syncKey=None, syncMedia=False)
    pm.save()
    pm.db.close()
    PROFILE.mkdir(exist_ok=True)
    config = PROFILE / "SynapsePro_Data/addon_settings.json"
    config.parent.mkdir(exist_ok=True)
    config.write_text(
        json.dumps({"onboarding_completed": True, "gamification_popups_enabled": False})
    )
    col = Collection(str(PROFILE / "collection.anki2"))
    col.set_config("fsrs", True)
    did = col.decks.id("学习验证")
    model = col.models.by_name("Basic")
    for index in range(60):
        note = col.new_note(model)
        note["Front"] = f'Synthetic question {index}<img src="test.png">'
        note["Back"] = f"Synthetic answer {index}"
        col.add_note(note, did)
    cids = col.find_cards("")
    for index, cid in enumerate(cids):
        card = col.get_card(cid)
        card.type = card.queue = 2
        card.ivl, card.reps = 20, 14
        card.due = col.sched.today + (0 if index < 12 else 5)
        col.update_card(card)
        col.db.execute(
            "UPDATE cards SET data=? WHERE id=?",
            json.dumps({"s": 20, "d": 5, "dr": 0.9}),
            cid,
        )
    for day in range(2, 16):
        for index in range(16):
            rid = (col.sched.day_cutoff - day * 86400 + 3600) * 1000 + index
            cid = cids[((day - 2) * 16 + index) % 60]
            col.db.execute(
                "INSERT INTO revlog VALUES(?,?,?,?,?,?,?,?,?)",
                rid,
                cid,
                -1,
                1 if index == 0 else 3,
                20,
                15,
                2500,
                2000,
                1,
            )
    Path(col.media.dir(), "test.png").write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
        )
    )
    col.decks.select(did)
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
    until = time.monotonic() + 0.3
    wait(lambda: time.monotonic() >= until)
    mw.grab().save(str(BASE / f"{mode}-{label}.png"))


try:
    if mode == "write":
        prepare()
    assert (BASE / ".builtin-test").read_text() == "synthetic data only"
    import aqt
    from aqt.builtin_features.learning import metrics, service, workspace
    from aqt.builtin_features.learning.settings import OWN_KEY, secret_path
    from aqt.builtin_features.protected_secrets import write_secrets
    from aqt.qt import QApplication, QLabel, QShortcut, QTimer

    app = aqt._run(
        ["anki", "-b", str(BASE), "-p", "Learning-Test", "--safemode", "-l", "zh_CN"],
        exec=False,
    )
    mw = aqt.mw

    def dialog_guard():
        modal = QApplication.activeModalWidget()
        if modal:
            text = " | ".join(label.text() for label in modal.findChildren(QLabel))
            results["errors"].append(text)
            modal.reject()

    guard = QTimer()
    guard.timeout.connect(dialog_guard)
    guard.start(500)
    wait(
        lambda: (
            mw.col is not None
            and mw.state == "deckBrowser"
            and getattr(mw, "learning_workspace", None).store is not None
        )
    )
    col, w = mw.col, mw.learning_workspace
    did = col.decks.id("学习验证")
    results["source"] = workspace.__file__
    check(
        "built-in workspace starts with native reviewer",
        w.mw.reviewer is mw.reviewer and "builtin_features" in workspace.__file__,
    )
    check("automation is initially off", not w.store.settings()["daily_enabled"])
    w.deck.setCurrentIndex(w.deck.findData(int(did)))
    w.open(0)
    wait(lambda: w.snapshot is not None and not w.refreshing)
    check(
        "overview shows actual scoped history",
        w.snapshot["cards"]["total"] == 60 and "评分记录" in w.summary.toPlainText(),
    )
    graph = col._backend.graphs(search=metrics.scope_query(col, did, True), days=7)
    retention = graph.true_retention.week
    check(
        "overview matches native retention numerator and denominator",
        w.snapshot["summary"]["long_passed"]
        == retention.young_passed + retention.mature_passed
        and w.snapshot["summary"]["long_reviews"]
        == retention.young_passed
        + retention.mature_passed
        + retention.young_failed
        + retention.mature_failed,
    )
    screenshot("overview")
    w.show_graphs()
    wait(lambda: js(w.graph_web, "document.querySelectorAll('svg').length") > 0)
    check(
        "embedded graphs retain scope and render",
        "learning=1" in w.graph_web.url().toString()
        and "预测" in js(w.graph_web, "document.body.innerText")
        and "Error" not in js(w.graph_web, "document.body.innerText"),
    )
    screenshot("graphs")
    if mode == "write":
        settings = w.store.settings() | {
            "consent": True,
            "deck_id": int(did),
            "minutes": 60,
            "new_limit": 30,
            "use_existing_key": False,
            "enabled_since": int(time.time()) - 15 * 86400,
        }
        w.store.save_settings(settings)
        write_secrets(secret_path(w.store), {OWN_KEY: "synthetic-smoke-key"})
        captured = []

        def fake_api(payload, key):
            captured.append(payload)
            before = payload["parameters"]["new_per_day"]
            content = {
                "snapshot_id": payload["snapshot_id"],
                "decision": "propose",
                "summary": "合成报告：根据学习负担减少每日新卡。",
                "observations": ["数据仅为合成测试"],
                "inferences": ["不能推断真实用户学习效果"],
                "changes": [
                    {
                        "parameter": "new_per_day",
                        "before": before,
                        "after": before - 2,
                        "reason": "合成建议，验证确认流程",
                        "evidence": ["recent_recorded_seconds"],
                    }
                ],
            }
            return content, {
                "model": "synthetic-deepseek",
                "request_id": "synthetic",
                "usage": {"prompt_tokens": 100, "completion_tokens": 100},
                "estimated_cost": 0.001,
            }

        workspace.analyze = lambda store, report_id, snapshot, settings, key, **kwargs: (
            service.analyze(
                store, report_id, snapshot, settings, key, requester=fake_api, **kwargs
            )
        )
        w.open(2)
        before_cards = col.db.all("SELECT * FROM cards ORDER BY id")
        before_reviews = col.db.all("SELECT * FROM revlog ORDER BY id")
        w.analyze_button.click()
        wait(lambda: not w.analyzing)
        check(
            "report completes through UI without applying",
            len(captured) == 1
            and w.store.reports()[0]["status"] == "ready"
            and metrics.parameters(col, did)["new_per_day"] == 20,
        )
        check(
            "API receives only aggregates",
            "Synthetic question" not in json.dumps(captured)
            and str(did) not in json.dumps(captured),
        )
        screenshot("ai")
        workspace.askUser = lambda *args, **kwargs: True
        w.apply_button.click()
        wait(
            lambda: (
                bool(w.store.actions()) and w.store.actions()[0]["status"] == "applied"
            )
        )
        check(
            "confirmed new-card limit applied without review changes",
            metrics.parameters(col, did)["new_per_day"] == 18
            and col.db.all("SELECT * FROM revlog ORDER BY id") == before_reviews
            and col.db.all("SELECT * FROM cards ORDER BY id") == before_cards,
        )
        w.open(3)
        w.confirm_revert()
        wait(lambda: w.store.actions()[0]["status"] == "reverted")
        check(
            "explicit revert restores inherited limit",
            metrics.parameters(col, did)["override"] is None,
        )
        screenshot("history")
        w.open(0)
        w.start_review()
        wait(lambda: mw.state == "review" and mw.reviewer.state == "question")
        wait(
            lambda: (
                "Synthetic question"
                in (js(mw.web, "document.querySelector('#qa')?.innerText") or "")
            )
        )
        first_card, started = mw.reviewer.card.id, mw.reviewer.card.timer_started
        rating_key = mw.pm.get_answer_key(3)
        w.open(1)
        w.open(1)
        check(
            "rating shortcut is registered exactly once",
            sum(
                shortcut.key().toString() == rating_key
                for shortcut in mw.findChildren(QShortcut)
            )
            == 1,
        )
        mw.reviewer.auto_advance_enabled = True
        w.open(0)
        mw.reviewer._on_show_answer_timeout()
        check(
            "hidden reviewer cannot auto-reveal an answer",
            mw.reviewer.state == "question",
        )
        w.open(1)
        check(
            "native auto-advance choice survives temporary navigation",
            mw.reviewer.auto_advance_enabled,
        )
        mw.reviewer.auto_advance_enabled = False
        mw.reviewer._showAnswer()
        wait(
            lambda: (
                "Synthetic answer"
                in (js(mw.web, "document.querySelector('#qa')?.innerText") or "")
            )
        )
        w.open(0)
        mw.reviewer._answerCard(3)
        check(
            "hidden reviewer cannot grade and tab switch retains card",
            len(col.db.all("SELECT id FROM revlog")) == len(before_reviews)
            and mw.reviewer.card.id == first_card
            and mw.reviewer.state == "answer"
            and mw.reviewer.card.timer_started == started,
        )
        w.open(1)
        check(
            "template and media survive navigation",
            "Synthetic answer" in js(mw.web, "document.querySelector('#qa').innerText")
            and "test.png" in mw.reviewer.card.question(),
        )
        screenshot("answer")
        mw.reviewer._answerCard(3)
        wait(
            lambda: (
                col.db.scalar("SELECT COUNT(*) FROM revlog") == len(before_reviews) + 1
                and mw.reviewer.state == "question"
            )
        )
        check(
            "one grade creates one durable session event",
            metrics.session_summary(col, w.session["events"])["reviews"] == 1,
        )
        mw.undo()
        wait(
            lambda: col.db.scalar("SELECT COUNT(*) FROM revlog") == len(before_reviews)
        )
        check(
            "native undo removes rating from session result",
            metrics.session_summary(col, w.session["events"])["reviews"] == 0,
        )
        wait(lambda: mw.reviewer.state in ("question", "answer"))
        if mw.reviewer.state == "question":
            mw.reviewer._showAnswer()
        mw.reviewer._answerCard(3)
        wait(
            lambda: (
                col.db.scalar("SELECT COUNT(*) FROM revlog") == len(before_reviews) + 1
                and mw.reviewer.state == "question"
            )
        )
        w.finish_button.click()
        wait(
            lambda: (
                mw.state == "overview"
                and w.pages.currentIndex() == 0
                and not w.refreshing
            )
        )
        check(
            "finishing opens refreshed scoped result",
            "1 次评分" in w.result.text()
            and metrics.session_summary(
                col, json.loads(w.store.sessions()[0]["events"])
            )["reviews"]
            == 1,
        )
        screenshot("finished")
        (BASE / "expected.json").write_text(
            json.dumps(
                {
                    "reviews": col.db.scalar("SELECT COUNT(*) FROM revlog"),
                    "sessions": len(w.store.sessions()),
                    "reports": len(w.store.reports()),
                }
            )
        )
    else:
        expected = json.loads((BASE / "expected.json").read_text())
        check(
            "reviews reports and session history survive restart",
            col.db.scalar("SELECT COUNT(*) FROM revlog") == expected["reviews"]
            and len(w.store.sessions()) == expected["sessions"]
            and len(w.store.reports()) == expected["reports"],
        )
        check(
            "reverted limit remains restored",
            metrics.parameters(col, did)["override"] is None,
        )
        w.open(3)
        screenshot("history")
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
