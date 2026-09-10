"""Check source syntax, JSON, archive identity, and upstream differences."""
import ast
import hashlib
import json
from pathlib import Path
import warnings
import zipfile
import sys

root = Path(__file__).resolve().parents[1]
addon = root / "addon"
upstream = root / "original" / "upstream"
def meaningful(name):
    return "__MACOSX" not in Path(name).parts and Path(name).name != ".DS_Store"
files = [p for p in addon.rglob("*") if p.is_file() and meaningful(p.relative_to(addon)) and "__pycache__" not in p.parts]
imports = set()
captured = []
for p in files:
    if p.suffix == ".py":
        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            tree = ast.parse(p.read_text(encoding="utf-8-sig"), filename=str(p))
        captured.extend(f"{p.name}:{w.lineno}: {w.message}" for w in ws)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(n.name for n in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                imports.add(node.module)
    elif p.suffix == ".json":
        json.loads(p.read_text(encoding="utf-8-sig"))
with zipfile.ZipFile(root / "original" / "236979321.ankiaddon") as z:
    changed = [str(p.relative_to(addon)) for p in files if p.relative_to(addon).as_posix() not in z.namelist() or p.read_bytes() != z.read(p.relative_to(addon).as_posix())]
    removed = [n for n in z.namelist() if not n.endswith('/') and meaningful(n) and not (addon / n).exists()]
differences = [p.relative_to(addon).as_posix() for p in files if not (upstream / p.relative_to(addon)).exists() or p.read_bytes() != (upstream / p.relative_to(addon)).read_bytes()]
content_differences = [name for name in differences if not (upstream / name).exists() or (addon / name).read_bytes().replace(b'\r\n', b'\n') != (upstream / name).read_bytes().replace(b'\r\n', b'\n')]
report = dict(file_count=len(files), python_count=sum(p.suffix == ".py" for p in files), json_count=sum(p.suffix == ".json" for p in files), archive_differences=changed, archive_removed=removed, upstream_byte_difference_count=len(differences), upstream_content_differences=content_differences, imports=sorted(imports), syntax_warnings=captured)
(root / "docs" / "source-inspection.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps({k:v for k,v in report.items() if k not in ("imports", "syntax_warnings")}, indent=2))
if "--baseline" in sys.argv:
    assert not changed and not removed
