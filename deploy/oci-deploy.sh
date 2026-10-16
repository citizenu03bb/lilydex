#!/usr/bin/env bash
# Déploiement complet du code, de la sauvegarde vérifiée et des services systemd sur OCI.
# Compatible Oracle Linux (opc@<IP>) et Ubuntu (ubuntu@<IP>).
# Usage : ./deploy/oci-deploy.sh <opc|ubuntu>@<IP_OCI> <DOMAINE_HTTPS>
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <user@oci-ip> <domaine-https>" >&2
    exit 1
fi

REMOTE_HOST="$1"
DOMAIN="$2"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "[1/6] Vérification de la présence des secrets sur le serveur..."
if ! ssh "$REMOTE_HOST" "sudo test -f /etc/pokeprice/pokeprice.env"; then
    echo "Exécution préalable de oci-sync-secrets.sh..."
    ./deploy/oci-sync-secrets.sh "$REMOTE_HOST" "$DOMAIN"
fi

echo "[2/6] Synchronisation des fichiers suivis par Git vers /opt/pokeprice..."
ssh "$REMOTE_HOST" "sudo install -d -m 0755 -o pokeprice -g pokeprice /opt/pokeprice"
git ls-files -z | rsync -az --no-owner --no-group --rsync-path="sudo rsync" --from0 --files-from=- ./ "${REMOTE_HOST}:/opt/pokeprice/"
ssh "$REMOTE_HOST" "sudo chown -R pokeprice:pokeprice /opt/pokeprice"

echo "[3/6] Installation de Python 3.13 et de l'environnement virtuel (uv sync)..."
ssh "$REMOTE_HOST" "cd /opt/pokeprice && \
    sudo -u pokeprice env HOME=/srv/pokeprice /usr/local/bin/uv python install 3.13 && \
    sudo -u pokeprice env HOME=/srv/pokeprice /usr/local/bin/uv sync --frozen --extra web"

# Sur Oracle Linux (SELinux), marquer les exécutables du venv et de uv comme bin_t pour que systemd puisse les lancer
ssh "$REMOTE_HOST" "if command -v chcon >/dev/null 2>&1 && command -v getenforce >/dev/null 2>&1 && [ \"\$(getenforce)\" != 'Disabled' ]; then \
    sudo chcon -R -t bin_t /srv/pokeprice/.local/share/uv/python /opt/pokeprice/.venv/bin 2>/dev/null || true; \
fi"

echo "[4/6] Initialisation de la collection si /srv/pokeprice/inventory est vide..."
if ! ssh "$REMOTE_HOST" "sudo test -f /srv/pokeprice/inventory/collection.sqlite3"; then
    echo "Création/vérification d'une archive quotidienne fraîche sur le portable..."
    .venv/bin/python -m pokeprice.manage backup-daily
    LATEST_ZIP="$(ls -1t data/backups/daily-*.zip | head -n 1)"
    echo "Transfert de ${LATEST_ZIP} vers le serveur..."
    scp "$LATEST_ZIP" "${REMOTE_HOST}:/tmp/pokeprice-init.zip"
    ssh "$REMOTE_HOST" "sudo chown pokeprice:pokeprice /tmp/pokeprice-init.zip && \
        sudo rmdir /srv/pokeprice/inventory 2>/dev/null || true && \
        sudo -u pokeprice env HOME=/srv/pokeprice /opt/pokeprice/.venv/bin/python -m pokeprice.manage \
            --data /srv/pokeprice/inventory restore /tmp/pokeprice-init.zip && \
        sudo rm -f /tmp/pokeprice-init.zip && \
        sudo -u pokeprice env HOME=/srv/pokeprice /opt/pokeprice/.venv/bin/python -m pokeprice.manage \
            --data /srv/pokeprice/inventory backup-daily"
else
    echo "Base existante détectée dans /srv/pokeprice/inventory/collection.sqlite3 (conservée)."
fi

echo "[5/6] Installation des unités systemd et configuration de Caddy pour ${DOMAIN}..."
ssh "$REMOTE_HOST" "sudo cp /opt/pokeprice/deploy/pokeprice.service /etc/systemd/system/ && \
    sudo cp /opt/pokeprice/deploy/pokeprice-backup.service /etc/systemd/system/ && \
    sudo cp /opt/pokeprice/deploy/pokeprice-backup.timer /etc/systemd/system/ && \
    if command -v restorecon >/dev/null 2>&1; then sudo restorecon -v /etc/systemd/system/pokeprice* >/dev/null 2>&1 || true; fi && \
    sudo sed 's/cards.example.com/${DOMAIN}/g' /opt/pokeprice/deploy/Caddyfile.example | sudo tee /etc/caddy/Caddyfile >/dev/null && \
    sudo systemctl daemon-reload && \
    sudo systemctl enable --now pokeprice.service pokeprice-backup.timer && \
    sudo systemctl restart pokeprice.service && \
    sudo systemctl reload-or-restart caddy"

echo "[6/6] Vérification de l'état local et HTTPS du service..."
ssh "$REMOTE_HOST" "for i in 1 2 3 4 5; do curl -fsS -H 'Host: ${DOMAIN}' http://127.0.0.1:3820/health && break || sleep 1; done"
echo ""
echo "Déploiement terminé avec succès : https://${DOMAIN}"
