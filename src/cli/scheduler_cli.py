"""
CLI for managing the processing scheduler
"""

import click
import logging
import json
from datetime import datetime, timedelta
from typing import Optional

from src.database.session import SessionManager
from src.database.config import DatabaseConfig
from src.config.settings import Settings
from src.scheduler import ProcessingScheduler, StateManager, BatchProcessor
from src.ringcentral.auth import RingCentralAuth
from src.transcription.pipeline import TranscriptionPipeline
from src.storage.google_drive import GoogleDriveManager
from src.monitoring import MetricsCollector, HealthChecker, AlertManager

logger = logging.getLogger(__name__)


def create_scheduler() -> ProcessingScheduler:
    """Create and configure scheduler instance"""
    settings = Settings()

    # Initialize database
    db_config = DatabaseConfig(settings.database_url)
    session_manager = SessionManager(db_config)

    # Initialize components
    ringcentral_auth = RingCentralAuth(
        client_id=settings.ringcentral_client_id,
        client_secret=settings.ringcentral_client_secret,
        jwt_token=settings.ringcentral_jwt_token,
        server_url=settings.ringcentral_server_url
    )

    transcription_pipeline = TranscriptionPipeline(
        session_manager=session_manager,
        model_name=settings.whisper_model,
        device=settings.whisper_device
    )

    drive_manager = GoogleDriveManager(
        credentials_path=settings.google_credentials_path,
        session_manager=session_manager
    )

    metrics_collector = MetricsCollector(
        prometheus_enabled=settings.prometheus_enabled
    )

    health_checker = HealthChecker(
        check_interval=60
    )

    alert_manager = AlertManager()

    # Create scheduler
    scheduler_config = {
        'daily_schedule_time': settings.daily_schedule_time,
        'batch_size': settings.batch_size,
        'max_retries': settings.max_retries,
        'historical_days': settings.historical_days
    }

    scheduler = ProcessingScheduler(
        session_manager=session_manager,
        ringcentral_auth=ringcentral_auth,
        transcription_pipeline=transcription_pipeline,
        drive_manager=drive_manager,
        metrics_collector=metrics_collector,
        health_checker=health_checker,
        alert_manager=alert_manager,
        config=scheduler_config
    )

    return scheduler


@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
def cli(verbose):
    """Call Recording System Scheduler CLI"""
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


@cli.command()
def start():
    """Start the automated scheduler"""
    try:
        scheduler = create_scheduler()

        click.echo("Starting processing scheduler...")
        scheduler.start()

        click.echo(f"Scheduler started. Daily processing scheduled at {scheduler.daily_schedule_time}")
        click.echo("Press Ctrl+C to stop")

        # Keep running
        import signal
        import sys

        def signal_handler(sig, frame):
            click.echo("\nStopping scheduler...")
            scheduler.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.pause()

    except Exception as e:
        click.echo(f"Error starting scheduler: {e}", err=True)
        raise


@cli.command()
def status():
    """Get scheduler status"""
    try:
        scheduler = create_scheduler()
        status_info = scheduler.get_status()

        click.echo("\nScheduler Status:")
        click.echo("-" * 40)
        click.echo(f"Running: {status_info['is_running']}")
        click.echo(f"Daily Schedule: {status_info['daily_schedule_time']}")
        click.echo(f"Last Run: {status_info.get('last_successful_run', 'Never')}")
        click.echo(f"Next Run: {status_info.get('next_run', 'Not scheduled')}")
        click.echo(f"Total Processed: {status_info['total_processed']}")
        click.echo(f"Total Succeeded: {status_info['total_succeeded']}")
        click.echo(f"Total Failed: {status_info['total_failed']}")

        if status_info.get('current_stats'):
            click.echo("\nCurrent Processing:")
            stats = status_info['current_stats']
            click.echo(f"  Started: {stats['start_time']}")
            click.echo(f"  Recordings: {stats['total_recordings']}")

    except Exception as e:
        click.echo(f"Error getting status: {e}", err=True)
        raise


@cli.command()
@click.option('--days', '-d', default=60, help='Number of days to process')
@click.option('--start-date', '-s', help='Start date (YYYY-MM-DD)')
@click.option('--end-date', '-e', help='End date (YYYY-MM-DD)')
def process_historical(days, start_date, end_date):
    """Process historical recordings"""
    try:
        scheduler = create_scheduler()

        # Determine date range
        if start_date and end_date:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
        else:
            end = datetime.utcnow().date()
            start = end - timedelta(days=days)

        click.echo(f"Processing historical recordings from {start} to {end}")
        click.echo("This may take a while...")

        # Initialize clients
        scheduler.initialize_clients()

        # Process historical data
        scheduler.process_historical(start, end)

        click.echo("Historical processing complete")

    except Exception as e:
        click.echo(f"Error processing historical data: {e}", err=True)
        raise


@cli.command()
def run_once():
    """Run processing once immediately"""
    try:
        scheduler = create_scheduler()

        click.echo("Running one-time processing...")

        # Initialize clients
        scheduler.initialize_clients()

        # Run processing
        scheduler.run_daily_processing()

        click.echo("Processing complete")

    except Exception as e:
        click.echo(f"Error running processing: {e}", err=True)
        raise


@cli.group()
def batch():
    """Batch processing commands"""
    pass


@batch.command('create')
@click.option('--start-date', '-s', required=True, help='Start date (YYYY-MM-DD)')
@click.option('--end-date', '-e', required=True, help='End date (YYYY-MM-DD)')
@click.option('--workers', '-w', default=4, help='Number of concurrent workers')
def create_batch(start_date, end_date, workers):
    """Create and start a new batch"""
    try:
        settings = Settings()
        db_config = DatabaseConfig(settings.database_url)
        session_manager = SessionManager(db_config)
        state_manager = StateManager(session_manager)

        # Create components
        scheduler = create_scheduler()
        scheduler.initialize_clients()

        batch_processor = BatchProcessor(
            session_manager=session_manager,
            state_manager=state_manager,
            ringcentral_client=scheduler.ringcentral_client,
            transcription_pipeline=scheduler.transcription_pipeline,
            drive_manager=scheduler.drive_manager,
            metrics_collector=scheduler.metrics,
            max_workers=workers
        )

        # Parse dates
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()

        click.echo(f"Creating batch for {start} to {end} with {workers} workers")

        # Progress callback
        def show_progress(progress):
            click.echo(f"Progress: {progress['current_date']} - "
                      f"Processed: {progress['processed']}, "
                      f"Succeeded: {progress['succeeded']}, "
                      f"Failed: {progress['failed']}")

        # Process batch
        results = batch_processor.process_date_range(
            start_date=start,
            end_date=end,
            progress_callback=show_progress
        )

        click.echo("\nBatch Processing Complete:")
        click.echo(f"Batch ID: {results['batch_id']}")
        click.echo(f"Total Processed: {results['total_processed']}")
        click.echo(f"Succeeded: {results['total_succeeded']}")
        click.echo(f"Failed: {results['total_failed']}")

        if results['errors']:
            click.echo(f"Errors: {len(results['errors'])}")
            for error in results['errors'][:5]:
                click.echo(f"  - {error}")

    except Exception as e:
        click.echo(f"Error creating batch: {e}", err=True)
        raise


@batch.command('resume')
@click.argument('batch_id')
@click.option('--workers', '-w', default=4, help='Number of concurrent workers')
def resume_batch(batch_id, workers):
    """Resume an existing batch"""
    try:
        settings = Settings()
        db_config = DatabaseConfig(settings.database_url)
        session_manager = SessionManager(db_config)
        state_manager = StateManager(session_manager)

        # Load batch
        batch = state_manager.load_batch(batch_id)
        if not batch:
            click.echo(f"Batch {batch_id} not found", err=True)
            return

        click.echo(f"Resuming batch {batch_id} from {batch.current_date}")

        # Create components
        scheduler = create_scheduler()
        scheduler.initialize_clients()

        batch_processor = BatchProcessor(
            session_manager=session_manager,
            state_manager=state_manager,
            ringcentral_client=scheduler.ringcentral_client,
            transcription_pipeline=scheduler.transcription_pipeline,
            drive_manager=scheduler.drive_manager,
            metrics_collector=scheduler.metrics,
            max_workers=workers
        )

        # Progress callback
        def show_progress(progress):
            click.echo(f"Progress: {progress['current_date']} - "
                      f"Processed: {progress['processed']}, "
                      f"Succeeded: {progress['succeeded']}, "
                      f"Failed: {progress['failed']}")

        # Resume processing
        results = batch_processor.process_date_range(
            start_date=datetime.fromisoformat(batch.start_date).date(),
            end_date=datetime.fromisoformat(batch.end_date).date(),
            resume_batch_id=batch_id,
            progress_callback=show_progress
        )

        click.echo("\nBatch Processing Complete:")
        click.echo(f"Total Processed: {results['total_processed']}")
        click.echo(f"Succeeded: {results['total_succeeded']}")
        click.echo(f"Failed: {results['total_failed']}")

    except Exception as e:
        click.echo(f"Error resuming batch: {e}", err=True)
        raise


@batch.command('list')
def list_batches():
    """List all batches"""
    try:
        settings = Settings()
        db_config = DatabaseConfig(settings.database_url)
        session_manager = SessionManager(db_config)
        state_manager = StateManager(session_manager)

        batches = state_manager.get_active_batches()

        if not batches:
            click.echo("No active batches found")
            return

        click.echo("\nActive Batches:")
        click.echo("-" * 60)

        for batch in batches:
            click.echo(f"ID: {batch.batch_id}")
            click.echo(f"  Date Range: {batch.start_date} to {batch.end_date}")
            click.echo(f"  Current: {batch.current_date}")
            click.echo(f"  Processed: {batch.total_processed}")
            click.echo(f"  Failed: {batch.total_failed}")
            click.echo(f"  Completed: {batch.completed}")
            click.echo()

    except Exception as e:
        click.echo(f"Error listing batches: {e}", err=True)
        raise


@cli.command()
def retry_failed():
    """Retry failed recordings"""
    try:
        settings = Settings()
        db_config = DatabaseConfig(settings.database_url)
        session_manager = SessionManager(db_config)
        state_manager = StateManager(session_manager)

        click.echo("Retrying failed recordings...")

        # Create components
        scheduler = create_scheduler()
        scheduler.initialize_clients()

        batch_processor = BatchProcessor(
            session_manager=session_manager,
            state_manager=state_manager,
            ringcentral_client=scheduler.ringcentral_client,
            transcription_pipeline=scheduler.transcription_pipeline,
            drive_manager=scheduler.drive_manager,
            metrics_collector=scheduler.metrics
        )

        # Process failed recordings
        results = batch_processor.process_failed_recordings()

        click.echo("\nRetry Complete:")
        click.echo(f"Total Processed: {results['total_processed']}")
        click.echo(f"Succeeded: {results['total_succeeded']}")
        click.echo(f"Failed: {results['total_failed']}")

    except Exception as e:
        click.echo(f"Error retrying failed recordings: {e}", err=True)
        raise


@cli.command()
def summary():
    """Get processing summary"""
    try:
        settings = Settings()
        db_config = DatabaseConfig(settings.database_url)
        session_manager = SessionManager(db_config)
        state_manager = StateManager(session_manager)

        summary = state_manager.get_processing_summary()

        click.echo("\nProcessing Summary:")
        click.echo("-" * 40)
        click.echo(f"Total Recordings: {summary['total_recordings']}")
        click.echo(f"Completed: {summary['completed']}")
        click.echo("\nPending:")
        for stage, count in summary['pending'].items():
            click.echo(f"  {stage}: {count}")
        click.echo("\nFailed:")
        for stage, count in summary['failed'].items():
            click.echo(f"  {stage}: {count}")
        click.echo(f"\nActive Batches: {summary['active_batches']}")

    except Exception as e:
        click.echo(f"Error getting summary: {e}", err=True)
        raise


if __name__ == '__main__':
    cli()