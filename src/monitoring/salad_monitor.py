#!/usr/bin/env python3
"""
Salad Cloud Transcription Monitoring Dashboard
Real-time monitoring and alerting for transcription services
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
import threading
import signal

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.transcription.salad_transcriber_enhanced import SaladTranscriberEnhanced
from src.config.settings import Settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TranscriptionMonitor:
    """
    Monitoring dashboard for Salad Cloud transcription service
    """

    def __init__(
        self,
        refresh_interval: int = 10,
        alert_thresholds: Optional[Dict] = None,
        log_dir: Optional[str] = None
    ):
        """
        Initialize monitoring dashboard

        Args:
            refresh_interval: Seconds between dashboard refreshes
            alert_thresholds: Alert threshold configuration
            log_dir: Directory for monitoring logs
        """
        self.settings = Settings()
        self.refresh_interval = refresh_interval
        self.running = False

        # Initialize transcriber for metrics access
        self.transcriber = SaladTranscriberEnhanced(
            api_key=self.settings.salad_api_key,
            organization_name=self.settings.salad_org_name,
            enable_monitoring=True
        )

        # Alert thresholds
        self.alert_thresholds = alert_thresholds or {
            'success_rate_min': 95.0,  # Alert if success rate drops below 95%
            'max_processing_seconds': 300,  # Alert if processing takes > 5 minutes
            'max_active_jobs': 50,  # Alert if too many concurrent jobs
            'error_rate_max': 5.0  # Alert if error rate exceeds 5%
        }

        # Monitoring logs
        self.log_dir = Path(log_dir or '/var/www/call-recording-system/logs/monitoring')
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Alert state
        self.alerts_triggered = {}
        self.alert_history = []

    def start(self):
        """Start monitoring dashboard"""
        self.running = True
        logger.info("Starting Salad Cloud Monitoring Dashboard")

        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Start monitoring loop
        try:
            while self.running:
                self._update_dashboard()
                time.sleep(self.refresh_interval)
        except KeyboardInterrupt:
            logger.info("Monitoring stopped by user")
        finally:
            self._cleanup()

    def stop(self):
        """Stop monitoring dashboard"""
        self.running = False

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.stop()

    def _update_dashboard(self):
        """Update and display monitoring dashboard"""
        try:
            # Clear screen (for terminal display)
            os.system('clear' if os.name == 'posix' else 'cls')

            # Get current metrics
            metrics = self.transcriber.get_metrics()
            health = self.transcriber.health_check()

            # Display header
            self._display_header()

            # Display health status
            self._display_health(health)

            # Display key metrics
            self._display_metrics(metrics)

            # Display active jobs
            self._display_active_jobs(metrics.get('active_jobs', []))

            # Display recent jobs
            self._display_recent_jobs(metrics.get('recent_jobs', []))

            # Check and display alerts
            self._check_alerts(metrics)

            # Log metrics
            self._log_metrics(metrics)

        except Exception as e:
            logger.error(f"Error updating dashboard: {e}")

    def _display_header(self):
        """Display dashboard header"""
        print("=" * 80)
        print("SALAD CLOUD TRANSCRIPTION MONITORING DASHBOARD".center(80))
        print("=" * 80)
        print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
        print(f"Organization: {self.settings.salad_org_name}")
        print(f"Engine: FULL (Best Practices)")
        print(f"Language: {self.settings.salad_language} (American English)")
        print("=" * 80)

    def _display_health(self, health: Dict[str, Any]):
        """Display health status"""
        print("\n📊 HEALTH STATUS")
        print("-" * 40)

        status = health.get('status', 'unknown')
        status_emoji = "✅" if status == 'healthy' else "⚠️" if status == 'degraded' else "❌"

        print(f"{status_emoji} Service Status: {status.upper()}")
        print(f"   API Status: {health.get('api_status', 'unknown')}")

        if 'error' in health:
            print(f"   ⚠️ Error: {health['error']}")

    def _display_metrics(self, metrics: Dict[str, Any]):
        """Display key performance metrics"""
        print("\n📈 KEY METRICS")
        print("-" * 40)

        # Success rate with color coding
        success_rate = metrics.get('success_rate', 0)
        success_emoji = "🟢" if success_rate >= 95 else "🟡" if success_rate >= 90 else "🔴"
        print(f"{success_emoji} Success Rate: {success_rate}%")

        # Job statistics
        print(f"📋 Total Jobs: {metrics.get('total_jobs', 0)}")
        print(f"   ✅ Successful: {metrics.get('successful_jobs', 0)}")
        print(f"   ❌ Failed: {metrics.get('failed_jobs', 0)}")
        print(f"   ⏱️ Timeout: {metrics.get('timeout_jobs', 0)}")
        print(f"   🔄 Active: {metrics.get('active_job_count', 0)}")

        # Processing statistics
        print(f"\n⏱️ PROCESSING STATISTICS")
        print(f"   Total Audio: {metrics.get('total_audio_hours', 0):.2f} hours")
        print(f"   Total Processing: {metrics.get('total_processing_hours', 0):.2f} hours")
        print(f"   Avg Processing Time: {metrics.get('average_processing_seconds', 0):.1f} seconds")
        print(f"   Words Transcribed: {metrics.get('total_words_transcribed', 0):,}")

        # Uptime
        uptime_seconds = metrics.get('uptime_seconds', 0)
        uptime_str = self._format_duration(uptime_seconds)
        print(f"\n🕐 Uptime: {uptime_str}")

    def _display_active_jobs(self, active_jobs: List[Dict]):
        """Display active jobs"""
        if not active_jobs:
            return

        print("\n🔄 ACTIVE JOBS")
        print("-" * 40)

        for job in active_jobs[:5]:  # Show max 5 active jobs
            status = job.get('status', 'unknown')
            started = job.get('started', 'N/A')
            url = job.get('url', 'N/A')

            # Truncate URL for display
            if len(url) > 50:
                url = url[:47] + "..."

            print(f"   • Status: {status} | Started: {started}")
            print(f"     URL: {url}")

    def _display_recent_jobs(self, recent_jobs: List[Dict]):
        """Display recent completed jobs"""
        if not recent_jobs:
            return

        print("\n📝 RECENT JOBS")
        print("-" * 40)

        for job in recent_jobs[:5]:  # Show max 5 recent jobs
            job_id = job.get('job_id', 'N/A')[:8]  # Truncate ID
            status = job.get('status', 'unknown')
            words = job.get('word_count', 0)
            confidence = job.get('confidence', 0) * 100
            processing_time = job.get('processing_time', 0)

            status_emoji = "✅" if status == 'succeeded' else "❌"
            print(f"   {status_emoji} {job_id}: {words} words | "
                  f"Confidence: {confidence:.1f}% | Time: {processing_time:.1f}s")

    def _check_alerts(self, metrics: Dict[str, Any]):
        """Check and display alerts based on thresholds"""
        alerts = []

        # Check success rate
        success_rate = metrics.get('success_rate', 100)
        if success_rate < self.alert_thresholds['success_rate_min']:
            alerts.append(f"⚠️ Success rate below threshold: {success_rate}% < {self.alert_thresholds['success_rate_min']}%")

        # Check active jobs
        active_count = metrics.get('active_job_count', 0)
        if active_count > self.alert_thresholds['max_active_jobs']:
            alerts.append(f"⚠️ Too many active jobs: {active_count} > {self.alert_thresholds['max_active_jobs']}")

        # Check average processing time
        avg_processing = metrics.get('average_processing_seconds', 0)
        if avg_processing > self.alert_thresholds['max_processing_seconds']:
            alerts.append(f"⚠️ High average processing time: {avg_processing:.1f}s > {self.alert_thresholds['max_processing_seconds']}s")

        # Check error rate
        total_jobs = metrics.get('total_jobs', 1)
        failed_jobs = metrics.get('failed_jobs', 0)
        error_rate = (failed_jobs / total_jobs * 100) if total_jobs > 0 else 0
        if error_rate > self.alert_thresholds['error_rate_max']:
            alerts.append(f"⚠️ High error rate: {error_rate:.1f}% > {self.alert_thresholds['error_rate_max']}%")

        # Display alerts
        if alerts:
            print("\n🚨 ALERTS")
            print("-" * 40)
            for alert in alerts:
                print(f"   {alert}")
                self._log_alert(alert)

        # Display API errors if any
        api_errors = metrics.get('api_errors', {})
        if api_errors:
            print("\n⚠️ API ERRORS")
            print("-" * 40)
            for error, count in list(api_errors.items())[:5]:  # Show top 5 errors
                print(f"   • {error}: {count} occurrences")

    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format"""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        parts.append(f"{secs}s")

        return " ".join(parts)

    def _log_metrics(self, metrics: Dict[str, Any]):
        """Log metrics to file for historical analysis"""
        try:
            timestamp = datetime.now(timezone.utc)
            log_file = self.log_dir / f"metrics_{timestamp.strftime('%Y%m%d')}.jsonl"

            # Add timestamp to metrics
            metrics['timestamp'] = timestamp.isoformat()

            # Append to log file
            with open(log_file, 'a') as f:
                f.write(json.dumps(metrics, default=str) + '\n')

        except Exception as e:
            logger.error(f"Failed to log metrics: {e}")

    def _log_alert(self, alert: str):
        """Log alert to file"""
        try:
            timestamp = datetime.now(timezone.utc)
            alert_file = self.log_dir / f"alerts_{timestamp.strftime('%Y%m%d')}.log"

            with open(alert_file, 'a') as f:
                f.write(f"{timestamp.isoformat()} - {alert}\n")

            # Add to alert history
            self.alert_history.append({
                'timestamp': timestamp.isoformat(),
                'alert': alert
            })

            # Keep only last 100 alerts in memory
            if len(self.alert_history) > 100:
                self.alert_history = self.alert_history[-100:]

        except Exception as e:
            logger.error(f"Failed to log alert: {e}")

    def _cleanup(self):
        """Cleanup on shutdown"""
        logger.info("Cleaning up monitoring dashboard...")

        # Save final metrics
        try:
            metrics = self.transcriber.get_metrics()
            metrics['shutdown_time'] = datetime.now(timezone.utc).isoformat()
            self._log_metrics(metrics)
        except Exception as e:
            logger.error(f"Error saving final metrics: {e}")

        logger.info("Monitoring dashboard stopped")

    def generate_report(self, period_hours: int = 24) -> Dict[str, Any]:
        """
        Generate monitoring report for specified period

        Args:
            period_hours: Number of hours to include in report

        Returns:
            Report dictionary
        """
        report = {
            'period_hours': period_hours,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'metrics': self.transcriber.get_metrics(),
            'health': self.transcriber.health_check(),
            'alerts': self.alert_history[-20:]  # Last 20 alerts
        }

        # Calculate period statistics from logs
        try:
            start_time = datetime.now(timezone.utc) - timedelta(hours=period_hours)
            period_stats = self._calculate_period_stats(start_time)
            report['period_statistics'] = period_stats
        except Exception as e:
            logger.error(f"Error calculating period statistics: {e}")

        return report

    def _calculate_period_stats(self, start_time: datetime) -> Dict[str, Any]:
        """Calculate statistics for a specific period from logs"""
        stats = {
            'total_jobs': 0,
            'successful_jobs': 0,
            'failed_jobs': 0,
            'total_words': 0,
            'total_audio_seconds': 0
        }

        # Read metrics logs for the period
        for log_file in self.log_dir.glob("metrics_*.jsonl"):
            try:
                with open(log_file, 'r') as f:
                    for line in f:
                        try:
                            metric = json.loads(line)
                            metric_time = datetime.fromisoformat(metric.get('timestamp', ''))

                            if metric_time >= start_time:
                                # Aggregate statistics
                                stats['total_jobs'] = max(stats['total_jobs'],
                                                         metric.get('total_jobs', 0))
                                stats['successful_jobs'] = max(stats['successful_jobs'],
                                                              metric.get('successful_jobs', 0))
                                stats['failed_jobs'] = max(stats['failed_jobs'],
                                                          metric.get('failed_jobs', 0))
                                stats['total_words'] = max(stats['total_words'],
                                                          metric.get('total_words_transcribed', 0))
                                stats['total_audio_seconds'] = max(stats['total_audio_seconds'],
                                                                   metric.get('total_audio_seconds', 0))
                        except Exception:
                            continue
            except Exception:
                continue

        return stats


def main():
    """Main entry point for monitoring dashboard"""
    # Parse command line arguments
    import argparse

    parser = argparse.ArgumentParser(description='Salad Cloud Transcription Monitoring Dashboard')
    parser.add_argument(
        '--refresh',
        type=int,
        default=10,
        help='Refresh interval in seconds (default: 10)'
    )
    parser.add_argument(
        '--report',
        action='store_true',
        help='Generate report instead of running dashboard'
    )
    parser.add_argument(
        '--period',
        type=int,
        default=24,
        help='Report period in hours (default: 24)'
    )
    parser.add_argument(
        '--log-dir',
        type=str,
        help='Directory for monitoring logs'
    )

    args = parser.parse_args()

    # Initialize monitor
    monitor = TranscriptionMonitor(
        refresh_interval=args.refresh,
        log_dir=args.log_dir
    )

    if args.report:
        # Generate and print report
        report = monitor.generate_report(period_hours=args.period)
        print(json.dumps(report, indent=2, default=str))
    else:
        # Start monitoring dashboard
        monitor.start()


if __name__ == "__main__":
    main()