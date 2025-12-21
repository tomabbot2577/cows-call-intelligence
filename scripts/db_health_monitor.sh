#!/bin/bash
# Database Health Monitor
# Runs every 5 minutes via cron to detect and fix database issues
# Created: 2025-12-21

LOG_DIR="/var/www/call-recording-system/logs"
LOG_FILE="$LOG_DIR/db_health.log"
ALERT_FILE="$LOG_DIR/db_alerts.log"

# Database credentials
export PGPASSWORD="REDACTED_DB_PASSWORD"
DB_USER="call_insights_user"
DB_NAME="call_insights"
DB_HOST="localhost"

# Thresholds
IDLE_TIMEOUT_MINUTES=30
QUERY_TIMEOUT_MINUTES=10
LOCK_WAIT_MINUTES=5

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Timestamp
NOW=$(date '+%Y-%m-%d %H:%M:%S')

log() {
    echo "[$NOW] $1" >> "$LOG_FILE"
}

alert() {
    echo "[$NOW] ALERT: $1" >> "$ALERT_FILE"
    echo "[$NOW] ALERT: $1" >> "$LOG_FILE"
}

# Function to run psql query
run_query() {
    psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -t -c "$1" 2>/dev/null
}

log "Health check started"

# 1. Check for idle in transaction connections (stuck transactions)
IDLE_TRANS=$(run_query "
    SELECT pid, usename, state,
           EXTRACT(EPOCH FROM (NOW() - query_start))/60 as minutes,
           LEFT(query, 100) as query
    FROM pg_stat_activity
    WHERE state = 'idle in transaction'
    AND query_start < NOW() - INTERVAL '$IDLE_TIMEOUT_MINUTES minutes'
    AND datname = '$DB_NAME';
")

if [ -n "$IDLE_TRANS" ]; then
    alert "Found idle in transaction connections older than $IDLE_TIMEOUT_MINUTES minutes"

    # Kill them
    KILLED=$(run_query "
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE state = 'idle in transaction'
        AND query_start < NOW() - INTERVAL '$IDLE_TIMEOUT_MINUTES minutes'
        AND datname = '$DB_NAME';
    ")

    log "Killed idle transactions: $KILLED"
fi

# 2. Check for long-running queries
LONG_QUERIES=$(run_query "
    SELECT pid, usename, state,
           EXTRACT(EPOCH FROM (NOW() - query_start))/60 as minutes,
           LEFT(query, 100) as query
    FROM pg_stat_activity
    WHERE state = 'active'
    AND query NOT LIKE '%pg_stat_activity%'
    AND query_start < NOW() - INTERVAL '$QUERY_TIMEOUT_MINUTES minutes'
    AND datname = '$DB_NAME';
")

if [ -n "$LONG_QUERIES" ]; then
    alert "Found queries running longer than $QUERY_TIMEOUT_MINUTES minutes"
    log "Long queries: $LONG_QUERIES"

    # Kill them (be careful with this in production)
    KILLED=$(run_query "
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE state = 'active'
        AND query NOT LIKE '%pg_stat_activity%'
        AND query_start < NOW() - INTERVAL '$QUERY_TIMEOUT_MINUTES minutes'
        AND datname = '$DB_NAME';
    ")

    log "Killed long-running queries: $KILLED"
fi

# 3. Check for lock waits
LOCK_WAITS=$(run_query "
    SELECT blocked_locks.pid AS blocked_pid,
           blocked_activity.usename AS blocked_user,
           EXTRACT(EPOCH FROM (NOW() - blocked_activity.query_start))/60 as wait_minutes
    FROM pg_catalog.pg_locks blocked_locks
    JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
    JOIN pg_catalog.pg_locks blocking_locks
        ON blocking_locks.locktype = blocked_locks.locktype
        AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
        AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
        AND blocking_locks.pid != blocked_locks.pid
    WHERE NOT blocked_locks.granted
    AND blocked_activity.query_start < NOW() - INTERVAL '$LOCK_WAIT_MINUTES minutes';
")

if [ -n "$LOCK_WAITS" ]; then
    alert "Found queries waiting on locks for more than $LOCK_WAIT_MINUTES minutes"
    log "Lock waits: $LOCK_WAITS"
fi

# 4. Check connection count
CONN_COUNT=$(run_query "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = '$DB_NAME';")
CONN_COUNT=$(echo "$CONN_COUNT" | tr -d ' ')

if [ "$CONN_COUNT" -gt 50 ]; then
    alert "High connection count: $CONN_COUNT"
fi

log "Connections: $CONN_COUNT"

# 5. Quick database stats
STATS=$(run_query "
    SELECT
        (SELECT COUNT(*) FROM call_log) as call_log_count,
        (SELECT COUNT(*) FROM transcripts) as transcripts_count;
")

log "Stats: $STATS"
log "Health check completed"

# Keep logs from growing too large (keep last 10000 lines)
if [ -f "$LOG_FILE" ]; then
    tail -10000 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

exit 0
