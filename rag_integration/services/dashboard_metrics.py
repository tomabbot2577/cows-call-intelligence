"""
Dashboard Metrics Service

Aggregates and calculates dashboard metrics from call_log,
transcripts, insights, and kb_freshdesk_qa tables.
"""

import os
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
import psycopg2
from psycopg2.extras import RealDictCursor

from rag_integration.config.employee_names import (
    canonicalize_employee_name,
    get_canonical_employee_list,
    get_employee_name_variations,
    is_employee
)

logger = logging.getLogger(__name__)


def get_db_url() -> str:
    """Get database connection URL."""
    return os.getenv('RAG_DATABASE_URL') or os.getenv('DATABASE_URL', '')


class DashboardMetricsService:
    """
    Aggregates and calculates dashboard metrics from multiple data sources.
    """

    # Productivity score weights (must sum to 100)
    # KEY METRICS: Calls and Tickets are primary ranking factors
    SCORE_WEIGHTS = {
        'total_calls': 30,           # KEY: Target 50+ calls/period
        'tickets_closed': 25,        # KEY: Target 30+ tickets closed/period
        'tickets_opened': 20,        # KEY: Target 20+ tickets opened/period
        'no_overdue_tickets': 15,    # KEY: Penalty for tickets >5 days old
        'answer_rate': 5,            # Target: 85%+
        'avg_quality_score': 5,      # Target: 7+/10
    }

    # Activity targets for scoring (adjustable)
    ACTIVITY_TARGETS = {
        'calls_per_month': 50,       # Target calls for full points
        'tickets_closed_per_month': 30,
        'tickets_opened_per_month': 20,
    }

    # Grade thresholds
    GRADE_THRESHOLDS = [
        (97, 'A+'), (93, 'A'), (90, 'A-'),
        (87, 'B+'), (83, 'B'), (80, 'B-'),
        (77, 'C+'), (73, 'C'), (70, 'C-'),
        (60, 'D'), (0, 'F')
    ]

    def __init__(self, db_url: str = None):
        self.db_url = db_url or get_db_url()

    def get_connection(self):
        """Get database connection."""
        return psycopg2.connect(self.db_url)

    # =========================================================================
    # PERIOD HELPERS
    # =========================================================================

    def get_period_dates(self, period: str,
                         start_date: str = None,
                         end_date: str = None) -> Tuple[date, date]:
        """
        Convert period string to date range.

        Args:
            period: 'today', 'wtd', 'last_week', 'mtd', 'qtd', 'ytd', 'custom'
            start_date: For custom period (YYYY-MM-DD)
            end_date: For custom period (YYYY-MM-DD)

        Returns:
            (start_date, end_date) tuple
        """
        today = date.today()

        if period == 'today':
            return today, today

        elif period == 'wtd':  # Week to date (Monday start)
            monday = today - timedelta(days=today.weekday())
            return monday, today

        elif period == 'last_week':  # Previous full week (Mon-Sun)
            last_monday = today - timedelta(days=today.weekday() + 7)
            last_sunday = last_monday + timedelta(days=6)
            return last_monday, last_sunday

        elif period == 'mtd':  # Month to date
            return date(today.year, today.month, 1), today

        elif period == 'qtd':  # Quarter to date
            quarter_start_month = ((today.month - 1) // 3) * 3 + 1
            return date(today.year, quarter_start_month, 1), today

        elif period == 'ytd':  # Year to date
            return date(today.year, 1, 1), today

        elif period == 'custom' and start_date and end_date:
            return (
                datetime.strptime(start_date, '%Y-%m-%d').date(),
                datetime.strptime(end_date, '%Y-%m-%d').date()
            )

        else:
            return today, today

    # =========================================================================
    # EMPLOYEE LOOKUP
    # =========================================================================

    def get_employee_for_extension(self, extension: str) -> Optional[str]:
        """Look up employee name from extension number."""
        if not extension:
            return None

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT employee_name FROM extension_employee_map
                    WHERE extension_number = %s
                    ORDER BY confidence_score DESC
                    LIMIT 1
                """, (extension,))
                result = cur.fetchone()
                return result[0] if result else None

    def get_freshdesk_agent_mapping(self, agent_name: str) -> Optional[str]:
        """Map Freshdesk agent name to PCR employee name."""
        if not agent_name:
            return None

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pcr_employee_name FROM freshdesk_agent_map
                    WHERE freshdesk_agent_name = %s AND pcr_employee_name IS NOT NULL
                """, (agent_name,))
                result = cur.fetchone()
                return result[0] if result else None

    def get_active_employees(self, period: str = 'today',
                             min_calls: int = 0,
                             min_tickets: int = 0,
                             start_date: str = None,
                             end_date: str = None) -> List[str]:
        """
        Get list of employees with activity in the period.

        Args:
            period: Time period to check
            min_calls: Minimum calls to be considered active
            min_tickets: Minimum tickets to be considered active
            start_date: Optional explicit start date (for custom period)
            end_date: Optional explicit end date (for custom period)

        Returns:
            List of employee names with activity
        """
        period_start, period_end = self.get_period_dates(period, start_date, end_date)

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Get employees from call_log via extension mapping
                cur.execute("""
                    SELECT DISTINCT COALESCE(e.employee_name, c.to_name) as employee_name
                    FROM call_log c
                    LEFT JOIN extension_employee_map e
                        ON c.to_extension_number = e.extension_number
                    WHERE c.start_time::date BETWEEN %s AND %s
                      AND (c.to_name IS NOT NULL OR e.employee_name IS NOT NULL)
                    GROUP BY COALESCE(e.employee_name, c.to_name)
                    HAVING COUNT(*) >= %s
                """, (period_start, period_end, min_calls))
                call_employees = {row[0] for row in cur.fetchall() if row[0]}

                # Get employees from transcripts
                cur.execute("""
                    SELECT DISTINCT employee_name
                    FROM transcripts
                    WHERE call_date BETWEEN %s AND %s
                      AND employee_name IS NOT NULL
                      AND employee_name != ''
                """, (period_start, period_end))
                transcript_employees = {row[0] for row in cur.fetchall() if row[0]}

                # Get employees from Freshdesk (via mapping)
                cur.execute("""
                    SELECT DISTINCT f.pcr_employee_name
                    FROM kb_freshdesk_qa q
                    JOIN freshdesk_agent_map f ON q.agent_name = f.freshdesk_agent_name
                    WHERE (q.created_at::date BETWEEN %s AND %s
                           OR q.resolved_at::date BETWEEN %s AND %s)
                      AND f.pcr_employee_name IS NOT NULL
                    GROUP BY f.pcr_employee_name
                    HAVING COUNT(*) >= %s
                """, (period_start, period_end, period_start, period_end, min_tickets))
                ticket_employees = {row[0] for row in cur.fetchall() if row[0]}

        # Union all sources
        all_employees = call_employees | transcript_employees | ticket_employees
        return sorted(list(all_employees))

    # =========================================================================
    # CALL METRICS
    # =========================================================================

    def get_call_metrics(self, employee_name: str, period: str,
                         start_date: str = None,
                         end_date: str = None) -> Dict:
        """
        Get call metrics for an employee within a period.

        Returns dict with:
            total_calls, answered_calls, missed_calls, voicemail_calls,
            answer_rate, inbound_calls, outbound_calls, avg_duration_seconds,
            total_duration_seconds, hourly_volume,
            avg_wait_time_seconds, voicemail_business_hours, voicemail_after_hours,
            calls_over_1_min_wait
        """
        period_start, period_end = self.get_period_dates(period, start_date, end_date)

        # Get all name variations for this employee
        name_variations = get_employee_name_variations(employee_name)
        # Create ILIKE patterns for each variation
        name_patterns = [f'%{v}%' for v in name_variations]

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get call metrics from call_log
                # Match employee by extension mapping, call_log names, OR transcripts employee_name
                # Also calculate wait time from call_legs (time between first and last leg)
                cur.execute("""
                    WITH employee_calls AS (
                        SELECT c.*,
                            -- Calculate wait time from call_legs (difference between first and last leg startTime)
                            CASE
                                WHEN c.call_legs IS NOT NULL
                                     AND jsonb_array_length(c.call_legs) >= 2
                                     AND c.call_result IN ('Accepted', 'Call connected')
                                THEN EXTRACT(EPOCH FROM (
                                    (c.call_legs->-1->>'startTime')::timestamp -
                                    (c.call_legs->0->>'startTime')::timestamp
                                ))
                                ELSE NULL
                            END as wait_seconds
                        FROM call_log c
                        LEFT JOIN extension_employee_map e_to
                            ON c.to_extension_number = e_to.extension_number
                        LEFT JOIN extension_employee_map e_from
                            ON c.from_extension_number = e_from.extension_number
                        LEFT JOIN transcripts t
                            ON c.ringcentral_id = t.recording_id
                        WHERE c.start_time::date BETWEEN %s AND %s
                          AND (
                              -- Match via extension mapping
                              e_to.employee_name ILIKE ANY(%s)
                              OR e_from.employee_name ILIKE ANY(%s)
                              -- Match via call_log names
                              OR c.to_name ILIKE ANY(%s)
                              OR c.from_name ILIKE ANY(%s)
                              -- Match via transcripts employee_name (historical data)
                              OR t.employee_name ILIKE ANY(%s)
                          )
                    )
                    SELECT
                        COUNT(*) as total_calls,
                        COUNT(*) FILTER (WHERE call_result IN ('Accepted', 'Call connected')) as answered_calls,
                        COUNT(*) FILTER (WHERE call_result = 'Missed') as missed_calls,
                        COUNT(*) FILTER (WHERE call_result = 'Voicemail') as voicemail_calls,
                        COUNT(*) FILTER (WHERE direction = 'Inbound') as inbound_calls,
                        COUNT(*) FILTER (WHERE direction = 'Outbound') as outbound_calls,
                        COALESCE(AVG(duration_seconds), 0) as avg_duration_seconds,
                        COALESCE(SUM(duration_seconds), 0) as total_duration_seconds,
                        -- New metrics: wait time
                        COALESCE(AVG(wait_seconds) FILTER (WHERE wait_seconds >= 0), 0) as avg_wait_time_seconds,
                        COUNT(*) FILTER (WHERE wait_seconds > 60) as calls_over_1_min_wait,
                        -- Voicemail by business hours (8am-5pm local time)
                        COUNT(*) FILTER (
                            WHERE call_result = 'Voicemail'
                            AND EXTRACT(HOUR FROM start_time AT TIME ZONE 'America/New_York') BETWEEN 8 AND 16
                        ) as voicemail_business_hours,
                        COUNT(*) FILTER (
                            WHERE call_result = 'Voicemail'
                            AND (EXTRACT(HOUR FROM start_time AT TIME ZONE 'America/New_York') < 8
                                 OR EXTRACT(HOUR FROM start_time AT TIME ZONE 'America/New_York') >= 17)
                        ) as voicemail_after_hours
                    FROM employee_calls
                """, (period_start, period_end, name_patterns, name_patterns, name_patterns, name_patterns, name_patterns))

                metrics = dict(cur.fetchone())

                # Calculate answer rate
                total = metrics['total_calls'] or 0
                answered = metrics['answered_calls'] or 0
                metrics['answer_rate'] = round((answered / total * 100), 1) if total > 0 else 0

                # Get hourly volume (include both inbound and outbound)
                cur.execute("""
                    WITH employee_calls AS (
                        SELECT c.*
                        FROM call_log c
                        LEFT JOIN extension_employee_map e_to
                            ON c.to_extension_number = e_to.extension_number
                        LEFT JOIN extension_employee_map e_from
                            ON c.from_extension_number = e_from.extension_number
                        LEFT JOIN transcripts t
                            ON c.ringcentral_id = t.recording_id
                        WHERE c.start_time::date BETWEEN %s AND %s
                          AND (
                              e_to.employee_name ILIKE ANY(%s)
                              OR e_from.employee_name ILIKE ANY(%s)
                              OR c.to_name ILIKE ANY(%s)
                              OR c.from_name ILIKE ANY(%s)
                              OR t.employee_name ILIKE ANY(%s)
                          )
                    )
                    SELECT
                        EXTRACT(HOUR FROM start_time) as hour,
                        COUNT(*) as count,
                        COUNT(*) FILTER (WHERE direction = 'Inbound') as inbound,
                        COUNT(*) FILTER (WHERE direction = 'Outbound') as outbound
                    FROM employee_calls
                    GROUP BY EXTRACT(HOUR FROM start_time)
                    ORDER BY hour
                """, (period_start, period_end, name_patterns, name_patterns, name_patterns, name_patterns, name_patterns))

                hourly = {int(row['hour']): {
                    'total': row['count'],
                    'inbound': row['inbound'],
                    'outbound': row['outbound']
                } for row in cur.fetchall()}

                metrics['hourly_volume'] = hourly

                # Try to get talk time from transcripts (with diarization)
                talk_metrics = self._get_talk_time_metrics(
                    cur, employee_name, period_start, period_end
                )
                metrics.update(talk_metrics)

        return metrics

    def _get_talk_time_metrics(self, cur, employee_name: str,
                               period_start: date, period_end: date) -> Dict:
        """
        Get talk time metrics from transcripts with diarization data.
        Returns avg_talk_time_seconds, avg_hold_time_seconds, employee_talk_pct
        """
        # For now, we don't have reliable talk time extraction
        # This would need to parse transcript_segments JSONB
        # Return placeholders that indicate data is not available
        return {
            'avg_talk_time_seconds': None,
            'avg_hold_time_seconds': None,
            'avg_ring_time_seconds': None,
            'employee_talk_pct': None
        }

    # =========================================================================
    # TICKET METRICS
    # =========================================================================

    def get_ticket_metrics(self, employee_name: str, period: str,
                           start_date: str = None,
                           end_date: str = None) -> Dict:
        """
        Get ticket metrics for an employee (via Freshdesk agent mapping).

        Returns dict with:
            tickets_opened, tickets_closed, tickets_open_total,
            tickets_over_5_days, aging_distribution
        """
        period_start, period_end = self.get_period_dates(period, start_date, end_date)

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get Freshdesk agent names for this employee
                cur.execute("""
                    SELECT freshdesk_agent_name FROM freshdesk_agent_map
                    WHERE pcr_employee_name = %s
                """, (employee_name,))
                agent_names = [row['freshdesk_agent_name'] for row in cur.fetchall()]

                if not agent_names:
                    # No mapping - return zeros
                    return {
                        'tickets_opened': 0,
                        'tickets_closed': 0,
                        'tickets_open_total': 0,
                        'tickets_over_1_day': 0,
                        'tickets_over_3_days': 0,
                        'tickets_over_5_days': 0,
                        'tickets_over_7_days': 0,
                        'avg_first_response_minutes': None,
                        'first_contact_resolution_rate': 0,
                        'aging_distribution': {
                            '0-1 days': 0,
                            '1-3 days': 0,
                            '3-5 days': 0,
                            '5-7 days': 0,
                            '7+ days': 0
                        }
                    }

                # Get ticket counts
                cur.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE created_at::date BETWEEN %s AND %s)
                            as tickets_opened,
                        COUNT(*) FILTER (WHERE resolved_at::date BETWEEN %s AND %s)
                            as tickets_closed,
                        COUNT(*) FILTER (WHERE resolved_at IS NULL)
                            as tickets_open_total
                    FROM kb_freshdesk_qa
                    WHERE agent_name = ANY(%s)
                """, (period_start, period_end, period_start, period_end, agent_names))
                counts = dict(cur.fetchone())

                # Get aging breakdown (for open tickets)
                cur.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE NOW() - created_at < INTERVAL '1 day') as d0_1,
                        COUNT(*) FILTER (WHERE NOW() - created_at >= INTERVAL '1 day'
                                           AND NOW() - created_at < INTERVAL '3 days') as d1_3,
                        COUNT(*) FILTER (WHERE NOW() - created_at >= INTERVAL '3 days'
                                           AND NOW() - created_at < INTERVAL '5 days') as d3_5,
                        COUNT(*) FILTER (WHERE NOW() - created_at >= INTERVAL '5 days'
                                           AND NOW() - created_at < INTERVAL '7 days') as d5_7,
                        COUNT(*) FILTER (WHERE NOW() - created_at >= INTERVAL '7 days') as d7_plus,
                        COUNT(*) FILTER (WHERE NOW() - created_at >= INTERVAL '1 day') as over_1,
                        COUNT(*) FILTER (WHERE NOW() - created_at >= INTERVAL '3 days') as over_3,
                        COUNT(*) FILTER (WHERE NOW() - created_at >= INTERVAL '5 days') as over_5,
                        COUNT(*) FILTER (WHERE NOW() - created_at >= INTERVAL '7 days') as over_7
                    FROM kb_freshdesk_qa
                    WHERE agent_name = ANY(%s)
                      AND resolved_at IS NULL
                """, (agent_names,))
                aging = dict(cur.fetchone())

                return {
                    'tickets_opened': counts['tickets_opened'] or 0,
                    'tickets_closed': counts['tickets_closed'] or 0,
                    'tickets_open_total': counts['tickets_open_total'] or 0,
                    'tickets_over_1_day': aging['over_1'] or 0,
                    'tickets_over_3_days': aging['over_3'] or 0,
                    'tickets_over_5_days': aging['over_5'] or 0,
                    'tickets_over_7_days': aging['over_7'] or 0,
                    'avg_first_response_minutes': None,  # Not tracked in current schema
                    'first_contact_resolution_rate': 0,   # Would need more data
                    'aging_distribution': {
                        '0-1 days': aging['d0_1'] or 0,
                        '1-3 days': aging['d1_3'] or 0,
                        '3-5 days': aging['d3_5'] or 0,
                        '5-7 days': aging['d5_7'] or 0,
                        '7+ days': aging['d7_plus'] or 0
                    }
                }

    # =========================================================================
    # QUALITY METRICS
    # =========================================================================

    def get_quality_metrics(self, employee_name: str, period: str,
                            start_date: str = None,
                            end_date: str = None) -> Dict:
        """
        Get call quality metrics from insights table.

        Returns dict with:
            avg_quality_score, sentiment_distribution,
            escalation_count, first_contact_resolution_count, churn_risk_high_count
        """
        period_start, period_end = self.get_period_dates(period, start_date, end_date)

        # Get all name variations for this employee
        name_variations = get_employee_name_variations(employee_name)
        name_patterns = [f'%{v}%' for v in name_variations]

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get quality metrics from insights joined with transcripts
                cur.execute("""
                    SELECT
                        AVG(i.call_quality_score) as avg_quality_score,
                        COUNT(*) FILTER (WHERE i.customer_sentiment = 'positive') as positive_count,
                        COUNT(*) FILTER (WHERE i.customer_sentiment = 'negative') as negative_count,
                        COUNT(*) FILTER (WHERE i.customer_sentiment = 'neutral') as neutral_count,
                        COUNT(*) FILTER (WHERE i.escalation_required = true) as escalation_count,
                        COUNT(*) FILTER (WHERE i.first_call_resolution = true)
                            as first_contact_resolution
                    FROM insights i
                    JOIN transcripts t ON i.recording_id = t.recording_id
                    WHERE t.call_date BETWEEN %s AND %s
                      AND t.employee_name ILIKE ANY(%s)
                """, (period_start, period_end, name_patterns))

                quality = dict(cur.fetchone())

                # Get churn risk from call_resolutions
                cur.execute("""
                    SELECT COUNT(*) as high_churn_count
                    FROM call_resolutions r
                    JOIN transcripts t ON r.recording_id = t.recording_id
                    WHERE t.call_date BETWEEN %s AND %s
                      AND t.employee_name ILIKE ANY(%s)
                      AND r.churn_risk = 'high'
                """, (period_start, period_end, name_patterns))

                churn = cur.fetchone()

                # Calculate sentiment distribution
                total_sentiment = (
                    (quality['positive_count'] or 0) +
                    (quality['negative_count'] or 0) +
                    (quality['neutral_count'] or 0)
                )

                return {
                    'avg_quality_score': round(float(quality['avg_quality_score'] or 0), 1),
                    'sentiment_distribution': {
                        'positive': quality['positive_count'] or 0,
                        'negative': quality['negative_count'] or 0,
                        'neutral': quality['neutral_count'] or 0
                    },
                    'positive_sentiment_rate': round(
                        (quality['positive_count'] or 0) / total_sentiment * 100, 1
                    ) if total_sentiment > 0 else 0,
                    'escalation_count': quality['escalation_count'] or 0,
                    'first_contact_resolution_count': quality['first_contact_resolution'] or 0,
                    'churn_risk_high_count': churn['high_churn_count'] if churn else 0
                }

    # =========================================================================
    # PRODUCTIVITY SCORE
    # =========================================================================

    def calculate_productivity_score(self, call_metrics: Dict,
                                     ticket_metrics: Dict,
                                     quality_metrics: Dict) -> Dict:
        """
        Calculate weighted productivity score (0-100) and grade.

        KEY METRICS (90% of score):
        - Total calls: 30% (target 50+ calls/period)
        - Tickets closed: 25% (target 30+ tickets/period)
        - Tickets opened: 20% (target 20+ tickets/period)
        - No overdue tickets: 15% (penalty for tickets >5 days)

        SECONDARY METRICS (10% of score):
        - Answer rate: 5% (target 85%+)
        - Avg quality score: 5% (target 7+/10)

        Returns dict with score, grade, and breakdown
        """
        breakdown = {}

        # =============================================
        # KEY METRICS (90% of total score)
        # =============================================

        # 1. Total Calls (0-30 points) - KEY METRIC
        # Target: 50 calls/period for full points
        total_calls = call_metrics.get('total_calls', 0)
        target_calls = self.ACTIVITY_TARGETS['calls_per_month']
        breakdown['total_calls'] = min(total_calls / target_calls * 30, 30)

        # 2. Tickets Closed (0-25 points) - KEY METRIC
        # Target: 30 tickets closed/period for full points
        tickets_closed = ticket_metrics.get('tickets_closed', 0)
        target_closed = self.ACTIVITY_TARGETS['tickets_closed_per_month']
        breakdown['tickets_closed'] = min(tickets_closed / target_closed * 25, 25)

        # 3. Tickets Opened (0-20 points) - KEY METRIC
        # Target: 20 tickets opened/period for full points
        tickets_opened = ticket_metrics.get('tickets_opened', 0)
        target_opened = self.ACTIVITY_TARGETS['tickets_opened_per_month']
        breakdown['tickets_opened'] = min(tickets_opened / target_opened * 20, 20)

        # 4. No Overdue Tickets (0-15 points) - KEY METRIC
        # Full points if 0 tickets >5 days, decreases with more overdue
        tickets_over_5_days = ticket_metrics.get('tickets_over_5_days', 0)
        if tickets_over_5_days == 0:
            breakdown['no_overdue'] = 15
        elif tickets_over_5_days <= 2:
            breakdown['no_overdue'] = 10
        elif tickets_over_5_days <= 5:
            breakdown['no_overdue'] = 5
        else:
            breakdown['no_overdue'] = 0

        # =============================================
        # SECONDARY METRICS (10% of total score)
        # =============================================

        # 5. Answer rate (0-5 points) - target 85%
        answer_rate = call_metrics.get('answer_rate', 0)
        breakdown['answer_rate'] = min(answer_rate / 85 * 5, 5)

        # 6. Quality score (0-5 points) - target 7/10
        quality = quality_metrics.get('avg_quality_score', 0)
        breakdown['quality'] = min(quality / 7 * 5, 5)

        # Calculate total score
        score = sum(breakdown.values())

        # Determine grade
        grade = 'F'
        for threshold, g in self.GRADE_THRESHOLDS:
            if score >= threshold:
                grade = g
                break

        return {
            'score': round(score, 1),
            'grade': grade,
            'breakdown': {k: round(v, 1) for k, v in breakdown.items()}
        }

    # =========================================================================
    # COMBINED METRICS
    # =========================================================================

    def get_combined_metrics(self, employee_name: str, period: str,
                             start_date: str = None,
                             end_date: str = None) -> Dict:
        """Get all metrics combined for dashboard display."""
        period_start, period_end = self.get_period_dates(period, start_date, end_date)

        call_metrics = self.get_call_metrics(employee_name, period, start_date, end_date)
        ticket_metrics = self.get_ticket_metrics(employee_name, period, start_date, end_date)
        quality_metrics = self.get_quality_metrics(employee_name, period, start_date, end_date)
        productivity = self.calculate_productivity_score(
            call_metrics, ticket_metrics, quality_metrics
        )

        return {
            'employee_name': employee_name,
            'period': period,
            'period_dates': {
                'start': period_start.isoformat(),
                'end': period_end.isoformat()
            },
            'calls': call_metrics,
            'tickets': ticket_metrics,
            'quality': quality_metrics,
            'productivity': productivity,
            'generated_at': datetime.now().isoformat()
        }

    # =========================================================================
    # TEAM METRICS (for Admin Dashboard)
    # =========================================================================

    def get_team_metrics(self, period: str,
                         min_activity: int = 1) -> List[Dict]:
        """
        Get metrics for all canonical employees with activity.

        Args:
            period: Time period
            min_activity: Minimum calls OR tickets to be included

        Returns:
            List of employee metrics, sorted by productivity score
        """
        # Use canonical employee list to ensure consistent names
        canonical_employees = get_canonical_employee_list()

        team = []
        for emp in canonical_employees:
            try:
                metrics = self.get_combined_metrics(emp, period)
                # Only include if they have activity
                if (metrics['calls']['total_calls'] >= min_activity or
                    metrics['tickets']['tickets_opened'] >= min_activity or
                    metrics['tickets']['tickets_closed'] >= min_activity):
                    team.append(metrics)
            except Exception as e:
                logger.warning(f"Error getting metrics for {emp}: {e}")
                continue

        # Sort by productivity score descending
        team.sort(key=lambda x: x['productivity']['score'], reverse=True)
        return team

    # =========================================================================
    # AGGREGATION (for cron job)
    # =========================================================================

    def aggregate_daily_metrics(self, metric_date: date = None) -> int:
        """
        Aggregate all metrics for all canonical employees for a given date.
        Called by daily cron job to populate user_daily_metrics table.

        Returns: Number of employees processed
        """
        if metric_date is None:
            metric_date = date.today()

        logger.info(f"Aggregating daily metrics for {metric_date}")

        # Use canonical employee list - only these 22 employees
        canonical_employees = get_canonical_employee_list()

        count = 0
        for emp in canonical_employees:
            try:
                # Get metrics using canonical name (get_combined_metrics handles variations)
                metrics = self.get_combined_metrics(
                    emp, 'custom',
                    start_date=metric_date.isoformat(),
                    end_date=metric_date.isoformat()
                )

                # Only save if there's activity
                if (metrics['calls']['total_calls'] > 0 or
                    metrics['tickets']['tickets_opened'] > 0 or
                    metrics['tickets']['tickets_closed'] > 0):
                    self._save_daily_metrics(emp, metric_date, metrics)
                    count += 1

            except Exception as e:
                logger.error(f"Error aggregating metrics for {emp}: {e}")

        logger.info(f"Aggregated metrics for {count} employees")
        return count

    def _save_daily_metrics(self, employee_name: str, metric_date: date,
                            metrics: Dict) -> None:
        """Save or update daily metrics record."""
        calls = metrics['calls']
        tickets = metrics['tickets']
        quality = metrics['quality']
        productivity = metrics['productivity']

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO user_daily_metrics (
                        employee_name, metric_date,
                        total_calls, answered_calls, missed_calls, voicemail_calls,
                        inbound_calls, outbound_calls,
                        avg_duration_seconds, total_duration_seconds,
                        avg_talk_time_seconds, avg_hold_time_seconds,
                        employee_talk_pct,
                        avg_wait_time_seconds, calls_over_1_min_wait,
                        voicemail_business_hours, voicemail_after_hours,
                        avg_quality_score,
                        positive_sentiment_count, negative_sentiment_count, neutral_sentiment_count,
                        escalation_count, first_contact_resolution_count, high_churn_risk_count,
                        tickets_opened, tickets_closed, tickets_open_total,
                        tickets_over_1_day, tickets_over_3_days, tickets_over_5_days, tickets_over_7_days,
                        productivity_score, productivity_grade, productivity_breakdown,
                        updated_at
                    ) VALUES (
                        %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        NOW()
                    )
                    ON CONFLICT (employee_name, metric_date) DO UPDATE SET
                        total_calls = EXCLUDED.total_calls,
                        answered_calls = EXCLUDED.answered_calls,
                        missed_calls = EXCLUDED.missed_calls,
                        voicemail_calls = EXCLUDED.voicemail_calls,
                        inbound_calls = EXCLUDED.inbound_calls,
                        outbound_calls = EXCLUDED.outbound_calls,
                        avg_duration_seconds = EXCLUDED.avg_duration_seconds,
                        total_duration_seconds = EXCLUDED.total_duration_seconds,
                        avg_talk_time_seconds = EXCLUDED.avg_talk_time_seconds,
                        avg_hold_time_seconds = EXCLUDED.avg_hold_time_seconds,
                        employee_talk_pct = EXCLUDED.employee_talk_pct,
                        avg_wait_time_seconds = EXCLUDED.avg_wait_time_seconds,
                        calls_over_1_min_wait = EXCLUDED.calls_over_1_min_wait,
                        voicemail_business_hours = EXCLUDED.voicemail_business_hours,
                        voicemail_after_hours = EXCLUDED.voicemail_after_hours,
                        avg_quality_score = EXCLUDED.avg_quality_score,
                        positive_sentiment_count = EXCLUDED.positive_sentiment_count,
                        negative_sentiment_count = EXCLUDED.negative_sentiment_count,
                        neutral_sentiment_count = EXCLUDED.neutral_sentiment_count,
                        escalation_count = EXCLUDED.escalation_count,
                        first_contact_resolution_count = EXCLUDED.first_contact_resolution_count,
                        high_churn_risk_count = EXCLUDED.high_churn_risk_count,
                        tickets_opened = EXCLUDED.tickets_opened,
                        tickets_closed = EXCLUDED.tickets_closed,
                        tickets_open_total = EXCLUDED.tickets_open_total,
                        tickets_over_1_day = EXCLUDED.tickets_over_1_day,
                        tickets_over_3_days = EXCLUDED.tickets_over_3_days,
                        tickets_over_5_days = EXCLUDED.tickets_over_5_days,
                        tickets_over_7_days = EXCLUDED.tickets_over_7_days,
                        productivity_score = EXCLUDED.productivity_score,
                        productivity_grade = EXCLUDED.productivity_grade,
                        productivity_breakdown = EXCLUDED.productivity_breakdown,
                        updated_at = NOW()
                """, (
                    employee_name, metric_date,
                    calls['total_calls'], calls['answered_calls'],
                    calls['missed_calls'], calls['voicemail_calls'],
                    calls['inbound_calls'], calls['outbound_calls'],
                    calls['avg_duration_seconds'], calls['total_duration_seconds'],
                    calls.get('avg_talk_time_seconds'),
                    calls.get('avg_hold_time_seconds'),
                    calls.get('employee_talk_pct'),
                    calls.get('avg_wait_time_seconds'),
                    calls.get('calls_over_1_min_wait', 0),
                    calls.get('voicemail_business_hours', 0),
                    calls.get('voicemail_after_hours', 0),
                    quality['avg_quality_score'],
                    quality['sentiment_distribution']['positive'],
                    quality['sentiment_distribution']['negative'],
                    quality['sentiment_distribution']['neutral'],
                    quality['escalation_count'],
                    quality['first_contact_resolution_count'],
                    quality['churn_risk_high_count'],
                    tickets['tickets_opened'], tickets['tickets_closed'],
                    tickets['tickets_open_total'],
                    tickets['tickets_over_1_day'], tickets['tickets_over_3_days'],
                    tickets['tickets_over_5_days'], tickets['tickets_over_7_days'],
                    productivity['score'], productivity['grade'],
                    psycopg2.extras.Json(productivity['breakdown'])
                ))
                conn.commit()

    def aggregate_hourly_volume(self, metric_date: date = None) -> int:
        """
        Aggregate hourly call volume for all employees.
        Returns: Number of records created/updated
        """
        if metric_date is None:
            metric_date = date.today()

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Delete existing records for this date
                cur.execute("""
                    DELETE FROM user_hourly_call_volume WHERE metric_date = %s
                """, (metric_date,))

                # Insert aggregated data
                cur.execute("""
                    INSERT INTO user_hourly_call_volume
                        (employee_name, metric_date, hour_of_day,
                         total_calls, inbound_calls, outbound_calls,
                         answered_calls, missed_calls)
                    SELECT
                        COALESCE(e.employee_name, c.to_name) as employee_name,
                        c.start_time::date as metric_date,
                        EXTRACT(HOUR FROM c.start_time)::integer as hour_of_day,
                        COUNT(*) as total_calls,
                        COUNT(*) FILTER (WHERE c.direction = 'Inbound') as inbound_calls,
                        COUNT(*) FILTER (WHERE c.direction = 'Outbound') as outbound_calls,
                        COUNT(*) FILTER (WHERE c.call_result IN ('Accepted', 'Call connected')) as answered_calls,
                        COUNT(*) FILTER (WHERE c.call_result = 'Missed') as missed_calls
                    FROM call_log c
                    LEFT JOIN extension_employee_map e
                        ON c.to_extension_number = e.extension_number
                    WHERE c.start_time::date = %s
                      AND (c.to_name IS NOT NULL OR e.employee_name IS NOT NULL)
                    GROUP BY
                        COALESCE(e.employee_name, c.to_name),
                        c.start_time::date,
                        EXTRACT(HOUR FROM c.start_time)
                """, (metric_date,))

                count = cur.rowcount
                conn.commit()

        logger.info(f"Aggregated {count} hourly volume records for {metric_date}")
        return count


# Singleton instance
_metrics_service = None


def get_metrics_service() -> DashboardMetricsService:
    """Get singleton instance of metrics service."""
    global _metrics_service
    if _metrics_service is None:
        _metrics_service = DashboardMetricsService()
    return _metrics_service
