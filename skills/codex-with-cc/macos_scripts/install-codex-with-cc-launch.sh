#!/bin/zsh
set -euo pipefail
SCRIPT_DIR="${0:A:h}"
exec "$SCRIPT_DIR/_runtime.sh" install_fixed_launcher.py "$@"
