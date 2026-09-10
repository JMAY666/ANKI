"""Run regression tests against the same source/runtime as the application."""

import sys
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root / p) for p in ("qt", "pylib", "out/qt", "out/pylib")]
suite = unittest.defaultTestLoader.discover(str(root / "tests"))
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
