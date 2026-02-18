#!/bin/zsh
# render-birdweather.sh
# Daily automated render of birdweather/index.qmd + full site, then commit & push.
# Designed to run via macOS launchd at 12 PM local time.

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
PROJECT_DIR="/Users/connorfrench/Dropbox/personal_website"
LOG_FILE="$HOME/Library/Logs/render-birdweather.log"
QUARTO="/Applications/quarto/bin/quarto"
PIXI="$HOME/.pixi/bin/pixi"
GIT="/usr/bin/git"
PIXI_MANIFEST="$PROJECT_DIR/birdweather/pixi.toml"

# ── Helpers ──────────────────────────────────────────────────────────────────
timestamp() {
  date "+%Y-%m-%d %H:%M:%S"
}

log() {
  echo "[$(timestamp)] $1" | tee -a "$LOG_FILE"
}

notify_failure() {
  local msg="$1"
  log "FAILURE: $msg"
  osascript -e "display notification \"$msg\" with title \"BirdWeather Render Failed\"" 2>/dev/null || true
}

# ── Main ─────────────────────────────────────────────────────────────────────
log "====== Starting birdweather render ======"

cd "$PROJECT_DIR" || { notify_failure "Could not cd to $PROJECT_DIR"; exit 1; }

# Source the .env file so BIRDWEATHER_STATION_ID is available
if [[ -f birdweather/.env ]]; then
  set -a
  source birdweather/.env
  set +a
  log "Loaded birdweather/.env"
else
  notify_failure "birdweather/.env not found"
  exit 1
fi

# Step 1: Render birdweather page using Pixi environment
log "Rendering birdweather/index.qmd..."
if ! "$PIXI" run --manifest-path "$PIXI_MANIFEST" "$QUARTO" render birdweather/index.qmd >> "$LOG_FILE" 2>&1; then
  notify_failure "quarto render birdweather/index.qmd failed"
  exit 1
fi
log "birdweather/index.qmd rendered successfully"

# Step 2: Render the full site
log "Rendering full site..."
if ! "$QUARTO" render >> "$LOG_FILE" 2>&1; then
  notify_failure "quarto render (full site) failed"
  exit 1
fi
log "Full site rendered successfully"

# Step 3: Commit and push changes
log "Committing changes..."
"$GIT" add _freeze/ >> "$LOG_FILE" 2>&1
"$GIT" add -u >> "$LOG_FILE" 2>&1

# Only commit if there are staged changes
if "$GIT" diff --cached --quiet; then
  log "No changes to commit. Skipping push."
else
  "$GIT" commit -m "auto: daily birdweather update ($(date '+%Y-%m-%d'))" >> "$LOG_FILE" 2>&1
  log "Pushing to origin..."
  if ! "$GIT" push >> "$LOG_FILE" 2>&1; then
    notify_failure "git push failed"
    exit 1
  fi
  log "Pushed successfully"
fi

log "====== Birdweather render complete ======"
