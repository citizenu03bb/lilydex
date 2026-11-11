#!/usr/bin/env bash
# Renouvellement de la clé de l'agent des lots, côté opérateur.
#
# Lancé chaque jour par pokeprice-lots-key.timer sous le compte de l'opérateur,
# qui a déjà ssh vers le serveur. L'agent des lots ne renouvelle jamais son
# propre accès : il ne fait que lire le jeton déposé ici.
#
# Configuration : ~/.config/pokeprice/lots-key.env (mode 0600, hors dépôt),
# ou le fichier nommé par LOTS_KEY_ENV :
#   POKEPRICE_OCI_HOST       compte@serveur (sinon lu dans backup.env)
#   LOTS_OWNER               compte administrateur délégant
#   LOTS_ALBUM               album nommé par l'accès
#   LOTS_TOKEN_DIR           dossier de dépôt lisible par le groupe de l'agent
#   LOTS_RENEW_BEFORE_HOURS  renouveler à moins de N heures de l'échéance (48)
#   LOTS_NAME                nom de l'accès (lots-doublons)
#   LOTS_VALUE_CEILING_EUR   plafond par carte (défaut du serveur sinon)
#
# Le jeton n'est jamais affiché : seuls l'identifiant et l'échéance le sont.
# Remote scripts are single-quoted on purpose: they expand on the server.
# shellcheck disable=SC2016
set -euo pipefail

CONFIG="${LOTS_KEY_ENV:-$HOME/.config/pokeprice/lots-key.env}"
BACKUP_ENV="${POKEPRICE_BACKUP_ENV:-$HOME/.config/pokeprice/backup.env}"
if [ -f "$CONFIG" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$CONFIG"
    set +a
fi
if [ -z "${POKEPRICE_OCI_HOST:-}" ] && [ -f "$BACKUP_ENV" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$BACKUP_ENV"
    set +a
fi

: "${POKEPRICE_OCI_HOST:?POKEPRICE_OCI_HOST manquant (lots-key.env ou backup.env)}"
: "${LOTS_OWNER:?LOTS_OWNER manquant}"
: "${LOTS_ALBUM:?LOTS_ALBUM manquant}"
: "${LOTS_TOKEN_DIR:?LOTS_TOKEN_DIR manquant}"
LOTS_RENEW_BEFORE_HOURS="${LOTS_RENEW_BEFORE_HOURS:-48}"
LOTS_NAME="${LOTS_NAME:-lots-doublons}"
LOTS_VALUE_CEILING_EUR="${LOTS_VALUE_CEILING_EUR:-}"
ACTOR="system:lots-key-renew"
CLIENT="Agent des lots de doublons (poste de l'opérateur, renouvellement automatique)"

if ! [[ "$LOTS_RENEW_BEFORE_HOURS" =~ ^[0-9]+$ ]]; then
    echo "LOTS_RENEW_BEFORE_HOURS doit être un nombre d'heures." >&2
    exit 2
fi
if [ ! -d "$LOTS_TOKEN_DIR" ]; then
    echo "Dossier de dépôt absent : $LOTS_TOKEN_DIR" >&2
    exit 2
fi

umask 077
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT

# Remote side: every pokeprice command runs as the service account, on the
# production base named explicitly, from a folder that account can read.
REMOTE_PRELUDE='set -euo pipefail
cd /
manage() {
    sudo -n -u pokeprice env HOME=/srv/pokeprice /opt/pokeprice/.venv/bin/python \
        -m pokeprice.manage --data /srv/pokeprice/inventory "$@"
}
'

remote() {
    # remote SCRIPT ARG... : SCRIPT on stdin, arguments quoted for the remote shell.
    local script="$1"
    shift
    local quoted=""
    if [ "$#" -gt 0 ]; then
        quoted="$(printf '%q ' "$@")"
    fi
    ssh -o BatchMode=yes "$POKEPRICE_OCI_HOST" "bash -s -- $quoted" <<<"$REMOTE_PRELUDE$script"
}

when() {
    python3 -c 'import sys, time; print(time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(sys.argv[1]))))' "$1"
}

write_private() {
    # write_private NAME : stdin to LOTS_TOKEN_DIR/NAME, mode 0640, atomically.
    local tmp
    tmp="$(mktemp "$LOTS_TOKEN_DIR/.$1.XXXXXX")"
    if ! { cat >"$tmp" && chmod 0640 "$tmp" && mv -f -- "$tmp" "$LOTS_TOKEN_DIR/$1"; }; then
        rm -f -- "$tmp"
        return 1
    fi
}

OLD_ID=""
if [ -f "$LOTS_TOKEN_DIR/access-id" ]; then
    OLD_ID="$(tr -d '[:space:]' <"$LOTS_TOKEN_DIR/access-id")"
fi

if [ -n "$OLD_ID" ]; then
    remote 'manage agent-list' >"$WORK/list.json"
    STATE="$(python3 - "$WORK/list.json" "$OLD_ID" "$LOTS_RENEW_BEFORE_HOURS" <<'PY'
import json, sys, time
grants = json.load(open(sys.argv[1]))
grant = next((g for g in grants if str(g.get("id")) == sys.argv[2]), None)
if grant is None:
    print("renew absent 0")
elif grant.get("revoked_at"):
    print("renew revoked", int(grant["expires_at"]))
elif int(grant["expires_at"]) - time.time() < int(sys.argv[3]) * 3600:
    print("renew expiring", int(grant["expires_at"]))
else:
    print("fresh valid", int(grant["expires_at"]))
PY
)"
    read -r DECISION REASON EXPIRES <<<"$STATE"
    if [ "$DECISION" = fresh ]; then
        echo "Accès lots $OLD_ID valable jusqu'au $(when "$EXPIRES") : rien à faire."
        exit 0
    fi
    case "$REASON" in
        absent) echo "Accès lots $OLD_ID inconnu du serveur : nouvel accès." ;;
        revoked) echo "Accès lots $OLD_ID révoqué : nouvel accès." ;;
        *) echo "Accès lots $OLD_ID échu le $(when "$EXPIRES") : nouvel accès." ;;
    esac
else
    echo "Aucun accès lots enregistré dans le dossier de dépôt : nouvel accès."
fi

# Create the new access. The token file lives in a private folder of the
# service account, removed in all cases; the token comes back on stdout after
# the JSON summary, into a private local file, never on the terminal.
CREATE='DIR="$(sudo -n -u pokeprice mktemp -d)"
trap '\''sudo -n -u pokeprice rm -rf -- "$DIR"'\'' EXIT
ceiling=()
if [ -n "$6" ]; then ceiling=(--value-ceiling-eur "$6"); fi
manage agent-create "$1" --owner "$2" --album "$3" --client "$4" --actor "$5" \
    --lots-read --lots-compose --lots-publish "${ceiling[@]}" --token-file "$DIR/token"
printf "\n@@TOKEN@@\n"
sudo -n -u pokeprice cat -- "$DIR/token"
'
CREATED=0
remote "$CREATE" "$LOTS_NAME" "$LOTS_OWNER" "$LOTS_ALBUM" "$CLIENT" "$ACTOR" \
    "$LOTS_VALUE_CEILING_EUR" >"$WORK/created" || CREATED=$?

# Extract the id and expiry; on success also store the token (0640, atomic).
if ! NEW="$(python3 - "$WORK/created" "$LOTS_TOKEN_DIR" "$CREATED" <<'PY'
import json, os, sys, tempfile
raw = open(sys.argv[1]).read()
head, sep, tail = raw.partition("\n@@TOKEN@@\n")
try:
    grant = json.loads(head)
except ValueError:
    sys.exit(1)
token = tail.strip()
if sys.argv[3] != "0" or not sep or not token or any(c.isspace() for c in token):
    print(grant.get("id", ""), "-")
    sys.exit(3)
fd, tmp = tempfile.mkstemp(dir=sys.argv[2], prefix=".token.")
try:
    os.fchmod(fd, 0o640)
    with os.fdopen(fd, "w") as stream:
        stream.write(token + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, os.path.join(sys.argv[2], "token"))
except BaseException:
    os.unlink(tmp)
    raise
print(grant["id"], int(grant["expires_at"]))
PY
)"; then
    read -r ORPHAN _ <<<"${NEW:-}"
    if [ -n "${ORPHAN:-}" ]; then
        echo "Accès $ORPHAN créé mais jeton non récupéré : révocation." >&2
        remote 'manage agent-revoke "$1" --actor "$2" >/dev/null' "$ORPHAN" "$ACTOR" \
            || echo "Révocation de $ORPHAN impossible : à révoquer à la main." >&2
    fi
    echo "Création de l'accès lots impossible : l'ancien accès reste en place." >&2
    exit 1
fi
read -r NEW_ID NEW_EXPIRES <<<"$NEW"
printf '%s\n' "$NEW_ID" | write_private access-id
echo "Nouvel accès lots $NEW_ID valable jusqu'au $(when "$NEW_EXPIRES")."

# Only a still-live old access needs revoking; an unknown or revoked one does not.
if [ "${REASON:-}" = expiring ] && [ "$OLD_ID" != "$NEW_ID" ]; then
    if ! remote 'manage agent-revoke "$1" --actor "$2" >/dev/null' "$OLD_ID" "$ACTOR"; then
        echo "Révocation de l'ancien accès $OLD_ID impossible ; le nouveau jeton est en place." >&2
        exit 1
    fi
    echo "Ancien accès lots $OLD_ID révoqué."
fi
