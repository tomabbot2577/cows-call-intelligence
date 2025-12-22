#!/usr/bin/env python3
"""
Aggregate Daily Metrics Job

Runs periodically to update today's metrics in user_daily_metrics table.
Called by cron every 15 minutes during business hours.

Usage:
    python -m rag_integration.jobs.aggregate_daily_metrics [--date YYYY-MM-DD]
"""

import os
import sys
import argparse
import logging
from datetime import date

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from rag_integration.services.dashboard_metrics import DashboardMetricsService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def aggregate_metrics(target_date: date = None) -> dict:
    """
    Aggregate metrics for the specified date.

    Args:
        target_date: Date to aggregate (defaults to today)

    Returns:
        dict with stats: employees_processed, errors
    """
    if target_date is None:
        target_date = date.today()

    service = DashboardMetricsService()

    stats = {
        'date': target_date.isoformat(),
        'employees_processed': 0,
        'hourly_volume_updated': False,
        'errors': []
    }

    try:
        logger.info(f"Aggregating daily metrics for {target_date}")

        # Aggregate daily metrics for all employees
        employee_count = service.aggregate_daily_metrics(target_date)
        stats['employees_processed'] = employee_count

        # Aggregate hourly volume
        service.aggregate_hourly_volume(target_date)
        stats['hourly_volume_updated'] = True

        logger.info(f"Aggregation complete: {employee_count} employees processed")

    except Exception as e:
        error_msg = f"Error aggregating metrics: {str(e)}"
        logger.error(error_msg)
        stats['errors'].append(error_msg)

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Aggregate daily metrics for dashboard'
    )
    parser.add_argument(
        '--date', type=str, default=None,
        help='Specific date to aggregate (YYYY-MM-DD), defaults to today'
    )

    args = parser.parse_args()

    target_date = None
    if args.date:
        target_date = date.fromisoformat(args.date)

    stats = aggregate_metrics(target_date)

    print("\n" + "="*50)
    print("AGGREGATION COMPLETE")
    print("="*50)
    print(f"Date: {stats['date']}")
    print(f"Employees processed: {stats['employees_processed']}")
    print(f"Hourly volume updated: {stats['hourly_volume_updated']}")
    print(f"Errors: {len(stats['errors'])}")

    if stats['errors']:
        print("\nErrors:")
        for err in stats['errors']:
            print(f"  - {err}")

    # Exit with error code if there were errors
    sys.exit(1 if stats['errors'] else 0)


if __name__ == '__main__':
    main()
