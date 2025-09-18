"""
Health check system for monitoring service status
"""

import os
import logging
import psutil
import time
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timedelta
from enum import Enum
import json
import subprocess

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"


class ComponentHealth:
    """Health status of a single component"""

    def __init__(
        self,
        name: str,
        status: HealthStatus,
        message: str = "",
        details: Optional[Dict[str, Any]] = None
    ):
        self.name = name
        self.status = status
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'name': self.name,
            'status': self.status.value,
            'message': self.message,
            'details': self.details,
            'timestamp': self.timestamp.isoformat()
        }


class HealthChecker:
    """
    System health checker with multiple component monitoring
    """

    # Thresholds for system resources
    THRESHOLDS = {
        'cpu_percent': 80.0,
        'memory_percent': 85.0,
        'disk_percent': 90.0,
        'disk_io_read_mb': 100.0,
        'disk_io_write_mb': 100.0,
        'network_errors': 100,
        'process_count': 500
    }

    def __init__(self, check_interval: int = 60):
        """
        Initialize health checker

        Args:
            check_interval: Interval between checks in seconds
        """
        self.check_interval = check_interval
        self.last_check_time = None
        self.check_history = []
        self.max_history_size = 100
        self.component_checks = {}
        self.alert_callbacks = []

        # Register default checks
        self._register_default_checks()

        logger.info("HealthChecker initialized")

    def _register_default_checks(self):
        """Register default health checks"""
        self.register_check('system', self._check_system_resources)
        self.register_check('database', self._check_database)
        self.register_check('disk_space', self._check_disk_space)
        self.register_check('network', self._check_network)
        self.register_check('services', self._check_services)

    def register_check(
        self,
        name: str,
        check_func: Callable[[], ComponentHealth]
    ):
        """
        Register a health check

        Args:
            name: Check name
            check_func: Function that returns ComponentHealth
        """
        self.component_checks[name] = check_func
        logger.debug(f"Registered health check: {name}")

    def add_alert_callback(
        self,
        callback: Callable[[Dict[str, Any]], None]
    ):
        """
        Add alert callback for unhealthy status

        Args:
            callback: Function called when unhealthy status detected
        """
        self.alert_callbacks.append(callback)

    def check_health(self) -> Dict[str, Any]:
        """
        Perform complete health check

        Returns:
            Dictionary with health status
        """
        start_time = time.time()
        components = {}
        overall_status = HealthStatus.HEALTHY

        # Check each component
        for name, check_func in self.component_checks.items():
            try:
                component_health = check_func()
                components[name] = component_health

                # Update overall status
                if component_health.status == HealthStatus.CRITICAL:
                    overall_status = HealthStatus.CRITICAL
                elif component_health.status == HealthStatus.UNHEALTHY and overall_status != HealthStatus.CRITICAL:
                    overall_status = HealthStatus.UNHEALTHY
                elif component_health.status == HealthStatus.DEGRADED and overall_status == HealthStatus.HEALTHY:
                    overall_status = HealthStatus.DEGRADED

            except Exception as e:
                logger.error(f"Health check failed for {name}: {e}")
                components[name] = ComponentHealth(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check failed: {e}"
                )
                if overall_status != HealthStatus.CRITICAL:
                    overall_status = HealthStatus.UNHEALTHY

        check_duration = time.time() - start_time

        # Create health report
        health_report = {
            'status': overall_status.value,
            'timestamp': datetime.utcnow().isoformat(),
            'check_duration_seconds': check_duration,
            'components': {name: comp.to_dict() for name, comp in components.items()}
        }

        # Update history
        self._update_history(health_report)

        # Trigger alerts if unhealthy
        if overall_status in [HealthStatus.UNHEALTHY, HealthStatus.CRITICAL]:
            self._trigger_alerts(health_report)

        self.last_check_time = datetime.utcnow()

        return health_report

    def _check_system_resources(self) -> ComponentHealth:
        """
        Check system resources (CPU, memory, etc.)

        Returns:
            ComponentHealth object
        """
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk_io = psutil.disk_io_counters()

            details = {
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_available_gb': memory.available / (1024**3),
                'disk_read_mb': disk_io.read_bytes / (1024**2) if disk_io else 0,
                'disk_write_mb': disk_io.write_bytes / (1024**2) if disk_io else 0,
                'process_count': len(psutil.pids())
            }

            # Determine status
            if cpu_percent > self.THRESHOLDS['cpu_percent']:
                status = HealthStatus.UNHEALTHY
                message = f"High CPU usage: {cpu_percent:.1f}%"
            elif memory.percent > self.THRESHOLDS['memory_percent']:
                status = HealthStatus.UNHEALTHY
                message = f"High memory usage: {memory.percent:.1f}%"
            elif cpu_percent > self.THRESHOLDS['cpu_percent'] * 0.8:
                status = HealthStatus.DEGRADED
                message = "System resources elevated"
            else:
                status = HealthStatus.HEALTHY
                message = "System resources normal"

            return ComponentHealth(
                name='system',
                status=status,
                message=message,
                details=details
            )

        except Exception as e:
            return ComponentHealth(
                name='system',
                status=HealthStatus.UNHEALTHY,
                message=f"Failed to check system resources: {e}"
            )

    def _check_database(self) -> ComponentHealth:
        """
        Check database connectivity and health

        Returns:
            ComponentHealth object
        """
        try:
            from src.database.utils import DatabaseUtils

            db_health = DatabaseUtils.check_database_health()

            if db_health['status'] == 'healthy':
                status = HealthStatus.HEALTHY
                message = "Database connected"
            else:
                status = HealthStatus.UNHEALTHY
                message = f"Database error: {db_health.get('error', 'Unknown')}"

            return ComponentHealth(
                name='database',
                status=status,
                message=message,
                details=db_health
            )

        except ImportError:
            return ComponentHealth(
                name='database',
                status=HealthStatus.DEGRADED,
                message="Database check not available"
            )
        except Exception as e:
            return ComponentHealth(
                name='database',
                status=HealthStatus.UNHEALTHY,
                message=f"Database check failed: {e}"
            )

    def _check_disk_space(self) -> ComponentHealth:
        """
        Check disk space availability

        Returns:
            ComponentHealth object
        """
        try:
            disk_usage = psutil.disk_usage('/')

            details = {
                'total_gb': disk_usage.total / (1024**3),
                'used_gb': disk_usage.used / (1024**3),
                'free_gb': disk_usage.free / (1024**3),
                'percent_used': disk_usage.percent
            }

            if disk_usage.percent > self.THRESHOLDS['disk_percent']:
                status = HealthStatus.CRITICAL
                message = f"Critical: Disk usage {disk_usage.percent:.1f}%"
            elif disk_usage.percent > self.THRESHOLDS['disk_percent'] * 0.9:
                status = HealthStatus.UNHEALTHY
                message = f"High disk usage: {disk_usage.percent:.1f}%"
            elif disk_usage.percent > self.THRESHOLDS['disk_percent'] * 0.8:
                status = HealthStatus.DEGRADED
                message = f"Disk usage elevated: {disk_usage.percent:.1f}%"
            else:
                status = HealthStatus.HEALTHY
                message = f"Disk usage normal: {disk_usage.percent:.1f}%"

            return ComponentHealth(
                name='disk_space',
                status=status,
                message=message,
                details=details
            )

        except Exception as e:
            return ComponentHealth(
                name='disk_space',
                status=HealthStatus.UNHEALTHY,
                message=f"Failed to check disk space: {e}"
            )

    def _check_network(self) -> ComponentHealth:
        """
        Check network connectivity

        Returns:
            ComponentHealth object
        """
        try:
            net_io = psutil.net_io_counters()

            details = {
                'bytes_sent_mb': net_io.bytes_sent / (1024**2),
                'bytes_recv_mb': net_io.bytes_recv / (1024**2),
                'packets_sent': net_io.packets_sent,
                'packets_recv': net_io.packets_recv,
                'errors_in': net_io.errin,
                'errors_out': net_io.errout,
                'drop_in': net_io.dropin,
                'drop_out': net_io.dropout
            }

            total_errors = net_io.errin + net_io.errout

            if total_errors > self.THRESHOLDS['network_errors']:
                status = HealthStatus.DEGRADED
                message = f"Network errors detected: {total_errors}"
            else:
                status = HealthStatus.HEALTHY
                message = "Network connectivity normal"

            return ComponentHealth(
                name='network',
                status=status,
                message=message,
                details=details
            )

        except Exception as e:
            return ComponentHealth(
                name='network',
                status=HealthStatus.UNHEALTHY,
                message=f"Failed to check network: {e}"
            )

    def _check_services(self) -> ComponentHealth:
        """
        Check critical services status

        Returns:
            ComponentHealth object
        """
        services_to_check = ['postgresql', 'nginx']  # Add services as needed
        service_status = {}

        for service in services_to_check:
            try:
                # Check if service is running (Linux systemd)
                result = subprocess.run(
                    ['systemctl', 'is-active', service],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                service_status[service] = result.stdout.strip() == 'active'
            except Exception:
                # Try alternative check or skip
                service_status[service] = None

        # Determine overall status
        failed_services = [
            svc for svc, status in service_status.items()
            if status is False
        ]

        if failed_services:
            status = HealthStatus.UNHEALTHY
            message = f"Services down: {', '.join(failed_services)}"
        else:
            status = HealthStatus.HEALTHY
            message = "All services running"

        return ComponentHealth(
            name='services',
            status=status,
            message=message,
            details={'services': service_status}
        )

    def _update_history(self, health_report: Dict[str, Any]):
        """
        Update health check history

        Args:
            health_report: Health report to add
        """
        self.check_history.append(health_report)

        # Limit history size
        if len(self.check_history) > self.max_history_size:
            self.check_history = self.check_history[-self.max_history_size:]

    def _trigger_alerts(self, health_report: Dict[str, Any]):
        """
        Trigger alert callbacks

        Args:
            health_report: Health report that triggered alert
        """
        for callback in self.alert_callbacks:
            try:
                callback(health_report)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")

    def get_uptime(self) -> float:
        """
        Calculate system uptime percentage from history

        Returns:
            Uptime percentage
        """
        if not self.check_history:
            return 100.0

        healthy_checks = sum(
            1 for check in self.check_history
            if check['status'] in ['healthy', 'degraded']
        )

        return (healthy_checks / len(self.check_history)) * 100

    def get_summary(self) -> Dict[str, Any]:
        """
        Get health check summary

        Returns:
            Summary dictionary
        """
        current_health = self.check_health()

        return {
            'current_status': current_health['status'],
            'uptime_percentage': self.get_uptime(),
            'last_check': self.last_check_time.isoformat() if self.last_check_time else None,
            'check_interval_seconds': self.check_interval,
            'history_size': len(self.check_history),
            'components': current_health['components']
        }

    def save_health_report(self, output_path: str):
        """
        Save health report to file

        Args:
            output_path: Path to save report
        """
        report = {
            'generated_at': datetime.utcnow().isoformat(),
            'summary': self.get_summary(),
            'history': self.check_history[-20:]  # Last 20 checks
        }

        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)

        logger.info(f"Health report saved to {output_path}")