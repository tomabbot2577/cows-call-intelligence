#!/bin/bash
# Freshdesk Complete Pipeline - Runs 2x daily
# 1. Sync NEW tickets from Freshdesk (since last check)
# 2. AI enrich the tickets with insights
# 3. Export to Vertex AI RAG
# Created: 2025-12-21

cd /var/www/call-recording-system
source venv/bin/activate

# Load environment variables
set -a
source .env
set +a

LOG_DIR="logs"
LOG_FILE="$LOG_DIR/freshdesk_pipeline_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

echo "========================================" >> "$LOG_FILE"
echo "Freshdesk Pipeline Started: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# Get counts before
BEFORE_COUNT=$(python -c "
import psycopg2
conn = psycopg2.connect('postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM kb_freshdesk_qa')
print(cur.fetchone()[0])
" 2>/dev/null || echo 0)

ENRICHED_BEFORE=$(python -c "
import psycopg2
conn = psycopg2.connect('postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM kb_freshdesk_qa WHERE enriched_at IS NOT NULL')
print(cur.fetchone()[0])
" 2>/dev/null || echo 0)

echo "Before: Total=$BEFORE_COUNT, Enriched=$ENRICHED_BEFORE" >> "$LOG_FILE"

# ============================================
# STEP 1: Sync NEW tickets from Freshdesk
# ============================================
echo "" >> "$LOG_FILE"
echo "--- STEP 1: Syncing New Freshdesk Tickets ---" >> "$LOG_FILE"

# Sync tickets from last 7 days (catches any missed + new ones)
python -m rag_integration.jobs.freshdesk_sync_cron >> "$LOG_FILE" 2>&1

AFTER_SYNC=$(python -c "
import psycopg2
conn = psycopg2.connect('postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM kb_freshdesk_qa')
print(cur.fetchone()[0])
" 2>/dev/null || echo 0)

NEW_TICKETS=$((AFTER_SYNC - BEFORE_COUNT))
echo "Sync complete: +$NEW_TICKETS new tickets (Total: $AFTER_SYNC)" >> "$LOG_FILE"

# ============================================
# STEP 2: AI Enrich unenriched tickets
# ============================================
echo "" >> "$LOG_FILE"
echo "--- STEP 2: AI Enrichment ---" >> "$LOG_FILE"

PENDING=$(python -c "
import psycopg2
conn = psycopg2.connect('postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM kb_freshdesk_qa WHERE enriched_at IS NULL')
print(cur.fetchone()[0])
" 2>/dev/null || echo 0)

echo "Pending enrichment: $PENDING tickets" >> "$LOG_FILE"

if [ "$PENDING" -gt 0 ]; then
    # Run enrichment (skip reset to only enrich new ones, skip dedupe as it runs in sync)
    python -m rag_integration.jobs.cleanup_and_enrich --skip-reset --skip-dedupe --skip-export --workers 10 >> "$LOG_FILE" 2>&1
    echo "Enrichment complete" >> "$LOG_FILE"
else
    echo "No tickets pending enrichment, skipping" >> "$LOG_FILE"
fi

ENRICHED_AFTER=$(python -c "
import psycopg2
conn = psycopg2.connect('postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM kb_freshdesk_qa WHERE enriched_at IS NOT NULL')
print(cur.fetchone()[0])
" 2>/dev/null || echo 0)

NEW_ENRICHED=$((ENRICHED_AFTER - ENRICHED_BEFORE))
echo "Enriched: +$NEW_ENRICHED new (Total enriched: $ENRICHED_AFTER)" >> "$LOG_FILE"

# ============================================
# STEP 3: Export to Vertex AI RAG
# ============================================
echo "" >> "$LOG_FILE"
echo "--- STEP 3: Export to Vertex AI RAG ---" >> "$LOG_FILE"

# Only export if we have enriched data
if [ "$ENRICHED_AFTER" -gt 0 ]; then
    python -m rag_integration.jobs.freshdesk_vertex_import >> "$LOG_FILE" 2>&1
    echo "Vertex AI RAG export complete" >> "$LOG_FILE"
else
    echo "No enriched data to export, skipping" >> "$LOG_FILE"
fi

# ============================================
# Summary
# ============================================
echo "" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"
echo "Pipeline Summary:" >> "$LOG_FILE"
echo "  New tickets synced: $NEW_TICKETS" >> "$LOG_FILE"
echo "  New tickets enriched: $NEW_ENRICHED" >> "$LOG_FILE"
echo "  Total Q&A pairs: $AFTER_SYNC" >> "$LOG_FILE"
echo "  Total enriched: $ENRICHED_AFTER" >> "$LOG_FILE"
echo "Freshdesk Pipeline completed: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# Keep logs for 30 days
find "$LOG_DIR" -name "freshdesk_pipeline_*.log" -mtime +30 -delete 2>/dev/null

exit 0
