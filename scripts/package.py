"""Package only reviewed, tracked addon files; exclude test profiles and tooling."""
from pathlib import Path
import subprocess
import zipfile

root = Path(__file__).resolve().parents[1]
paths = subprocess.check_output(["git", "ls-files", "-z", "--", "addon/"], cwd=root).decode().split("\0")
dest = root / "dist" / "SynapsePro-1.5.0-local.ankiaddon"
dest.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
    for name in filter(None, paths):
        p = root / name
        z.write(p, p.relative_to(root / "addon").as_posix())
with zipfile.ZipFile(dest) as z:
    assert z.testzip() is None
    assert "__init__.py" in z.namelist() and "manifest.json" in z.namelist()
print(dest)
