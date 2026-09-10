"""Package only reviewed, tracked addon files; exclude test profiles and tooling."""
from pathlib import Path
import subprocess
import zipfile
import json

root = Path(__file__).resolve().parents[1]
paths = subprocess.check_output(["git", "ls-files", "-z", "--", "addon/"], cwd=root).decode().split("\0")
version = json.loads((root / "addon/manifest.json").read_text())["human_version"]
dest = root / "dist" / f"SynapsePro-{version}.ankiaddon"
dest.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
    for name in filter(None, paths):
        p = root / name
        if not p.is_file():
            continue  # Tracked removals may not have been staged yet.
        z.write(p, p.relative_to(root / "addon").as_posix())
with zipfile.ZipFile(dest) as z:
    assert z.testzip() is None
    assert "__init__.py" in z.namelist() and "manifest.json" in z.namelist()
print(dest)
