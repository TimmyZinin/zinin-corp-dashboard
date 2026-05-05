#!/bin/bash
# Outreach dashboard data refresh + sync to corp.timzinin.com
# Triggered by launchd every 30s.
#
# Steps:
#   1. Run generate.py → produces fresh stats/agents/events/conversations JSON
#   2. rsync new JSON to /opt/ai-corp-dashboards/outreach/data/ on Contabo VPS
#
# Logs: ~/Library/Logs/outreach-dashboard.log (rotated by size in script)

set -u

DASH_DIR="$HOME/zinin-corp-dashboard/outreach"
DATA_DIR="$DASH_DIR/data"
LOG="$HOME/Library/Logs/outreach-dashboard.log"
SERVER="root@185.202.239.165"
REMOTE_DATA="/opt/ai-corp-dashboards/outreach/data/"

# Rotate log if > 5MB
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 5242880 ]; then
  mv "$LOG" "$LOG.old"
fi

mkdir -p "$(dirname "$LOG")"

# Python SSL cert bundle (launchd inherits minimal env; without this Twenty/SJ
# HTTPS calls fail with CERTIFICATE_VERIFY_FAILED).
if [ -z "${SSL_CERT_FILE:-}" ]; then
  CERTS=$(/usr/bin/env python3 -c "import certifi; print(certifi.where())" 2>/dev/null)
  [ -n "$CERTS" ] && export SSL_CERT_FILE="$CERTS" REQUESTS_CA_BUNDLE="$CERTS"
fi

ts() { date "+%Y-%m-%d %H:%M:%S"; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

log "── sync start ──"

# 1. Generate
if /usr/bin/env python3 "$DATA_DIR/generate.py" >>"$LOG" 2>&1; then
  log "generate OK"
else
  log "generate FAILED ($?)"
  exit 1
fi

# 2. Rsync to server (only the JSON files; HTML deployed separately)
RSYNC_OPTS=(-az --delete-after --include='*.json' --exclude='*' --timeout=10
            -e "ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new")

if rsync "${RSYNC_OPTS[@]}" "$DATA_DIR/" "$SERVER:$REMOTE_DATA" >>"$LOG" 2>&1; then
  log "rsync OK"
else
  log "rsync FAILED ($?)"
fi

log "── sync done ──"
