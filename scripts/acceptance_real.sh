#!/bin/sh
# Run the real-model acceptance flow: build the wheel, start it as a full instance with
# real Pi agents, send the Supervisor a request, and check that the code lands on main.
#
#   scripts/acceptance_real.sh [provider] [model]
#
# Defaults to Pi's own default provider and model. Prints a REPORT line at the end and
# writes it to logs/acceptance-<model>.json for comparing models and harnesses.
set -e
cd "$(dirname "$0")/.."
PROVIDER=${1:-${ORCHESTRA_ACCEPTANCE_PROVIDER:-}}
MODEL=${2:-${ORCHESTRA_ACCEPTANCE_MODEL:-}}
PORT=${PORT:-8079}
VENV=$(mktemp -d)/venv
rm -rf dist && uv build --wheel -q
uv venv -q "$VENV" && uv pip install -q --python "$VENV/bin/python" dist/orchestra-*.whl
mkdir -p logs
LOG=logs/acceptance-target.log
"$VENV/bin/python" scripts/acceptance_target.py --port "$PORT" --real \
  ${PROVIDER:+--provider "$PROVIDER"} ${MODEL:+--model "$MODEL"} > "$LOG" 2>&1 &
TARGET=$!
trap 'pkill -P $TARGET 2>/dev/null; kill $TARGET 2>/dev/null; pkill -f "$VENV/bin/python -m orchestra" 2>/dev/null' EXIT
for _ in $(seq 1 60); do curl -s -m 2 -o /dev/null "http://127.0.0.1:$PORT/api/state" && break; sleep 2; done
ORCHESTRA_ACCEPTANCE=1 ORCHESTRA_TARGET_URL="http://127.0.0.1:$PORT" \
ORCHESTRA_ACCEPTANCE_MODEL="$MODEL" ORCHESTRA_ACCEPTANCE_REPORT="logs/acceptance-${MODEL:-default}.json" \
  uv run pytest tests/acceptance/test_real_flow.py -q -s -p no:cacheprovider
