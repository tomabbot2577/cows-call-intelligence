"""
Report Generation Jobs - Generate reports from RAG queries.
"""

import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import logging
import json

from ..services.query_router import QueryRouter

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate various reports using RAG queries."""

    def __init__(self):
        self.router = QueryRouter()

    async def generate_churn_risk_report(
        self,
        min_score: int = 7,
        days_back: int = 7
    ) -> Dict[str, Any]:
        """
        Generate a churn risk report for high-risk customers.

        Args:
            min_score: Minimum churn risk score to include
            days_back: Number of days to look back
        """
        query = f"""
        Analyze all calls from the past {days_back} days with churn risk score of {min_score} or higher.

        For each high-risk call, provide:
        1. Customer name and company
        2. Call date and agent who handled it
        3. Churn risk score and reasoning
        4. Key frustration points mentioned
        5. Recommended retention actions

        Group by risk level (Critical 9-10, High 7-8) and prioritize by urgency.
        End with a summary of total customers at risk and top 3 retention priorities.
        """

        result = await self.router.route_query(query, force_system="vertex")

        return {
            "report_type": "churn_risk",
            "generated_at": datetime.now().isoformat(),
            "parameters": {
                "min_score": min_score,
                "days_back": days_back
            },
            "response": result.get("response", ""),
            "system_used": result.get("system", "vertex"),
            "query_time_ms": result.get("query_time_ms", 0)
        }

    async def generate_agent_performance_report(
        self,
        agent_name: str,
        date_range: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate a performance report for a specific agent.

        Args:
            agent_name: Name of the agent
            date_range: Optional date range (today, this_week, this_month)
        """
        date_context = ""
        if date_range == "today":
            date_context = "from today"
        elif date_range == "this_week":
            date_context = "from this week"
        elif date_range == "this_month":
            date_context = "from this month"
        else:
            date_context = "from all available data"

        query = f"""
        Generate a comprehensive performance report for agent "{agent_name}" {date_context}.

        Include the following metrics and analysis:

        1. CALL VOLUME & OVERVIEW
           - Total calls handled
           - Average call duration
           - Call types breakdown (support, sales, complaints, etc.)

        2. QUALITY METRICS
           - Average call quality score
           - Customer satisfaction scores
           - First call resolution rate
           - Loop closure compliance

        3. CUSTOMER SENTIMENT
           - Sentiment distribution (positive/neutral/negative)
           - Average empathy score
           - Communication clarity score

        4. STRENGTHS (with specific examples)
           - What this agent does well
           - Positive customer feedback themes

        5. AREAS FOR IMPROVEMENT
           - Skills that need development
           - Common issues in their calls
           - Specific coaching recommendations

        6. SUGGESTED TRAINING
           - Priority training topics
           - Recommended phrases to use

        End with an overall performance rating and 3 key action items for improvement.
        """

        result = await self.router.route_query(query, force_system="vertex")

        return {
            "report_type": "agent_performance",
            "generated_at": datetime.now().isoformat(),
            "parameters": {
                "agent_name": agent_name,
                "date_range": date_range
            },
            "response": result.get("response", ""),
            "system_used": result.get("system", "vertex"),
            "query_time_ms": result.get("query_time_ms", 0)
        }

    async def generate_daily_summary(self, date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Generate a daily summary report.

        Args:
            date: Date to summarize (defaults to yesterday)
        """
        if date is None:
            date = datetime.now() - timedelta(days=1)

        date_str = date.strftime("%Y-%m-%d")

        query = f"""
        Generate a comprehensive daily summary for {date_str}.

        Include:

        1. CALL VOLUME SUMMARY
           - Total calls received
           - Breakdown by call type
           - Peak hours

        2. QUALITY OVERVIEW
           - Average quality score
           - Calls above/below quality threshold
           - Resolution rate

        3. CUSTOMER SENTIMENT
           - Overall sentiment distribution
           - Notable positive interactions
           - Concerning negative interactions

        4. HIGH PRIORITY ITEMS
           - Customers requiring immediate follow-up
           - Escalations needed
           - High churn risk customers

        5. AGENT HIGHLIGHTS
           - Top performing agents
           - Agents needing attention

        6. KEY INSIGHTS
           - Common themes or issues
           - Process improvement opportunities
           - Knowledge gaps identified

        End with 3 action items for leadership attention.
        """

        result = await self.router.route_query(query, force_system="gemini")

        return {
            "report_type": "daily_summary",
            "generated_at": datetime.now().isoformat(),
            "parameters": {
                "date": date_str
            },
            "response": result.get("response", ""),
            "system_used": result.get("system", "gemini"),
            "query_time_ms": result.get("query_time_ms", 0)
        }

    async def generate_competitor_mention_report(
        self,
        days_back: int = 30
    ) -> Dict[str, Any]:
        """
        Generate a report of competitor mentions in calls.
        """
        query = f"""
        Analyze all calls from the past {days_back} days where competitors were mentioned.

        Provide:

        1. COMPETITOR OVERVIEW
           - Which competitors were mentioned and how often
           - Context of mentions (comparison, switching threat, feature request)

        2. COMPETITIVE INSIGHTS
           - What features/pricing customers compare
           - Why customers consider competitors
           - What they like about competitors

        3. WIN/LOSS ANALYSIS
           - Calls where we retained the customer despite competitor mention
           - Calls where customer indicated they might switch

        4. STRATEGIC RECOMMENDATIONS
           - Areas where we need to improve vs competitors
           - Talking points for sales/support teams
           - Product/service gaps to address

        Include specific examples and quotes where relevant.
        """

        result = await self.router.route_query(query, force_system="gemini")

        return {
            "report_type": "competitor_mentions",
            "generated_at": datetime.now().isoformat(),
            "parameters": {
                "days_back": days_back
            },
            "response": result.get("response", ""),
            "system_used": result.get("system", "gemini"),
            "query_time_ms": result.get("query_time_ms", 0)
        }

    async def generate_training_needs_report(self) -> Dict[str, Any]:
        """
        Generate a report identifying training needs across the team.
        """
        query = """
        Analyze recent calls to identify training needs across the support team.

        Provide:

        1. KNOWLEDGE GAPS
           - Common questions agents couldn't answer
           - Product areas where agents lack confidence
           - Process/policy confusion

        2. SKILL GAPS
           - Communication skills needing improvement
           - Technical skills needing development
           - Soft skills (empathy, de-escalation, etc.)

        3. BY AGENT BREAKDOWN
           - Which agents need what training
           - Priority level for each

        4. RECOMMENDED TRAINING PROGRAM
           - Priority topics for team-wide training
           - Individual coaching recommendations
           - Resources or documentation to create

        5. QUICK WINS
           - Simple phrases or techniques that could improve call quality
           - Easy process improvements

        Include specific examples from calls to illustrate each point.
        """

        result = await self.router.route_query(query, force_system="gemini")

        return {
            "report_type": "training_needs",
            "generated_at": datetime.now().isoformat(),
            "parameters": {},
            "response": result.get("response", ""),
            "system_used": result.get("system", "gemini"),
            "query_time_ms": result.get("query_time_ms", 0)
        }

    def format_report_as_html(self, report: Dict[str, Any]) -> str:
        """Format a report as HTML for email sending."""
        report_type = report.get("report_type", "unknown").replace("_", " ").title()
        generated_at = report.get("generated_at", "")
        response = report.get("response", "No content")

        # Convert markdown-style formatting to HTML
        content = response.replace("\n", "<br>")
        content = content.replace("**", "<strong>").replace("**", "</strong>")

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; }}
                h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
                .meta {{ color: #666; font-size: 0.9em; margin-bottom: 20px; }}
                .content {{ background: #f9f9f9; padding: 20px; border-radius: 8px; }}
                .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 0.85em; }}
            </style>
        </head>
        <body>
            <h1>{report_type} Report</h1>
            <div class="meta">Generated: {generated_at}</div>
            <div class="content">{content}</div>
            <div class="footer">
                <p>This report was automatically generated by the COWS Call Intelligence RAG System.</p>
                <p>System: {report.get('system_used', 'N/A')} | Query Time: {report.get('query_time_ms', 0)}ms</p>
            </div>
        </body>
        </html>
        """

        return html


# Scheduled report functions for cron jobs
async def run_daily_churn_report():
    """Run daily churn risk report - for cron."""
    from .email_sender import EmailSender

    generator = ReportGenerator()
    sender = EmailSender()

    logger.info("Generating daily churn risk report...")
    report = await generator.generate_churn_risk_report(min_score=7, days_back=1)

    html_content = generator.format_report_as_html(report)

    await sender.send_report(
        subject="Daily Churn Risk Report",
        html_content=html_content,
        report_type="churn_risk"
    )

    logger.info("Daily churn risk report sent successfully")


async def run_daily_summary_report():
    """Run daily summary report - for cron."""
    from .email_sender import EmailSender

    generator = ReportGenerator()
    sender = EmailSender()

    logger.info("Generating daily summary report...")
    report = await generator.generate_daily_summary()

    html_content = generator.format_report_as_html(report)

    await sender.send_report(
        subject="Daily Call Intelligence Summary",
        html_content=html_content,
        report_type="daily_summary"
    )

    logger.info("Daily summary report sent successfully")


if __name__ == "__main__":
    import asyncio

    async def test():
        generator = ReportGenerator()

        # Test churn report
        print("Testing Churn Risk Report...")
        report = await generator.generate_churn_risk_report(min_score=7, days_back=7)
        print(f"Report generated: {report['report_type']}")
        print(f"Response preview: {report['response'][:500]}...")

    asyncio.run(test())
