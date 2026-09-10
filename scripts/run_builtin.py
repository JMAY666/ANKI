"""Run the compiled local Anki source with normal backup behavior."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ("qt", "pylib", "out/qt", "out/pylib")]
os.environ.pop("ANKIDEV", None)

import aqt

aqt.run()
