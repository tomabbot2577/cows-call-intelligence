#!/bin/bash
# Freshdesk Knowledge Base Sync
# Run daily via cron to sync Freshdesk tickets to KB and export to JSONL

cd /var/www/call-recording-system
source venv/bin/activate
source .env

python -m rag_integration.jobs.freshdesk_sync_cron

exit $?
