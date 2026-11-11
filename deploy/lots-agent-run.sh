#!/usr/bin/env bash
# Lanceur de l'agent des lots, sous l'utilisateur local dédié.
#
# Met à jour le clone public (git pull --ff-only), synchronise son
# environnement (uv sync), copie le jeton déposé par l'opérateur dans un
# fichier privé (0600, exigé par le client), puis lance la commande dans le
# clone : lots-agent-run.sh uv run scripts/pokeprice_lots.py --api ...
#
# Configuration facultative : ~/.config/pokeprice/agent.env (ou AGENT_ENV) :
#   POKEPRICE_AGENT_URL  adresse de l'API agent
#   LOTS_TOKEN_DIR       dossier de dépôt du jeton (token)
#   LOTS_CLONE           clone du dépôt (~/lilydex)
set -euo pipefail

ENV_FILE="${AGENT_ENV:-$HOME/.config/pokeprice/agent.env}"
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
fi
CLONE="${LOTS_CLONE:-$HOME/lilydex}"
: "${LOTS_TOKEN_DIR:?LOTS_TOKEN_DIR manquant (agent.env)}"
export PATH="$HOME/.local/bin:$PATH"

if [ "$#" -eq 0 ]; then
    echo "Usage : $0 COMMANDE [ARGUMENT...]" >&2
    exit 2
fi

if ! git -C "$CLONE" pull --ff-only -q; then
    echo "Attention : mise à jour du clone impossible, la copie actuelle sert." >&2
fi
(cd "$CLONE" && uv sync -q)

# The drop folder is group-readable (0640); the client wants a private file.
umask 077
PRIVATE="${XDG_RUNTIME_DIR:-$HOME/.cache}/pokeprice"
mkdir -p -- "$PRIVATE"
TMP="$(mktemp "$PRIVATE/.lots-token.XXXXXX")"
if ! { cat -- "$LOTS_TOKEN_DIR/token" >"$TMP" && mv -f -- "$TMP" "$PRIVATE/lots.token"; }; then
    rm -f -- "$TMP"
    echo "Jeton des lots illisible dans $LOTS_TOKEN_DIR." >&2
    exit 1
fi

export POKEPRICE_AGENT_TOKEN_FILE="$PRIVATE/lots.token"
if [ -n "${POKEPRICE_AGENT_URL:-}" ]; then
    export POKEPRICE_AGENT_URL
fi
cd "$CLONE"
exec "$@"
