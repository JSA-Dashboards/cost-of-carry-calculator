#!/bin/bash
# Daily futures-settlement archive (settlement_archive.py) on the JSA droplet.
# Installed as a crontab line through /opt/alerting/cron-alert, same as run_ams.sh:
#   30 16 * * 1-5  /opt/alerting/cron-alert "Settlement archive" \
#                  "/opt/cost-of-carry-calculator/logs/settlements_*.log" \
#                  /opt/cost-of-carry-calculator/deploy/run_settlements.sh
# Pass --backfill to reload everything Massive still serves.
set -e
APP=/opt/cost-of-carry-calculator
LOCKFILE=$APP/run_settlements.lock
LOGDIR=$APP/logs
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/settlements_$(date +%Y%m%d_%H%M%S).log"

exec 200>"$LOCKFILE"
flock -n 200 || { echo "$(date): already running, skipping" >> "$LOGFILE"; exit 0; }

cd "$APP"
git pull --quiet >> "$LOGFILE" 2>&1
set -a; source .env; set +a
.venv/bin/python scripts/refresh_settlements.py "$@" >> "$LOGFILE" 2>&1

# Keep a month of logs; the archive's own history lives in Snowflake.
find "$LOGDIR" -name 'settlements_*.log' -mtime +30 -delete
