#!/bin/bash
# Vertex RAG Export - Exports analyzed calls to Vertex AI RAG
# Runs after AI Layers complete to upload enriched call data
# Created: 2025-12-21

cd /var/www/call-recording-system
source venv/bin/activate

# Load environment variables
set -a
source .env
set +a

LOG_DIR="logs"
LOG_FILE="$LOG_DIR/vertex_rag_export_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

echo "========================================" >> "$LOG_FILE"
echo "Vertex RAG Export Started: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# Show status before processing
echo "--- Status Before Export ---" >> "$LOG_FILE"
python -m rag_integration.jobs.rag_sync_job --status >> "$LOG_FILE" 2>&1

# Export calls with all 5 layers complete to Vertex RAG
# - batch-size 100: Process 100 calls per batch
# - max-batches 20: Process up to 20 batches (2000 calls total)
echo "" >> "$LOG_FILE"
echo "--- Exporting to Vertex RAG ---" >> "$LOG_FILE"
python -m rag_integration.jobs.rag_sync_job --batch-size 100 --max-batches 20 >> "$LOG_FILE" 2>&1

# Show status after processing
echo "" >> "$LOG_FILE"
echo "--- Status After Export ---" >> "$LOG_FILE"
python -m rag_integration.jobs.rag_sync_job --status >> "$LOG_FILE" 2>&1

echo "" >> "$LOG_FILE"
echo "Vertex RAG Export completed: $(date)" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# Keep logs for 30 days
find "$LOG_DIR" -name "vertex_rag_export_*.log" -mtime +30 -delete 2>/dev/null

exit 0
