"""Pytest conftest for dataset pipeline tests.

Adds dataset/scripts/ (the parent of this tests/ directory) to sys.path so
tests can `import utils` the same way the pipeline scripts do (they rely on
Python automatically prepending the executed script's own directory).
"""
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

ROOT = SCRIPTS_DIR.parents[1]
OUT_DIR = ROOT / "dataset" / "output"
