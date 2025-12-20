#!/bin/bash
# Monitor transcription and restart if stuck

LOG_FILE="/var/www/call-recording-system/logs/parallel_batch_20251220_001305.log"
SCRIPT="/var/www/call-recording-system/parallel_transcriber.py"
WORKERS=4
STUCK_TIMEOUT=120  # 2 minutes without log update = stuck

cd /var/www/call-recording-system
source venv/bin/activate

while true; do
    # Check if process is running
    PID=$(pgrep -f "parallel_transcriber.py")
    
    if [ -z "$PID" ]; then
        # Process not running - check if queue is empty
        QUEUE_COUNT=$(ls data/audio_queue/*.mp3 2>/dev/null | wc -l)
        
        if [ "$QUEUE_COUNT" -eq 0 ]; then
            echo "$(date): Queue empty - transcription complete!"
            break
        else
            echo "$(date): Process died with $QUEUE_COUNT files remaining. Restarting..."
            nohup python $SCRIPT --limit 2000 --workers $WORKERS >> $LOG_FILE 2>&1 &
            sleep 10
        fi
    else
        # Check if stuck (no log update)
        LAST_MOD=$(stat -c %Y $LOG_FILE 2>/dev/null || echo 0)
        sleep $STUCK_TIMEOUT
        CURRENT_MOD=$(stat -c %Y $LOG_FILE 2>/dev/null || echo 0)
        
        if [ "$LAST_MOD" == "$CURRENT_MOD" ]; then
            echo "$(date): Process appears stuck (no update in ${STUCK_TIMEOUT}s). Killing PID $PID..."
            kill -9 $PID 2>/dev/null
            sleep 5
        else
            # Show progress
            PROCESSED=$(grep -c "SUCCESS:" $LOG_FILE 2>/dev/null || echo 0)
            FAILED=$(grep -c "FAILED:" $LOG_FILE 2>/dev/null || echo 0)
            QUEUE=$(ls data/audio_queue/*.mp3 2>/dev/null | wc -l)
            echo "$(date): Running OK - Processed: $PROCESSED, Failed: $FAILED, Queue: $QUEUE"
        fi
    fi
done
