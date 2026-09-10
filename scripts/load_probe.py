"""Integration probe using Anki's documented exec=False test entry point.

Does not run the event loop or accept onboarding. Not a UI acceptance test.
"""
from pathlib import Path
import json
import os
import sys

root = Path(__file__).resolve().parents[1]
base = root / "runtime" / "load-probe"
assert (base / "prefs21.db").exists(), "Run prepare.py load-probe first"
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "synapsepro-isolated-load-probe"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import aqt
app = aqt._run(["anki", "-b", str(base), "-p", "SynapsePro-Test", "-l", "en_US"], exec=False)
addon = sys.modules.get("236979321")
report = {
    "anki_version": aqt.appVersion,
    "app_created": app is not None,
    "addon_imported": addon is not None,
    "modules_loaded": bool(addon and addon.modules_loaded),
    "profile_hook_registered": bool(addon and addon.on_profile_open in aqt.gui_hooks.profile_did_open._hooks),
    "profile_base": aqt.mw.pm.base,
    "event_loop_executed": False,
    "onboarding_accepted": False,
}
(base / "load-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2), flush=True)
ok = all(report[k] for k in ("app_created", "addon_imported", "modules_loaded", "profile_hook_registered"))
# Offscreen probe has no UI lifecycle; terminate only this dedicated subprocess.
sys.stdout.flush()
if hasattr(sys.stderr, "flush"):
    sys.stderr.flush()
os._exit(0 if ok else 1)
