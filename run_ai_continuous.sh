#!/bin/bash
# Continuous AI processing wrapper

source venv/bin/activate

BATCH_ID=$1
BATCH_SIZE=${2:-50}

echo "Starting continuous AI processing - Batch ID: $BATCH_ID, Size: $BATCH_SIZE"

while true; do
    # Check if there are still records to process
    REMAINING=$(PGPASSWORD=call_insights_pass psql -U call_insights_user -d call_insights -h localhost -t -c "
        SELECT COUNT(*)
        FROM transcript_embeddings te
        WHERE NOT EXISTS (
            SELECT 1 FROM insights i
            WHERE i.recording_id = te.recording_id
            AND i.customer_sentiment IS NOT NULL
        );" | tr -d ' ')

    if [ "$REMAINING" -eq 0 ]; then
        echo "All records processed! Exiting."
        break
    fi

    echo "Processing batch - $REMAINING records remaining"

    # Run the processor for one batch
    python process_complete_insights.py --limit $BATCH_SIZE --batch-id $BATCH_ID

    # Brief pause between batches
    sleep 5
done

echo "Batch $BATCH_ID complete!"