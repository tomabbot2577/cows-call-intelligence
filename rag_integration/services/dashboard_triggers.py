"""
Dashboard Email Trigger Service

Handles creation, evaluation, and notification for dashboard metric triggers.
"""

import os
import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
import json

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


class DashboardTriggerService:
    """Service for managing and evaluating dashboard email triggers."""

    def __init__(self):
        self.db_url = os.getenv(
            'RAG_DATABASE_URL',
            os.getenv('DATABASE_URL', '')
        )
        # Email configuration
        self.smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.smtp_user = os.getenv('SMTP_USER', '')
        self.smtp_password = os.getenv('GMAIL_APP_PASSWORD', os.getenv('SMTP_PASSWORD', ''))
        if self.smtp_password:
            self.smtp_password = self.smtp_password.replace(' ', '')
        self.default_from = self.smtp_user
        self.default_to = os.getenv('ALERT_EMAIL_TO', 'sabbey@mainsequence.net')

    def _get_connection(self):
        """Get a database connection."""
        return psycopg2.connect(self.db_url)

    # =========================================
    # CRUD Operations
    # =========================================

    def create_trigger(self, config: dict, created_by: str = None) -> int:
        """
        Create a new trigger.

        Args:
            config: Trigger configuration with keys:
                - name: Trigger name
                - description: Optional description
                - trigger_type: 'threshold_alert', 'below_expectations', etc.
                - applies_to: 'all_users' or 'specific_users'
                - target_employees: List of employee names (if specific_users)
                - conditions: List of condition dicts
                - condition_logic: 'AND' or 'OR'
                - frequency: 'realtime', 'hourly', 'daily', 'weekly'
                - schedule_time: Time for daily/weekly triggers
                - schedule_day: Day (0-6) for weekly triggers
                - notify_admin, notify_user, notify_all_admins: booleans
                - custom_emails: List of additional email addresses
                - cooldown_minutes: Minimum time between triggers
                - email_subject_template, email_body_template: Custom templates
            created_by: Username of creator

        Returns:
            The new trigger ID
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO dashboard_email_triggers (
                        name, description, trigger_type, applies_to,
                        target_employees, conditions, condition_logic,
                        frequency, schedule_time, schedule_day,
                        notify_admin, notify_user, notify_all_admins,
                        custom_emails, cooldown_minutes,
                        email_subject_template, email_body_template,
                        created_by, is_active
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, TRUE
                    ) RETURNING id
                """, (
                    config.get('name'),
                    config.get('description'),
                    config.get('trigger_type', 'threshold_alert'),
                    config.get('applies_to', 'all_users'),
                    config.get('target_employees'),
                    json.dumps(config.get('conditions', {})),
                    config.get('condition_logic', 'AND'),
                    config.get('frequency', 'daily'),
                    config.get('schedule_time'),
                    config.get('schedule_day'),
                    config.get('notify_admin', True),
                    config.get('notify_user', False),
                    config.get('notify_all_admins', False),
                    config.get('custom_emails'),
                    config.get('cooldown_minutes', 60),
                    config.get('email_subject_template'),
                    config.get('email_body_template'),
                    created_by
                ))
                trigger_id = cur.fetchone()[0]
                conn.commit()
                logger.info(f"Created trigger {trigger_id}: {config.get('name')}")
                return trigger_id
        finally:
            conn.close()

    def update_trigger(self, trigger_id: int, updates: dict) -> bool:
        """Update an existing trigger."""
        conn = self._get_connection()
        try:
            # Build dynamic update query
            set_clauses = []
            values = []

            allowed_fields = [
                'name', 'description', 'is_active', 'trigger_type',
                'applies_to', 'target_employees', 'conditions',
                'condition_logic', 'frequency', 'schedule_time',
                'schedule_day', 'notify_admin', 'notify_user',
                'notify_all_admins', 'custom_emails', 'cooldown_minutes',
                'email_subject_template', 'email_body_template'
            ]

            for field in allowed_fields:
                if field in updates:
                    value = updates[field]
                    if field == 'conditions':
                        value = json.dumps(value)
                    set_clauses.append(f"{field} = %s")
                    values.append(value)

            if not set_clauses:
                return False

            set_clauses.append("updated_at = NOW()")
            values.append(trigger_id)

            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE dashboard_email_triggers
                    SET {', '.join(set_clauses)}
                    WHERE id = %s
                """, values)
                conn.commit()
                return cur.rowcount > 0
        finally:
            conn.close()

    def delete_trigger(self, trigger_id: int) -> bool:
        """Delete a trigger."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM dashboard_email_triggers WHERE id = %s",
                    (trigger_id,)
                )
                conn.commit()
                return cur.rowcount > 0
        finally:
            conn.close()

    def get_trigger(self, trigger_id: int) -> Optional[dict]:
        """Get a single trigger by ID."""
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM dashboard_email_triggers WHERE id = %s
                """, (trigger_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            conn.close()

    def list_triggers(self, active_only: bool = False) -> List[dict]:
        """List all triggers."""
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = "SELECT * FROM dashboard_email_triggers"
                if active_only:
                    query += " WHERE is_active = TRUE"
                query += " ORDER BY name"
                cur.execute(query)
                return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    # =========================================
    # Trigger Evaluation
    # =========================================

    def evaluate_condition(self, condition: dict, metrics: dict) -> bool:
        """
        Evaluate a single condition against metrics.

        Args:
            condition: Dict with 'metric', 'operator', 'value'
            metrics: The employee's metrics

        Returns:
            True if condition is met (trigger should fire)
        """
        metric_name = condition.get('metric')
        operator = condition.get('operator', 'less_than')
        threshold = condition.get('value', 0)

        # Get the metric value from the nested structure
        actual_value = None

        # Map metric names to locations in the metrics dict
        metric_paths = {
            'answer_rate': ('calls', 'answer_rate'),
            'total_calls': ('calls', 'total_calls'),
            'avg_duration': ('calls', 'avg_duration_seconds'),
            'missed_calls': ('calls', 'missed_calls'),
            'tickets_open_total': ('tickets', 'tickets_open_total'),
            'tickets_over_5_days': ('tickets', 'tickets_over_5_days'),
            'tickets_closed': ('tickets', 'tickets_closed'),
            'avg_quality_score': ('quality', 'avg_quality_score'),
            'escalation_count': ('quality', 'escalation_count'),
            'churn_risk_high_count': ('quality', 'churn_risk_high_count'),
            'productivity_score': ('productivity', 'score'),
        }

        if metric_name in metric_paths:
            path = metric_paths[metric_name]
            section = metrics.get(path[0], {})
            actual_value = section.get(path[1], 0)
        else:
            # Try to find it directly
            for section in ['calls', 'tickets', 'quality', 'productivity']:
                if metric_name in metrics.get(section, {}):
                    actual_value = metrics[section][metric_name]
                    break

        if actual_value is None:
            logger.warning(f"Metric '{metric_name}' not found in metrics")
            return False

        # Compare based on operator
        if operator == 'less_than':
            return actual_value < threshold
        elif operator == 'less_than_or_equal':
            return actual_value <= threshold
        elif operator == 'greater_than':
            return actual_value > threshold
        elif operator == 'greater_than_or_equal':
            return actual_value >= threshold
        elif operator == 'equals':
            return actual_value == threshold
        elif operator == 'not_equals':
            return actual_value != threshold
        else:
            logger.warning(f"Unknown operator: {operator}")
            return False

    def evaluate_trigger(self, trigger: dict, employee_name: str,
                         metrics: dict) -> dict:
        """
        Evaluate a trigger for a specific employee.

        Returns:
            dict with 'should_fire', 'reason', 'metric_values'
        """
        result = {
            'should_fire': False,
            'reason': '',
            'metric_values': {},
            'conditions_met': []
        }

        conditions = trigger.get('conditions', {})
        if not conditions:
            return result

        # Handle both single condition dict and list of conditions
        if isinstance(conditions, dict) and 'metric' in conditions:
            conditions = [conditions]
        elif isinstance(conditions, dict) and 'conditions' in conditions:
            conditions = conditions['conditions']

        if not isinstance(conditions, list):
            conditions = [conditions]

        logic = trigger.get('condition_logic', 'AND')
        met_conditions = []

        for cond in conditions:
            if not isinstance(cond, dict):
                continue

            is_met = self.evaluate_condition(cond, metrics)

            if is_met:
                met_conditions.append(cond)
                result['metric_values'][cond.get('metric')] = {
                    'threshold': cond.get('value'),
                    'operator': cond.get('operator'),
                }

        result['conditions_met'] = met_conditions

        # Determine if trigger fires based on logic
        if logic == 'AND':
            result['should_fire'] = len(met_conditions) == len(conditions)
        else:  # OR
            result['should_fire'] = len(met_conditions) > 0

        if result['should_fire']:
            reasons = []
            for cond in met_conditions:
                reasons.append(
                    f"{cond.get('metric')} {cond.get('operator')} {cond.get('value')}"
                )
            result['reason'] = ', '.join(reasons)

        return result

    def check_cooldown(self, trigger_id: int) -> bool:
        """
        Check if a trigger is within its cooldown period.

        Returns:
            True if trigger can fire (not in cooldown)
        """
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT last_triggered_at, cooldown_minutes
                    FROM dashboard_email_triggers
                    WHERE id = %s
                """, (trigger_id,))
                row = cur.fetchone()

                if not row or not row['last_triggered_at']:
                    return True

                cooldown = row['cooldown_minutes'] or 60
                last_triggered = row['last_triggered_at']
                cutoff = datetime.now() - timedelta(minutes=cooldown)

                return last_triggered < cutoff
        finally:
            conn.close()

    # =========================================
    # Email Sending
    # =========================================

    def _get_recipients(self, trigger: dict, employee_name: str = None) -> List[str]:
        """Build list of email recipients for a trigger."""
        recipients = []

        # Custom emails
        if trigger.get('custom_emails'):
            recipients.extend(trigger['custom_emails'])

        # Default to admin alert email if notify_admin
        if trigger.get('notify_admin') and self.default_to:
            if self.default_to not in recipients:
                recipients.append(self.default_to)

        # Get user's email if notify_user
        if trigger.get('notify_user') and employee_name:
            # Look up user's email
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT email FROM users
                        WHERE LOWER(CONCAT(first_name, ' ', last_name)) = LOWER(%s)
                           OR LOWER(username) = LOWER(%s)
                    """, (employee_name, employee_name))
                    row = cur.fetchone()
                    if row and row[0] and row[0] not in recipients:
                        recipients.append(row[0])
            finally:
                conn.close()

        # Get all admin emails if notify_all_admins
        if trigger.get('notify_all_admins'):
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT email FROM users
                        WHERE role = 'admin' AND email IS NOT NULL
                    """)
                    for row in cur.fetchall():
                        if row[0] and row[0] not in recipients:
                            recipients.append(row[0])
            finally:
                conn.close()

        return recipients

    def _build_email_content(self, trigger: dict, employee_name: str,
                             evaluation: dict, metrics: dict) -> tuple:
        """
        Build email subject and body.

        Returns:
            (subject, body_html)
        """
        trigger_name = trigger.get('name', 'Dashboard Alert')
        trigger_type = trigger.get('trigger_type', 'threshold_alert')

        # Default subject
        subject = trigger.get('email_subject_template')
        if not subject:
            subject = f"[ConvoMetrics Alert] {trigger_name} - {employee_name}"

        # Variable substitution
        subject = subject.replace('{employee_name}', employee_name)
        subject = subject.replace('{trigger_name}', trigger_name)
        subject = subject.replace('{date}', date.today().isoformat())

        # Build body
        body_template = trigger.get('email_body_template')
        if body_template:
            body = body_template
            body = body.replace('{employee_name}', employee_name)
            body = body.replace('{trigger_name}', trigger_name)
            body = body.replace('{reason}', evaluation.get('reason', ''))
        else:
            # Default body
            body = f"""
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
<h2 style="color: #e74c3c;">Dashboard Alert: {trigger_name}</h2>

<p><strong>Employee:</strong> {employee_name}</p>
<p><strong>Trigger Type:</strong> {trigger_type.replace('_', ' ').title()}</p>
<p><strong>Reason:</strong> {evaluation.get('reason', 'Condition met')}</p>
<p><strong>Date:</strong> {date.today().isoformat()}</p>

<h3>Current Metrics</h3>
<table style="border-collapse: collapse; width: 100%;">
<tr style="background: #f8f9fa;">
    <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Metric</th>
    <th style="padding: 8px; border: 1px solid #ddd; text-align: right;">Value</th>
</tr>
"""
            # Add call metrics
            calls = metrics.get('calls', {})
            body += f"""
<tr><td style="padding: 8px; border: 1px solid #ddd;">Total Calls</td>
    <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">{calls.get('total_calls', 0)}</td></tr>
<tr><td style="padding: 8px; border: 1px solid #ddd;">Answer Rate</td>
    <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">{calls.get('answer_rate', 0)}%</td></tr>
"""
            # Add ticket metrics
            tickets = metrics.get('tickets', {})
            body += f"""
<tr><td style="padding: 8px; border: 1px solid #ddd;">Open Tickets</td>
    <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">{tickets.get('tickets_open_total', 0)}</td></tr>
<tr><td style="padding: 8px; border: 1px solid #ddd;">Overdue (>5d)</td>
    <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">{tickets.get('tickets_over_5_days', 0)}</td></tr>
"""
            # Add quality metrics
            quality = metrics.get('quality', {})
            body += f"""
<tr><td style="padding: 8px; border: 1px solid #ddd;">Avg Quality</td>
    <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">{quality.get('avg_quality_score', 0):.1f}</td></tr>
"""
            # Add productivity
            prod = metrics.get('productivity', {})
            body += f"""
<tr><td style="padding: 8px; border: 1px solid #ddd;">Productivity Score</td>
    <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">{prod.get('score', 0)} ({prod.get('grade', '-')})</td></tr>
</table>

<p style="margin-top: 20px;">
<a href="http://31.97.102.13:8081/dashboard/admin/user/{employee_name}"
   style="background: #3498db; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">
   View Dashboard
</a>
</p>

<hr style="margin-top: 30px; border: none; border-top: 1px solid #ddd;">
<p style="color: #666; font-size: 12px;">
This is an automated alert from ConvoMetrics - BLT Workflow: Client PC Recruiter.
To modify this trigger, visit the <a href="http://31.97.102.13:8081/admin/triggers">Trigger Settings</a>.
</p>
</body>
</html>
"""

        return subject, body

    def send_email(self, to_addresses: List[str], subject: str, body_html: str) -> bool:
        """
        Send an email.

        Returns:
            True if email was sent successfully
        """
        if not self.smtp_user or not self.smtp_password:
            logger.warning("SMTP credentials not configured - skipping email")
            return False

        if not to_addresses:
            logger.warning("No recipients specified - skipping email")
            return False

        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.default_from
            msg['To'] = ', '.join(to_addresses)

            # Attach HTML body
            html_part = MIMEText(body_html, 'html')
            msg.attach(html_part)

            context = ssl.create_default_context()

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls(context=context)
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.default_from, to_addresses, msg.as_string())

            logger.info(f"Email sent to {to_addresses}")
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return False

    # =========================================
    # Trigger Execution
    # =========================================

    def fire_trigger(self, trigger: dict, employee_name: str,
                     evaluation: dict, metrics: dict) -> dict:
        """
        Fire a trigger - send notifications and log the event.

        Returns:
            dict with 'success', 'email_sent', 'recipients', 'error'
        """
        result = {
            'success': False,
            'email_sent': False,
            'recipients': [],
            'error': None
        }

        try:
            # Get recipients
            recipients = self._get_recipients(trigger, employee_name)
            result['recipients'] = recipients

            # Build email content
            subject, body = self._build_email_content(
                trigger, employee_name, evaluation, metrics
            )

            # Send email
            if recipients:
                result['email_sent'] = self.send_email(recipients, subject, body)

            # Log the trigger execution
            self._log_trigger_execution(
                trigger, employee_name, evaluation, metrics,
                recipients, result['email_sent'], subject
            )

            # Update trigger's last_triggered_at
            self._update_trigger_timestamp(trigger['id'])

            result['success'] = True

        except Exception as e:
            logger.error(f"Fire trigger error: {e}")
            result['error'] = str(e)

        return result

    def _log_trigger_execution(self, trigger: dict, employee_name: str,
                                evaluation: dict, metrics: dict,
                                recipients: List[str], email_sent: bool,
                                subject: str):
        """Log a trigger execution to the dashboard_trigger_log table."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                # Get first condition for logging
                cond = evaluation.get('conditions_met', [{}])[0] if evaluation.get('conditions_met') else {}

                cur.execute("""
                    INSERT INTO dashboard_trigger_log (
                        trigger_id, trigger_name, employee_name, period,
                        metric_name, metric_value, threshold_value,
                        metrics_snapshot, evaluation_result, trigger_reason,
                        recipients, email_sent, email_subject, action_taken
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s
                    )
                """, (
                    trigger.get('id'),
                    trigger.get('name'),
                    employee_name,
                    'today',  # TODO: get from context
                    cond.get('metric'),
                    evaluation.get('metric_values', {}).get(cond.get('metric'), {}).get('actual'),
                    cond.get('value'),
                    json.dumps(metrics),
                    'triggered',
                    evaluation.get('reason'),
                    recipients,
                    email_sent,
                    subject,
                    'email_sent' if email_sent else 'email_failed'
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Log trigger execution error: {e}")
        finally:
            conn.close()

    def _update_trigger_timestamp(self, trigger_id: int):
        """Update the last_triggered_at timestamp."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE dashboard_email_triggers
                    SET last_triggered_at = NOW(),
                        trigger_count = COALESCE(trigger_count, 0) + 1
                    WHERE id = %s
                """, (trigger_id,))
                conn.commit()
        finally:
            conn.close()

    def get_trigger_history(self, trigger_id: int = None,
                            employee_name: str = None,
                            limit: int = 50) -> List[dict]:
        """Get trigger execution history."""
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT * FROM dashboard_trigger_log
                    WHERE 1=1
                """
                params = []

                if trigger_id:
                    query += " AND trigger_id = %s"
                    params.append(trigger_id)

                if employee_name:
                    query += " AND employee_name = %s"
                    params.append(employee_name)

                query += " ORDER BY triggered_at DESC LIMIT %s"
                params.append(limit)

                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()


# Singleton instance
_trigger_service = None


def get_trigger_service() -> DashboardTriggerService:
    """Get the singleton trigger service instance."""
    global _trigger_service
    if _trigger_service is None:
        _trigger_service = DashboardTriggerService()
    return _trigger_service
