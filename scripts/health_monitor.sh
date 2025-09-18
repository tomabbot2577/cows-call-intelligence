#!/bin/bash

# Call Recording System - Health Monitor Script
# Run this script to get a quick health status of the system

echo "======================================"
echo "Call Recording System - Health Monitor"
echo "======================================"
echo "Timestamp: $(date)"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check service status
echo "1. SERVICE STATUS"
echo "-----------------"
if systemctl is-active --quiet call-recording-processor; then
    echo -e "${GREEN}✓${NC} Service is running"
    systemctl status call-recording-processor --no-pager | grep -E "Active:|Main PID:" | head -2
else
    echo -e "${RED}✗${NC} Service is not running"
fi
echo ""

# Check database connection
echo "2. DATABASE STATUS"
echo "------------------"
if sudo -u postgres psql -d call_recordings -c "SELECT 1;" &>/dev/null; then
    echo -e "${GREEN}✓${NC} PostgreSQL is accessible"

    # Get recording statistics
    sudo -u postgres psql -d call_recordings -t -c "
    SELECT
        'Total Recordings: ' || COUNT(*) as stat
    FROM call_recordings
    UNION ALL
    SELECT
        'Completed: ' || COUNT(*)
    FROM call_recordings
    WHERE upload_status = 'completed'
    UNION ALL
    SELECT
        'Pending Download: ' || COUNT(*)
    FROM call_recordings
    WHERE download_status = 'pending'
    UNION ALL
    SELECT
        'Pending Transcription: ' || COUNT(*)
    FROM call_recordings
    WHERE transcription_status = 'pending' AND download_status = 'completed'
    UNION ALL
    SELECT
        'Pending Upload: ' || COUNT(*)
    FROM call_recordings
    WHERE upload_status = 'pending' AND transcription_status = 'completed'
    UNION ALL
    SELECT
        'Failed: ' || COUNT(*)
    FROM call_recordings
    WHERE download_status = 'failed' OR transcription_status = 'failed' OR upload_status = 'failed';"
else
    echo -e "${RED}✗${NC} Cannot connect to PostgreSQL"
fi
echo ""

# Check disk usage
echo "3. DISK USAGE"
echo "-------------"
DISK_USAGE=$(df -h /opt/call_recording_system | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -lt 80 ]; then
    echo -e "${GREEN}✓${NC} Disk usage is healthy"
elif [ "$DISK_USAGE" -lt 90 ]; then
    echo -e "${YELLOW}⚠${NC} Disk usage is high"
else
    echo -e "${RED}✗${NC} Disk usage is critical"
fi
df -h /opt/call_recording_system | grep -v Filesystem
echo ""

# Check memory usage
echo "4. MEMORY USAGE"
echo "---------------"
MEMORY_USAGE=$(free | grep Mem | awk '{print int($3/$2 * 100)}')
if [ "$MEMORY_USAGE" -lt 80 ]; then
    echo -e "${GREEN}✓${NC} Memory usage is healthy ($MEMORY_USAGE%)"
elif [ "$MEMORY_USAGE" -lt 90 ]; then
    echo -e "${YELLOW}⚠${NC} Memory usage is high ($MEMORY_USAGE%)"
else
    echo -e "${RED}✗${NC} Memory usage is critical ($MEMORY_USAGE%)"
fi
free -h | grep -E "^Mem:|^Swap:"
echo ""

# Check recent errors
echo "5. RECENT ERRORS (Last 24 hours)"
echo "---------------------------------"
LOG_FILE="/opt/call_recording_system/logs/app.log"
if [ -f "$LOG_FILE" ]; then
    ERROR_COUNT=$(grep -c "ERROR" "$LOG_FILE" 2>/dev/null || echo "0")
    CRITICAL_COUNT=$(grep -c "CRITICAL" "$LOG_FILE" 2>/dev/null || echo "0")

    if [ "$CRITICAL_COUNT" -gt 0 ]; then
        echo -e "${RED}✗${NC} Found $CRITICAL_COUNT CRITICAL errors"
    elif [ "$ERROR_COUNT" -gt 10 ]; then
        echo -e "${YELLOW}⚠${NC} Found $ERROR_COUNT ERROR messages"
    elif [ "$ERROR_COUNT" -gt 0 ]; then
        echo -e "${GREEN}✓${NC} Found $ERROR_COUNT minor errors"
    else
        echo -e "${GREEN}✓${NC} No errors found"
    fi

    if [ "$ERROR_COUNT" -gt 0 ]; then
        echo "Latest errors:"
        grep "ERROR\|CRITICAL" "$LOG_FILE" | tail -3
    fi
else
    echo -e "${YELLOW}⚠${NC} Log file not found"
fi
echo ""

# Check last processing run
echo "6. LAST PROCESSING RUN"
echo "----------------------"
if [ -f "$LOG_FILE" ]; then
    LAST_RUN=$(grep "Starting daily processing run\|Daily processing completed" "$LOG_FILE" | tail -1)
    if [ -n "$LAST_RUN" ]; then
        echo "$LAST_RUN"
    else
        echo "No processing run found in logs"
    fi
fi
echo ""

# Check API connections
echo "7. API CONNECTIVITY"
echo "-------------------"
# Check RingCentral
if curl -s --head https://platform.ringcentral.com | head -n 1 | grep "HTTP/[12]" > /dev/null; then
    echo -e "${GREEN}✓${NC} RingCentral API is reachable"
else
    echo -e "${RED}✗${NC} Cannot reach RingCentral API"
fi

# Check Google
if curl -s --head https://www.googleapis.com | head -n 1 | grep "HTTP/[12]" > /dev/null; then
    echo -e "${GREEN}✓${NC} Google API is reachable"
else
    echo -e "${RED}✗${NC} Cannot reach Google API"
fi
echo ""

# Check Python processes
echo "8. PYTHON PROCESSES"
echo "-------------------"
PYTHON_COUNT=$(ps aux | grep -c "[p]ython.*scheduler")
if [ "$PYTHON_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓${NC} Found $PYTHON_COUNT scheduler process(es)"
    ps aux | grep "[p]ython.*scheduler" | awk '{print "  PID:", $2, "CPU:", $3"%", "MEM:", $4"%", "TIME:", $10}'
else
    echo -e "${YELLOW}⚠${NC} No scheduler processes found"
fi
echo ""

# Overall health score
echo "======================================"
echo "OVERALL HEALTH SUMMARY"
echo "======================================"

HEALTH_SCORE=100
ISSUES=""

# Calculate health score
if ! systemctl is-active --quiet call-recording-processor; then
    HEALTH_SCORE=$((HEALTH_SCORE - 50))
    ISSUES="${ISSUES}- Service not running\n"
fi

if ! sudo -u postgres psql -d call_recordings -c "SELECT 1;" &>/dev/null; then
    HEALTH_SCORE=$((HEALTH_SCORE - 30))
    ISSUES="${ISSUES}- Database connection failed\n"
fi

if [ "$DISK_USAGE" -gt 90 ]; then
    HEALTH_SCORE=$((HEALTH_SCORE - 20))
    ISSUES="${ISSUES}- Disk usage critical\n"
elif [ "$DISK_USAGE" -gt 80 ]; then
    HEALTH_SCORE=$((HEALTH_SCORE - 10))
    ISSUES="${ISSUES}- Disk usage high\n"
fi

if [ "$MEMORY_USAGE" -gt 90 ]; then
    HEALTH_SCORE=$((HEALTH_SCORE - 15))
    ISSUES="${ISSUES}- Memory usage critical\n"
elif [ "$MEMORY_USAGE" -gt 80 ]; then
    HEALTH_SCORE=$((HEALTH_SCORE - 5))
    ISSUES="${ISSUES}- Memory usage high\n"
fi

if [ "$CRITICAL_COUNT" -gt 0 ]; then
    HEALTH_SCORE=$((HEALTH_SCORE - 20))
    ISSUES="${ISSUES}- Critical errors in logs\n"
elif [ "$ERROR_COUNT" -gt 10 ]; then
    HEALTH_SCORE=$((HEALTH_SCORE - 10))
    ISSUES="${ISSUES}- Multiple errors in logs\n"
fi

# Display health score
if [ "$HEALTH_SCORE" -ge 90 ]; then
    echo -e "Health Score: ${GREEN}$HEALTH_SCORE/100${NC} - EXCELLENT"
elif [ "$HEALTH_SCORE" -ge 70 ]; then
    echo -e "Health Score: ${GREEN}$HEALTH_SCORE/100${NC} - GOOD"
elif [ "$HEALTH_SCORE" -ge 50 ]; then
    echo -e "Health Score: ${YELLOW}$HEALTH_SCORE/100${NC} - NEEDS ATTENTION"
else
    echo -e "Health Score: ${RED}$HEALTH_SCORE/100${NC} - CRITICAL"
fi

if [ -n "$ISSUES" ]; then
    echo ""
    echo "Issues found:"
    echo -e "$ISSUES"
fi

echo ""
echo "======================================"
echo "Run 'systemctl status call-recording-processor' for more details"
echo "Check logs at: /opt/call_recording_system/logs/app.log"