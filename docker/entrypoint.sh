#!/bin/sh
# Fails fast with a readable message when /data isn't writable — the single most common
# self-hosting mistake (a bind mount owned by root against the container's uid 1000).
set -e

DATA_DIR="${MOULAGA_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR" 2>/dev/null || true
if [ ! -w "$DATA_DIR" ]; then
  echo "ERREUR : $DATA_DIR n'est pas accessible en écriture (uid $(id -u))." >&2
  echo "Corrige les droits du volume, par ex. : chown -R 1000:1000 ./data" >&2
  exit 1
fi

case "${MOULAGA_DEMO_MODE:-false}" in
  1|true|TRUE|True|yes|YES|Yes|on|ON|On)
    echo "Mode demo actif : reinitialisation des donnees synthetiques."
    moulaga-seed-demo --reset
    ;;
  0|false|FALSE|False|no|NO|No|off|OFF|Off|"")
    ;;
  *)
    echo "ERREUR : MOULAGA_DEMO_MODE doit etre un booleen (true ou false)." >&2
    exit 1
    ;;
esac

exec "$@"
