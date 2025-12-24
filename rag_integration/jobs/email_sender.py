"""
Email Sender - Send reports and alerts via email.
"""

import os
import logging
from typing import List, Optional
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import asyncio

import aiosmtplib
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class EmailSender:
    """Send emails for reports and alerts."""

    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.from_email = os.getenv("REPORT_FROM_EMAIL", self.smtp_user)
        self.default_recipients = self._parse_recipients(
            os.getenv("REPORT_RECIPIENTS", "")
        )

    def _parse_recipients(self, recipients_str: str) -> List[str]:
        """Parse comma-separated recipient list."""
        if not recipients_str:
            return []
        return [r.strip() for r in recipients_str.split(",") if r.strip()]

    async def send_email(
        self,
        subject: str,
        html_content: str,
        recipients: Optional[List[str]] = None,
        text_content: Optional[str] = None
    ) -> bool:
        """
        Send an email.

        Args:
            subject: Email subject
            html_content: HTML body content
            recipients: List of recipient emails (defaults to configured recipients)
            text_content: Optional plain text alternative

        Returns:
            True if sent successfully
        """
        if not self.smtp_user or not self.smtp_password:
            logger.warning("SMTP credentials not configured, skipping email")
            return False

        recipients = recipients or self.default_recipients
        if not recipients:
            logger.warning("No recipients configured, skipping email")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_email
            msg["To"] = ", ".join(recipients)

            # Add plain text version
            if text_content:
                text_part = MIMEText(text_content, "plain")
                msg.attach(text_part)

            # Add HTML version
            html_part = MIMEText(html_content, "html")
            msg.attach(html_part)

            # Send email
            await aiosmtplib.send(
                msg,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                start_tls=True
            )

            logger.info(f"Email sent successfully: {subject} to {recipients}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    async def send_report(
        self,
        subject: str,
        html_content: str,
        report_type: str,
        recipients: Optional[List[str]] = None
    ) -> bool:
        """
        Send a report email with standard formatting.

        Args:
            subject: Report subject
            html_content: HTML report content
            report_type: Type of report for logging
            recipients: Optional specific recipients
        """
        # Add timestamp to subject
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        full_subject = f"[ConvoMetrics Report] {subject} - {timestamp}"

        success = await self.send_email(
            subject=full_subject,
            html_content=html_content,
            recipients=recipients
        )

        if success:
            logger.info(f"Report sent: {report_type}")
        else:
            logger.error(f"Failed to send report: {report_type}")

        return success

    async def send_alert(
        self,
        alert_type: str,
        title: str,
        message: str,
        priority: str = "normal",
        details: Optional[dict] = None,
        recipients: Optional[List[str]] = None
    ) -> bool:
        """
        Send an alert email.

        Args:
            alert_type: Type of alert (churn_risk, escalation, quality)
            title: Alert title
            message: Alert message
            priority: Alert priority (low, normal, high, critical)
            details: Optional additional details
            recipients: Optional specific recipients
        """
        priority_colors = {
            "low": "#27ae60",
            "normal": "#3498db",
            "high": "#f39c12",
            "critical": "#e74c3c"
        }

        priority_emoji = {
            "low": "ℹ️",
            "normal": "⚠️",
            "high": "🔶",
            "critical": "🚨"
        }

        color = priority_colors.get(priority, "#3498db")
        emoji = priority_emoji.get(priority, "⚠️")

        # Build details HTML
        details_html = ""
        if details:
            details_html = "<table style='width: 100%; border-collapse: collapse; margin-top: 15px;'>"
            for key, value in details.items():
                details_html += f"""
                <tr>
                    <td style='padding: 8px; border-bottom: 1px solid #ddd; font-weight: bold; width: 30%;'>{key}</td>
                    <td style='padding: 8px; border-bottom: 1px solid #ddd;'>{value}</td>
                </tr>
                """
            details_html += "</table>"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }}
                .alert-box {{ border: 2px solid {color}; border-radius: 8px; overflow: hidden; }}
                .alert-header {{ background: {color}; color: white; padding: 15px 20px; font-size: 1.2em; }}
                .alert-body {{ padding: 20px; background: #f9f9f9; }}
                .alert-message {{ margin-bottom: 15px; }}
                .footer {{ margin-top: 20px; padding-top: 15px; border-top: 1px solid #ddd; color: #666; font-size: 0.85em; }}
            </style>
        </head>
        <body>
            <div class="alert-box">
                <div class="alert-header">
                    {emoji} {title}
                </div>
                <div class="alert-body">
                    <div class="alert-message">{message}</div>
                    {details_html}
                </div>
            </div>
            <div class="footer">
                <p>Alert Type: {alert_type} | Priority: {priority.upper()}</p>
                <p>Generated by ConvoMetrics BLT System at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
        </body>
        </html>
        """

        subject = f"{emoji} [{priority.upper()}] {title}"

        return await self.send_email(
            subject=subject,
            html_content=html_content,
            recipients=recipients
        )

    async def send_churn_alert(
        self,
        customer_name: str,
        company: str,
        churn_score: int,
        call_id: str,
        agent_name: str,
        key_concerns: List[str],
        recipients: Optional[List[str]] = None
    ) -> bool:
        """
        Send a high churn risk alert.
        """
        priority = "critical" if churn_score >= 9 else "high"

        concerns_list = "\n".join([f"• {c}" for c in key_concerns])

        details = {
            "Customer": customer_name,
            "Company": company,
            "Churn Risk Score": f"{churn_score}/10",
            "Call ID": call_id,
            "Handled By": agent_name,
            "Key Concerns": concerns_list
        }

        message = f"""
        A customer has been identified as {priority.upper()} churn risk during a recent call.
        Immediate attention may be required to retain this customer.
        """

        return await self.send_alert(
            alert_type="churn_risk",
            title=f"High Churn Risk: {customer_name} ({company})",
            message=message,
            priority=priority,
            details=details,
            recipients=recipients
        )

    async def send_escalation_alert(
        self,
        customer_name: str,
        call_id: str,
        agent_name: str,
        escalation_reason: str,
        risk_level: str,
        recipients: Optional[List[str]] = None
    ) -> bool:
        """
        Send an escalation required alert.
        """
        priority_map = {
            "low": "normal",
            "medium": "high",
            "high": "critical"
        }
        priority = priority_map.get(risk_level.lower(), "high")

        details = {
            "Customer": customer_name,
            "Call ID": call_id,
            "Agent": agent_name,
            "Risk Level": risk_level.upper(),
            "Reason": escalation_reason
        }

        message = f"""
        A call has been flagged for escalation. Please review and take appropriate action.
        """

        return await self.send_alert(
            alert_type="escalation",
            title=f"Escalation Required: {customer_name}",
            message=message,
            priority=priority,
            details=details,
            recipients=recipients
        )

    async def send_quality_alert(
        self,
        call_id: str,
        agent_name: str,
        quality_score: float,
        issues: List[str],
        recipients: Optional[List[str]] = None
    ) -> bool:
        """
        Send a low quality score alert.
        """
        priority = "critical" if quality_score < 3 else "high"

        issues_list = "\n".join([f"• {i}" for i in issues])

        details = {
            "Call ID": call_id,
            "Agent": agent_name,
            "Quality Score": f"{quality_score}/10",
            "Issues Identified": issues_list
        }

        message = f"""
        A call has received a quality score below the acceptable threshold.
        Review recommended for coaching and quality improvement.
        """

        return await self.send_alert(
            alert_type="quality",
            title=f"Low Quality Call: Agent {agent_name}",
            message=message,
            priority=priority,
            details=details,
            recipients=recipients
        )


# Convenience functions for cron jobs
async def check_and_send_churn_alerts():
    """Check for high churn risk calls and send alerts."""
    # This would be called by a cron job to check recent calls
    # and send alerts for any with high churn risk

    # For now, this is a placeholder that would integrate with
    # the database to find recent high-risk calls

    logger.info("Checking for high churn risk calls...")
    # Implementation would query the database for recent calls
    # with churn_risk_score >= 8 and send alerts


if __name__ == "__main__":
    async def test():
        sender = EmailSender()

        # Test alert
        success = await sender.send_alert(
            alert_type="test",
            title="Test Alert",
            message="This is a test alert from the ConvoMetrics system.",
            priority="normal",
            details={"Test Key": "Test Value"}
        )
        print(f"Test alert sent: {success}")

    asyncio.run(test())
