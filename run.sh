#!/usr/bin/env bash
# ─────────────────────────────────────────────────
#  Universal Android App Trainer
#
#  Usage:
#    ./run.sh                          # interactive menu
#    ./run.sh train com.example.app    # jump to train mode
#    ./run.sh run   com.example.app    # run all saved flows
#    ./run.sh list  com.example.app    # list recorded flows
#    ./run.sh generate com.example.app # generate pytest file
# ─────────────────────────────────────────────────
set -e
cd "$(dirname "$0")"

VENV=.venv
if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment…"
    python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"

if ! python3 -c "import rich" 2>/dev/null; then
    echo "Installing dependencies…"
    pip install -r requirements.txt -q
fi

mkdir -p reports/screenshots tests/generated

python3 cli.py "$@"
