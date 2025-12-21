#!/bin/bash
# Cron Job Verification Script
# Checks all pipeline jobs completed successfully without errors
# ONLY sends email alerts when failures/errors are detected
# Created: 2025-12-21

cd /var/www/call-recording-system
source .env 2>/dev/null

# Configuration
LOG_DIR="logs"
ALERT_LOG="$LOG_DIR/cron_alerts.log"
TODAY=$(date +%Y%m%d)
CURRENT_HOUR=$(date +%H)
ALERT_FILE="/tmp/cron_job_alert_${TODAY}.txt"
HAS_ERRORS=0
ERRORS_DETAIL=""

# Email settings (from .env)
SMTP_HOST="${SMTP_HOST:-smtp.gmail.com}"
SMTP_PORT="${SMTP_PORT:-587}"
SMTP_USER="${SMTP_USER:-}"
SMTP_PASSWORD="${SMTP_PASSWORD:-}"
ALERT_EMAIL="${ALERT_EMAIL_TO:-sabbey@mainsequence.net}"

mkdir -p "$LOG_DIR"

# Initialize alert file
echo "========================================" > "$ALERT_FILE"
echo "CRON JOB VERIFICATION REPORT" >> "$ALERT_FILE"
echo "Date: $(date)" >> "$ALERT_FILE"
echo "Server: $(hostname)" >> "$ALERT_FILE"
echo "========================================" >> "$ALERT_FILE"
echo "" >> "$ALERT_FILE"

log_alert() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$ALERT_LOG"
    echo "$1" >> "$ALERT_FILE"
}

# Check if a job should have run by now
# Args: job_name, scheduled_hours (comma-separated), log_pattern
check_job() {
    local job_name="$1"
    local scheduled_hours="$2"  # e.g., "6,18" for 6am and 6pm
    local log_pattern="$3"
    local log_file=$(ls -t ${LOG_DIR}/${log_pattern}${TODAY}.log 2>/dev/null | head -1)

    echo "[$job_name]" >> "$ALERT_FILE"

    # Determine if job should have run by now
    local should_have_run=0
    local expected_runs=0
    IFS=',' read -ra HOURS <<< "$scheduled_hours"
    for hour in "${HOURS[@]}"; do
        # Add 1 hour buffer for job to complete
        local check_hour=$((hour + 1))
        if [ "$CURRENT_HOUR" -ge "$check_hour" ]; then
            should_have_run=1
            expected_runs=$((expected_runs + 1))
        fi
    done

    # If job shouldn't have run yet today, skip
    if [ "$should_have_run" -eq 0 ]; then
        echo "  [PENDING] Not scheduled yet today (runs at ${scheduled_hours}:00)" >> "$ALERT_FILE"
        return 0
    fi

    # Job should have run - check if log exists
    if [ -z "$log_file" ] || [ ! -f "$log_file" ]; then
        log_alert "  [FAILED] Job did not run! Expected by now (scheduled: ${scheduled_hours}:00)"
        ERRORS_DETAIL="${ERRORS_DETAIL}\n- $job_name: Did not run (no log file)"
        HAS_ERRORS=1
        return 1
    fi

    # Check log age - should be recent
    local file_mod_time=$(stat -c %Y "$log_file" 2>/dev/null || echo 0)
    local file_age=$(( $(date +%s) - $file_mod_time ))
    local file_age_hours=$((file_age / 3600))

    # Check for error patterns in log
    local errors=$(grep -ciE "error|exception|failed|failure|timeout|traceback|critical" "$log_file" 2>/dev/null || echo 0)

    # Exclude common false positives
    local real_errors=$(grep -iE "error|exception|failed|failure|timeout|traceback|critical" "$log_file" 2>/dev/null | \
        grep -cvE "error_details.*\[\]|errors.*0|no errors|error_count.*0|failed.*0" || echo 0)

    # Check for completion markers
    local completed=$(grep -ciE "complete|success|finished|done" "$log_file" 2>/dev/null || echo 0)

    if [ "$real_errors" -gt 0 ]; then
        log_alert "  [ERROR] Found $real_errors errors in log"
        echo "  --- Recent Errors ---" >> "$ALERT_FILE"
        grep -iE "error|exception|failed|failure|timeout|traceback|critical" "$log_file" | \
            grep -vE "error_details.*\[\]|errors.*0|no errors" | tail -5 >> "$ALERT_FILE"
        echo "  ---" >> "$ALERT_FILE"
        ERRORS_DETAIL="${ERRORS_DETAIL}\n- $job_name: $real_errors errors found"
        HAS_ERRORS=1
        return 1
    fi

    if [ "$completed" -eq 0 ]; then
        log_alert "  [WARNING] No completion marker - job may have stalled"
        ERRORS_DETAIL="${ERRORS_DETAIL}\n- $job_name: May have stalled (no completion marker)"
        HAS_ERRORS=1
        return 1
    fi

    # Job completed successfully
    local last_run=$(date -d @$file_mod_time '+%H:%M')
    echo "  [OK] Last run: $last_run (${file_age_hours}h ago)" >> "$ALERT_FILE"
    return 0
}

# ============================================
# Check each pipeline job with scheduled times
# ============================================

echo "--- Pipeline Job Status ---" >> "$ALERT_FILE"
echo "" >> "$ALERT_FILE"

# Job: scheduled_hours, log_pattern
check_job "RingCentral Download" "6,18" "ringcentral_v2_"
echo "" >> "$ALERT_FILE"

check_job "Transcription" "6,18" "transcription_v2_"
echo "" >> "$ALERT_FILE"

check_job "AI Layers 1-5" "7,19" "ai_layers_"
echo "" >> "$ALERT_FILE"

check_job "Vertex RAG Export" "8,20" "vertex_rag_export_"
echo "" >> "$ALERT_FILE"

check_job "Freshdesk Pipeline" "9,21" "freshdesk_pipeline_"
echo "" >> "$ALERT_FILE"

# ============================================
# Check database connectivity
# ============================================

echo "--- System Health ---" >> "$ALERT_FILE"
echo "" >> "$ALERT_FILE"

source venv/bin/activate 2>/dev/null

echo "[Database]" >> "$ALERT_FILE"
DB_CHECK=$(python3 -c "
import psycopg2
try:
    conn = psycopg2.connect('postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights')
    cur = conn.cursor()
    cur.execute('SELECT 1')
    print('OK')
except Exception as e:
    print(f'ERROR: {e}')
" 2>&1)

if [[ "$DB_CHECK" == "OK" ]]; then
    echo "  [OK] Connection successful" >> "$ALERT_FILE"
else
    log_alert "  [ERROR] Connection failed: $DB_CHECK"
    ERRORS_DETAIL="${ERRORS_DETAIL}\n- Database: Connection failed"
    HAS_ERRORS=1
fi

# ============================================
# Check disk space
# ============================================

echo "" >> "$ALERT_FILE"
echo "[Disk Space]" >> "$ALERT_FILE"

DISK_USAGE=$(df -h /var/www/call-recording-system | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 90 ]; then
    log_alert "  [CRITICAL] Usage at ${DISK_USAGE}%"
    ERRORS_DETAIL="${ERRORS_DETAIL}\n- Disk: Critical at ${DISK_USAGE}%"
    HAS_ERRORS=1
elif [ "$DISK_USAGE" -gt 80 ]; then
    log_alert "  [WARNING] Usage at ${DISK_USAGE}%"
else
    echo "  [OK] Usage at ${DISK_USAGE}%" >> "$ALERT_FILE"
fi

# ============================================
# Summary
# ============================================

echo "" >> "$ALERT_FILE"
echo "========================================" >> "$ALERT_FILE"
if [ $HAS_ERRORS -eq 1 ]; then
    echo "STATUS: ERRORS DETECTED" >> "$ALERT_FILE"
    echo "" >> "$ALERT_FILE"
    echo "Issues Found:" >> "$ALERT_FILE"
    echo -e "$ERRORS_DETAIL" >> "$ALERT_FILE"
else
    echo "STATUS: ALL SYSTEMS OK" >> "$ALERT_FILE"
fi
echo "========================================" >> "$ALERT_FILE"

# ============================================
# Send email ONLY if errors detected
# ============================================

send_email_alert() {
    python3 << PYEOF
import smtplib
import ssl
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

smtp_host = "${SMTP_HOST}"
smtp_port = int("${SMTP_PORT}")
smtp_user = "${SMTP_USER}"
# Use GMAIL_APP_PASSWORD (spaces removed)
smtp_pass = "${GMAIL_APP_PASSWORD}".replace(" ", "") if "${GMAIL_APP_PASSWORD}" else "${SMTP_PASSWORD}"
to_email = "${ALERT_EMAIL}"

if not smtp_user or not smtp_pass:
    print("SMTP credentials not configured - skipping email")
    exit(0)

try:
    with open("$ALERT_FILE", 'r') as f:
        body = f.read()

    msg = MIMEMultipart()
    msg['Subject'] = '[ALERT] PCR COWS Pipeline - Errors Detected $(date +%Y-%m-%d)'
    msg['From'] = smtp_user
    msg['To'] = to_email
    msg.attach(MIMEText(body, 'plain'))

    context = ssl.create_default_context()

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls(context=context)
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)

    print(f"Alert email sent to {to_email}")
except smtplib.SMTPAuthenticationError:
    print("Gmail authentication failed - need App Password")
    print("To fix: Go to https://myaccount.google.com/apppasswords")
    print("Create an App Password and add to .env as GMAIL_APP_PASSWORD=xxxx")
except Exception as e:
    print(f"Email failed: {e}")
PYEOF
}

# Write alert to a persistent file for web dashboard / manual review
write_alert_file() {
    local PERSISTENT_ALERT="/var/www/call-recording-system/data/alerts/pipeline_alert_$(date +%Y%m%d_%H%M%S).txt"
    mkdir -p /var/www/call-recording-system/data/alerts
    cp "$ALERT_FILE" "$PERSISTENT_ALERT"
    echo "Alert saved to: $PERSISTENT_ALERT"

    # Keep only last 30 days of alerts
    find /var/www/call-recording-system/data/alerts -name "*.txt" -mtime +30 -delete 2>/dev/null
}

# Update dashboard status file
update_dashboard_status() {
    python3 << PYEOF
import json
from datetime import datetime

status = {
    "last_check": datetime.now().isoformat(),
    "has_errors": $HAS_ERRORS == 1,
    "status": "ERROR" if $HAS_ERRORS == 1 else "OK",
    "current_hour": $CURRENT_HOUR
}

with open("/var/www/call-recording-system/data/pipeline_status.json", 'w') as f:
    json.dump(status, f, indent=2)
PYEOF
}

# Always update dashboard status
update_dashboard_status

# ONLY send notifications if there are errors
if [ $HAS_ERRORS -eq 1 ]; then
    echo "" >> "$ALERT_LOG"
    log_alert "ERRORS DETECTED - Sending notifications"

    # Always save alert to file (for dashboard/review)
    write_alert_file

    # Try to send email
    send_email_alert

    echo "" >> "$ALERT_LOG"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - All jobs OK, no alerts needed" >> "$ALERT_LOG"
fi

# Print report to stdout (for manual runs)
cat "$ALERT_FILE"

# Exit with error code if issues found (useful for monitoring)
exit $HAS_ERRORS
