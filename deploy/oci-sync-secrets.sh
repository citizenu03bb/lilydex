#!/usr/bin/env bash
# Synchronisation sécurisée des secrets du portable vers l'instance OCI.
# AUCUN secret n'est affiché sur stdout/stderr ni passé en argument CLI.
# Usage : ./deploy/oci-sync-secrets.sh ubuntu@<IP_OCI> <DOMAINE_HTTPS>
set +x
set -euo pipefail
umask 0077

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <user@oci-ip> <domaine-https>" >&2
    exit 1
fi

REMOTE_HOST="$1"
DOMAIN="$2"
LOCAL_ENV="${HOME}/.env"

if [ ! -f "$LOCAL_ENV" ]; then
    echo "Erreur : fichier $LOCAL_ENV introuvable." >&2
    exit 1
fi

if ! grep -sq "^GEMINI_API_KEY=\|^GOOGLE_API_KEY=" "$LOCAL_ENV"; then
    echo "Erreur : ni GEMINI_API_KEY ni GOOGLE_API_KEY n'est défini dans $LOCAL_ENV." >&2
    exit 1
fi

echo "Transfert chiffré de la configuration secrète vers ${REMOTE_HOST}:/etc/pokeprice/pokeprice.env..."

{
    printf "POKEPRICE_HOST=%s\n" "$DOMAIN"
    grep -E "^(GEMINI_API_KEY|GOOGLE_API_KEY)=" "$LOCAL_ENV" | tail -n 1
} | ssh "$REMOTE_HOST" "sudo install -d -m 0750 -o root -g pokeprice /etc/pokeprice && \
    sudo tee /etc/pokeprice/pokeprice.env >/dev/null && \
    sudo chown root:pokeprice /etc/pokeprice/pokeprice.env && \
    sudo chmod 0640 /etc/pokeprice/pokeprice.env"

# Vérification distante sans afficher la valeur
ssh "$REMOTE_HOST" "sudo grep -sq '^POKEPRICE_HOST=' /etc/pokeprice/pokeprice.env && \
    sudo grep -sq '^GEMINI_API_KEY=\|^GOOGLE_API_KEY=' /etc/pokeprice/pokeprice.env"

echo "OK : /etc/pokeprice/pokeprice.env configuré et vérifié (mode 0640, root:pokeprice, zéro secret affiché)."
