#!/bin/bash
# Dashboard Metrics Aggregation Script
# Aggregates daily metrics for user dashboards
# Usage: run_dashboard_metrics.sh [--full]

cd /var/www/call-recording-system
source venv/bin/activate
source .env 2>/dev/null

LOG_DIR="logs"
LOG_FILE="$LOG_DIR/dashboard_metrics_$(date +%Y%m%d).log"
mkdir -p "$LOG_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting dashboard metrics aggregation" >> "$LOG_FILE"

if [ "$1" == "--full" ]; then
    # Full daily aggregation (typically run at midnight)
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Running full daily aggregation" >> "$LOG_FILE"
    python -m rag_integration.jobs.aggregate_daily_metrics 2>&1 >> "$LOG_FILE"
else
    # Quick update for today's metrics (run every 15 min during business hours)
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Running quick metrics update" >> "$LOG_FILE"
    python -m rag_integration.jobs.aggregate_daily_metrics 2>&1 >> "$LOG_FILE"
fi

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Dashboard metrics aggregation completed successfully" >> "$LOG_FILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Dashboard metrics aggregation FAILED (exit code: $EXIT_CODE)" >> "$LOG_FILE"
fi

echo "" >> "$LOG_FILE"
exit $EXIT_CODE
