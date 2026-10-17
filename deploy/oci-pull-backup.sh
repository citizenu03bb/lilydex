#!/usr/bin/env bash
# Rapatriement ("Pull") de la dernière sauvegarde quotidienne vérifiée du serveur OCI vers
# data/oci-backups/oci-daily-<date>.zip, avec contrôle SHA-256 et restauration de contrôle,
# puis en option la copie Drive. Le jeton Google Drive reste uniquement sur le portable.
# Mêmes commandes que le timer pokeprice-drive-backup : voir docs/DAILY-BACKUPS.md.
# Usage : ./deploy/oci-pull-backup.sh opc@<IP_OCI> [--push-drive]
set -euo pipefail
umask 077

if [ "$#" -lt 1 ] || { [ "$#" -eq 2 ] && [ "$2" != "--push-drive" ]; } || [ "$#" -gt 2 ]; then
    echo "Usage: $0 <user@oci-ip> [--push-drive]" >&2
    exit 1
fi

cd "$(dirname "$0")/.."
if [ "${2:-}" = "--push-drive" ]; then
    exec .venv/bin/python -m pokeprice.manage backup-server-drive --host "$1" \
        --mirror data/oci-backups --rclone "${HOME}/.local/bin/rclone" --remote gdrive
fi
exec .venv/bin/python -m pokeprice.manage backup-server-pull --host "$1" --mirror data/oci-backups
