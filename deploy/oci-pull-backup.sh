#!/usr/bin/env bash
# Rapatriement ("Pull") de la dernière sauvegarde quotidienne vérifiée depuis l'instance OCI
# vers le portable, suivi de la vérification locale. Le jeton Google Drive reste uniquement sur le portable.
# Usage : ./deploy/oci-pull-backup.sh ubuntu@<IP_OCI> [--push-drive]
set -euo pipefail
# Archives and partial downloads are private from their first byte.
umask 077

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <user@oci-ip> [--push-drive]" >&2
    exit 1
fi

REMOTE_HOST="$1"
PUSH_DRIVE="${2:-}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p data/backups

echo "[1/3] Déclenchement / vérification de la sauvegarde quotidienne sur le serveur OCI..."
ssh "$REMOTE_HOST" "sudo systemctl start pokeprice-backup.service"

# The glob must expand as root: the SSH user cannot read the backups folder.
REMOTE_LATEST="$(ssh "$REMOTE_HOST" "sudo sh -c 'ls -1t /srv/pokeprice/backups/daily-*.zip | head -n 1'")"
if [ -z "$REMOTE_LATEST" ]; then
    echo "Erreur : aucune archive daily-*.zip trouvée sur le serveur." >&2
    exit 1
fi

ARCHIVE_NAME="$(basename "$REMOTE_LATEST")"
LOCAL_TARGET="data/backups/${ARCHIVE_NAME}"
TMP_RESTORE=""
cleanup() {
    # An interrupted transfer must not leave a partial archive behind.
    rm -f "${LOCAL_TARGET}.part"
    if [ -n "$TMP_RESTORE" ]; then rm -rf "$TMP_RESTORE"; fi
}
trap cleanup EXIT

echo "[2/3] Rapatriement de ${ARCHIVE_NAME} via SSH..."
ssh "$REMOTE_HOST" "sudo cat '$REMOTE_LATEST'" > "${LOCAL_TARGET}.part"
mv "${LOCAL_TARGET}.part" "$LOCAL_TARGET"
chmod 0600 "$LOCAL_TARGET"

echo "[3/3] Restauration de contrôle sur le portable..."
TMP_RESTORE="$(mktemp -d -t pokeprice-oci-verify-XXXXXX)"
.venv/bin/python -m pokeprice.manage --data "${TMP_RESTORE}/collection" restore "$LOCAL_TARGET"

if [ "$PUSH_DRIVE" = "--push-drive" ]; then
    echo "Téléversement vers Google Drive depuis le portable..."
    .venv/bin/python -m pokeprice.manage backup-drive --rclone "${HOME}/.local/bin/rclone" --remote gdrive
fi

echo "OK : ${LOCAL_TARGET} rapatriée et vérifiée."
