#!/usr/bin/env python3
"""Host-native Claude Code entrypoint; never launches a nested Claude CLI."""
import os
import sys
from pathlib import Path

plugin_root = Path(__file__).resolve().parents[3]
script = plugin_root / "scripts" / "devflow_host.py"
os.execv(sys.executable, [sys.executable, str(script), "--native-host", "claude", *sys.argv[1:]])
