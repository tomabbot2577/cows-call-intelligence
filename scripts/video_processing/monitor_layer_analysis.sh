#!/bin/bash
# Monitor layer analysis progress every 2 minutes

cd /var/www/call-recording-system
source .env 2>/dev/null || true

while true; do
  clear
  echo "=== Layer Analysis Progress - $(date '+%Y-%m-%d %H:%M:%S') ==="
  echo ""
  PGPASSWORD="${PG_PASSWORD:-$DB_PASSWORD}" psql -U call_insights_user -h localhost -d call_insights -t -c \
    "SELECT 'Analyzed: ' || COUNT(*) FILTER (WHERE layer1_complete = TRUE) ||
            ' | Pending: ' || COUNT(*) FILTER (WHERE layer1_complete IS NULL OR layer1_complete = FALSE) ||
            ' | Total: ' || COUNT(*)
     FROM video_meetings WHERE transcript_text IS NOT NULL;"
  echo ""
  echo "--- Last 10 log entries ---"
  tail -10 /var/www/call-recording-system/logs/layer_analysis.log 2>/dev/null | grep -E "(Analyzing|Saved|COMPLETE)"
  echo ""
  echo "Press Ctrl+C to stop monitoring"
  sleep 120
done
