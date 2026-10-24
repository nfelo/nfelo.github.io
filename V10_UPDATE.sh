#!/usr/bin/env bash
set -euo pipefail
v10_root="$(cd -- "$(dirname -- "$0")" && pwd)"
python3 "$v10_root/scripts/v10/run_update.py" --repo "$v10_root" "$@"
