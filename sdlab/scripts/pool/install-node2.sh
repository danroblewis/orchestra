#!/bin/sh
# Installs (or updates the settings of) node2's CPU pool worker from this machine (docs/pool.md,
# "Deployment"): the token, a boot checkout cloned from the server's bundle (no GitHub, no push), its
# venv, and the systemd --user service. Code updates need nothing from here: the worker follows the
# main line's HEAD itself.
#   sh scripts/pool/install-node2.sh            (SLOTS=23 MEMGB=50 HEAVY=2 HIGHGB=53 MAXGB=55 by default)
set -e
cd "$(dirname "$0")/../.." || exit 1
HOST=${NODE2_SSH:-ubuntu@10.198.1.109}
SERVER=${POOL_SERVER:-http://10.198.1.131:8020}
SLOTS=${SLOTS:-23} MEMGB=${MEMGB:-50} HEAVY=${HEAVY:-2} HIGHGB=${HIGHGB:-53} MAXGB=${MAXGB:-55}
HEAD=$(git rev-parse sdlab)
r() { ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" "$@"; }
r 'mkdir -p ~/.sdlab/pool && chmod 700 ~/.sdlab && umask 077 && cat > ~/.sdlab/pool.token && chmod 600 ~/.sdlab/pool.token && echo node2 > ~/.sdlab/machine' < ~/.sdlab/pool.token
r "set -e; cd ~/.sdlab/pool; if [ ! -d boot/.git ]; then
     curl -fsS -H \"X-Pool-Token: \$(cat ~/.sdlab/pool.token)\" '$SERVER/api/pool/code/bundle?want=$HEAD' -o boot.bundle
     git clone -q boot.bundle boot; rm boot.bundle; git -C boot remote remove origin; git -C boot checkout -q --detach $HEAD
   fi; cd boot/sdlab && ~/.local/bin/uv sync -q --all-extras"
sed -e "s/@SLOTS@/$SLOTS/" -e "s/@MEMGB@/$MEMGB/" -e "s/@HEAVY@/$HEAVY/" -e "s/@HIGHGB@/$HIGHGB/" -e "s/@MAXGB@/$MAXGB/" \
  scripts/pool/sdlab-pool-worker.service | r 'mkdir -p ~/.config/systemd/user && cat > ~/.config/systemd/user/sdlab-pool-worker.service'
r 'loginctl show-user "$USER" -p Linger | grep -q yes || loginctl enable-linger "$USER";
   systemctl --user daemon-reload && systemctl --user enable -q sdlab-pool-worker && systemctl --user restart sdlab-pool-worker &&
   systemctl --user --no-pager status sdlab-pool-worker | head -5'
