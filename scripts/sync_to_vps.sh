#!/bin/bash

# Call Recording System - Sync Script
# Syncs local changes to VPS (for development/updates)

# Configuration - EDIT THESE
VPS_IP="YOUR_VPS_IP"
VPS_USER="root"
LOCAL_DIR="/Users/steveabbey/claude/callrecord/call_recording_system"
REMOTE_DIR="/opt/call_recording_system"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "======================================"
echo "Syncing to VPS: ${VPS_USER}@${VPS_IP}"
echo "======================================"

# Check if VPS_IP is configured
if [ "$VPS_IP" = "YOUR_VPS_IP" ]; then
    echo -e "${YELLOW}Please edit this script and set your VPS_IP${NC}"
    exit 1
fi

# Sync files using rsync
echo "Syncing files..."
rsync -avz --progress \
    --exclude 'venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.env' \
    --exclude '.git/' \
    --exclude 'data/audio/*' \
    --exclude 'data/transcripts/*' \
    --exclude 'logs/*' \
    --exclude '*.log' \
    --exclude '.DS_Store' \
    --exclude 'config/google_service_account.json' \
    ${LOCAL_DIR}/ \
    ${VPS_USER}@${VPS_IP}:${REMOTE_DIR}/

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Files synced successfully${NC}"

    # Optional: Restart service after sync
    read -p "Restart service on VPS? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ssh ${VPS_USER}@${VPS_IP} "systemctl restart call-recording-processor"
        echo -e "${GREEN}✓ Service restarted${NC}"
    fi
else
    echo "Sync failed"
    exit 1
fi

echo ""
echo "To check status on VPS:"
echo "  ssh ${VPS_USER}@${VPS_IP}"
echo "  systemctl status call-recording-processor"
echo "  tail -f /opt/call_recording_system/logs/app.log"