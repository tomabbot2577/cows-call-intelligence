#!/bin/bash
# Setup Database Health Monitoring
# Run this script once to configure everything
# Created: 2025-12-21

echo "=== Database Health Monitoring Setup ==="

# 1. Add PostgreSQL timeout settings
echo ""
echo "Step 1: Adding PostgreSQL timeout settings..."

PG_CONF="/etc/postgresql/17/main/postgresql.conf"

# Check if settings already exist
if grep -q "idle_in_transaction_session_timeout" "$PG_CONF" 2>/dev/null; then
    echo "  Settings already exist in postgresql.conf"
else
    echo "  Adding timeout settings to postgresql.conf..."
    sudo tee -a "$PG_CONF" > /dev/null << 'EOF'

# Database Health Settings - Added 2025-12-21
idle_in_transaction_session_timeout = '30min'  # Kill idle transactions after 30 min
statement_timeout = '10min'                     # Kill queries running > 10 min
lock_timeout = '5min'                           # Kill queries waiting on locks > 5 min
EOF
    echo "  Settings added!"
fi

# 2. Reload PostgreSQL
echo ""
echo "Step 2: Reloading PostgreSQL..."
sudo systemctl reload postgresql
echo "  PostgreSQL reloaded!"

# 3. Add cron job for health monitor
echo ""
echo "Step 3: Setting up cron job..."

# Check if cron job already exists
CRON_EXISTS=$(crontab -l 2>/dev/null | grep -c "db_health_monitor.sh")

if [ "$CRON_EXISTS" -gt 0 ]; then
    echo "  Cron job already exists"
else
    # Add new cron job
    (crontab -l 2>/dev/null; echo "*/5 * * * * /var/www/call-recording-system/scripts/db_health_monitor.sh") | crontab -
    echo "  Cron job added (runs every 5 minutes)"
fi

# 4. Test the health monitor
echo ""
echo "Step 4: Testing health monitor..."
/var/www/call-recording-system/scripts/db_health_monitor.sh
echo "  Test complete!"

# 5. Show current settings
echo ""
echo "=== Current PostgreSQL Timeout Settings ==="
sudo -u postgres psql -c "SHOW idle_in_transaction_session_timeout;" 2>/dev/null || echo "  (requires postgres user)"
sudo -u postgres psql -c "SHOW statement_timeout;" 2>/dev/null || echo "  (requires postgres user)"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Logs will be written to:"
echo "  /var/www/call-recording-system/logs/db_health.log"
echo "  /var/www/call-recording-system/logs/db_alerts.log"
echo ""
echo "To check status: cat /var/www/call-recording-system/logs/db_health.log | tail -20"
