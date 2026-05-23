#!/bin/sh
umask 0022

# Allow appuser to use the Docker socket (needed for TP.psort → docker run psortb)
if [ -S /var/run/docker.sock ]; then
  chmod 666 /var/run/docker.sock 2>/dev/null || true
fi

# Paramiko rejects a mounted read-only ~/.ssh if ownership or modes look unsafe.
# Copy it into a writable HOME and normalize permissions, but keep host/key selection
# delegated to the existing ~/.ssh/config mounted from the host.
SSH_SOURCE_DIR="${HOME}/.ssh"
FAKE_HOME=/tmp/fakehome
FAKE_SSH_DIR="${FAKE_HOME}/.ssh"
if [ -d "$SSH_SOURCE_DIR" ]; then
  mkdir -p "$FAKE_SSH_DIR"
  cp -rp "$SSH_SOURCE_DIR"/. "$FAKE_SSH_DIR"/ 2>/dev/null || true
  chmod 700 "$FAKE_HOME" "$FAKE_SSH_DIR" 2>/dev/null || true
  find "$FAKE_SSH_DIR" -type d -exec chmod 700 {} \; 2>/dev/null || true
  find "$FAKE_SSH_DIR" -type f -exec chmod 600 {} \; 2>/dev/null || true
  # Ensure paramiko can find the key for the cluster SSH host
  if [ -n "$SSH_HOSTNAME" ] && [ -f "$FAKE_SSH_DIR/id_ed25519_agutson_cluster" ]; then
    printf '\nHost %s\n  IdentityFile %s/id_ed25519_agutson_cluster\n  StrictHostKeyChecking no\n' "$SSH_HOSTNAME" "$FAKE_SSH_DIR" >> "$FAKE_SSH_DIR/config"
  fi
  export HOME="$FAKE_HOME"
fi

. /opt/conda/etc/profile.d/conda.sh
conda activate tpv2

if [ -f ./pipeline/exports.sh ]; then
  . ./pipeline/exports.sh
fi

QUEUE_POLL_INTERVAL="${QUEUE_POLL_INTERVAL:-5}"

exec python manage.py tpweb_process_genome_queue --poll-interval "${QUEUE_POLL_INTERVAL}"
