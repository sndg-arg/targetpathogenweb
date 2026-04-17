#!/bin/sh
# Allow appuser to use the Docker socket (needed for TP.psort → docker run psortb)
if [ -S /var/run/docker.sock ]; then
  chmod 666 /var/run/docker.sock 2>/dev/null || true
fi

# Fix SSH config permissions (mounted volume may have wrong owner for paramiko)
if [ -d "$HOME/.ssh" ]; then
  cp -rp "$HOME/.ssh" /tmp/.ssh-fixed 2>/dev/null || true
  chmod 700 /tmp/.ssh-fixed 2>/dev/null || true
  chmod 600 /tmp/.ssh-fixed/config 2>/dev/null || true
  chmod 600 /tmp/.ssh-fixed/id_* /tmp/.ssh-fixed/cluster_qb 2>/dev/null || true
  # Ensure paramiko can find the key for the cluster SSH host
  if [ -n "$SSH_HOSTNAME" ] && [ -f /tmp/.ssh-fixed/id_ed25519_agutson_cluster ]; then
    printf '\nHost %s\n  IdentityFile /tmp/.ssh-fixed/id_ed25519_agutson_cluster\n  StrictHostKeyChecking no\n' "$SSH_HOSTNAME" >> /tmp/.ssh-fixed/config
  fi
  export HOME_SSH_ORIG="$HOME/.ssh"
  ln -sfn /tmp/.ssh-fixed "$HOME/.ssh" 2>/dev/null || true
fi

. /opt/conda/etc/profile.d/conda.sh
conda activate tpv2

if [ -f ./pipeline/exports.sh ]; then
  . ./pipeline/exports.sh
fi

QUEUE_POLL_INTERVAL="${QUEUE_POLL_INTERVAL:-5}"

exec python manage.py tpweb_process_genome_queue --poll-interval "${QUEUE_POLL_INTERVAL}"
