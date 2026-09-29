#!/usr/bin/env python3
import os
import sys
from pathlib import Path

plugin_root = Path(__file__).resolve().parents[3]
script = plugin_root / "scripts" / "devflow_host.py"
os.execv(sys.executable, [sys.executable, str(script), *sys.argv[1:]])
