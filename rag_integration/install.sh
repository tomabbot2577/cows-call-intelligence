#!/bin/bash
# Install and setup ConvoMetrics BLT Integration

set -e

echo "=========================================="
echo "ConvoMetrics BLT - Installation Script"
echo "=========================================="

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo: sudo ./install.sh"
    exit 1
fi

cd /var/www/call-recording-system

# 1. Install Python dependencies
echo ""
echo "[1/6] Installing Python dependencies..."
sudo -u www-data /var/www/call-recording-system/venv/bin/pip install -r rag_integration/requirements.txt

# 2. Create log directory
echo ""
echo "[2/6] Creating log directories..."
mkdir -p /var/log/cows
chown www-data:www-data /var/log/cows

# 3. Create export directory
echo ""
echo "[3/6] Creating export directory..."
mkdir -p /var/www/call-recording-system/rag_integration/exports
chown www-data:www-data /var/www/call-recording-system/rag_integration/exports

# 4. Install systemd service
echo ""
echo "[4/6] Installing systemd service..."
cp rag_integration/cows-rag-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable cows-rag-api.service

# 5. Setup cron jobs
echo ""
echo "[5/6] Setting up cron jobs..."
bash rag_integration/setup_cron.sh

# 6. Start the service
echo ""
echo "[6/6] Starting RAG API service..."
systemctl start cows-rag-api.service

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "RAG API running at: http://localhost:8081"
echo ""
echo "Useful commands:"
echo "  - Check status: sudo systemctl status cows-rag-api"
echo "  - View logs: tail -f /var/log/cows/rag-api.log"
echo "  - Restart: sudo systemctl restart cows-rag-api"
echo "  - Stop: sudo systemctl stop cows-rag-api"
echo ""
echo "Manual export: python -m rag_integration.jobs.export_pipeline"
echo ""
