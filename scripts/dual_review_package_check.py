"""Start the packaged executable only against an already verified synthetic profile."""

import json
import os
import sqlite3
import subprocess
import sys
import uuid
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
base = (ROOT / "runtime" / sys.argv[1]).resolve()
assert base.parent == (ROOT / "runtime").resolve()
assert (base / ".builtin-test").read_text() == "synthetic data only"
assert json.loads((base / "results.json").read_text(encoding="utf-8"))["passed"]
package = ROOT / "dist" / "Anki-dual-review-26.8.1"
assert "dual_review" in json.loads(
    (package / "INTEGRATED-BUILD.json").read_text(encoding="utf-8")
)
database = base / "Dual-Review-Test" / "collection.anki2"


def snapshot():
    with closing(
        sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    ) as connection:
        return {
            "cards": connection.execute(
                "select id,did,queue,type,due,ivl,reps,lapses from cards order by id"
            ).fetchall(),
            "revlog": connection.execute("select * from revlog order by id").fetchall(),
        }


before = snapshot()
assert before["revlog"]
diagnostics = base / "builtin_features" / "startup-diagnostics.json"
previous_stamp = diagnostics.stat().st_mtime_ns if diagnostics.exists() else None
env = os.environ.copy()
env.pop("ANKIDEV", None)
env.pop("ANKI_TEST_MODE", None)
env.update(
    ANKI_BUILTIN_DIAGNOSTICS="1",
    ANKI_BUILTIN_DIAGNOSTICS_EXIT="1",
    ANKI_SINGLE_INSTANCE_KEY="dual-review-executable-" + uuid.uuid4().hex,
    QT_QPA_PLATFORM="offscreen",
    QT_QPA_FONTDIR=str(Path(env.get("WINDIR", "C:/Windows")) / "Fonts"),
    QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu",
    PYTHONUTF8="1",
    PYTHONIOENCODING="utf-8",
)
# The offscreen Qt platform keeps the test off the desktop while allowing its
# virtual window to be exposed, which WebEngine needs for startup rendering.
with (base / "executable.log").open("wb") as log:
    result = subprocess.run(
        [
            str(package / "Anki.exe"),
            "-b",
            str(base),
            "-p",
            "Dual-Review-Test",
            "--safemode",
            "-l",
            "zh_CN",
        ],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        timeout=45,
    )
assert result.returncode == 0, result.returncode
assert diagnostics.stat().st_mtime_ns != previous_stamp, (
    "No fresh startup report was written"
)
report = json.loads(
    (base / "builtin_features" / "startup-diagnostics.json").read_text(encoding="utf-8")
)
assert report["ready"] and report["collection_open"] and not report["developer_mode"]
assert report["legacy_modules_loaded"] == []
assert Path(report["synapsepro_source"]).is_relative_to(package)
assert snapshot() == before, "Restart changed scheduling or review history"
verification = {
    "passed": True,
    "cards": len(before["cards"]),
    "reviews": len(before["revlog"]),
    "exit_code": result.returncode,
}
(base / "executable-results.json").write_text(
    json.dumps(verification, indent=2), encoding="utf-8"
)
print(json.dumps(verification), flush=True)
