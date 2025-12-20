#!/bin/bash
# Run AI processing continuously

source venv/bin/activate

BATCH_ID=$1
BATCH_SIZE=${2:-30}

echo "Starting AI processing - Batch ID: $BATCH_ID"

while true; do
    # Check remaining
    REMAINING=$(PGPASSWORD=call_insights_pass psql -U call_insights_user -d call_insights -h localhost -t -c "
        SELECT COUNT(*)
        FROM transcript_embeddings te
        WHERE NOT EXISTS (
            SELECT 1 FROM insights i
            WHERE i.recording_id = te.recording_id
            AND i.customer_sentiment IS NOT NULL
        );" | tr -d ' ')

    if [ "$REMAINING" -eq 0 ]; then
        echo "All records processed!"
        break
    fi

    echo "Processing batch - $REMAINING records remaining"

    # Get batch of recordings to process
    RECORDINGS=$(PGPASSWORD=call_insights_pass psql -U call_insights_user -d call_insights -h localhost -t -c "
        SELECT te.recording_id
        FROM transcript_embeddings te
        WHERE NOT EXISTS (
            SELECT 1 FROM insights i
            WHERE i.recording_id = te.recording_id
            AND i.customer_sentiment IS NOT NULL
        )
        ORDER BY te.recording_id
        LIMIT $BATCH_SIZE;" | tr -d ' ')

    # Process each recording
    for RECORDING_ID in $RECORDINGS; do
        echo "Processing $RECORDING_ID..."
        python process_complete_insights.py "$RECORDING_ID" --batch-id "$BATCH_ID" 2>&1
        sleep 3
    done

    echo "Batch complete, checking for more..."
    sleep 5
done

echo "$BATCH_ID complete!"