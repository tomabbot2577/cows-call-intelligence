#!/bin/bash
#
# RAG Sync Job Runner
# Runs every 60 minutes via cron to sync analyzed calls to Vertex AI RAG
#
# Usage:
#   ./run_rag_sync.sh              # Normal run
#   ./run_rag_sync.sh --status     # Check status only
#   ./run_rag_sync.sh --dry-run    # Show what would be done
#

set -e

# Configuration
PROJECT_DIR="/var/www/call-recording-system"
VENV_DIR="$PROJECT_DIR/venv"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/rag_sync_cron.log"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Timestamp for logging
timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

log() {
    echo "[$(timestamp)] $1" | tee -a "$LOG_FILE"
}

# Check if another instance is running
LOCK_FILE="/tmp/rag_sync_job.lock"
if [ -f "$LOCK_FILE" ]; then
    # Check if the process is still running
    OLD_PID=$(cat "$LOCK_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        log "ERROR: Another instance is running (PID: $OLD_PID)"
        exit 1
    else
        log "WARNING: Stale lock file found, removing..."
        rm -f "$LOCK_FILE"
    fi
fi

# Create lock file
echo $$ > "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

log "=== Starting RAG Sync Job ==="

# Change to project directory
cd "$PROJECT_DIR"

# Activate virtual environment
if [ -f "$VENV_DIR/bin/activate" ]; then
    source "$VENV_DIR/bin/activate"
else
    log "ERROR: Virtual environment not found at $VENV_DIR"
    exit 1
fi

# Load environment variables
if [ -f "$PROJECT_DIR/.env" ]; then
    export $(grep -v '^#' "$PROJECT_DIR/.env" | xargs)
fi

# Run the sync job
log "Running RAG sync job..."

# Pass through any command line arguments
python -m rag_integration.jobs.rag_sync_job "$@" 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    log "RAG Sync completed successfully"
else
    log "ERROR: RAG Sync failed with exit code $EXIT_CODE"
fi

log "=== RAG Sync Job Finished ==="

exit $EXIT_CODE
