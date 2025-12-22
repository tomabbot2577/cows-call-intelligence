#!/usr/bin/env python3
"""
Evaluate Triggers Job

Evaluates dashboard email triggers and sends notifications.
Called by cron at different intervals based on trigger frequency.

Usage:
    python -m rag_integration.jobs.evaluate_triggers --frequency realtime
    python -m rag_integration.jobs.evaluate_triggers --frequency daily
    python -m rag_integration.jobs.evaluate_triggers --frequency weekly
"""

import os
import sys
import argparse
import logging
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from rag_integration.services.dashboard_triggers import DashboardTriggerService
from rag_integration.services.dashboard_metrics import DashboardMetricsService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def evaluate_triggers(frequency: str = 'daily') -> dict:
    """
    Evaluate all triggers of a given frequency.

    Args:
        frequency: 'realtime', 'hourly', 'daily', or 'weekly'

    Returns:
        dict with stats: triggers_evaluated, triggers_fired, emails_sent, errors
    """
    trigger_service = DashboardTriggerService()
    metrics_service = DashboardMetricsService()

    stats = {
        'frequency': frequency,
        'triggers_evaluated': 0,
        'triggers_fired': 0,
        'emails_sent': 0,
        'errors': [],
        'details': []
    }

    try:
        # Get active triggers matching the frequency
        all_triggers = trigger_service.list_triggers(active_only=True)
        triggers = [t for t in all_triggers if t.get('frequency') == frequency]

        logger.info(f"Found {len(triggers)} active {frequency} triggers")

        for trigger in triggers:
            stats['triggers_evaluated'] += 1
            trigger_id = trigger['id']
            trigger_name = trigger.get('name', f'Trigger {trigger_id}')

            try:
                # Get employees to evaluate
                if trigger.get('applies_to') == 'specific_users' and trigger.get('target_employees'):
                    employees = trigger['target_employees']
                else:
                    # Get all active employees
                    team = metrics_service.get_team_metrics(period='today', min_activity=0)
                    employees = [m['employee_name'] for m in team]

                logger.info(f"Evaluating trigger '{trigger_name}' for {len(employees)} employees")

                for employee in employees:
                    # Check cooldown
                    if not trigger_service.check_cooldown(trigger_id):
                        logger.debug(f"Trigger {trigger_id} in cooldown for {employee}")
                        continue

                    # Get metrics
                    metrics = metrics_service.get_combined_metrics(employee, 'today')

                    # Evaluate trigger
                    evaluation = trigger_service.evaluate_trigger(trigger, employee, metrics)

                    if evaluation['should_fire']:
                        logger.info(f"Trigger '{trigger_name}' fired for {employee}: {evaluation['reason']}")

                        # Fire the trigger
                        result = trigger_service.fire_trigger(
                            trigger, employee, evaluation, metrics
                        )

                        if result['success']:
                            stats['triggers_fired'] += 1
                            if result['email_sent']:
                                stats['emails_sent'] += 1

                            stats['details'].append({
                                'trigger': trigger_name,
                                'employee': employee,
                                'reason': evaluation['reason'],
                                'email_sent': result['email_sent'],
                                'recipients': result['recipients']
                            })
                        else:
                            stats['errors'].append(
                                f"Failed to fire trigger {trigger_name} for {employee}: {result.get('error')}"
                            )

            except Exception as e:
                error_msg = f"Error evaluating trigger {trigger_name}: {str(e)}"
                logger.error(error_msg)
                stats['errors'].append(error_msg)

    except Exception as e:
        error_msg = f"Error in trigger evaluation: {str(e)}"
        logger.error(error_msg)
        stats['errors'].append(error_msg)

    logger.info(f"Evaluation complete: {stats['triggers_fired']} triggers fired, "
                f"{stats['emails_sent']} emails sent")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Evaluate dashboard email triggers'
    )
    parser.add_argument(
        '--frequency', type=str, default='daily',
        choices=['realtime', 'hourly', 'daily', 'weekly'],
        help='Trigger frequency to evaluate (default: daily)'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Show what would be evaluated without actually sending emails'
    )

    args = parser.parse_args()

    if args.dry_run:
        print(f"DRY RUN: Would evaluate {args.frequency} triggers")
        trigger_service = DashboardTriggerService()
        triggers = trigger_service.list_triggers(active_only=True)
        matching = [t for t in triggers if t.get('frequency') == args.frequency]
        print(f"Found {len(matching)} {args.frequency} triggers:")
        for t in matching:
            print(f"  - {t['name']} ({t['trigger_type']})")
        return

    stats = evaluate_triggers(args.frequency)

    print("\n" + "="*50)
    print("TRIGGER EVALUATION COMPLETE")
    print("="*50)
    print(f"Frequency: {stats['frequency']}")
    print(f"Triggers evaluated: {stats['triggers_evaluated']}")
    print(f"Triggers fired: {stats['triggers_fired']}")
    print(f"Emails sent: {stats['emails_sent']}")
    print(f"Errors: {len(stats['errors'])}")

    if stats['details']:
        print("\nFired Triggers:")
        for d in stats['details']:
            print(f"  - {d['trigger']} -> {d['employee']}")
            print(f"    Reason: {d['reason']}")
            print(f"    Email sent: {d['email_sent']}")

    if stats['errors']:
        print("\nErrors:")
        for err in stats['errors']:
            print(f"  - {err}")

    # Exit with error code if there were errors
    sys.exit(1 if stats['errors'] else 0)


if __name__ == '__main__':
    main()
