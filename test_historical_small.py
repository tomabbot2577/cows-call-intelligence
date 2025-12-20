#!/usr/bin/env python3
"""
Test the historical processing with just 2 recordings
"""

import logging
from datetime import datetime, timezone

# Import the processor
from historical_catchup import HistoricalProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def main():
    """Test with just 2 recordings from September 17, 2025"""
    print("\n" + "=" * 80)
    print("🧪 TESTING HISTORICAL PROCESSOR WITH 2 RECORDINGS")
    print("=" * 80)

    # Test with just September 17, 2025
    start_date = datetime(2025, 9, 17, 0, 0, 0, tzinfo=timezone.utc)
    end_date = datetime(2025, 9, 17, 23, 59, 59, tzinfo=timezone.utc)

    print(f"\n📅 Test Period: {start_date.date()} (1 day)")
    print("⚙️  Max Workers: 2")
    print("📦 Processing first 2 recordings only\n")

    try:
        # Create processor
        processor = HistoricalProcessor(max_workers=2)

        # Fetch recordings
        print("Fetching recordings...")
        recordings = processor.fetch_recordings(start_date, end_date)

        if not recordings:
            print("No recordings found")
            return

        print(f"Found {len(recordings)} recordings")

        # Process only first 2
        test_recordings = recordings[:2]
        print(f"\n🔄 Processing first {len(test_recordings)} recordings as a test...\n")

        # Process them
        processor.process_batch(test_recordings, batch_size=2)

        # Generate summary
        summary = processor.generate_summary(start_date, end_date)
        print(summary)

        processor.cleanup()

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        raise


if __name__ == "__main__":
    main()