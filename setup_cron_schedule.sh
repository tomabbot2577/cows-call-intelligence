#!/bin/bash

# Setup cron schedule for RingCentral recording checker
# Runs 6 times per day: 7am, 10am, 1pm, 3pm, 5pm, 8pm

echo "Setting up cron schedule for RingCentral recording checker..."

# Create the cron job script
cat > /var/www/call-recording-system/run_ringcentral_check.sh << 'EOF'
#!/bin/bash

# RingCentral Recording Checker Script
# This runs automatically via cron to check for new recordings

# Set environment
export PATH="/usr/local/bin:/usr/bin:/bin"
cd /var/www/call-recording-system

# Load environment variables
source .env

# Activate virtual environment
source venv/bin/activate

# Log file
LOG_FILE="/var/www/call-recording-system/logs/ringcentral_checker_$(date +%Y%m%d).log"
mkdir -p /var/www/call-recording-system/logs

# Run the checker
echo "[$(date)] Starting RingCentral check..." >> "$LOG_FILE"
python3 src/scheduler/ringcentral_checker.py --limit 30 >> "$LOG_FILE" 2>&1
echo "[$(date)] Check complete" >> "$LOG_FILE"

# Also trigger transcription processing if there are files in queue
QUEUE_COUNT=$(ls -1 /var/www/call-recording-system/data/audio_queue/*.mp3 2>/dev/null | wc -l)
if [ "$QUEUE_COUNT" -gt 0 ]; then
    echo "[$(date)] Found $QUEUE_COUNT files in queue, triggering transcription..." >> "$LOG_FILE"
    python3 src/scheduler/transcription_processor.py --limit 10 >> "$LOG_FILE" 2>&1
fi
EOF

# Make it executable
chmod +x /var/www/call-recording-system/run_ringcentral_check.sh

# Add to crontab
# Check if cron jobs already exist
crontab -l 2>/dev/null | grep -q "run_ringcentral_check.sh"
if [ $? -ne 0 ]; then
    # Add the cron jobs
    (crontab -l 2>/dev/null; cat << 'CRON'
# RingCentral Recording Checker - runs 6 times daily
0 7 * * * /var/www/call-recording-system/run_ringcentral_check.sh
0 10 * * * /var/www/call-recording-system/run_ringcentral_check.sh
0 13 * * * /var/www/call-recording-system/run_ringcentral_check.sh
0 15 * * * /var/www/call-recording-system/run_ringcentral_check.sh
0 17 * * * /var/www/call-recording-system/run_ringcentral_check.sh
0 20 * * * /var/www/call-recording-system/run_ringcentral_check.sh

# Daily cleanup of old logs (keep 30 days)
0 2 * * * find /var/www/call-recording-system/logs -name "*.log" -mtime +30 -delete

# Weekly summary report (Mondays at 9am)
0 9 * * 1 /var/www/call-recording-system/venv/bin/python /var/www/call-recording-system/src/reporting/weekly_summary.py
CRON
    ) | crontab -
    echo "✅ Cron schedule added successfully"
else
    echo "⚠️  Cron jobs already exist"
fi

echo ""
echo "=== Schedule Summary ==="
echo "RingCentral checks will run at:"
echo "  • 7:00 AM"
echo "  • 10:00 AM"
echo "  • 1:00 PM"
echo "  • 3:00 PM"
echo "  • 5:00 PM"
echo "  • 8:00 PM"
echo ""
echo "Logs will be stored in: /var/www/call-recording-system/logs/"
echo ""
echo "To view current cron jobs: crontab -l"
echo "To edit cron jobs: crontab -e"
echo "To test manually: ./run_ringcentral_check.sh"