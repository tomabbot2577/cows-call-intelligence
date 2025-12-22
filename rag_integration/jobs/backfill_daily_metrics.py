#!/usr/bin/env python3
"""
Backfill Daily Metrics Job

Processes historical data to populate user_daily_metrics table.
Run once after migration, or to refresh historical data.

Usage:
    python -m rag_integration.jobs.backfill_daily_metrics [--days 90] [--date YYYY-MM-DD]
"""

import os
import sys
import argparse
import logging
from datetime import date, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from rag_integration.services.dashboard_metrics import DashboardMetricsService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def backfill_metrics(days: int = 90, specific_date: str = None) -> dict:
    """
    Backfill daily metrics for the specified number of days.

    Args:
        days: Number of days to backfill (from today backwards)
        specific_date: If provided, only process this specific date (YYYY-MM-DD)

    Returns:
        dict with stats: dates_processed, employees_total, errors
    """
    service = DashboardMetricsService()

    stats = {
        'dates_processed': 0,
        'employees_total': 0,
        'errors': []
    }

    if specific_date:
        # Process single date
        dates = [date.fromisoformat(specific_date)]
    else:
        # Process range of dates
        today = date.today()
        dates = [today - timedelta(days=i) for i in range(days)]

    total_dates = len(dates)
    logger.info(f"Starting backfill for {total_dates} dates")

    for i, metric_date in enumerate(dates):
        try:
            logger.info(f"Processing {metric_date} ({i+1}/{total_dates})")

            # Aggregate daily metrics
            employee_count = service.aggregate_daily_metrics(metric_date)
            stats['employees_total'] += employee_count

            # Aggregate hourly volume
            service.aggregate_hourly_volume(metric_date)

            stats['dates_processed'] += 1

            if (i + 1) % 10 == 0:
                logger.info(f"Progress: {i+1}/{total_dates} dates processed")

        except Exception as e:
            error_msg = f"Error processing {metric_date}: {str(e)}"
            logger.error(error_msg)
            stats['errors'].append(error_msg)

    logger.info(f"Backfill complete: {stats['dates_processed']} dates, "
                f"{stats['employees_total']} employee-days, "
                f"{len(stats['errors'])} errors")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Backfill daily metrics for historical data'
    )
    parser.add_argument(
        '--days', type=int, default=90,
        help='Number of days to backfill (default: 90)'
    )
    parser.add_argument(
        '--date', type=str, default=None,
        help='Specific date to process (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Show what would be processed without actually processing'
    )

    args = parser.parse_args()

    if args.dry_run:
        if args.date:
            print(f"Would process: {args.date}")
        else:
            today = date.today()
            start_date = today - timedelta(days=args.days - 1)
            print(f"Would process {args.days} days: {start_date} to {today}")
        return

    stats = backfill_metrics(days=args.days, specific_date=args.date)

    print("\n" + "="*50)
    print("BACKFILL COMPLETE")
    print("="*50)
    print(f"Dates processed: {stats['dates_processed']}")
    print(f"Total employee-days: {stats['employees_total']}")
    print(f"Errors: {len(stats['errors'])}")

    if stats['errors']:
        print("\nErrors:")
        for err in stats['errors'][:10]:  # Show first 10
            print(f"  - {err}")
        if len(stats['errors']) > 10:
            print(f"  ... and {len(stats['errors']) - 10} more")


if __name__ == '__main__':
    main()
