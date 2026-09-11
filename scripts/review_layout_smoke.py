"""Exercise the real review WebViews with synthetic text/media and an isolated profile."""

import html
import json
import os
import subprocess
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
mode = sys.argv[2] if len(sys.argv) > 2 else "verify"
assert name and Path(name).name == name and name not in (".", "..")
BASE = ROOT / "runtime" / name
PROFILE = BASE / "Review-Layout-Test"
os.environ.pop("ANKIDEV", None)
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "review-layout-smoke-" + name
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
results = {"checks": {}, "geometry": {}, "errors": [], "mode": mode}


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
    pm.create("Review-Layout-Test")
    pm.load("Review-Layout-Test")
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
    col = Collection(str(PROFILE / "collection.anki2"))
    model = col.models.by_name("Basic")
    did = col.decks.id("布局验收::合成卡片")
    col.media.write_data(
        "layout.svg",
        b'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900"><rect width="1200" height="900" fill="#d5e8df"/><circle cx="600" cy="450" r="300" fill="#7fae99"/><text x="400" y="460" font-size="60">Synthetic image</text></svg>',
    )
    for index in range(8):
        note = col.new_note(model)
        for field in ("Front", "Back"):
            content = (
                f"<h2>{field} · 合成卡片 {index}</h2>"
                + "<p>这段长文本用于检查窗口变化后的换行与滚动。</p>" * 18
                + '<img src="layout.svg"><p id="layout-end">内容末尾</p>'
            )
            if index % 2 == 0:
                content = (
                    '<style>img{max-width:100%;height:auto}</style><body style="margin:8px;background:white"><input id="keep-input" value=""><button onclick="this.textContent=\'已展开\'">展开图片</button>'
                    + content
                    + "</body>"
                )
                note[field] = (
                    '<iframe id="receiver" width="100%" style="border:0;height:0" srcdoc="'
                    + html.escape(content, quote=True)
                    + '"></iframe><script>document.body.style.margin="0";document.body.style.padding="0";'
                    + 'document.getElementById("receiver").style.height=(window.innerHeight-5)+"px";</script>'
                )
            else:
                note[field] = content
        col.add_note(note, did)
    col.decks.select(did)
    col.close()


def wait(predicate, timeout=30):
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


def settle():
    wait(lambda: not mw._background_op_count)
    until = time.monotonic() + 0.7
    wait(lambda: time.monotonic() >= until)


def measure(label):
    settle()
    data = {}
    for key, widget in (
        ("window", mw),
        ("workspace", w),
        ("native", w.native),
        ("card", mw.web),
        ("bottom", mw.bottomWeb),
    ):
        rect = widget.geometry()
        data[key] = {
            "rect": [rect.x(), rect.y(), rect.width(), rect.height()],
            "min": [widget.minimumWidth(), widget.minimumHeight()],
            "max": [widget.maximumWidth(), widget.maximumHeight()],
        }
    data["bottom_dom"] = js(
        mw.bottomWeb,
        """({width: innerWidth, height: innerHeight,
        nodes: ['html','body','#outer','#innertable','#middle','button'].map(s=>{
            const e=document.querySelector(s), r=e?.getBoundingClientRect(), c=e&&getComputedStyle(e);
            return {s, rect:r?.toJSON(), height:c?.height, min:c?.minHeight, padding:c?.padding, position:c?.position};
        })})""",
    )
    data["card_dom"] = js(
        mw.web,
        """({height:innerHeight,frameHeight:document.getElementById('receiver')?.getBoundingClientRect().height})""",
    )
    results["geometry"][label] = data
    print("GEOMETRY", label, json.dumps(data), flush=True)
    mw.grab().save(str(BASE / f"{mode}-{label}.png"))
    return data


def controls_fit(label):
    value = js(
        mw.bottomWeb,
        """Array.from(document.querySelectorAll('button')).every(e=>{
        const r=e.getBoundingClientRect();return r.width>0 && r.left>=0 && r.top>=0 && r.right<=innerWidth+1 && r.bottom<=innerHeight+1;
    }) && Array.from(document.querySelectorAll('.stattxt,.nobold')).filter(e=>e.offsetWidth && e.textContent).every(e=>{
        const r=e.getBoundingClientRect();return r.top>=0 && r.bottom<=innerHeight+1;
    })""",
    )
    if not value:
        measure(label + "-invalid")
        results["invalid_controls"] = js(
            mw.bottomWeb,
            """Array.from(document.querySelectorAll('button,.stattxt,.nobold')).map(e=>({text:e.textContent,rect:e.getBoundingClientRect().toJSON(),display:getComputedStyle(e).display,parentDisplay:getComputedStyle(e.parentElement).display}))""",
        )
    check(label + " buttons and counts fit", value)
    check(
        label + " compact footer",
        40 <= mw.bottomWeb.height() <= (160 if mw.bottomWeb.width() <= 583 else 110),
    )


def frame_fits(label):
    check(
        label + " full-card iframe follows viewport",
        js(
            mw.web,
            """Math.abs(innerHeight-document.getElementById('receiver').getBoundingClientRect().height-5)<=1""",
        ),
    )


def drag(edge, dx=0, dy=0):
    handle = w.native.viewport.handles[edge]
    start = handle.rect().center()
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(handle, start + QPoint(dx, dy))
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton)
    settle()


def buttons():
    return js(
        mw.bottomWeb,
        "Array.from(document.querySelectorAll('button[data-ease]')).map(e=>Number(e.dataset.ease))",
    )


def click_web(web, selector):
    point = js(
        web,
        f"(()=>{{const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];}})()",
    )
    QTest.mouseClick(
        web.focusProxy() or web,
        Qt.MouseButton.LeftButton,
        pos=QPoint(round(point[0]), round(point[1])),
    )


def collection_snapshot():
    return {
        "notes": mw.col.db.all("SELECT * FROM notes ORDER BY id"),
        "cards": mw.col.db.all("SELECT * FROM cards ORDER BY id"),
        "notetypes": mw.col.db.all("SELECT * FROM notetypes ORDER BY id"),
        "templates": mw.col.db.all("SELECT * FROM templates ORDER BY ntid,ord"),
        "revlog": mw.col.db.all("SELECT * FROM revlog ORDER BY id"),
    }


def verify_layout():
    from aqt.builtin_features.learning.review_layout import LAYOUT_KEY
    from aqt.theme import Theme, theme_manager

    viewport = w.native.viewport
    before = collection_snapshot()
    cid = mw.reviewer.card.id
    frame_fits("initial")
    controls_fit("initial")
    if mode == "restart":
        expected = json.loads((BASE / "expected-layout.json").read_text())
        check(
            "new process restores both saved dimensions",
            mw.pm.profile[LAYOUT_KEY] == expected
            and list(viewport.ratios) == [expected["width"], expected["height"]],
        )
        check(
            "restored size is applied to the card",
            mw.web.width() < viewport.width() - 50
            and mw.web.height() < viewport.height() - 30,
        )
        w.reset_layout_button.click()
        settle()
        check(
            "reset removes remembered size in the current profile",
            mw.pm.profile[LAYOUT_KEY] == {"width": 1.0, "height": 1.0},
        )
        frame_fits("restart reset")
        check(
            "restart layout operations preserve templates and collection rows",
            collection_snapshot() == before,
        )
        return

    wait(
        lambda: js(
            mw.web,
            "!!document.getElementById('receiver').contentDocument.getElementById('keep-input')",
        )
    )
    js(
        mw.web,
        """(()=>{const f=document.getElementById('receiver');window.layoutFrameDocument=f.contentDocument;f.contentDocument.getElementById('keep-input').value='keep me';f.contentDocument.querySelector('button').click();f.contentWindow.scrollTo(0,180);})()""",
    )
    width, height = mw.web.width(), mw.web.height()
    zoom = mw.web.zoomFactor()
    drag("right", dx=-150)
    drag("bottom", dy=-120)
    check(
        "mouse dragging changes width and height",
        mw.web.width() < width - 100 and mw.web.height() < height - 60,
    )
    check(
        "dragging preserves card identity face and zoom",
        mw.reviewer.card.id == cid
        and mw.reviewer.state == "question"
        and mw.web.zoomFactor() == zoom,
    )
    check(
        "resizing keeps iframe document input expanded content and scroll",
        js(
            mw.web,
            """(()=>{const f=document.getElementById('receiver');return f.contentDocument===window.layoutFrameDocument && f.contentDocument.getElementById('keep-input').value==='keep me' && f.contentDocument.querySelector('button').textContent==='已展开' && f.contentWindow.scrollY>0;})()""",
        ),
    )
    frame_fits("window drag")
    measure("window-dragged")
    preferred = viewport.ratios
    mw.activateWindow()
    settle()
    mw.on_toggle_full_screen()
    settle()
    check(
        "fullscreen retains the saved layout proportions", viewport.ratios == preferred
    )
    frame_fits("fullscreen")
    width, height = mw.web.width(), mw.web.height()
    drag("left", dx=70)
    drag("bottom", dy=-70)
    check(
        "fullscreen supports both drag directions",
        mw.web.width() < width and mw.web.height() < height,
    )
    controls_fit("fullscreen dragged")
    frame_fits("fullscreen dragged")
    w.reset_layout_button.click()
    settle()
    check(
        "reset fills the available card area",
        viewport.ratios == (1, 1) and viewport.height() - mw.web.height() == 8,
    )
    frame_fits("fullscreen reset")
    measure("fullscreen-reset")
    click_web(mw.bottomWeb, "#ansbut")
    wait(lambda: mw.reviewer.state == "answer" and len(buttons()) == 4)
    settle()
    check("show answer remains clickable", mw.reviewer.card.id == cid)
    frame_fits("answer")
    controls_fit("answer")
    selector = w.review_bar.findChild(QComboBox)
    selector.setCurrentIndex(1)
    wait(lambda: len(buttons()) == 2)
    check(
        "PassFail switch keeps current answer",
        mw.reviewer.card.id == cid and mw.reviewer.state == "answer",
    )
    controls_fit("PassFail")
    selector.setCurrentIndex(0)
    wait(lambda: buttons() == [1, 2, 3, 4])
    check(
        "layout and mode changes leave collection data unchanged",
        collection_snapshot() == before,
    )
    measure("fullscreen-answer")
    mw.on_toggle_full_screen()
    mw.resize(640, 480)
    settle()
    check(
        "narrow window keeps viewport and footer inside their parent",
        viewport.rect().contains(mw.web.geometry())
        and w.native.rect().contains(mw.bottomWeb.geometry()),
    )
    controls_fit("narrow")
    frame_fits("narrow")
    drag("right", dx=-1000)
    drag("bottom", dy=-1000)
    check(
        "dragging cannot collapse the card",
        mw.web.width() >= 400 and mw.web.height() >= 180,
    )
    controls_fit("minimum size")
    measure("minimum-size")
    sys.modules["aqt.builtin_features.synapsepro"].addon_settings[
        "theme_restart_warning_suppressed"
    ] = True
    mw.pm.set_theme(Theme.DARK)
    theme_manager.apply_style()
    mw.resize(1394, 870)
    w.reset_layout_button.click()
    settle()
    frame_fits("dark")
    controls_fit("dark")
    measure("dark-answer")
    # An actual rating is performed only after proving layout changes are read-only.
    count = mw.col.db.scalar("SELECT COUNT(*) FROM revlog")
    click_web(mw.bottomWeb, 'button[data-ease="4"]')
    wait(
        lambda: (
            mw.col.db.scalar("SELECT COUNT(*) FROM revlog") == count + 1
            and mw.reviewer.state == "question"
            and mw.reviewer.card.id != cid
        )
    )
    check(
        "native rating button records its original rating",
        mw.col.db.scalar("SELECT ease FROM revlog ORDER BY id DESC LIMIT 1") == 4,
    )
    check(
        "next card uses the ordinary text renderer",
        not js(mw.web, "!!document.getElementById('receiver')"),
    )
    QTest.keyClick(mw, Qt.Key.Key_Space)
    wait(lambda: mw.reviewer.state == "answer" and len(buttons()) == 4)
    check("space shortcut still shows the answer", mw.reviewer.state == "answer")
    wait(
        lambda: js(
            mw.web,
            "Array.from(document.querySelectorAll('#qa img')).every(e=>e.complete && e.naturalWidth>0)",
        )
    )
    js(mw.web, "window.scrollTo(0,document.documentElement.scrollHeight)")
    check(
        "long text and images scroll to the end",
        js(
            mw.web,
            "window.scrollY>0 && document.getElementById('layout-end').getBoundingClientRect().bottom<=innerHeight+2",
        ),
    )
    controls_fit("text answer")
    measure("text-image-answer")
    selector.setCurrentIndex(1)
    wait(lambda: len(buttons()) == 2)
    expected_ease = buttons()[-1]
    count = mw.col.db.scalar("SELECT COUNT(*) FROM revlog")
    QTest.keyClick(mw, Qt.Key.Key_3)
    wait(
        lambda: (
            mw.col.db.scalar("SELECT COUNT(*) FROM revlog") == count + 1
            and mw.reviewer.state == "question"
        )
    )
    check(
        "PassFail rating shortcut retains its original mapping",
        mw.col.db.scalar("SELECT ease FROM revlog ORDER BY id DESC LIMIT 1")
        == expected_ease,
    )
    drag("right", dx=-130)
    drag("bottom", dy=-80)
    expected = mw.pm.profile[LAYOUT_KEY]
    (BASE / "expected-layout.json").write_text(json.dumps(expected))
    w.finish_button.click()
    wait(lambda: mw.state == "deckBrowser")
    settle()
    check(
        "deck browser fills its page with resize handles hidden",
        mw.web.geometry() == viewport.rect()
        and all(h.isHidden() for h in viewport.handles.values()),
    )
    js(mw.web, "document.querySelector('.deck-study-card').click()")
    wait(lambda: mw.reviewer.state == "question")
    settle()
    check(
        "returning to review restores the chosen layout",
        list(viewport.ratios) == [expected["width"], expected["height"]],
    )


def verify_page_lifecycle():
    diagnosing = mode == "pages-diagnose"

    def report(label, value):
        if diagnosing:
            results["checks"][label] = bool(value)
            print("CHECK", label, bool(value), flush=True)
        else:
            check(label, value)

    def inactive(label, home=False):
        settle()
        report(
            label + " has no visible or clickable footer", not mw.bottomWeb.isVisible()
        )
        if home:
            report(
                label + " returns all footer space to the page",
                w.native.viewport.height() == w.native.height(),
            )
            report(
                label + " clears review buttons from the old document",
                js(
                    mw.bottomWeb,
                    "document.querySelectorAll('#ansbut,button[data-ease]').length",
                )
                == 0,
            )

    def resize_pages(label, home=False):
        for width, height in ((1000, 720), (640, 480)):
            mw.resize(width, height)
            inactive(f"{label} {width}x{height}", home)
        mw.showMaximized()
        inactive(label + " maximized", home)
        mw.showNormal()
        mw.activateWindow()
        settle()
        mw.on_toggle_full_screen()
        inactive(label + " fullscreen", home)
        mw.on_toggle_full_screen()
        inactive(label + " restored", home)
        measure(label)

    def change_resolution(label):
        if mode != "pages-resolution":
            return
        import win32api
        import win32con

        device = None
        for index in range(16):
            try:
                candidate_device = win32api.EnumDisplayDevices(None, index)
            except win32api.error:
                break
            if candidate_device.StateFlags & win32con.DISPLAY_DEVICE_PRIMARY_DEVICE:
                device = candidate_device.DeviceName
                break
        assert device, "No primary display"
        original = win32api.EnumDisplaySettings(device, win32con.ENUM_CURRENT_SETTINGS)
        target = None
        index = 0
        while True:
            try:
                candidate = win32api.EnumDisplaySettings(device, index)
            except win32api.error:
                break
            index += 1
            if (
                (candidate.PelsWidth, candidate.PelsHeight) == (1600, 900)
                and candidate.BitsPerPel == original.BitsPerPel
                and candidate.DisplayFrequency == original.DisplayFrequency
            ):
                target = candidate
                break
        assert target and (original.PelsWidth, original.PelsHeight) != (1600, 900)
        assert (
            win32api.ChangeDisplaySettingsEx(device, target, win32con.CDS_TEST)
            == win32con.DISP_CHANGE_SUCCESSFUL
        )
        # A separate process restores the exact original mode on EOF, request,
        # or a 15-second timeout, even if the Qt test process fails.
        restore_code = """
import os,sys,threading,win32api,win32con
device=sys.argv[1]
original=win32api.EnumDisplaySettings(device,win32con.ENUM_CURRENT_SETTINGS)
def restore():
    result=win32api.ChangeDisplaySettingsEx(device,original,0)
    os._exit(0 if result==win32con.DISP_CHANGE_SUCCESSFUL else 1)
timer=threading.Timer(15,restore)
timer.start()
print('ready',flush=True)
sys.stdin.readline()
restore()
"""
        guard_process = subprocess.Popen(
            [sys.executable, "-c", restore_code, device],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert guard_process.stdout.readline().strip() == "ready"
        try:
            check(
                label + " accepts a temporary resolution change",
                win32api.ChangeDisplaySettingsEx(device, target, 0)
                == win32con.DISP_CHANGE_SUCCESSFUL,
            )
            inactive(label + " at 1600x900", True)
            current = win32api.EnumDisplaySettings(
                device, win32con.ENUM_CURRENT_SETTINGS
            )
            check(
                label + " actually changed the display resolution",
                (current.PelsWidth, current.PelsHeight) == (1600, 900),
            )
            results.setdefault("display_modes", []).append(
                {
                    "before": [
                        original.PelsWidth,
                        original.PelsHeight,
                        original.DisplayFrequency,
                    ],
                    "during": [
                        current.PelsWidth,
                        current.PelsHeight,
                        current.DisplayFrequency,
                    ],
                }
            )
        finally:
            win32api.ChangeDisplaySettingsEx(device, original, 0)
            guard_process.communicate("restore\n", timeout=6)
            assert guard_process.returncode == 0, "Display restore watchdog failed"
        restored = win32api.EnumDisplaySettings(device, win32con.ENUM_CURRENT_SETTINGS)
        check(
            label + " restores the exact original display mode",
            (restored.PelsWidth, restored.PelsHeight, restored.DisplayFrequency)
            == (original.PelsWidth, original.PelsHeight, original.DisplayFrequency),
        )
        inactive(label + " after resolution restoration", True)

    inactive("fresh home", True)
    resize_pages("fresh home", True)
    change_resolution("fresh home resolution")
    js(mw.web, "document.querySelector('.deck-study-card').click()")
    wait(
        lambda: (
            mw.reviewer.state == "question"
            and js(mw.bottomWeb, "!!document.getElementById('ansbut')")
            and js(mw.web, "!!document.querySelector('#qa iframe, #qa h2')")
        )
    )
    settle()
    report("review shows the question controls", mw.bottomWeb.isVisible())
    cid = mw.reviewer.card.id
    w.open(0)
    inactive("statistics while review is paused")
    resize_pages("statistics while review is paused")
    w.show_review()
    settle()
    report(
        "resuming review keeps the card and question",
        mw.bottomWeb.isVisible()
        and mw.reviewer.card.id == cid
        and mw.reviewer.state == "question",
    )
    click_web(mw.bottomWeb, "#ansbut")
    wait(lambda: mw.reviewer.state == "answer" and len(buttons()) == 4)
    report("answer controls remain usable", mw.bottomWeb.isVisible())
    w.finish_button.click()
    wait(
        lambda: (
            mw.state == "deckBrowser"
            and js(mw.web, "!!document.querySelector('.deck-workspace')")
        )
    )
    inactive("home after review", True)
    resize_pages("home after review", True)
    change_resolution("home after review resolution")
    w.open(0)
    inactive("statistics from home")
    resize_pages("statistics from home")
    mw.moveToState("deckBrowser")
    wait(lambda: js(mw.web, "!!document.querySelector('.deck-study-card')"))
    settle()
    js(mw.web, "document.querySelector('.deck-study-card').click()")
    wait(
        lambda: (
            mw.reviewer.state == "question"
            and js(mw.bottomWeb, "!!document.getElementById('ansbut')")
        )
    )
    settle()
    report("reentering review restores show answer", mw.bottomWeb.isVisible())
    QTest.keyClick(mw, Qt.Key.Key_Space)
    wait(lambda: mw.reviewer.state == "answer" and len(buttons()) == 4)
    count = mw.col.db.scalar("SELECT COUNT(*) FROM revlog")
    QTest.keyClick(mw, Qt.Key.Key_4)
    wait(
        lambda: (
            mw.col.db.scalar("SELECT COUNT(*) FROM revlog") == count + 1
            and mw.reviewer.state == "question"
        )
    )
    report(
        "answer and rating shortcuts work after page changes",
        mw.col.db.scalar("SELECT ease FROM revlog ORDER BY id DESC LIMIT 1") == 4,
    )
    if diagnosing:
        assert all(results["checks"].values()), (
            "Reproduced inactive-page review controls or footer space"
        )


if mode == "executable":
    assert (BASE / ".builtin-test").read_text() == "synthetic data only"
    assert package, "Set ANKI_BUILTIN_PACKAGE_ROOT to the packaged application"
    executable = Path(package).resolve() / "Anki.exe"
    environment = os.environ | {
        "ANKI_BUILTIN_DIAGNOSTICS": "1",
        "ANKI_BUILTIN_DIAGNOSTICS_EXIT": "1",
    }
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    completed = subprocess.run(
        [
            str(executable),
            "-b",
            str(BASE),
            "-p",
            "Review-Layout-Test",
            "--safemode",
            "-l",
            "zh_CN",
        ],
        env=environment,
        startupinfo=startup,
        timeout=60,
        check=True,
    )
    diagnostics = json.loads(
        (BASE / "builtin_features/startup-diagnostics.json").read_text(encoding="utf8")
    )
    check(
        "packaged executable opens the isolated collection",
        diagnostics["ready"] and diagnostics["collection_open"],
    )
    check(
        "packaged executable loads its own built-in code",
        Path(diagnostics["synapsepro_source"]).is_relative_to(Path(package).resolve()),
    )
    check("packaged executable exits normally", completed.returncode == 0)
    results["passed"] = True
    (BASE / "executable-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
    )
    sys.exit(0)


try:
    if mode != "restart":
        prepare()
    assert (BASE / ".builtin-test").read_text() == "synthetic data only"
    from PyQt6.QtTest import QTest

    import aqt
    from aqt.progress import ProgressDialog
    from aqt.qt import QApplication, QComboBox, QLabel, QPoint, Qt, QTimer

    app = aqt._run(
        [
            "anki",
            "-b",
            str(BASE),
            "-p",
            "Review-Layout-Test",
            "--safemode",
            "-l",
            "zh_CN",
        ],
        exec=False,
    )
    mw = aqt.mw

    def dialog_guard():
        modal = QApplication.activeModalWidget()
        if modal and not isinstance(modal, ProgressDialog):
            results["errors"].append(
                " | ".join(label.text() for label in modal.findChildren(QLabel))
            )
            modal.reject()

    guard = QTimer()
    guard.timeout.connect(dialog_guard)
    guard.start(500)
    wait(lambda: mw.col and mw.state == "deckBrowser" and mw.learning_workspace.store)
    wait(lambda: sys.modules["aqt.builtin_features.synapsepro"]._daily_maintenance_done)
    w = mw.learning_workspace
    mw.resize(1394, 870)
    mw.move(80, 80)
    wait(
        lambda: (
            mw.web._domDone
            and js(mw.web, "!!document.querySelector('.deck-workspace')")
        )
    )
    settle()
    if mode in ("pages", "pages-diagnose", "pages-resolution"):
        verify_page_lifecycle()
    else:
        js(mw.web, "document.querySelector('.deck-study-card').click()")
        wait(
            lambda: (
                mw.reviewer.state == "question"
                and js(mw.bottomWeb, "!!document.getElementById('ansbut')")
                and js(mw.web, "!!document.querySelector('#qa iframe, #qa h2')")
            )
        )
        measure("window-question")
        if mode == "diagnose":
            mw.activateWindow()
            mw.on_toggle_full_screen()
            measure("fullscreen-question")
            mw.reviewer._showAnswer()
            wait(lambda: len(buttons()) == 4)
            measure("fullscreen-answer")
            mw.on_toggle_full_screen()
            measure("window-answer")
            check(
                "review front and answer remain available",
                mw.reviewer.state == "answer",
            )
        else:
            verify_layout()
    w.profile_close()
    mw.pm.save()
    mw.col.close()
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
