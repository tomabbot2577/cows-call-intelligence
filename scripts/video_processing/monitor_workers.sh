#!/bin/bash
cd /var/www/call-recording-system
source venv/bin/activate

LOG_FILE="logs/worker_monitor.log"

while true; do
    echo "$(date): Checking workers..." >> $LOG_FILE
    
    # Check if batch process is running
    PROCS=$(ps aux | grep batch_transcribe_videos.py | grep -v grep | wc -l)
    
    if [ "$PROCS" -eq 0 ]; then
        echo "$(date): No workers running - restarting with 5 workers" >> $LOG_FILE
        nohup python scripts/video_processing/batch_transcribe_videos.py --workers 5 --limit 90 >> logs/batch_5w.log 2>&1 &
        echo "$(date): Restarted PID: $!" >> $LOG_FILE
    else
        # Check progress
        TRANSCRIBED=$(PGPASSWORD='REDACTED_DB_PASSWORD' psql -U call_insights_user -h localhost -d call_insights -t -c "SELECT COUNT(*) FROM video_meetings WHERE source='ringcentral' AND transcript_text IS NOT NULL;")
        PENDING=$(PGPASSWORD='REDACTED_DB_PASSWORD' psql -U call_insights_user -h localhost -d call_insights -t -c "SELECT COUNT(*) FROM video_meetings WHERE source='ringcentral' AND transcript_text IS NULL;")
        echo "$(date): Workers running. Transcribed: $TRANSCRIBED, Pending: $PENDING" >> $LOG_FILE
    fi
    
    sleep 300  # 5 minutes
done
