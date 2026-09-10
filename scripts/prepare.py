"""Create a fresh isolated Anki fixture; never overwrite an existing run."""
from pathlib import Path
import json
import shutil
import sys
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
base = ROOT / "runtime" / (sys.argv[1] if len(sys.argv) > 1 else "manual")
assert base.resolve().is_relative_to(ROOT / "runtime")
if base.exists():
    raise SystemExit(f"Already exists; reuse it or choose a new run name: {base}")
base.mkdir(parents=True)
shutil.copytree(ROOT / "addon", base / "addons21" / "236979321",
                ignore=shutil.ignore_patterns("__MACOSX", ".DS_Store", "__pycache__"))
manifest = json.loads((ROOT / "addon" / "manifest.json").read_text(encoding="utf-8"))
(base / "addons21" / "236979321" / "meta.json").write_text(json.dumps({
    "name": "SynapsePro", "disabled": False, "mod": 1786729966,
    "min_point_version": manifest["min_point_version"],
    "max_point_version": manifest.get("max_point_version", 0),
    "human_version": manifest["human_version"],
}), encoding="utf-8")
from aqt.profiles import ProfileManager
from anki.collection import Collection
pm = ProfileManager(base)
pm.setupMeta()
pm.create("SynapsePro-Test")
pm.load("SynapsePro-Test")
pm.meta["defaultLang"] = "zh_CN"
pm.profile.update(autoSync=False, syncKey=None, syncMedia=False, firstRun=False)
pm.save()
col = Collection(pm.collectionPath())
did = col.decks.id("SynapsePro-Synthetic-Test")
note = col.new_note(col.models.by_name("Basic"))
note["Front"] = "Synthetic test: 2 + 2?"
note["Back"] = "4"
col.add_note(note, did)
col.close()
col = Collection(pm.collectionPath())
assert col.decks.id_for_name("SynapsePro-Synthetic-Test") == did
assert len(col.find_notes('deck:SynapsePro-Synthetic-Test')) == 1
col.close()
pm.db.close()
if base.name == "smoke-1.5.1":
    profile = base / "SynapsePro-Test"
    with sqlite3.connect(profile / "notebook.sqlite") as db:
        db.execute("CREATE TABLE notes (body TEXT)")
        db.execute("INSERT INTO notes VALUES (?)", ('Synthetic legacy note',))
    (profile / "mindmap_recovery.json").write_text('{"mindmaps": [{"title": "Synthetic old map"}]}')
    for folder in ("mindmap_web_data", "website_web_data"):
        (profile / folder).mkdir()
        (profile / folder / "synthetic").write_bytes(b"Synthetic retained user storage")
print(f"Prepared isolated profile and verified synthetic note persistence: {base}")
