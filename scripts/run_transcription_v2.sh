#!/bin/bash
# Transcription Processor v2
# Runs after RingCentral download to transcribe new recordings
# Created: 2025-12-21

cd /var/www/call-recording-system
source venv/bin/activate

# Load environment variables
set -a
source .env
set +a

LOG_DIR="logs"
LOG_FILE="$LOG_DIR/transcription_v2_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

echo "========================================" >> "$LOG_FILE"
echo "Transcription Started: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# Process up to 50 recordings per run with 5 second rate limit
python src/scheduler/transcription_processor_v2.py --limit 50 --rate-limit 5 >> "$LOG_FILE" 2>&1

echo "Transcription completed: $(date)" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# Keep logs for 30 days
find "$LOG_DIR" -name "transcription_v2_*.log" -mtime +30 -delete 2>/dev/null

exit 0
