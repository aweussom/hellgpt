#!/usr/bin/env bash
# Start HellGPT bot. Used by deploy.sh and @reboot crontab.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

# Source env vars
if [[ -f "$DIR/.env" ]]; then
    set -a
    source "$DIR/.env"
    set +a
fi

exec python3 bot/hellgpt.py
