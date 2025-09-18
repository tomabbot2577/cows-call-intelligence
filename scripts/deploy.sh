#!/bin/bash

# Call Recording System - Deployment Script
# This script automates the deployment process to your VPS

set -e  # Exit on error

# Configuration
VPS_IP="${1}"
VPS_USER="${2:-root}"
APP_DIR="/opt/call_recording_system"
LOCAL_DIR="$(pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Functions
print_success() { echo -e "${GREEN}✓${NC} $1"; }
print_error() { echo -e "${RED}✗${NC} $1"; }
print_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
print_info() { echo -e "ℹ $1"; }

# Check arguments
if [ -z "$VPS_IP" ]; then
    echo "Usage: $0 <vps-ip> [user]"
    echo "Example: $0 192.168.1.100 root"
    exit 1
fi

echo "========================================="
echo "Call Recording System - Deployment Script"
echo "========================================="
echo "VPS: ${VPS_USER}@${VPS_IP}"
echo "Local: ${LOCAL_DIR}"
echo "Remote: ${APP_DIR}"
echo ""

# Step 1: Check SSH connection
print_info "Testing SSH connection..."
if ssh -o ConnectTimeout=5 ${VPS_USER}@${VPS_IP} "echo connected" > /dev/null 2>&1; then
    print_success "SSH connection successful"
else
    print_error "Cannot connect to VPS via SSH"
    exit 1
fi

# Step 2: Create deployment package
print_info "Creating deployment package..."
TEMP_DIR=$(mktemp -d)
PACKAGE_FILE="${TEMP_DIR}/deployment.tar.gz"

tar -czf ${PACKAGE_FILE} \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    --exclude='venv' \
    --exclude='.env' \
    --exclude='.git' \
    --exclude='data/audio/*' \
    --exclude='data/transcripts/*' \
    --exclude='logs/*' \
    --exclude='*.log' \
    --exclude='.DS_Store' \
    --exclude='deployment.tar.gz' \
    .

PACKAGE_SIZE=$(du -h ${PACKAGE_FILE} | cut -f1)
print_success "Package created (${PACKAGE_SIZE})"

# Step 3: Transfer files
print_info "Transferring files to VPS..."
scp -q ${PACKAGE_FILE} ${VPS_USER}@${VPS_IP}:/tmp/deployment.tar.gz
print_success "Files transferred"

# Step 4: Deploy on VPS
print_info "Deploying on VPS..."

ssh ${VPS_USER}@${VPS_IP} << 'ENDSSH'
set -e

echo "Installing system dependencies..."
apt-get update > /dev/null 2>&1
apt-get install -y python3.10 python3.10-venv python3-pip postgresql postgresql-contrib ffmpeg > /dev/null 2>&1

echo "Creating application directory..."
mkdir -p /opt/call_recording_system
cd /opt/call_recording_system

echo "Extracting files..."
tar -xzf /tmp/deployment.tar.gz
rm /tmp/deployment.tar.gz

echo "Creating Python virtual environment..."
python3.10 -m venv venv
source venv/bin/activate

echo "Installing Python dependencies..."
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt

echo "Creating required directories..."
mkdir -p data/audio data/transcripts logs config
chmod 755 data logs

echo "Setting up database..."
sudo -u postgres psql -c "SELECT 1 FROM pg_database WHERE datname='call_recordings'" | grep -q 1 || \
sudo -u postgres psql << EOF
CREATE DATABASE call_recordings;
CREATE USER call_system WITH PASSWORD 'ChangeThisPassword123!';
GRANT ALL PRIVILEGES ON DATABASE call_recordings TO call_system;
ALTER USER call_system CREATEDB;
EOF

echo "Deployment complete on VPS"
ENDSSH

print_success "Deployment completed"

# Step 5: Post-deployment steps
echo ""
echo "========================================="
echo "POST-DEPLOYMENT STEPS"
echo "========================================="
echo ""
echo "1. Configure environment variables:"
echo "   ssh ${VPS_USER}@${VPS_IP}"
echo "   cd ${APP_DIR}"
echo "   cp .env.example .env"
echo "   nano .env"
echo ""
echo "2. Upload Google service account key:"
echo "   scp google_service_account.json ${VPS_USER}@${VPS_IP}:${APP_DIR}/config/"
echo ""
echo "3. Initialize database:"
echo "   ssh ${VPS_USER}@${VPS_IP}"
echo "   cd ${APP_DIR}"
echo "   source venv/bin/activate"
echo "   alembic upgrade head"
echo ""
echo "4. Test connections:"
echo "   python scripts/test_connections.py"
echo ""
echo "5. Create systemd service:"
echo "   sudo nano /etc/systemd/system/call-recording-processor.service"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable call-recording-processor"
echo "   sudo systemctl start call-recording-processor"
echo ""
echo "6. Check status:"
echo "   sudo systemctl status call-recording-processor"
echo ""

# Cleanup
rm -rf ${TEMP_DIR}

print_success "Deployment script completed!"
print_info "Follow the post-deployment steps above to complete setup"