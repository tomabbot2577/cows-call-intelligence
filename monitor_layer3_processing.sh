#!/bin/bash

# Monitor and auto-restart Layer 3 processing until all 1424 records are complete
# Checks every 5 minutes and starts new batches as needed

LOG_FILE="/tmp/layer3_monitor.log"
BATCH_SIZE=150
MAX_PARALLEL=10
TARGET_TOTAL=1424

echo "$(date): Starting Layer 3 monitoring loop" >> $LOG_FILE

while true; do
    # Get current count of Layer 3 enhanced records
    ENHANCED_COUNT=$(PGPASSWORD=${PG_PASSWORD} psql -U call_insights_user -d call_insights -h localhost -t -c "SELECT COUNT(*) FROM call_resolutions WHERE problem_complexity IS NOT NULL;" | xargs)

    # Get number of running processes
    RUNNING=$(ps aux | grep "python /tmp/layer3_resolution_enhanced.py" | grep -v grep | wc -l)

    echo "$(date): Enhanced: $ENHANCED_COUNT/$TARGET_TOTAL, Running processes: $RUNNING" >> $LOG_FILE

    # Check if we're done
    if [ "$ENHANCED_COUNT" -ge "$TARGET_TOTAL" ]; then
        echo "$(date): All records processed! Enhanced count: $ENHANCED_COUNT" >> $LOG_FILE
        echo "✅ COMPLETED: All $TARGET_TOTAL recordings have been enhanced with Layer 3 resolution analysis"
        break
    fi

    # Calculate remaining records
    REMAINING=$((TARGET_TOTAL - ENHANCED_COUNT))

    # If no processes running and still have work, start new batches
    if [ "$RUNNING" -eq 0 ] && [ "$REMAINING" -gt 0 ]; then
        # Calculate how many batches to start (up to MAX_PARALLEL)
        BATCHES_NEEDED=$((REMAINING / BATCH_SIZE))
        if [ "$BATCHES_NEEDED" -gt "$MAX_PARALLEL" ]; then
            BATCHES_NEEDED=$MAX_PARALLEL
        fi
        if [ "$BATCHES_NEEDED" -eq 0 ]; then
            BATCHES_NEEDED=1
        fi

        echo "$(date): Starting $BATCHES_NEEDED new batches..." >> $LOG_FILE

        # Start new batches
        for ((i=1; i<=BATCHES_NEEDED; i++)); do
            BATCH_ID="batch_$(date +%s)_$i"
            source /var/www/call-recording-system/venv/bin/activate && \
                python /tmp/layer3_resolution_enhanced.py --limit $BATCH_SIZE > /tmp/layer3_${BATCH_ID}.log 2>&1 &
            echo "$(date): Started $BATCH_ID (PID: $!)" >> $LOG_FILE
            sleep 2  # Small delay between starts
        done
    fi

    # Display progress
    PERCENT=$((ENHANCED_COUNT * 100 / TARGET_TOTAL))
    echo "📊 Layer 3 Progress: $ENHANCED_COUNT/$TARGET_TOTAL ($PERCENT%) | Running: $RUNNING processes | Remaining: $REMAINING"

    # Wait 5 minutes before next check
    sleep 300
done

echo "$(date): Monitoring complete. All records processed." >> $LOG_FILE