"""
Metrics collection and reporting system
"""

import os
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict, deque
import json
import threading
from prometheus_client import (
    Counter, Gauge, Histogram, Summary,
    generate_latest, CONTENT_TYPE_LATEST
)

logger = logging.getLogger(__name__)


class MetricType:
    """Metric types"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


class Metric:
    """Base metric class"""

    def __init__(self, name: str, description: str, metric_type: str):
        self.name = name
        self.description = description
        self.metric_type = metric_type
        self.values = deque(maxlen=1000)
        self.timestamp = datetime.utcnow()

    def record(self, value: float, labels: Optional[Dict[str, str]] = None):
        """Record a metric value"""
        self.values.append({
            'value': value,
            'labels': labels or {},
            'timestamp': datetime.utcnow()
        })

    def get_latest(self) -> Optional[float]:
        """Get latest value"""
        if self.values:
            return self.values[-1]['value']
        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for metric"""
        if not self.values:
            return {}

        values_only = [v['value'] for v in self.values]

        return {
            'count': len(values_only),
            'latest': values_only[-1],
            'min': min(values_only),
            'max': max(values_only),
            'avg': sum(values_only) / len(values_only),
            'sum': sum(values_only)
        }


class MetricsCollector:
    """
    Collects and manages system metrics
    """

    def __init__(self, prometheus_enabled: bool = True):
        """
        Initialize metrics collector

        Args:
            prometheus_enabled: Enable Prometheus metrics
        """
        self.prometheus_enabled = prometheus_enabled
        self.custom_metrics = {}
        self.metric_lock = threading.Lock()

        # Initialize Prometheus metrics if enabled
        if prometheus_enabled:
            self._init_prometheus_metrics()

        # Performance tracking
        self.operation_timings = defaultdict(list)
        self.operation_counts = defaultdict(int)

        logger.info("MetricsCollector initialized")

    def _init_prometheus_metrics(self):
        """Initialize Prometheus metrics"""
        # Counters
        self.prom_recordings_processed = Counter(
            'recordings_processed_total',
            'Total number of recordings processed'
        )
        self.prom_transcriptions_completed = Counter(
            'transcriptions_completed_total',
            'Total number of transcriptions completed'
        )
        self.prom_uploads_completed = Counter(
            'uploads_completed_total',
            'Total number of uploads completed'
        )
        self.prom_errors_total = Counter(
            'errors_total',
            'Total number of errors',
            ['component', 'severity']
        )

        # Gauges
        self.prom_queue_size = Gauge(
            'processing_queue_size',
            'Current processing queue size'
        )
        self.prom_active_workers = Gauge(
            'active_workers',
            'Number of active worker threads'
        )
        self.prom_memory_usage = Gauge(
            'memory_usage_bytes',
            'Current memory usage in bytes'
        )
        self.prom_disk_usage = Gauge(
            'disk_usage_percent',
            'Current disk usage percentage'
        )

        # Histograms
        self.prom_processing_duration = Histogram(
            'processing_duration_seconds',
            'Recording processing duration',
            buckets=(1, 5, 10, 30, 60, 120, 300, 600)
        )
        self.prom_transcription_duration = Histogram(
            'transcription_duration_seconds',
            'Transcription duration',
            buckets=(0.5, 1, 2, 5, 10, 30, 60)
        )
        self.prom_upload_duration = Histogram(
            'upload_duration_seconds',
            'Upload duration',
            buckets=(0.5, 1, 2, 5, 10, 30)
        )

        # Summaries
        self.prom_api_latency = Summary(
            'api_latency_seconds',
            'API request latency'
        )
        self.prom_confidence_score = Summary(
            'transcription_confidence',
            'Transcription confidence scores'
        )

    def record_counter(
        self,
        name: str,
        value: float = 1,
        description: str = "",
        labels: Optional[Dict[str, str]] = None
    ):
        """
        Record counter metric

        Args:
            name: Metric name
            value: Increment value
            description: Metric description
            labels: Metric labels
        """
        with self.metric_lock:
            if name not in self.custom_metrics:
                self.custom_metrics[name] = Metric(name, description, MetricType.COUNTER)

            self.custom_metrics[name].record(value, labels)

        # Update Prometheus if applicable
        if self.prometheus_enabled:
            self._update_prometheus_counter(name, value, labels)

    def record_gauge(
        self,
        name: str,
        value: float,
        description: str = "",
        labels: Optional[Dict[str, str]] = None
    ):
        """
        Record gauge metric

        Args:
            name: Metric name
            value: Gauge value
            description: Metric description
            labels: Metric labels
        """
        with self.metric_lock:
            if name not in self.custom_metrics:
                self.custom_metrics[name] = Metric(name, description, MetricType.GAUGE)

            self.custom_metrics[name].record(value, labels)

        # Update Prometheus if applicable
        if self.prometheus_enabled:
            self._update_prometheus_gauge(name, value, labels)

    def record_histogram(
        self,
        name: str,
        value: float,
        description: str = "",
        labels: Optional[Dict[str, str]] = None
    ):
        """
        Record histogram metric

        Args:
            name: Metric name
            value: Observation value
            description: Metric description
            labels: Metric labels
        """
        with self.metric_lock:
            if name not in self.custom_metrics:
                self.custom_metrics[name] = Metric(name, description, MetricType.HISTOGRAM)

            self.custom_metrics[name].record(value, labels)

        # Update Prometheus if applicable
        if self.prometheus_enabled:
            self._update_prometheus_histogram(name, value, labels)

    def record_operation_timing(
        self,
        operation: str,
        duration: float,
        success: bool = True
    ):
        """
        Record operation timing

        Args:
            operation: Operation name
            duration: Duration in seconds
            success: Whether operation succeeded
        """
        self.operation_timings[operation].append({
            'duration': duration,
            'success': success,
            'timestamp': datetime.utcnow()
        })

        self.operation_counts[operation] += 1

        # Keep only recent timings
        if len(self.operation_timings[operation]) > 1000:
            self.operation_timings[operation] = self.operation_timings[operation][-1000:]

    def time_operation(self, operation: str):
        """
        Context manager for timing operations

        Args:
            operation: Operation name

        Usage:
            with metrics.time_operation('transcription'):
                # Do transcription
        """
        class OperationTimer:
            def __init__(self, collector, op_name):
                self.collector = collector
                self.op_name = op_name
                self.start_time = None

            def __enter__(self):
                self.start_time = time.time()
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                duration = time.time() - self.start_time
                success = exc_type is None
                self.collector.record_operation_timing(self.op_name, duration, success)

        return OperationTimer(self, operation)

    def _update_prometheus_counter(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]]
    ):
        """Update Prometheus counter"""
        if name == 'recordings_processed':
            self.prom_recordings_processed.inc(value)
        elif name == 'transcriptions_completed':
            self.prom_transcriptions_completed.inc(value)
        elif name == 'uploads_completed':
            self.prom_uploads_completed.inc(value)
        elif name == 'errors':
            if labels:
                self.prom_errors_total.labels(**labels).inc(value)

    def _update_prometheus_gauge(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]]
    ):
        """Update Prometheus gauge"""
        if name == 'queue_size':
            self.prom_queue_size.set(value)
        elif name == 'active_workers':
            self.prom_active_workers.set(value)
        elif name == 'memory_usage':
            self.prom_memory_usage.set(value)
        elif name == 'disk_usage':
            self.prom_disk_usage.set(value)

    def _update_prometheus_histogram(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]]
    ):
        """Update Prometheus histogram"""
        if name == 'processing_duration':
            self.prom_processing_duration.observe(value)
        elif name == 'transcription_duration':
            self.prom_transcription_duration.observe(value)
        elif name == 'upload_duration':
            self.prom_upload_duration.observe(value)
        elif name == 'api_latency':
            self.prom_api_latency.observe(value)
        elif name == 'confidence_score':
            self.prom_confidence_score.observe(value)

    def get_metrics_summary(self) -> Dict[str, Any]:
        """
        Get summary of all metrics

        Returns:
            Dictionary with metrics summary
        """
        summary = {
            'custom_metrics': {},
            'operation_timings': {},
            'operation_counts': dict(self.operation_counts)
        }

        # Custom metrics
        with self.metric_lock:
            for name, metric in self.custom_metrics.items():
                summary['custom_metrics'][name] = {
                    'type': metric.metric_type,
                    'stats': metric.get_stats()
                }

        # Operation timings
        for operation, timings in self.operation_timings.items():
            if timings:
                durations = [t['duration'] for t in timings]
                success_count = sum(1 for t in timings if t['success'])

                summary['operation_timings'][operation] = {
                    'count': len(timings),
                    'success_rate': success_count / len(timings),
                    'avg_duration': sum(durations) / len(durations),
                    'min_duration': min(durations),
                    'max_duration': max(durations)
                }

        return summary

    def get_prometheus_metrics(self) -> bytes:
        """
        Get Prometheus metrics in text format

        Returns:
            Prometheus metrics as bytes
        """
        if not self.prometheus_enabled:
            return b""

        return generate_latest()

    def export_metrics(self, output_path: str):
        """
        Export metrics to file

        Args:
            output_path: Path to save metrics
        """
        metrics_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'summary': self.get_metrics_summary()
        }

        with open(output_path, 'w') as f:
            json.dump(metrics_data, f, indent=2)

        logger.info(f"Metrics exported to {output_path}")

    def reset_metrics(self):
        """Reset all metrics"""
        with self.metric_lock:
            self.custom_metrics.clear()

        self.operation_timings.clear()
        self.operation_counts.clear()

        logger.info("Metrics reset")

    def record_system_metrics(self):
        """Record current system metrics"""
        try:
            import psutil

            # Memory usage
            memory = psutil.virtual_memory()
            self.record_gauge('memory_usage', memory.used, "Memory usage in bytes")
            self.record_gauge('memory_percent', memory.percent, "Memory usage percentage")

            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            self.record_gauge('cpu_percent', cpu_percent, "CPU usage percentage")

            # Disk usage
            disk = psutil.disk_usage('/')
            self.record_gauge('disk_usage', disk.percent, "Disk usage percentage")
            self.record_gauge('disk_free_gb', disk.free / (1024**3), "Free disk space in GB")

            # Network I/O
            net_io = psutil.net_io_counters()
            self.record_counter('network_bytes_sent', net_io.bytes_sent, "Network bytes sent")
            self.record_counter('network_bytes_recv', net_io.bytes_recv, "Network bytes received")

        except ImportError:
            logger.warning("psutil not available, skipping system metrics")
        except Exception as e:
            logger.error(f"Failed to record system metrics: {e}")