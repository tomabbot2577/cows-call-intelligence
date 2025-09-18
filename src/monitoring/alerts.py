"""
Alerting system for email and Slack notifications
"""

import os
import logging
import json
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class AlertChannel(Enum):
    """Alert channels"""
    EMAIL = "email"
    SLACK = "slack"
    WEBHOOK = "webhook"
    LOG = "log"


class AlertPriority(Enum):
    """Alert priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Alert:
    """Represents an alert"""

    def __init__(
        self,
        title: str,
        message: str,
        priority: AlertPriority = AlertPriority.MEDIUM,
        component: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        channels: Optional[List[AlertChannel]] = None
    ):
        self.title = title
        self.message = message
        self.priority = priority
        self.component = component or "system"
        self.details = details or {}
        self.channels = channels or [AlertChannel.LOG]
        self.timestamp = datetime.utcnow()
        self.sent = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'title': self.title,
            'message': self.message,
            'priority': self.priority.value,
            'component': self.component,
            'details': self.details,
            'channels': [ch.value for ch in self.channels],
            'timestamp': self.timestamp.isoformat(),
            'sent': self.sent
        }


class EmailAlerter:
    """Email alert sender"""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        sender_email: str,
        sender_password: str,
        recipients: List[str],
        use_tls: bool = True
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.recipients = recipients
        self.use_tls = use_tls

    def send(self, alert: Alert) -> bool:
        """
        Send email alert

        Args:
            alert: Alert to send

        Returns:
            True if sent successfully
        """
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"[{alert.priority.value.upper()}] {alert.title}"
            msg['From'] = self.sender_email
            msg['To'] = ', '.join(self.recipients)

            # Create HTML content
            html_body = self._create_html_body(alert)
            html_part = MIMEText(html_body, 'html')
            msg.attach(html_part)

            # Create plain text content
            text_body = self._create_text_body(alert)
            text_part = MIMEText(text_body, 'plain')
            msg.attach(text_part)

            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()

                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)

            logger.info(f"Email alert sent: {alert.title}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email alert: {e}")
            return False

    def _create_html_body(self, alert: Alert) -> str:
        """Create HTML email body"""
        priority_color = {
            AlertPriority.LOW: '#28a745',
            AlertPriority.MEDIUM: '#ffc107',
            AlertPriority.HIGH: '#fd7e14',
            AlertPriority.CRITICAL: '#dc3545'
        }

        html = f"""
        <html>
            <body style="font-family: Arial, sans-serif;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: {priority_color[alert.priority]};">
                        {alert.title}
                    </h2>
                    <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px;">
                        <p><strong>Priority:</strong> {alert.priority.value.upper()}</p>
                        <p><strong>Component:</strong> {alert.component}</p>
                        <p><strong>Time:</strong> {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
                    </div>
                    <div style="margin-top: 20px;">
                        <h3>Message:</h3>
                        <p>{alert.message}</p>
                    </div>
        """

        if alert.details:
            html += """
                    <div style="margin-top: 20px;">
                        <h3>Details:</h3>
                        <pre style="background-color: #f8f9fa; padding: 10px; border-radius: 5px;">
            """
            html += json.dumps(alert.details, indent=2)
            html += """
                        </pre>
                    </div>
            """

        html += """
                </div>
            </body>
        </html>
        """

        return html

    def _create_text_body(self, alert: Alert) -> str:
        """Create plain text email body"""
        text = f"""
{alert.title}
{'=' * len(alert.title)}

Priority: {alert.priority.value.upper()}
Component: {alert.component}
Time: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}

Message:
{alert.message}
        """

        if alert.details:
            text += f"\n\nDetails:\n{json.dumps(alert.details, indent=2)}"

        return text


class SlackAlerter:
    """Slack alert sender"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, alert: Alert) -> bool:
        """
        Send Slack alert

        Args:
            alert: Alert to send

        Returns:
            True if sent successfully
        """
        try:
            # Create Slack message
            slack_message = self._create_slack_message(alert)

            # Send to Slack
            response = requests.post(
                self.webhook_url,
                json=slack_message,
                timeout=10
            )

            if response.status_code == 200:
                logger.info(f"Slack alert sent: {alert.title}")
                return True
            else:
                logger.error(f"Slack API error: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")
            return False

    def _create_slack_message(self, alert: Alert) -> Dict[str, Any]:
        """Create Slack message payload"""
        # Priority to color mapping
        priority_color = {
            AlertPriority.LOW: '#28a745',
            AlertPriority.MEDIUM: '#ffc107',
            AlertPriority.HIGH: '#fd7e14',
            AlertPriority.CRITICAL: '#dc3545'
        }

        # Priority to emoji mapping
        priority_emoji = {
            AlertPriority.LOW: ':information_source:',
            AlertPriority.MEDIUM: ':warning:',
            AlertPriority.HIGH: ':exclamation:',
            AlertPriority.CRITICAL: ':rotating_light:'
        }

        attachments = [
            {
                'color': priority_color[alert.priority],
                'title': f"{priority_emoji[alert.priority]} {alert.title}",
                'text': alert.message,
                'fields': [
                    {
                        'title': 'Priority',
                        'value': alert.priority.value.upper(),
                        'short': True
                    },
                    {
                        'title': 'Component',
                        'value': alert.component,
                        'short': True
                    },
                    {
                        'title': 'Time',
                        'value': alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC'),
                        'short': False
                    }
                ],
                'footer': 'Call Recording System',
                'ts': int(alert.timestamp.timestamp())
            }
        ]

        # Add details if present
        if alert.details:
            attachments[0]['fields'].append({
                'title': 'Details',
                'value': f"```{json.dumps(alert.details, indent=2)}```",
                'short': False
            })

        return {'attachments': attachments}


class AlertManager:
    """
    Manages alert sending across multiple channels
    """

    def __init__(self):
        """Initialize alert manager"""
        self.channels = {}
        self.alert_history = []
        self.max_history_size = 1000
        self.alert_rules = []

        # Initialize from environment variables
        self._initialize_from_env()

        logger.info("AlertManager initialized")

    def _initialize_from_env(self):
        """Initialize alerters from environment variables"""
        # Email configuration
        if os.getenv('SMTP_HOST'):
            try:
                email_alerter = EmailAlerter(
                    smtp_host=os.getenv('SMTP_HOST'),
                    smtp_port=int(os.getenv('SMTP_PORT', 587)),
                    sender_email=os.getenv('SMTP_USER'),
                    sender_password=os.getenv('SMTP_PASSWORD'),
                    recipients=os.getenv('ALERT_EMAIL', '').split(','),
                    use_tls=os.getenv('SMTP_TLS', 'true').lower() == 'true'
                )
                self.register_channel(AlertChannel.EMAIL, email_alerter)
                logger.info("Email alerting configured")
            except Exception as e:
                logger.warning(f"Failed to configure email alerting: {e}")

        # Slack configuration
        if os.getenv('SLACK_WEBHOOK'):
            slack_alerter = SlackAlerter(os.getenv('SLACK_WEBHOOK'))
            self.register_channel(AlertChannel.SLACK, slack_alerter)
            logger.info("Slack alerting configured")

    def register_channel(
        self,
        channel: AlertChannel,
        alerter: Any
    ):
        """
        Register alert channel

        Args:
            channel: Channel type
            alerter: Alerter instance
        """
        self.channels[channel] = alerter
        logger.info(f"Registered alert channel: {channel.value}")

    def send_alert(self, alert: Alert) -> bool:
        """
        Send alert through configured channels

        Args:
            alert: Alert to send

        Returns:
            True if sent successfully through at least one channel
        """
        success = False

        for channel in alert.channels:
            if channel == AlertChannel.LOG:
                # Always log alerts
                self._log_alert(alert)
                success = True

            elif channel in self.channels:
                try:
                    if self.channels[channel].send(alert):
                        success = True
                        alert.sent = True
                except Exception as e:
                    logger.error(f"Failed to send alert via {channel.value}: {e}")

        # Add to history
        self._add_to_history(alert)

        return success

    def send_error_alert(
        self,
        error: Exception,
        component: str = "unknown",
        operation: str = "unknown"
    ):
        """
        Send alert for an error

        Args:
            error: Exception that occurred
            component: Component where error occurred
            operation: Operation being performed
        """
        alert = Alert(
            title=f"Error in {component}",
            message=f"Error during {operation}: {str(error)}",
            priority=AlertPriority.HIGH,
            component=component,
            details={
                'error_type': type(error).__name__,
                'operation': operation
            },
            channels=[AlertChannel.LOG, AlertChannel.SLACK]
        )

        self.send_alert(alert)

    def send_health_alert(
        self,
        health_report: Dict[str, Any]
    ):
        """
        Send alert for health check failure

        Args:
            health_report: Health check report
        """
        if health_report['status'] == 'critical':
            priority = AlertPriority.CRITICAL
        elif health_report['status'] == 'unhealthy':
            priority = AlertPriority.HIGH
        else:
            priority = AlertPriority.MEDIUM

        # Find unhealthy components
        unhealthy_components = [
            name for name, comp in health_report.get('components', {}).items()
            if comp.get('status') in ['unhealthy', 'critical']
        ]

        alert = Alert(
            title=f"System Health Alert: {health_report['status'].upper()}",
            message=f"Health check failed. Unhealthy components: {', '.join(unhealthy_components)}",
            priority=priority,
            component="health_checker",
            details=health_report,
            channels=[AlertChannel.LOG, AlertChannel.EMAIL, AlertChannel.SLACK]
        )

        self.send_alert(alert)

    def _log_alert(self, alert: Alert):
        """
        Log alert

        Args:
            alert: Alert to log
        """
        log_message = f"ALERT [{alert.priority.value.upper()}] {alert.title}: {alert.message}"

        if alert.priority == AlertPriority.CRITICAL:
            logger.critical(log_message)
        elif alert.priority == AlertPriority.HIGH:
            logger.error(log_message)
        elif alert.priority == AlertPriority.MEDIUM:
            logger.warning(log_message)
        else:
            logger.info(log_message)

    def _add_to_history(self, alert: Alert):
        """
        Add alert to history

        Args:
            alert: Alert to add
        """
        self.alert_history.append(alert)

        # Limit history size
        if len(self.alert_history) > self.max_history_size:
            self.alert_history = self.alert_history[-self.max_history_size:]

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get alert statistics

        Returns:
            Statistics dictionary
        """
        stats = {
            'total_alerts': len(self.alert_history),
            'by_priority': {},
            'by_channel': {},
            'by_component': {},
            'recent_alerts': []
        }

        for alert in self.alert_history:
            # Count by priority
            priority = alert.priority.value
            stats['by_priority'][priority] = stats['by_priority'].get(priority, 0) + 1

            # Count by channel
            for channel in alert.channels:
                ch_name = channel.value
                stats['by_channel'][ch_name] = stats['by_channel'].get(ch_name, 0) + 1

            # Count by component
            component = alert.component
            stats['by_component'][component] = stats['by_component'].get(component, 0) + 1

        # Recent alerts
        stats['recent_alerts'] = [
            alert.to_dict() for alert in self.alert_history[-10:]
        ]

        return stats