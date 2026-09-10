"""Update an existing isolated run, with full backup and data hash verification.

Only runtime/<run>/addons21/236979321 is replaced. Unknown old addon files
(potential user data) are retained, except regenerable Python/macOS metadata.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
run = sys.argv[1] if len(sys.argv) > 1 else "manual"
assert run and Path(run).name == run and run not in (".", "..", "backups")
base = (root / "runtime" / run).resolve()
assert base.is_relative_to(root / "runtime")
target = base / "addons21" / "236979321"
assert target.is_dir() and (base / "prefs21.db").is_file()
command = r"Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'anki.exe' -or ($_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'import aqt|aqt\.run\(') } | Select-Object -ExpandProperty ProcessId"
running = subprocess.check_output(["powershell", "-NoProfile", "-Command", command], text=True).strip()
if running:
    raise SystemExit("Close Anki before deploying; active process IDs: " + running)

def user_hashes():
    return {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in base.rglob("*") if p.is_file() and "addons21" not in p.relative_to(base).parts}

before = user_hashes()
stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
backup = root / "runtime" / "backups" / (run + "-" + stamp)
assert not backup.exists() and not backup.is_relative_to(base)
shutil.copytree(base, backup)
# The immutable original commit is reachable after merging both histories;
# fresh clones need not have the old local-only baseline tag.
old_tracked = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "8710fb8e2a8032987316bcfaf855535531071f28", "--", "addon/"], cwd=root, text=True).splitlines()
old_tracked = {str(Path(p).relative_to("addon")).replace("\\", "/") for p in old_tracked}
stage = base / (".addon-stage-" + stamp)
shutil.copytree(root / "addon", stage, ignore=shutil.ignore_patterns("__MACOSX", ".DS_Store", "__pycache__", "*.pyc"))
preserved = []
for p in target.rglob("*"):
    rel = p.relative_to(target)
    if not p.is_file() or any(x in rel.parts for x in ("__MACOSX", "__pycache__")) or p.name == ".DS_Store" or p.suffix == ".pyc":
        continue
    if rel.as_posix() not in old_tracked and not (stage / rel).exists():
        (stage / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, stage / rel)
        preserved.append(rel.as_posix())
# Keep the old install outside addons21; it cannot load as a second addon.
previous = base / (".addon-previous-" + stamp)
target.rename(previous)
try:
    stage.rename(target)
except Exception:
    previous.rename(target)
    raise
after = user_hashes()
# Exclude the newly retained rollback install from the user-data comparison.
after = {p:h for p,h in after.items() if not p.startswith(previous.name + "/")}
assert before == after, "Unexpected profile data change; full backup is available"
report = {"run": run, "backup": str(backup), "previous_addon": str(previous),
          "profile_files_unchanged": len(before), "preserved_extra_files": preserved,
          "version": json.loads((target / "manifest.json").read_text())["human_version"]}
(root / "runtime" / ("deployment-" + run + ".json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps({k:v for k,v in report.items() if k != "preserved_extra_files"}, indent=2))
