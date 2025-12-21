#!/bin/bash
# RingCentral Call Log Checker v2
# Runs every 12 hours to fetch ALL calls from RingCentral
# Created: 2025-12-21

cd /var/www/call-recording-system
source venv/bin/activate

# Load environment variables
set -a
source .env
set +a

LOG_DIR="logs"
LOG_FILE="$LOG_DIR/ringcentral_v2_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

echo "========================================" >> "$LOG_FILE"
echo "RingCentral Check Started: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# Run the checker (14 hours back to ensure overlap with 12hr schedule)
python src/scheduler/ringcentral_checker_v2.py --hours-back 14 >> "$LOG_FILE" 2>&1

echo "Check completed: $(date)" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# Keep logs for 30 days
find "$LOG_DIR" -name "ringcentral_v2_*.log" -mtime +30 -delete 2>/dev/null

exit 0
