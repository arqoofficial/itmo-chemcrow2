#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

find "$SCRIPT_DIR" -name '.env.example' -type f | while read -r example; do
  target="${example%.example}"
  if [ -f "$target" ]; then
    echo "skip: $target already exists"
  else
    cp "$example" "$target"
    echo "created: $target"
  fi
done
