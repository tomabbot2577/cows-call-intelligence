#!/usr/bin/env python3
"""
Non-interactive runner for historical catch-up processing
"""

import logging
from datetime import datetime, timezone
from historical_catchup import HistoricalProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('historical_catchup_run.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def main():
    """Run the historical catch-up without prompts"""
    print("\n" + "=" * 100)
    print("🚀 HISTORICAL CALL RECORDING CATCH-UP PROCESSOR")
    print("=" * 100)

    # Define date range
    start_date = datetime(2025, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    end_date = datetime(2025, 9, 17, 23, 59, 59, tzinfo=timezone.utc)

    print(f"\n📅 Processing Period: {start_date.date()} to {end_date.date()}")
    print(f"⚙️  Max Workers: 4")
    print(f"📦 Batch Size: 10 recordings")
    print("\n🔄 Starting processing automatically...\n")

    try:
        # Create processor and run
        processor = HistoricalProcessor(max_workers=4)
        processor.run(
            start_date=start_date,
            end_date=end_date,
            batch_size=10
        )

        print("\n✅ Historical processing completed successfully!")
        print("📊 Check the generated summary files for details.")

    except KeyboardInterrupt:
        print("\n\n⚠️  Processing interrupted by user")
        logger.warning("Processing interrupted by user")
    except Exception as e:
        print(f"\n❌ Processing failed: {e}")
        logger.error(f"Processing failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()