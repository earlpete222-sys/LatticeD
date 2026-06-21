#!/usr/bin/env bash
# LatticeD installer for macOS and Linux.
#
# Walks a non-developer through Python, pip deps, Ollama, model pull,
# LATTICED_SECRET generation, and a start.sh launcher. Idempotent —
# re-running skips work already done.
#
# Sprint 45: Windows users should run Install-LatticeD.ps1 instead.

set -euo pipefail

LATTICED_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQS="${LATTICED_ROOT}/requirements.txt"
MODELS=("deepseek-r1:1.5b" "qwen2.5-coder:1.5b")
PYTHON_MIN_MAJOR=3
PYTHON_MIN_MINOR=12

SKIP_MODELS=0
FORCE=0
for arg in "$@"; do
    case "$arg" in
        --skip-models) SKIP_MODELS=1 ;;
        --force)       FORCE=1 ;;
        -h|--help)
            echo "Usage: ./install.sh [--skip-models] [--force]"
            exit 0
            ;;
    esac
done

step() { printf "\n[\e[36m%s\e[0m] %s\n" "$(date +%H:%M:%S)" "$1"; }
ok()   { printf "  \e[32mOK\e[0m  %s\n" "$1"; }
warn() { printf "  \e[33m!!\e[0m  %s\n" "$1"; }
fail() { printf "  \e[31mXX\e[0m  %s\n" "$1"; exit 1; }

cat <<BANNER

  ============================================================
   LatticeD Installer
   Personal AI that runs on your machine. Nothing leaves it.
  ============================================================

BANNER

# Detect OS for the right package manager prompts later.
case "$(uname -s)" in
    Darwin) OS=mac ;;
    Linux)  OS=linux ;;
    *)      fail "Unsupported OS: $(uname -s). Run Install-LatticeD.ps1 on Windows." ;;
esac

# ── Step 1: Python ─────────────────────────────────────────────────────────
step "Checking Python..."
PY="$(command -v python3 || true)"
if [[ -z "$PY" ]]; then PY="$(command -v python || true)"; fi

py_version_ok() {
    "$1" - <<PYEOF 2>/dev/null
import sys
need = (${PYTHON_MIN_MAJOR}, ${PYTHON_MIN_MINOR})
sys.exit(0 if sys.version_info[:2] >= need else 1)
PYEOF
}

if [[ -z "$PY" ]] || ! py_version_ok "$PY"; then
    warn "Python ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR}+ not found."
    if [[ "$OS" == "mac" ]]; then
        if command -v brew >/dev/null 2>&1; then
            echo "  Installing Python 3.12 via Homebrew..."
            brew install python@3.12
            PY="$(brew --prefix)/opt/python@3.12/bin/python3"
        else
            fail "Homebrew not found. Install it from https://brew.sh, then re-run this installer."
        fi
    else
        echo "  Trying apt (sudo required)..."
        if command -v apt-get >/dev/null 2>&1; then
            sudo apt-get update
            sudo apt-get install -y python3.12 python3.12-venv python3-pip
            PY="$(command -v python3.12 || command -v python3)"
        else
            fail "apt-get not found. Install Python ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR}+ manually, then re-run."
        fi
    fi
fi
ok "Python detected: $($PY --version)"

# ── Step 2: Python dependencies ────────────────────────────────────────────
step "Installing Python dependencies (this can take a few minutes the first time)..."
[[ -f "$REQS" ]] || fail "requirements.txt not found at $REQS"
PIP_ARGS=(-m pip install -r "$REQS")
[[ $FORCE -eq 1 ]] && PIP_ARGS+=(--upgrade)
"$PY" "${PIP_ARGS[@]}"
ok "Python dependencies installed."

# ── Step 3: Ollama ─────────────────────────────────────────────────────────
step "Checking Ollama..."
if command -v ollama >/dev/null 2>&1; then
    ok "Ollama on PATH."
else
    warn "Ollama not found."
    if [[ "$OS" == "mac" ]] && command -v brew >/dev/null 2>&1; then
        echo "  Installing via Homebrew..."
        brew install ollama
        ok "Ollama installed."
    else
        echo "  Installing via curl script (https://ollama.com/install.sh)..."
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL https://ollama.com/install.sh | sh
            ok "Ollama installed."
        else
            fail "curl not found. Install Ollama manually from https://ollama.com/download, then re-run."
        fi
    fi
fi

# Start the Ollama daemon if it isn't already running. On Mac the brew
# install starts it as a user agent automatically; on Linux it's a systemd
# service via the official installer. We just probe the API.
if ! curl -fsS http://localhost:11434/api/version >/dev/null 2>&1; then
    warn "Ollama daemon not responding on :11434."
    if [[ "$OS" == "mac" ]]; then
        echo "  Open the Ollama menu-bar app, then re-run this script (or run: brew services start ollama)."
    else
        echo "  Start the Ollama service: sudo systemctl start ollama"
    fi
fi

# ── Step 4: Pull models ────────────────────────────────────────────────────
if [[ $SKIP_MODELS -eq 1 ]]; then
    warn "Skipping model pull (--skip-models)."
else
    step "Pulling required models..."
    if command -v ollama >/dev/null 2>&1; then
        for m in "${MODELS[@]}"; do
            echo "  Pulling $m ..."
            if ollama pull "$m"; then
                ok "$m ready."
            else
                warn "ollama pull $m failed. Retry later with: ollama pull $m"
            fi
        done
    else
        warn "Ollama not on PATH yet — open a new terminal, then run:"
        for m in "${MODELS[@]}"; do echo "    ollama pull $m"; done
    fi
fi

# ── Step 5: LATTICED_SECRET ────────────────────────────────────────────────
step "Setting LATTICED_SECRET..."
ENV_FILE="${LATTICED_ROOT}/.env"
DEFAULT_SECRET="local_dev_secret_123"
EXISTING="${LATTICED_SECRET:-}"
if [[ -f "$ENV_FILE" ]]; then
    EXISTING="$(grep '^LATTICED_SECRET=' "$ENV_FILE" | cut -d= -f2- || true)"
fi

if [[ -n "$EXISTING" && "$EXISTING" != "$DEFAULT_SECRET" && $FORCE -eq 0 ]]; then
    ok "LATTICED_SECRET already set (length ${#EXISTING})."
else
    # 32 bytes of cryptographic randomness, base64-encoded, padding stripped.
    SECRET="$("$PY" -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode().rstrip("="))')"
    cat > "$ENV_FILE" <<EOF
# Generated by install.sh — source this file before launching LatticeD,
# or rely on start.sh which loads it automatically.
LATTICED_SECRET=${SECRET}
EOF
    chmod 600 "$ENV_FILE"
    ok "Generated a strong LATTICED_SECRET (saved to .env, mode 600)."
fi

# ── Step 6: start.sh launcher ──────────────────────────────────────────────
step "Writing start.sh launcher..."
START="${LATTICED_ROOT}/start.sh"
cat > "$START" <<'LAUNCH'
#!/usr/bin/env bash
# Generated by install.sh. Loads .env, optionally exposes on LAN for phone
# access over Tailscale (--lan), and launches LatticeD.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$HERE/.env" ]] && set -a && . "$HERE/.env" && set +a
for arg in "$@"; do
    case "$arg" in
        --lan) export LATTICED_HOST=0.0.0.0 ;;
    esac
done
PY="$(command -v python3 || command -v python)"
exec "$PY" "$HERE/latticed/latticed.py"
LAUNCH
chmod +x "$START"
ok "start.sh launcher written."

# ── Done ───────────────────────────────────────────────────────────────────
cat <<DONE

  ============================================================
   Install complete.

   Launch with:
     ./start.sh                  (local only)
     ./start.sh --lan            (expose on your private network)

   For phone access over Tailscale, see MOBILE.md.
  ============================================================

DONE
