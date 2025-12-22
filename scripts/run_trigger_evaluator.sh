#!/bin/bash
# Dashboard Trigger Evaluator Script
# Evaluates email triggers and sends notifications
# Usage: run_trigger_evaluator.sh --frequency [realtime|hourly|daily|weekly]

cd /var/www/call-recording-system
source venv/bin/activate
source .env 2>/dev/null

LOG_DIR="logs"
LOG_FILE="$LOG_DIR/trigger_evaluator_$(date +%Y%m%d).log"
mkdir -p "$LOG_DIR"

FREQUENCY="${2:-daily}"

echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting trigger evaluation (frequency: $FREQUENCY)" >> "$LOG_FILE"

python -m rag_integration.jobs.evaluate_triggers --frequency "$FREQUENCY" 2>&1 >> "$LOG_FILE"

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Trigger evaluation completed successfully" >> "$LOG_FILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Trigger evaluation FAILED (exit code: $EXIT_CODE)" >> "$LOG_FILE"
fi

echo "" >> "$LOG_FILE"
exit $EXIT_CODE
