#!/bin/sh
# The sources rig: a VictoriaMetrics of its own (container orchestra-test-vm on 127.0.0.1:8431,
# data in the docker volume orchestra-test-vm-data), a bearer-token proxy in front of it
# (127.0.0.1:8432), and the generator writing the owner's metric shape into it.
#
#   tests/sources/rig/rig.sh start     # fresh data: six hours backfilled, then live
#   tests/sources/rig/rig.sh status
#   tests/sources/rig/rig.sh stop      # stops the proxy and the generator, removes the container and its data
#
# The token is in $RIG_DIR/token (default ~/.orchestra-sources-rig), outside every repository,
# with the ground truth (ground_truth.jsonl, rule.json) and the logs.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
RIG_DIR=${RIG_DIR:-$HOME/.orchestra-sources-rig}
VM_PORT=${RIG_VM_PORT:-8431}
PROXY_PORT=${RIG_PROXY_PORT:-8432}
IMAGE=${RIG_VM_IMAGE:-victoriametrics/victoria-metrics:v1.106.1}
PY=${PYTHON:-python3}

stop_pid() {
  if [ -f "$RIG_DIR/$1.pid" ]; then
    kill "$(cat "$RIG_DIR/$1.pid")" 2>/dev/null || true
    rm -f "$RIG_DIR/$1.pid"
  fi
}

case "${1:-}" in
start)
  mkdir -p "$RIG_DIR"
  chmod 700 "$RIG_DIR"
  [ -s "$RIG_DIR/token" ] || (umask 077; "$PY" -c 'import secrets; print(secrets.token_hex(24))' > "$RIG_DIR/token")
  stop_pid proxy; stop_pid generator
  docker rm -f orchestra-test-vm >/dev/null 2>&1 || true
  docker volume rm orchestra-test-vm-data >/dev/null 2>&1 || true
  docker run -d --name orchestra-test-vm -p 127.0.0.1:$VM_PORT:8428 -v orchestra-test-vm-data:/storage "$IMAGE" \
    -storageDataPath=/storage -retentionPeriod=30d -httpListenAddr=:8428 -search.latencyOffset=0s -search.disableCache >/dev/null
  for _ in $(seq 1 30); do curl -sf "http://127.0.0.1:$VM_PORT/health" >/dev/null && break; sleep 1; done
  nohup "$PY" "$HERE/proxy.py" --listen 127.0.0.1:$PROXY_PORT --to "http://127.0.0.1:$VM_PORT" \
    --token-file "$RIG_DIR/token" ${RIG_PROXY_MODE:+--mode $RIG_PROXY_MODE} > "$RIG_DIR/proxy.log" 2>&1 &
  echo $! > "$RIG_DIR/proxy.pid"
  nohup "$PY" "$HERE/generator.py" --vm "http://127.0.0.1:$VM_PORT" --dir "$RIG_DIR" > "$RIG_DIR/generator.log" 2>&1 &
  echo $! > "$RIG_DIR/generator.pid"
  for _ in $(seq 1 120); do grep -q backfilled "$RIG_DIR/generator.log" 2>/dev/null && break; sleep 1; done
  cat "$RIG_DIR/generator.log"
  echo "rig up: VictoriaMetrics 127.0.0.1:$VM_PORT, proxy 127.0.0.1:$PROXY_PORT (bearer from $RIG_DIR/token)"
  ;;
stop)
  stop_pid proxy; stop_pid generator
  docker rm -f orchestra-test-vm >/dev/null 2>&1 || true
  docker volume rm orchestra-test-vm-data >/dev/null 2>&1 || true
  echo "rig stopped"
  ;;
status)
  docker ps --filter name=orchestra-test-vm --format '{{.Names}} {{.Status}} {{.Ports}}'
  for p in proxy generator; do
    if [ -f "$RIG_DIR/$p.pid" ] && kill -0 "$(cat "$RIG_DIR/$p.pid")" 2>/dev/null; then echo "$p running (pid $(cat "$RIG_DIR/$p.pid"))"; else echo "$p not running"; fi
  done
  [ -f "$RIG_DIR/ground_truth.jsonl" ] && echo "ground truth: $(wc -l < "$RIG_DIR/ground_truth.jsonl") minutes in $RIG_DIR/ground_truth.jsonl"
  ;;
*)
  echo "usage: $0 start|stop|status" >&2; exit 2 ;;
esac
