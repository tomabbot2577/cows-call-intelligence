#!/bin/bash

echo "🔍 Monitoring 15 recordings test..."
echo "Will automatically start 1535 historical backup when complete"
echo "================================================"

# Wait for the test_15_final.log to show completion
while true; do
    if grep -q "PROCESSING SUMMARY" test_15_final.log 2>/dev/null; then
        echo "✅ 15 recordings test completed!"

        # Extract summary
        echo ""
        echo "Test Results:"
        grep -A 10 "PROCESSING SUMMARY" test_15_final.log

        # Check if successful
        if grep -q "✨ Test complete!" test_15_final.log; then
            echo ""
            echo "🚀 Starting historical backup of 1535 recordings..."
            echo "================================================"

            # Start the historical backup
            source venv/bin/activate
            python historical_catchup_final.py 2>&1 | tee historical_backup_full.log

            echo ""
            echo "✅ Historical backup completed!"
            exit 0
        else
            echo "❌ Test had errors. Not starting backup."
            exit 1
        fi
    fi

    # Show current progress
    CURRENT=$(grep -c "Successfully processed recording" test_15_final.log 2>/dev/null || echo 0)
    echo "Progress: $CURRENT/15 recordings processed... ($(date '+%H:%M:%S'))"

    sleep 30
done