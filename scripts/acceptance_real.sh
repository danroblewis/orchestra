#!/bin/sh
# Run the real-model acceptance flow on every harness: build the wheel, install it in a
# fresh venv, and let tests/acceptance/test_real_flow.py start one full instance per
# harness (Pi, Claude Code, Codex) with real agents, send the Supervisor a request, and
# check that the code lands on main. Occasional: it needs the harness binaries and models.
#
#   scripts/acceptance_real.sh [harness,harness,...]
#
# Models come from the environment (see the test's docstring); defaults are this repo's
# orchestra.toml provider/model for Pi, haiku for Claude Code, Codex's default for Codex.
# A harness whose binary is missing is skipped. Reports land in logs/acceptance-<harness>-<model>.json.
#
#   scripts/acceptance_real.sh                 # all three
#   scripts/acceptance_real.sh pi,claude_code  # a subset
set -e
cd "$(dirname "$0")/.."
VENV=$(mktemp -d)/venv
rm -rf dist && uv build --wheel -q
uv venv -q "$VENV" && uv pip install -q --python "$VENV/bin/python" dist/orchestra-*.whl
mkdir -p logs
ORCHESTRA_ACCEPTANCE=1 ORCHESTRA_ACCEPTANCE_PYTHON="$VENV/bin/python" \
ORCHESTRA_ACCEPTANCE_HARNESSES="${1:-pi,claude_code,codex}" \
  uv run pytest tests/acceptance/test_real_flow.py -q -s -p no:cacheprovider -rs
