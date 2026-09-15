"""Synthetic Anki/WebEngine acceptance; no personal profile or live AI request."""

import base64
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
    sys.path[:0] = [str(ROOT / part) for part in ("qt", "pylib", "out/qt", "out/pylib")]
name = sys.argv[1]
assert name and Path(name).name == name and name not in (".", "..")
BASE = ROOT / "runtime" / name
assert not BASE.exists(), "Use a fresh synthetic run name"
BASE.mkdir(parents=True)
(BASE / ".builtin-test").write_text("synthetic data only")
os.environ.pop("ANKIDEV", None)
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "ai-images-" + name
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
results = {
    "checks": {},
    "errors": [],
    "live_api": False,
    "native_screen_capture": False,
}


def check(label, result):
    print("CHECK", label, bool(result), flush=True)
    results["checks"][label] = bool(result)
    assert result, label


def wait(predicate, timeout=25):
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


try:
    from anki.collection import Collection
    from anki.lang import set_lang
    from aqt.profiles import ProfileManager

    set_lang("en_US")
    pm = ProfileManager(str(BASE))
    pm.setupMeta()
    pm.meta.update(defaultLang="zh_CN", firstRun=False, updates=False)
    pm.create("AI-Images-Test")
    pm.load("AI-Images-Test")
    pm.profile.update(autoSync=False, syncKey=None, syncMedia=False)
    pm.save()
    pm.db.close()
    profile = BASE / "AI-Images-Test"
    settings = profile / "SynapsePro_Data/addon_settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"onboarding_completed": True, "gamification_popups_enabled": False})
    )
    col = Collection(str(profile / "collection.anki2"))
    model = col.models.by_name("Basic")
    decks = [col.decks.id("合成截图测试::" + side) for side in ("左", "右")]
    for deck in decks:
        for i in range(3):
            note = col.new_note(model)
            note["Front"] = (
                f'<h2>合成图片题 {i + 1}</h2><div style="background:#dceef7;padding:40px">截图测试区域<br>文字 + 图片</div>'
            )
            note["Back"] = "合成答案"
            col.add_note(note, deck)
    col.decks.select(decks[0])
    col.close()

    from PyQt6.QtTest import QTest

    import aqt
    from aqt.qt import (
        QApplication,
        QColor,
        QDialogButtonBox,
        QFileDialog,
        QImage,
        QPoint,
        Qt,
        QTimer,
    )

    app = aqt._run(
        ["anki", "-b", str(BASE), "-p", "AI-Images-Test", "--safemode", "-l", "zh_CN"],
        exec=False,
    )
    mw = aqt.mw
    previous_excepthook = sys.excepthook

    def record_exception(kind, value, tb):
        results["errors"].append("".join(traceback.format_exception(kind, value, tb)))
        previous_excepthook(kind, value, tb)

    sys.excepthook = record_exception
    wait(lambda: mw.col and mw.state == "deckBrowser" and mw.learning_workspace.store)
    wait(lambda: sys.modules["aqt.builtin_features.synapsepro"]._daily_maintenance_done)
    mw.resize(1300, 900)
    mw.activateWindow()
    mw.moveToState("review")
    reviewer = mw.reviewer
    wait(
        lambda: (
            reviewer.card
            and reviewer._states_mutated
            and js(reviewer.bottom.web, "!!document.getElementById('ai-screenshot')")
        )
    )
    schedule = mw.col.db.all("select id,due,reps,ivl from cards order by id")
    from aqt.builtin_features.synapsepro import ai_assistant as ai
    from aqt.builtin_features.synapsepro import ai_images

    ai._save_settings_dict(
        {
            "provider": "deepseek",
            "model": "deepseek-flash",
            "apiKey": "synthetic-key",
            "language": "Chinese (Simplified)",
        }
    )
    requests = []
    fail = False

    def stream(url, key, model, messages, on_chunk, **kwargs):
        assert key == "synthetic-key"
        requests.append({"url": url, "model": model, "messages": messages})
        if fail:
            raise RuntimeError("Synthetic connection failure")
        on_chunk("已收到文字与图片。合成回复。")

    ai._stream_openai_compat = stream
    # Offscreen Qt has no desktop surface. Only the capture boundary is replaced;
    # the selector, coordinate mapping, composer and bridge run unchanged.
    if not os.environ.get("ANKI_AI_NATIVE_CAPTURE"):
        from aqt.qt import QPixmap

        synthetic_capture = QPixmap(mw.size())
        synthetic_capture.fill(QColor("#dceef7"))
        ai._grab_anki_window = lambda: synthetic_capture
    else:
        native_grab = ai._grab_anki_window

        def grab_ready():
            capture = native_grab()
            capture.save(str(BASE / "captured-window.png"))
            pixels = capture.toImage()
            return (
                sum(
                    pixels.pixelColor(x, y).name() == "#dceef7"
                    for x in range(0, pixels.width(), 20)
                    for y in range(0, pixels.height(), 20)
                )
                > 20
            )

        # A DOM bridge callback can precede the first Chromium compositor frame.
        wait(grab_ready, timeout=10)
    phases = []

    def drive_capture():
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, ai_images.RegionCapture):
            phases.append("region")
            QTest.mousePress(dialog, Qt.MouseButton.LeftButton, pos=QPoint(620, 300))
            QTest.mouseMove(dialog, QPoint(220, 100))
            QTest.mouseRelease(dialog, Qt.MouseButton.LeftButton, pos=QPoint(220, 100))
        elif isinstance(dialog, ai_images.ScreenshotQuestion):
            phases.append("compose")
            dialog.question.setPlainText("请解释截图中的蓝色区域")
            buttons = dialog.findChild(QDialogButtonBox)
            next(
                button
                for button in buttons.buttons()
                if buttons.buttonRole(button) == QDialogButtonBox.ButtonRole.AcceptRole
            ).click()

    driver = QTimer()
    driver.timeout.connect(drive_capture)
    driver.start(50)
    reviewer.bottom.web.setFocus()
    js(reviewer.bottom.web, "document.getElementById('ai-screenshot').click()")
    wait(
        lambda: (
            len(requests) == 1
            and ai._webview
            and js(ai._webview, "!busy && !!document.querySelector('.msg.ai .bubble')")
        )
    )
    driver.stop()
    web = ai._webview
    check(
        "bottom button captures, composes, sends and opens the right dock",
        phases == ["region", "compose"]
        and ai._dock.isVisible()
        and mw.dockWidgetArea(ai._dock) == Qt.DockWidgetArea.RightDockWidgetArea,
    )
    message = requests[0]["messages"][-1]
    check(
        "one request includes screenshot and entered text",
        message["content"][0]["text"] == "请解释截图中的蓝色区域"
        and message["content"][1]["image_url"]["url"].startswith("data:image/"),
    )
    pixels = QImage.fromData(
        base64.b64decode(message["content"][1]["image_url"]["url"].split(",", 1)[1])
    )
    pixels.save(str(BASE / "sent-image.png"))
    check(
        "sent image contains the selected blue pixels",
        sum(
            pixels.pixelColor(x, y).name() == "#dceef7"
            for x in range(0, pixels.width(), 8)
            for y in range(0, pixels.height(), 8)
        )
        > 10,
    )
    results["native_screen_capture"] = bool(os.environ.get("ANKI_AI_NATIVE_CAPTURE"))
    wait(lambda: not ai._attachments)
    check(
        "chat displays sent screenshot and received answer",
        js(
            web,
            "document.querySelectorAll('.message-images img').length === 1 && document.getElementById('chat').textContent.includes('合成回复')",
        ),
    )
    check(
        "new controls are translated",
        js(
            web,
            "[...document.querySelectorAll('#input-wrap .image-action')].map(b=>b.textContent).join('|')",
        )
        == "添加图片|截图提问|默认 AI…",
    )
    mw.grab().save(str(BASE / "screenshot-question.png"))

    img = QImage(240, 140, QImage.Format.Format_RGB32)
    img.fill(QColor("#328866"))
    path = BASE / "synthetic.png"
    img.save(str(path))
    with patch.object(QFileDialog, "getOpenFileNames", return_value=([str(path)], "")):
        js(web, "document.querySelector('#input-wrap .image-action').click()")
        wait(lambda: len(ai._draft_image_ids) == 1)
    check(
        "file picker shows removable image preview",
        js(web, "document.querySelectorAll('#input-wrap .image-preview').length === 1"),
    )
    js(web, "document.querySelector('#input-wrap .image-remove').click()")
    wait(lambda: not ai._draft_image_ids)
    check("removal does not send a request", len(requests) == 1)
    QApplication.clipboard().setImage(img)
    js(
        web,
        "{const dt=new DataTransfer();dt.items.add(new File(['synthetic'],'image.png',{type:'image/png'}));document.getElementById('user-input').dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));}",
    )
    wait(lambda: len(ai._draft_image_ids) == 1)
    check(
        "pasted image enables send without text",
        js(web, "!document.getElementById('send-btn').disabled"),
    )
    fail = True
    js(
        web,
        "{let i=document.getElementById('user-input');i.value='保留失败草稿';i.dispatchEvent(new Event('input'));document.getElementById('send-btn').click();}",
    )
    wait(
        lambda: (
            len(requests) == 2
            and js(web, "!busy && document.querySelector('.bubble--error') !== null")
        )
    )
    check(
        "failed send keeps editable text and image",
        js(
            web,
            "document.getElementById('user-input').value === '保留失败草稿' && attachments.length === 1 && !document.getElementById('user-input').disabled",
        ),
    )
    fail = False
    js(web, "document.getElementById('send-btn').click()")
    wait(
        lambda: (
            len(requests) == 3
            and not ai._attachments
            and js(web, "!busy && !document.getElementById('user-input').value")
        )
    )
    check("retry succeeds and clears only the submitted draft", len(requests) == 3)

    # A bottom-bar question must not overwrite an unsent chat draft, including
    # when the screenshot needs retrying after a failed request.
    with patch.object(QFileDialog, "getOpenFileNames", return_value=([str(path)], "")):
        ai._action_choose_images({})
    js(web, "document.getElementById('user-input').value='另一个未发送草稿'")
    fail = True
    driver.start(50)
    ai._capture_image(True)
    driver.stop()
    wait(
        lambda: (
            len(requests) == 4
            and js(web, "!busy && !!document.querySelector('.msg.user .image-action')")
        )
    )
    check(
        "external screenshot failure preserves the existing composer draft",
        js(
            web,
            "document.getElementById('user-input').value === '另一个未发送草稿' && attachments.length === 1",
        ),
    )
    fail = False
    js(web, "document.querySelector('.msg.user .image-action').click()")
    wait(lambda: len(requests) == 5 and js(web, "!busy") and len(ai._attachments) == 1)
    check(
        "external screenshot retries the image and keeps unsent attachments",
        requests[-1]["messages"][-1]["content"][1]["type"] == "image_url"
        and len(ai._draft_image_ids) == 1,
    )
    js(web, "clearChat()")
    wait(lambda: not ai._attachments)

    ai._dock.hide()
    failed_requests_before = len(requests)

    def cancel_capture():
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, ai_images.RegionCapture):
            QTest.keyClick(dialog, Qt.Key.Key_Escape)

    cancel = QTimer()
    cancel.timeout.connect(cancel_capture)
    cancel.start(30)
    ai._capture_image(True)
    cancel.stop()
    check(
        "cancel does not send or open the hidden dock",
        len(requests) == failed_requests_before and ai._dock.isHidden(),
    )

    # Recreate the complete webview from stored configuration.
    ai.cleanup_ai_assistant_sidebar()
    ai.show_ai_assistant()
    wait(
        lambda: (
            ai._page_ready
            and js(
                ai._webview,
                "document.getElementById('model-label').textContent.includes('deepseek-flash')",
            )
        )
    )
    check(
        "default AI survives closing and recreating the sidebar",
        ai._load_settings()["provider"] == "deepseek"
        and ai._load_settings()["model"] == "deepseek-flash",
    )
    ai._dock.hide()
    owner = mw.dual_review
    from aqt.builtin_features.review_tools.config import get_config

    policy = get_config("policy")
    mw.review_tools.config.save("policy", policy | {"style": "advanced"})
    mw.review_tools.changed()
    wait(
        lambda: js(
            mw.reviewer.bottom.web,
            "!!document.querySelector('.timer_style') && document.querySelectorAll('#ai-screenshot').length === 1",
        )
    )
    check(
        "advanced bottom bar exposes one screenshot button",
        js(
            mw.reviewer.bottom.web,
            "document.querySelectorAll('#ai-screenshot').length === 1",
        ),
    )
    mw.review_tools.config.save("policy", policy)
    mw.review_tools.changed()
    owner.toggle()
    left, right = owner.panels
    wait(lambda: not left.pending and not right.pending)
    right.deck.setCurrentIndex(right.deck.findData(decks[1]))
    wait(
        lambda: (
            owner.enabled
            and all(panel.reviewer.card and not panel.pending for panel in owner.panels)
        )
    )
    wait(
        lambda: all(
            js(panel.reviewer.bottom.web, "!!document.getElementById('ai-screenshot')")
            for panel in owner.panels
        )
    )
    check(
        "both dual-review panes expose screenshot questions",
        all(
            js(panel.reviewer.bottom.web, "!!document.getElementById('ai-screenshot')")
            for panel in owner.panels
        ),
    )
    owner.toggle()
    wait(lambda: not owner.enabled)
    mw.resize(560, 750)
    wait(
        lambda: js(
            mw.reviewer.bottom.web,
            "[...document.querySelectorAll('#innertable button')].every(b => {const r=b.getBoundingClientRect();return r.left>=0 && r.right<=innerWidth+1})",
        )
    )
    check(
        "narrow review retains visible usable buttons",
        mw.learning_workspace.native.viewport.width()
        == mw.learning_workspace.native.width(),
    )
    mw.grab().save(str(BASE / "narrow.png"))
    check(
        "screenshot questions do not change review scheduling",
        schedule == mw.col.db.all("select id,due,reps,ivl from cards order by id")
        and mw.col.db.scalar("select count(*) from revlog") == 0,
    )
    check(
        "no image payload is saved in collection settings",
        not any("data:image/" in str(value) for value in mw.col.all_config().values()),
    )
    ai.cleanup_ai_assistant_sidebar()
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
