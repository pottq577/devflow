#!/usr/bin/env python3
from pathlib import Path
import os, sys

plugin_root = Path(__file__).resolve().parents[3]
script = plugin_root / "scripts" / "devflow.py"
os.execv(sys.executable, [sys.executable, str(script), *sys.argv[1:]])
