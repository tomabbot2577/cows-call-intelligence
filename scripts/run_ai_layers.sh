#!/bin/bash
# AI Layers 1-5 Processing
# Runs after transcription to enrich calls with AI insights
# Created: 2025-12-21

cd /var/www/call-recording-system
source venv/bin/activate

# Load environment variables
set -a
source .env
set +a

LOG_DIR="logs"
LOG_FILE="$LOG_DIR/ai_layers_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

echo "========================================" >> "$LOG_FILE"
echo "AI Layers Started: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# Process all 5 layers with limit of 100 records each
python process_all_layers_master.py --all --limit 100 >> "$LOG_FILE" 2>&1

echo "AI Layers completed: $(date)" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# Keep logs for 30 days
find "$LOG_DIR" -name "ai_layers_*.log" -mtime +30 -delete 2>/dev/null

exit 0
