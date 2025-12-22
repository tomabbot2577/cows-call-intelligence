#!/bin/bash
# Freshdesk Sync Monitor - Runs via cron every 15 minutes
# 1. Checks if sync is running, skips if already running
# 2. Syncs recent tickets (gentle approach to avoid rate limits)
# 3. Runs enrichment when sync complete
# Cron: */15 * * * * /var/www/call-recording-system/run_freshdesk_monitor.sh

LOCKFILE="/tmp/freshdesk_sync.lock"
LOGDIR="/var/www/call-recording-system/logs"
VENV="/var/www/call-recording-system/venv/bin/python"
PROJECT="/var/www/call-recording-system"

cd $PROJECT
source .env

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> $LOGDIR/freshdesk_monitor.log
}

# Check if sync is running (any freshdesk sync process)
SYNC_PID=$(pgrep -f "freshdesk.*sync" | head -1)

if [ -n "$SYNC_PID" ]; then
    log "Sync already running (PID $SYNC_PID), skipping"
    exit 0
fi

# Check if lock file exists and is recent (within 15 min)
if [ -f "$LOCKFILE" ]; then
    LOCK_AGE=$(( $(date +%s) - $(stat -c %Y "$LOCKFILE" 2>/dev/null || echo 0) ))
    if [ $LOCK_AGE -lt 900 ]; then
        log "Lock file recent ($LOCK_AGE sec old), skipping"
        exit 0
    else
        log "Stale lock file ($LOCK_AGE sec old), removing"
        rm -f $LOCKFILE
    fi
fi

# Get current counts
TOTAL=$($VENV -c "
import psycopg2
conn = psycopg2.connect('postgresql://call_insights_user:${PG_PASSWORD}@localhost/call_insights')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM kb_freshdesk_qa')
print(cur.fetchone()[0])
" 2>/dev/null || echo 0)

log "Current Q&A count: $TOTAL"

# Run the gentle sync script
log "Running gentle Freshdesk sync..."
$VENV -m rag_integration.jobs.freshdesk_sync_cron >> $LOGDIR/freshdesk_sync_$(date +%Y%m%d).log 2>&1
SYNC_EXIT=$?

if [ $SYNC_EXIT -eq 0 ]; then
    log "Sync completed successfully"
else
    log "Sync exited with code $SYNC_EXIT (may be rate limited, will retry later)"
fi

# Get new count
NEW_TOTAL=$($VENV -c "
import psycopg2
conn = psycopg2.connect('postgresql://call_insights_user:${PG_PASSWORD}@localhost/call_insights')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM kb_freshdesk_qa')
print(cur.fetchone()[0])
" 2>/dev/null || echo 0)

ADDED=$((NEW_TOTAL - TOTAL))
log "After sync: $NEW_TOTAL total (+$ADDED new)"

# Check if enrichment needed (only if we have data and sync succeeded)
if [ $SYNC_EXIT -eq 0 ] && [ "$NEW_TOTAL" -gt 0 ]; then
    ENRICHED=$($VENV -c "
import psycopg2
conn = psycopg2.connect('postgresql://call_insights_user:${PG_PASSWORD}@localhost/call_insights')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM kb_freshdesk_qa WHERE enriched_at IS NOT NULL')
print(cur.fetchone()[0])
" 2>/dev/null || echo 0)

    PENDING=$((NEW_TOTAL - ENRICHED))
    if [ "$PENDING" -gt 50 ]; then
        log "Running enrichment for $PENDING Q&As..."
        $VENV -m rag_integration.jobs.cleanup_and_enrich --skip-reset --workers 10 >> $LOGDIR/cleanup_enrich_$(date +%Y%m%d).log 2>&1
        log "Enrichment complete"
    fi
fi

log "Monitor complete"
