#!/bin/bash

# Local Document Manager - macOS launcher

set -u

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Finder-launched .command files may not inherit Homebrew's PATH.
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export PATH

VENV_DIR="$SCRIPT_DIR/.venv"
PY="$VENV_DIR/bin/python"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"
REQUIREMENTS_STAMP="$VENV_DIR/.requirements.checksum"
CONFIG_FILE="$SCRIPT_DIR/config.json"
HOST="127.0.0.1"
PORT=8765

pause_on_error() {
    if [ -t 0 ]; then
        printf "Press Return to close..."
        read -r _
    fi
}

fail() {
    printf "\n[ERROR] %s\n" "$1" >&2
    pause_on_error
    exit 1
}

find_python() {
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && \
            "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

echo "============================================"
echo "  Local Document Manager - Starting"
echo "============================================"

VENV_CREATED=0
if [ ! -x "$PY" ]; then
    echo "[1/3] Creating virtual environment..."
    SYSTEM_PYTHON="$(find_python)" || \
        fail "Python 3.10+ was not found. Install it and try again."

    "$SYSTEM_PYTHON" -m venv "$VENV_DIR" || \
        fail "Failed to create the virtual environment."

    [ -x "$PY" ] || fail "The virtual environment was created without a usable Python executable."
    VENV_CREATED=1
else
    "$PY" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1 || \
        fail "The existing .venv does not use Python 3.10+. Remove .venv and run this script again."
    echo "[1/3] Virtual environment ready."
fi

REQUIREMENTS_CHECKSUM="$(cksum < "$REQUIREMENTS_FILE")" || \
    fail "Could not read requirements.txt."
INSTALLED_CHECKSUM=""
if [ -f "$REQUIREMENTS_STAMP" ]; then
    INSTALLED_CHECKSUM="$(sed -n '1p' "$REQUIREMENTS_STAMP")"
fi

if [ "$INSTALLED_CHECKSUM" != "$REQUIREMENTS_CHECKSUM" ] || \
    ! "$PY" -c 'import aiofiles, docx, fastapi, multipart, pydantic, uvicorn' >/dev/null 2>&1; then
    echo "[2/3] Installing dependencies..."
    if [ "$VENV_CREATED" -eq 1 ]; then
        "$PY" -m pip install --upgrade pip -q || \
            echo "[WARN] Could not upgrade pip; continuing with the bundled version."
    fi
    "$PY" -m pip install -r "$REQUIREMENTS_FILE" || \
        fail "Failed to install Python dependencies."
    printf '%s\n' "$REQUIREMENTS_CHECKSUM" > "$REQUIREMENTS_STAMP" || \
        fail "Could not record the installed dependency versions."
fi

NETWORK_CONFIG="$(
    "$PY" -c 'import json, pathlib, sys; p = pathlib.Path(sys.argv[1]); cfg = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}; print(str(cfg.get("host", "127.0.0.1")) + "|" + str(int(cfg.get("port", 8765))))' "$CONFIG_FILE" 2>/dev/null || true
)"
case "$NETWORK_CONFIG" in
    *"|"*)
        CONFIG_HOST="${NETWORK_CONFIG%%|*}"
        CONFIG_PORT="${NETWORK_CONFIG#*|}"
        if [ -n "$CONFIG_HOST" ]; then
            HOST="$CONFIG_HOST"
        fi
        case "$CONFIG_PORT" in
            ""|*[!0-9]*) ;;
            *)
                if [ "$CONFIG_PORT" -ge 1 ] && [ "$CONFIG_PORT" -le 65535 ]; then
                    PORT="$CONFIG_PORT"
                fi
                ;;
        esac
        ;;
esac

BROWSER_HOST="$HOST"
case "$BROWSER_HOST" in
    "0.0.0.0"|"::") BROWSER_HOST="127.0.0.1" ;;
    *:*) BROWSER_HOST="[$BROWSER_HOST]" ;;
esac
URL="http://$BROWSER_HOST:$PORT"

echo "[2/3] Checking port $PORT..."
if command -v lsof >/dev/null 2>&1; then
    PORT_PIDS="$(lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
    if [ -n "$PORT_PIDS" ]; then
        echo "      Port $PORT is already in use:"
        for pid in $PORT_PIDS; do
            PROCESS_COMMAND="$(ps -p "$pid" -o command= 2>/dev/null || true)"
            echo "      PID $pid: $PROCESS_COMMAND"
        done
        fail "Stop the process using port $PORT, then try again."
    fi
else
    echo "      lsof not found; skipping the port check."
fi

echo "[3/3] Starting server and opening browser..."
echo "      URL: $URL"
echo "      Close this window to stop the server."
echo "============================================"

"$PY" -m backend.main
STATUS=$?

if [ "$STATUS" -ne 0 ] && [ "$STATUS" -ne 130 ] && [ "$STATUS" -ne 143 ]; then
    fail "Server exited with status $STATUS."
fi

exit "$STATUS"
