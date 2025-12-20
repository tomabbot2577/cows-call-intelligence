#!/bin/bash
# Setup cron jobs for RAG integration

# Create log directory if it doesn't exist
sudo mkdir -p /var/log/cows
sudo chown www-data:www-data /var/log/cows

# Create cron file
cat << 'EOF' | sudo tee /etc/cron.d/cows-rag
# COWS RAG Integration Cron Jobs

# Daily incremental export at 2 AM
0 2 * * * www-data cd /var/www/call-recording-system && /var/www/call-recording-system/venv/bin/python -m rag_integration.jobs.export_pipeline >> /var/log/cows/rag_export.log 2>&1

# Weekly full export on Sunday at 3 AM
0 3 * * 0 www-data cd /var/www/call-recording-system && /var/www/call-recording-system/venv/bin/python -m rag_integration.jobs.export_pipeline --full >> /var/log/cows/rag_export.log 2>&1

# Log rotation - keep last 30 days
0 0 * * * root find /var/log/cows -name "*.log" -mtime +30 -delete
EOF

# Set permissions
sudo chmod 644 /etc/cron.d/cows-rag

echo "Cron jobs configured. Verify with: cat /etc/cron.d/cows-rag"
