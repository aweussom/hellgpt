#!/usr/bin/env bash
# Deploy HellGPT to remote host.
# Usage: ./deploy.sh [user@host[:path]]
#
# Default target: tommyl@100.96.31.44:hellgpt/

set -Eeuo pipefail

TARGET="${1:-tommyl@100.96.31.44}"
REMOTE_PATH="hellgpt"

# Strip path from target if provided as user@host:path
if [[ "$TARGET" == *:* ]]; then
    REMOTE_PATH="${TARGET#*:}"
    TARGET="${TARGET%%:*}"
fi

REMOTE_USER="${TARGET%@*}"
REMOTE_HOME="/home/${REMOTE_USER}"
REMOTE_FULL="${REMOTE_HOME}/${REMOTE_PATH}"

SCREEN_SESSION="hellgpt"
ENV_FILE=".env"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# ---- Preflight checks ------------------------------------------------------

for cmd in rsync ssh; do
    command -v "$cmd" >/dev/null 2>&1 || { echo "Missing: $cmd"; exit 1; }
done

REQUIRED_ITEMS=(bot instructions data)
for item in "${REQUIRED_ITEMS[@]}"; do
    [[ -e "$item" ]] || { echo "Missing: $item"; exit 1; }
done

# ---- Validate remote env vars -----------------------------------------------

MISSING_ENVS=$(ssh "$TARGET" bash <<ENVCHECK
# Check .env file in the project dir, then fall back to environment
if [ -f "${REMOTE_FULL}/.env" ]; then
    set -a; source "${REMOTE_FULL}/.env"; set +a
fi
missing=""
for var in HELLGPT_DISCORD_TOKEN OLLAMA_API_KEY; do
    [ -z "\${!var:-}" ] && missing="\$missing \$var"
done
echo \$missing
ENVCHECK
)

if [[ -n "${MISSING_ENVS// /}" ]]; then
    echo "ERROR: Missing env vars on remote:${MISSING_ENVS}"
    echo "Create ${REMOTE_FULL}/.env with the required keys and redeploy."
    exit 1
fi

# ---- Sync files -------------------------------------------------------------

echo "Syncing to ${TARGET}:${REMOTE_FULL}/ ..."

ssh "$TARGET" "mkdir -p ${REMOTE_FULL}/{logs,data}"

rsync -avzR \
    --exclude __pycache__/ \
    --exclude '*.pyc' \
    --exclude logs/ \
    --exclude data/sessions.db \
    --exclude .env \
    --exclude '.env.*' \
    --exclude .claude/ \
    --exclude .git/ \
    --exclude PLAN.md \
    --exclude CLAUDE.md \
    bot \
    instructions \
    data \
    .env.example \
    .gitignore \
    "$TARGET:${REMOTE_FULL}/"

echo "Files synced."

# ---- Stop old session -------------------------------------------------------

echo "Stopping existing HellGPT session (if any) ..."
ssh "$TARGET" "
    if screen -list 2>/dev/null | grep -q '[.]${SCREEN_SESSION}[[:space:]]'; then
        screen -S ${SCREEN_SESSION} -X quit || true
        sleep 1
        # Force if still alive
        if screen -list 2>/dev/null | grep -q '[.]${SCREEN_SESSION}[[:space:]]'; then
            screen -S ${SCREEN_SESSION} -X stuff $'\003' || true
            sleep 0.5
            screen -S ${SCREEN_SESSION} -X quit || true
            pkill -f 'SCREEN.*[.]${SCREEN_SESSION}( |\$)' 2>/dev/null || true
        fi
        screen -wipe >/dev/null 2>&1 || true
        echo 'Old session stopped.'
    else
        echo 'No existing session.'
    fi
"

# ---- Start bot in screen ----------------------------------------------------

echo "Starting HellGPT in screen session '${SCREEN_SESSION}' ..."
ssh "$TARGET" "screen -dmS ${SCREEN_SESSION} ${REMOTE_FULL}/bot/start.sh"

# ---- Verify -----------------------------------------------------------------

sleep 2
ssh "$TARGET" "
    if screen -list 2>/dev/null | grep -q '[.]${SCREEN_SESSION}[[:space:]]'; then
        echo 'HellGPT is running.'
    else
        echo 'WARNING: HellGPT session not found — check logs.'
        exit 1
    fi
"

# ---- Ensure @reboot crontab entry ------------------------------------------

echo "Checking @reboot crontab entry ..."
CRON_CMD="screen -dmS ${SCREEN_SESSION} ${REMOTE_FULL}/bot/start.sh"

ssh "$TARGET" "
    if crontab -l 2>/dev/null | grep -qF '${SCREEN_SESSION}'; then
        echo '@reboot entry already exists.'
    else
        (crontab -l 2>/dev/null; echo '@reboot ${CRON_CMD}') | crontab -
        echo '@reboot entry added.'
    fi
"

# ---- Done -------------------------------------------------------------------

cat <<EOF

Deploy complete.

  Target:  ${TARGET}:${REMOTE_FULL}
  Session: screen -r ${SCREEN_SESSION}
  Logs:    ${REMOTE_FULL}/logs/hellgpt.log
  Startup: @reboot crontab entry installed

EOF
