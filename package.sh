#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CHANGELOG="plugins/devflow/CHANGELOG.md"

VERSION="$(
  grep -m1 -E '^##[[:space:]]+\[?v?[0-9]+\.[0-9]+\.[0-9]+' "$CHANGELOG" \
    | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' \
    | head -n1
)"

if [[ -z "$VERSION" ]]; then
  echo "Failed to detect DevFlow version from $CHANGELOG" >&2
  exit 1
fi

OUTPUT="devflow-${VERSION}.zip"

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