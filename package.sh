#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

OUTPUT="devflow-chat.zip"

rm -f "$OUTPUT"

zip -r "$OUTPUT" \
  AGENTS.md \
  CLAUDE.md \
  README.md \
  docs \
  plugins/devflow \
  -x "*/__pycache__/*" \
     "*.pyc" \
     "*.log"

echo "Created: $SCRIPT_DIR/$OUTPUT"