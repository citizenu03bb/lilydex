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
    # Contact and data controller of the /a-propos notice, then the seller alerts
    # (ntfy, SMTP, Web Push): the file is rewritten whole, so every variable is listed here.
    for name in POKEPRICE_CONTACT_EMAIL POKEPRICE_CONTROLLER_NAME POKEPRICE_PUBLIC_ORIGIN \
        POKEPRICE_NTFY_URL POKEPRICE_NTFY_TOKEN \
        POKEPRICE_SMTP_HOST POKEPRICE_SMTP_PORT POKEPRICE_SMTP_SECURITY \
        POKEPRICE_SMTP_USER POKEPRICE_SMTP_PASSWORD POKEPRICE_SMTP_FROM POKEPRICE_NOTIFY_EMAIL \
        POKEPRICE_VAPID_PUBLIC_KEY POKEPRICE_VAPID_PRIVATE_KEY POKEPRICE_VAPID_SUBJECT \
        POKEPRICE_PACKING_GRAMS; do
        grep -E "^${name}=" "$LOCAL_ENV" | tail -n 1 || true
    done
    # The management chat (decision 0031): its own Gemini key, never the OCR's.
    for name in POKEPRICE_ASSISTANT_GEMINI_KEY POKEPRICE_ASSISTANT_MODEL \
        POKEPRICE_ASSISTANT_DAILY_LIMIT POKEPRICE_ASSISTANT_PER_MINUTE; do
        grep -E "^${name}=" "$LOCAL_ENV" | tail -n 1 || true
    done
} | ssh "$REMOTE_HOST" "sudo install -d -m 0750 -o root -g pokeprice /etc/pokeprice && \
    sudo tee /etc/pokeprice/pokeprice.env >/dev/null && \
    sudo chown root:pokeprice /etc/pokeprice/pokeprice.env && \
    sudo chmod 0640 /etc/pokeprice/pokeprice.env"

# Vérification distante sans afficher la valeur
ssh "$REMOTE_HOST" "sudo grep -sq '^POKEPRICE_HOST=' /etc/pokeprice/pokeprice.env && \
    sudo grep -sq '^GEMINI_API_KEY=\|^GOOGLE_API_KEY=' /etc/pokeprice/pokeprice.env"

echo "OK : /etc/pokeprice/pokeprice.env configuré et vérifié (mode 0640, root:pokeprice, zéro secret affiché)."
