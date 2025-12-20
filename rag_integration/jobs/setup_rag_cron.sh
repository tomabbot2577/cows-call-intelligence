#!/bin/bash
#
# Setup script for RAG Sync Cron Job
# Installs a cron job that runs every 60 minutes
#
# Usage:
#   ./setup_rag_cron.sh         # Install cron job
#   ./setup_rag_cron.sh remove  # Remove cron job
#   ./setup_rag_cron.sh status  # Show current cron entry
#

set -e

PROJECT_DIR="/var/www/call-recording-system"
SCRIPT_PATH="$PROJECT_DIR/rag_integration/jobs/run_rag_sync.sh"
CRON_MARKER="# RAG_SYNC_JOB"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_status() {
    log_info "Current RAG sync cron entries:"
    crontab -l 2>/dev/null | grep -i "rag_sync\|run_rag_sync" || echo "  No RAG sync cron job found"
}

remove_cron() {
    log_info "Removing RAG sync cron job..."

    # Get current crontab, remove our entry, and reinstall
    (crontab -l 2>/dev/null | grep -v "run_rag_sync.sh" | grep -v "$CRON_MARKER") | crontab -

    log_info "RAG sync cron job removed"
    show_status
}

install_cron() {
    log_info "Installing RAG sync cron job..."

    # Check if script exists
    if [ ! -f "$SCRIPT_PATH" ]; then
        log_error "Script not found: $SCRIPT_PATH"
        exit 1
    fi

    # Check if script is executable
    if [ ! -x "$SCRIPT_PATH" ]; then
        log_warn "Making script executable..."
        chmod +x "$SCRIPT_PATH"
    fi

    # Remove existing entry if present
    (crontab -l 2>/dev/null | grep -v "run_rag_sync.sh" | grep -v "$CRON_MARKER") > /tmp/current_cron 2>/dev/null || true

    # Add new cron entry - runs at minute 30 of every hour
    # This avoids running at the top of the hour when other crons might run
    cat >> /tmp/current_cron << EOF

$CRON_MARKER - Runs every 60 minutes to sync analyzed calls to Vertex AI RAG
30 * * * * $SCRIPT_PATH >> $PROJECT_DIR/logs/rag_sync_cron.log 2>&1
EOF

    # Install new crontab
    crontab /tmp/current_cron
    rm /tmp/current_cron

    log_info "RAG sync cron job installed successfully!"
    echo ""
    log_info "Cron schedule: Every hour at :30 (e.g., 1:30, 2:30, 3:30...)"
    log_info "Log file: $PROJECT_DIR/logs/rag_sync_cron.log"
    echo ""
    show_status
}

# Main
case "${1:-install}" in
    install)
        install_cron
        ;;
    remove|uninstall)
        remove_cron
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: $0 [install|remove|status]"
        exit 1
        ;;
esac
