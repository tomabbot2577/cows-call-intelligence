"""
Database Reader Service - READ-ONLY access to existing PostgreSQL database.
"""

import os
from typing import Generator, Dict, Any, Optional, List
from datetime import datetime
from contextlib import contextmanager
import logging

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class DatabaseReader:
    """Read-only access to call recording database."""

    def __init__(self, database_url: Optional[str] = None):
        # Use RAG-specific database URL or default to call_insights
        self.database_url = database_url or os.getenv(
            "RAG_DATABASE_URL",
            "postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights"
        )

    @contextmanager
    def get_connection(self):
        """Get a read-only database connection."""
        conn = psycopg2.connect(self.database_url)
        conn.set_session(readonly=True)  # ENFORCE READ-ONLY
        try:
            yield conn
        finally:
            conn.close()

    def get_calls_for_export(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        require_all_layers: bool = True,
        min_layers: int = 4
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Fetch calls with transcripts and all metadata for RAG export.

        Args:
            since: Start date filter
            until: End date filter
            limit: Maximum records to return
            offset: Skip first N records
            require_all_layers: If True, require min_layers to be complete
            min_layers: Minimum layers required (4 or 5). Default 4.
                - 4 = Layers 1-4 (names, insights, resolutions, recommendations)
                - 5 = All layers including advanced metrics

        Layers:
        - Layer 1: Name extraction (employee_name, customer_name)
        - Layer 2: Sentiment analysis (insights table)
        - Layer 3: Resolution tracking (call_resolutions table)
        - Layer 4: Recommendations (call_recommendations table)
        - Layer 5: Advanced metrics (call_advanced_metrics table)
        """
        # Use INNER JOIN for required layers, LEFT JOIN for optional
        join_type = "INNER JOIN" if require_all_layers else "LEFT JOIN"
        # Layer 5 is optional if min_layers < 5
        layer5_join = "INNER JOIN" if (require_all_layers and min_layers >= 5) else "LEFT JOIN"

        query = f"""
        SELECT
            t.recording_id,
            t.call_date,
            t.call_time,
            t.duration_seconds,
            t.direction,
            t.from_number,
            t.to_number,
            t.customer_name,
            t.customer_company,
            t.customer_phone,
            t.employee_name,
            t.employee_department,
            t.transcript_text,
            t.word_count,
            t.confidence_score as transcript_confidence,

            -- Insights (Layer 2)
            i.customer_sentiment,
            i.call_quality_score,
            i.customer_satisfaction_score,
            i.call_type,
            i.issue_category,
            i.summary,
            i.key_topics,
            i.churn_risk_score,
            i.coaching_notes,
            i.follow_up_needed,
            i.escalation_required,
            i.first_call_resolution,
            i.sentiment_reasoning,
            i.quality_reasoning,
            i.overall_call_rating,

            -- Call Resolutions (Layer 3)
            cr.problem_complexity,
            cr.resolution_status,
            cr.resolution_details,
            cr.resolution_effectiveness,
            cr.empathy_score,
            cr.empathy_demonstrated,
            cr.active_listening_score,
            cr.employee_knowledge_level,
            cr.confidence_in_solution,
            cr.training_needed,
            cr.churn_risk as resolution_churn_risk,
            cr.revenue_impact,
            cr.customer_effort_score,
            cr.first_contact_resolution,
            cr.closure_score,
            cr.solution_summarized,
            cr.understanding_confirmed,
            cr.asked_if_anything_else,
            cr.next_steps_provided,
            cr.timeline_given,
            cr.contact_info_provided,
            cr.thanked_customer,
            cr.confirmed_satisfaction,

            -- Call Recommendations (Layer 4)
            rec.process_improvements,
            rec.employee_strengths,
            rec.employee_improvements,
            rec.suggested_phrases,
            rec.follow_up_actions,
            rec.knowledge_base_updates,
            rec.escalation_required as rec_escalation_required,
            rec.risk_level,
            rec.efficiency_score,
            rec.training_priority,

            -- Advanced Metrics (Layer 5)
            cam.recording_id as has_layer5,
            cam.buying_signals,
            cam.competitor_intelligence,
            cam.talk_listen_ratio,
            cam.compliance,
            cam.key_quotes,
            cam.qa_pairs,
            cam.urgency,
            cam.sales_opportunity_score,
            cam.compliance_score,
            cam.urgency_score

        FROM transcripts t
        {join_type} insights i ON t.recording_id = i.recording_id
        {join_type} call_resolutions cr ON t.recording_id = cr.recording_id
        {join_type} call_recommendations rec ON t.recording_id = rec.recording_id
        {layer5_join} call_advanced_metrics cam ON t.recording_id = cam.recording_id
        WHERE t.transcript_text IS NOT NULL
          AND LENGTH(t.transcript_text) > 100
          -- Layer 1: Require name extraction
          AND (t.employee_name IS NOT NULL OR t.customer_name IS NOT NULL)
        """

        params: List[Any] = []

        if since:
            query += " AND t.call_date >= %s"
            params.append(since.date() if isinstance(since, datetime) else since)

        if until:
            query += " AND t.call_date <= %s"
            params.append(until.date() if isinstance(until, datetime) else until)

        query += " ORDER BY t.call_date DESC, t.call_time DESC"

        if limit:
            query += " LIMIT %s"
            params.append(limit)

        if offset:
            query += " OFFSET %s"
            params.append(offset)

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                for row in cur:
                    yield dict(row)

    def get_call_count(self, since: Optional[datetime] = None) -> int:
        """Get total count of calls with transcripts."""
        query = """
            SELECT COUNT(*)
            FROM transcripts
            WHERE transcript_text IS NOT NULL
              AND LENGTH(transcript_text) > 100
        """
        params = []

        if since:
            query += " AND call_date >= %s"
            params.append(since.date() if isinstance(since, datetime) else since)

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchone()[0]

    def get_fully_analyzed_count(self, since: Optional[datetime] = None) -> int:
        """Get count of calls with ALL 5 layers of analysis complete."""
        query = """
            SELECT COUNT(*)
            FROM transcripts t
            INNER JOIN insights i ON t.recording_id = i.recording_id
            INNER JOIN call_resolutions cr ON t.recording_id = cr.recording_id
            INNER JOIN call_recommendations rec ON t.recording_id = rec.recording_id
            INNER JOIN call_advanced_metrics cam ON t.recording_id = cam.recording_id
            WHERE t.transcript_text IS NOT NULL
              AND LENGTH(t.transcript_text) > 100
              AND (t.employee_name IS NOT NULL OR t.customer_name IS NOT NULL)
        """
        params = []

        if since:
            query += " AND t.call_date >= %s"
            params.append(since.date() if isinstance(since, datetime) else since)

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchone()[0]

    def get_date_range(self) -> tuple:
        """Get earliest and latest call dates."""
        query = "SELECT MIN(call_date), MAX(call_date) FROM transcripts WHERE transcript_text IS NOT NULL"

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchone()

    def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics for dashboard."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                stats = {}

                # Total transcripts
                cur.execute("SELECT COUNT(*) as total FROM transcripts WHERE transcript_text IS NOT NULL")
                stats['total_transcripts'] = cur.fetchone()['total']

                # Layer 1: With name extraction
                cur.execute("""
                    SELECT COUNT(*) as total
                    FROM transcripts
                    WHERE transcript_text IS NOT NULL
                      AND (employee_name IS NOT NULL OR customer_name IS NOT NULL)
                """)
                stats['with_names'] = cur.fetchone()['total']

                # Layer 2: With insights (sentiment)
                cur.execute("""
                    SELECT COUNT(*) as total
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                """)
                stats['with_insights'] = cur.fetchone()['total']

                # Layer 3: With resolutions
                cur.execute("""
                    SELECT COUNT(*) as total
                    FROM transcripts t
                    JOIN call_resolutions cr ON t.recording_id = cr.recording_id
                """)
                stats['with_resolutions'] = cur.fetchone()['total']

                # Layer 4: With recommendations
                cur.execute("""
                    SELECT COUNT(*) as total
                    FROM transcripts t
                    JOIN call_recommendations rec ON t.recording_id = rec.recording_id
                """)
                stats['with_recommendations'] = cur.fetchone()['total']

                # Layer 5: With advanced metrics
                cur.execute("""
                    SELECT COUNT(*) as total
                    FROM transcripts t
                    JOIN call_advanced_metrics cam ON t.recording_id = cam.recording_id
                """)
                stats['with_advanced_metrics'] = cur.fetchone()['total']

                # LAYERS 1-4 COMPLETE (without requiring Layer 5)
                cur.execute("""
                    SELECT COUNT(*) as total
                    FROM transcripts t
                    INNER JOIN insights i ON t.recording_id = i.recording_id
                    INNER JOIN call_resolutions cr ON t.recording_id = cr.recording_id
                    INNER JOIN call_recommendations rec ON t.recording_id = rec.recording_id
                    WHERE t.transcript_text IS NOT NULL
                      AND LENGTH(t.transcript_text) > 100
                      AND (t.employee_name IS NOT NULL OR t.customer_name IS NOT NULL)
                """)
                stats['layers_1_to_4_complete'] = cur.fetchone()['total']

                # ALL 5 LAYERS COMPLETE - Ready for RAG export
                cur.execute("""
                    SELECT COUNT(*) as total
                    FROM transcripts t
                    INNER JOIN insights i ON t.recording_id = i.recording_id
                    INNER JOIN call_resolutions cr ON t.recording_id = cr.recording_id
                    INNER JOIN call_recommendations rec ON t.recording_id = rec.recording_id
                    INNER JOIN call_advanced_metrics cam ON t.recording_id = cam.recording_id
                    WHERE t.transcript_text IS NOT NULL
                      AND LENGTH(t.transcript_text) > 100
                      AND (t.employee_name IS NOT NULL OR t.customer_name IS NOT NULL)
                """)
                stats['all_5_layers_complete'] = cur.fetchone()['total']
                stats['fully_analyzed'] = stats['all_5_layers_complete']
                stats['ready_for_export'] = stats['layers_1_to_4_complete']  # Default to 4 layers

                # Date range
                cur.execute("""
                    SELECT MIN(call_date) as earliest, MAX(call_date) as latest
                    FROM transcripts WHERE transcript_text IS NOT NULL
                """)
                row = cur.fetchone()
                stats['earliest_date'] = str(row['earliest']) if row['earliest'] else None
                stats['latest_date'] = str(row['latest']) if row['latest'] else None

                # Sentiment distribution
                cur.execute("""
                    SELECT customer_sentiment, COUNT(*) as count
                    FROM insights
                    WHERE customer_sentiment IS NOT NULL
                    GROUP BY customer_sentiment
                """)
                stats['sentiment_distribution'] = {row['customer_sentiment']: row['count'] for row in cur.fetchall()}

                # Call type distribution
                cur.execute("""
                    SELECT call_type, COUNT(*) as count
                    FROM insights
                    WHERE call_type IS NOT NULL
                    GROUP BY call_type
                    ORDER BY count DESC
                    LIMIT 10
                """)
                stats['call_type_distribution'] = {row['call_type']: row['count'] for row in cur.fetchall()}

                return stats

    def test_connection(self) -> bool:
        """Test database connection."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    return cur.fetchone()[0] == 1
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False

    def get_agent_performance(self, agent_name: str, date_range: Optional[str] = None) -> Dict[str, Any]:
        """
        Get actual performance metrics for an agent from the database.

        Args:
            agent_name: Canonical agent name
            date_range: 'today', 'this_week', 'this_month', or None for all time
        """
        from ..config.employee_names import canonicalize_employee_name, NAME_VARIATIONS

        # Get all variations of this agent name for matching
        canonical = canonicalize_employee_name(agent_name) or agent_name
        name_variations = [canonical.lower()]
        for variation, canon in NAME_VARIATIONS.items():
            if canon == canonical:
                name_variations.append(variation.lower())

        # Build date filter
        date_filter = ""
        if date_range == "today":
            date_filter = "AND t.call_date = CURRENT_DATE"
        elif date_range == "this_week":
            date_filter = "AND t.call_date >= CURRENT_DATE - INTERVAL '7 days'"
        elif date_range == "this_month":
            date_filter = "AND t.call_date >= CURRENT_DATE - INTERVAL '30 days'"

        # Create LIKE pattern for name matching
        name_patterns = [f"%{v}%" for v in name_variations]

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                result = {}

                # Total calls handled
                cur.execute(f"""
                    SELECT COUNT(*) as total_calls
                    FROM transcripts t
                    WHERE (LOWER(t.employee_name) LIKE ANY(%s))
                    {date_filter}
                """, (name_patterns,))
                row = cur.fetchone()
                result['total_calls'] = row['total_calls'] if row else 0

                # Average quality score
                cur.execute(f"""
                    SELECT
                        ROUND(AVG(i.call_quality_score)::numeric, 1) as avg_quality,
                        ROUND(AVG(i.overall_call_rating)::numeric, 1) as avg_rating,
                        ROUND(AVG(i.customer_satisfaction_score)::numeric, 1) as avg_satisfaction
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE (LOWER(t.employee_name) LIKE ANY(%s))
                    {date_filter}
                """, (name_patterns,))
                row = cur.fetchone()
                result['avg_quality_score'] = float(row['avg_quality']) if row and row['avg_quality'] else 0
                result['avg_overall_rating'] = float(row['avg_rating']) if row and row['avg_rating'] else 0
                result['avg_satisfaction'] = float(row['avg_satisfaction']) if row and row['avg_satisfaction'] else 0

                # Sentiment distribution
                cur.execute(f"""
                    SELECT
                        i.customer_sentiment,
                        COUNT(*) as count
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE (LOWER(t.employee_name) LIKE ANY(%s))
                      AND i.customer_sentiment IS NOT NULL
                    {date_filter}
                    GROUP BY i.customer_sentiment
                """, (name_patterns,))
                result['sentiment_distribution'] = {row['customer_sentiment']: row['count'] for row in cur.fetchall()}

                # Call types
                cur.execute(f"""
                    SELECT
                        i.call_type,
                        COUNT(*) as count
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE (LOWER(t.employee_name) LIKE ANY(%s))
                      AND i.call_type IS NOT NULL
                    {date_filter}
                    GROUP BY i.call_type
                    ORDER BY count DESC
                """, (name_patterns,))
                result['call_types'] = {row['call_type']: row['count'] for row in cur.fetchall()}

                # Resolution metrics
                cur.execute(f"""
                    SELECT
                        ROUND(AVG(cr.empathy_score)::numeric, 1) as avg_empathy,
                        ROUND(AVG(cr.active_listening_score)::numeric, 1) as avg_listening,
                        ROUND(AVG(cr.closure_score)::numeric, 1) as avg_closure,
                        ROUND(AVG(cr.resolution_effectiveness)::numeric, 1) as avg_resolution,
                        SUM(CASE WHEN cr.first_contact_resolution THEN 1 ELSE 0 END) as first_contact_resolved
                    FROM transcripts t
                    JOIN call_resolutions cr ON t.recording_id = cr.recording_id
                    WHERE (LOWER(t.employee_name) LIKE ANY(%s))
                    {date_filter}
                """, (name_patterns,))
                row = cur.fetchone()
                result['avg_empathy_score'] = float(row['avg_empathy']) if row and row['avg_empathy'] else 0
                result['avg_listening_score'] = float(row['avg_listening']) if row and row['avg_listening'] else 0
                result['avg_closure_score'] = float(row['avg_closure']) if row and row['avg_closure'] else 0
                result['avg_resolution_effectiveness'] = float(row['avg_resolution']) if row and row['avg_resolution'] else 0
                result['first_contact_resolution_count'] = row['first_contact_resolved'] if row and row['first_contact_resolved'] else 0

                # Churn risk counts
                cur.execute(f"""
                    SELECT
                        cr.churn_risk,
                        COUNT(*) as count
                    FROM transcripts t
                    JOIN call_resolutions cr ON t.recording_id = cr.recording_id
                    WHERE (LOWER(t.employee_name) LIKE ANY(%s))
                      AND cr.churn_risk IS NOT NULL
                    {date_filter}
                    GROUP BY cr.churn_risk
                """, (name_patterns,))
                result['churn_risk_distribution'] = {row['churn_risk']: row['count'] for row in cur.fetchall()}

                # Top strengths and improvements (from recommendations)
                cur.execute(f"""
                    SELECT
                        rec.employee_strengths,
                        rec.employee_improvements
                    FROM transcripts t
                    JOIN call_recommendations rec ON t.recording_id = rec.recording_id
                    WHERE (LOWER(t.employee_name) LIKE ANY(%s))
                      AND rec.employee_strengths IS NOT NULL
                    {date_filter}
                    LIMIT 20
                """, (name_patterns,))

                all_strengths = []
                all_improvements = []
                for row in cur.fetchall():
                    if row['employee_strengths']:
                        if isinstance(row['employee_strengths'], list):
                            all_strengths.extend(row['employee_strengths'])
                        else:
                            all_strengths.append(row['employee_strengths'])
                    if row['employee_improvements']:
                        if isinstance(row['employee_improvements'], list):
                            all_improvements.extend(row['employee_improvements'])
                        else:
                            all_improvements.append(row['employee_improvements'])

                result['common_strengths'] = list(set(all_strengths))[:5]
                result['common_improvements'] = list(set(all_improvements))[:5]

                # Sample call summaries for context
                cur.execute(f"""
                    SELECT
                        i.summary,
                        i.call_quality_score,
                        i.customer_sentiment
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE (LOWER(t.employee_name) LIKE ANY(%s))
                      AND i.summary IS NOT NULL
                    {date_filter}
                    ORDER BY t.call_date DESC
                    LIMIT 5
                """, (name_patterns,))
                result['recent_call_summaries'] = [
                    {
                        'summary': row['summary'],
                        'quality': row['call_quality_score'],
                        'sentiment': row['customer_sentiment']
                    }
                    for row in cur.fetchall()
                ]

                # Recent calls with details (including phone numbers and call IDs)
                cur.execute(f"""
                    SELECT
                        t.recording_id,
                        t.call_date,
                        t.from_number,
                        t.to_number,
                        t.customer_name,
                        t.customer_company,
                        i.summary,
                        i.call_quality_score,
                        i.customer_sentiment,
                        i.call_type
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE (LOWER(t.employee_name) LIKE ANY(%s))
                    {date_filter}
                    ORDER BY t.call_date DESC
                    LIMIT 10
                """, (name_patterns,))
                result['recent_calls'] = [
                    {
                        'call_id': row['recording_id'],
                        'date': str(row['call_date']),
                        'from_number': row['from_number'] or 'N/A',
                        'to_number': row['to_number'] or 'N/A',
                        'customer_name': row['customer_name'] or 'Unknown',
                        'company': row['customer_company'] or 'Unknown',
                        'summary': row['summary'] or 'No summary',
                        'quality': row['call_quality_score'],
                        'sentiment': row['customer_sentiment'],
                        'call_type': row['call_type']
                    }
                    for row in cur.fetchall()
                ]

                result['agent_name'] = canonical
                result['date_range'] = date_range or 'all_time'

                return result

    def get_churn_risk_data(self, risk_level: str = 'high') -> Dict[str, Any]:
        """
        Get actual churn risk data from the database.

        Args:
            risk_level: Risk level to filter - 'high', 'medium', or 'all'
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                result = {}

                # Build risk filter
                if risk_level == 'high':
                    risk_filter = "cr.churn_risk = 'high'"
                elif risk_level == 'medium':
                    risk_filter = "cr.churn_risk IN ('high', 'medium')"
                else:
                    risk_filter = "cr.churn_risk IS NOT NULL AND cr.churn_risk != 'none' AND cr.churn_risk != 'low'"

                # High risk calls with details (including phone numbers)
                # Only include calls with valid dates and employee names
                cur.execute(f"""
                    SELECT
                        t.recording_id,
                        t.call_date,
                        t.from_number,
                        t.to_number,
                        t.customer_name,
                        t.customer_company,
                        t.employee_name,
                        i.call_quality_score,
                        i.summary,
                        cr.churn_risk as risk_level,
                        i.key_topics,
                        cr.improvement_suggestions,
                        i.customer_sentiment
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    JOIN call_resolutions cr ON t.recording_id = cr.recording_id
                    WHERE {risk_filter}
                      AND t.call_date IS NOT NULL
                    ORDER BY
                        CASE cr.churn_risk
                            WHEN 'high' THEN 1
                            WHEN 'medium' THEN 2
                            ELSE 3
                        END,
                        t.call_date DESC
                    LIMIT 50
                """)

                high_risk_calls = []
                for row in cur.fetchall():
                    high_risk_calls.append({
                        'call_id': row['recording_id'],
                        'call_date': str(row['call_date']),
                        'from_number': row['from_number'] or 'N/A',
                        'to_number': row['to_number'] or 'N/A',
                        'customer_name': row['customer_name'] or 'Unknown',
                        'customer_company': row['customer_company'] or 'Unknown',
                        'agent': row['employee_name'] or 'Unknown',
                        'quality_score': row['call_quality_score'],
                        'risk_level': row['risk_level'] or 'unknown',
                        'summary': row['summary'] or 'No summary available',
                        'topics': row['key_topics'] or [],
                        'issues': row['improvement_suggestions'] or [],
                        'sentiment': row['customer_sentiment'] or 'unknown'
                    })

                result['high_risk_calls'] = high_risk_calls
                result['total_high_risk'] = len(high_risk_calls)

                # Risk distribution
                cur.execute("""
                    SELECT
                        cr.churn_risk as risk_category,
                        COUNT(*) as count
                    FROM call_resolutions cr
                    WHERE cr.churn_risk IS NOT NULL
                    GROUP BY cr.churn_risk
                    ORDER BY
                        CASE cr.churn_risk
                            WHEN 'high' THEN 1
                            WHEN 'medium' THEN 2
                            WHEN 'low' THEN 3
                            ELSE 4
                        END
                """)
                result['risk_distribution'] = {row['risk_category']: row['count'] for row in cur.fetchall()}

                # Companies with multiple high/medium-risk calls
                cur.execute("""
                    SELECT
                        t.customer_company,
                        COUNT(*) as risk_count,
                        SUM(CASE WHEN cr.churn_risk = 'high' THEN 1 ELSE 0 END) as high_count
                    FROM transcripts t
                    JOIN call_resolutions cr ON t.recording_id = cr.recording_id
                    WHERE cr.churn_risk IN ('high', 'medium')
                      AND t.customer_company IS NOT NULL
                      AND t.customer_company != ''
                    GROUP BY t.customer_company
                    HAVING COUNT(*) > 1
                    ORDER BY
                        SUM(CASE WHEN cr.churn_risk = 'high' THEN 1 ELSE 0 END) DESC,
                        risk_count DESC
                    LIMIT 10
                """)
                result['repeat_risk_companies'] = [
                    {
                        'company': row['customer_company'],
                        'risk_count': row['risk_count'],
                        'high_count': row['high_count']
                    }
                    for row in cur.fetchall()
                ]

                return result


    def get_customer_companies(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get list of customer companies with call counts.
        Excludes internal companies (PC Recruiter, Main Sequence).
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        customer_company,
                        COUNT(*) as call_count,
                        COUNT(DISTINCT customer_name) as contact_count,
                        MAX(call_date) as last_call_date
                    FROM transcripts
                    WHERE customer_company IS NOT NULL
                      AND customer_company != ''
                      AND customer_company != 'Unknown'
                      AND LOWER(customer_company) NOT LIKE '%%pc recruiter%%'
                      AND LOWER(customer_company) NOT LIKE '%%main sequence%%'
                      AND LOWER(customer_company) NOT IN ('pcr', 'mst')
                    GROUP BY customer_company
                    ORDER BY call_count DESC
                    LIMIT %s
                """, (limit,))

                return [dict(row) for row in cur.fetchall()]

    def get_customer_report(self, company_name: str) -> Dict[str, Any]:
        """
        Get comprehensive report data for a customer company.

        Args:
            company_name: Company name to search for
        """
        from ..config.company_names import get_company_search_patterns, canonicalize_company_name

        patterns = get_company_search_patterns(company_name)
        canonical = canonicalize_company_name(company_name) or company_name

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                result = {'company_name': canonical}

                # Total calls and contacts
                cur.execute("""
                    SELECT
                        COUNT(*) as total_calls,
                        COUNT(DISTINCT customer_name) as unique_contacts,
                        MIN(call_date) as first_call,
                        MAX(call_date) as last_call
                    FROM transcripts
                    WHERE LOWER(customer_company) LIKE ANY(%s)
                """, (patterns,))
                row = cur.fetchone()
                result['total_calls'] = row['total_calls'] if row else 0
                result['unique_contacts'] = row['unique_contacts'] if row else 0
                result['first_call'] = str(row['first_call']) if row and row['first_call'] else None
                result['last_call'] = str(row['last_call']) if row and row['last_call'] else None

                if result['total_calls'] == 0:
                    return result

                # Contact list
                cur.execute("""
                    SELECT
                        customer_name,
                        COUNT(*) as call_count,
                        MAX(call_date) as last_call
                    FROM transcripts
                    WHERE LOWER(customer_company) LIKE ANY(%s)
                      AND customer_name IS NOT NULL
                      AND customer_name != ''
                      AND customer_name != 'Unknown'
                    GROUP BY customer_name
                    ORDER BY call_count DESC
                    LIMIT 10
                """, (patterns,))
                result['contacts'] = [dict(row) for row in cur.fetchall()]

                # Sentiment distribution
                cur.execute("""
                    SELECT
                        i.customer_sentiment,
                        COUNT(*) as count
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE LOWER(t.customer_company) LIKE ANY(%s)
                      AND i.customer_sentiment IS NOT NULL
                    GROUP BY i.customer_sentiment
                """, (patterns,))
                result['sentiment_distribution'] = {row['customer_sentiment']: row['count'] for row in cur.fetchall()}

                # Quality metrics
                cur.execute("""
                    SELECT
                        ROUND(AVG(i.call_quality_score)::numeric, 1) as avg_quality,
                        ROUND(AVG(i.customer_satisfaction_score)::numeric, 1) as avg_satisfaction
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE LOWER(t.customer_company) LIKE ANY(%s)
                """, (patterns,))
                row = cur.fetchone()
                result['avg_quality'] = float(row['avg_quality']) if row and row['avg_quality'] else 0
                result['avg_satisfaction'] = float(row['avg_satisfaction']) if row and row['avg_satisfaction'] else 0

                # Churn risk
                cur.execute("""
                    SELECT
                        cr.churn_risk,
                        COUNT(*) as count
                    FROM transcripts t
                    JOIN call_resolutions cr ON t.recording_id = cr.recording_id
                    WHERE LOWER(t.customer_company) LIKE ANY(%s)
                      AND cr.churn_risk IS NOT NULL
                    GROUP BY cr.churn_risk
                """, (patterns,))
                result['churn_risk_distribution'] = {row['churn_risk']: row['count'] for row in cur.fetchall()}

                # Call types
                cur.execute("""
                    SELECT
                        i.call_type,
                        COUNT(*) as count
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE LOWER(t.customer_company) LIKE ANY(%s)
                      AND i.call_type IS NOT NULL
                    GROUP BY i.call_type
                    ORDER BY count DESC
                """, (patterns,))
                result['call_types'] = {row['call_type']: row['count'] for row in cur.fetchall()}

                # Agents who handled their calls
                cur.execute("""
                    SELECT
                        t.employee_name,
                        COUNT(*) as call_count
                    FROM transcripts t
                    WHERE LOWER(t.customer_company) LIKE ANY(%s)
                      AND t.employee_name IS NOT NULL
                      AND t.employee_name != ''
                    GROUP BY t.employee_name
                    ORDER BY call_count DESC
                    LIMIT 5
                """, (patterns,))
                result['agents'] = [
                    {'name': row['employee_name'], 'calls': row['call_count']}
                    for row in cur.fetchall()
                ]

                # Recent calls with summaries
                cur.execute("""
                    SELECT
                        t.recording_id,
                        t.call_date,
                        t.customer_name,
                        t.employee_name,
                        i.summary,
                        i.customer_sentiment,
                        i.call_quality_score,
                        cr.churn_risk
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    LEFT JOIN call_resolutions cr ON t.recording_id = cr.recording_id
                    WHERE LOWER(t.customer_company) LIKE ANY(%s)
                    ORDER BY t.call_date DESC
                    LIMIT 10
                """, (patterns,))
                result['recent_calls'] = [
                    {
                        'call_id': row['recording_id'],
                        'date': str(row['call_date']),
                        'contact': row['customer_name'] or 'Unknown',
                        'agent': row['employee_name'] or 'Unknown',
                        'summary': row['summary'] or 'No summary',
                        'sentiment': row['customer_sentiment'],
                        'quality': row['call_quality_score'],
                        'churn_risk': row['churn_risk']
                    }
                    for row in cur.fetchall()
                ]

                # Common issues/topics
                cur.execute("""
                    SELECT i.key_topics
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE LOWER(t.customer_company) LIKE ANY(%s)
                      AND i.key_topics IS NOT NULL
                    LIMIT 20
                """, (patterns,))

                all_topics = []
                for row in cur.fetchall():
                    if row['key_topics'] and isinstance(row['key_topics'], list):
                        all_topics.extend(row['key_topics'])

                # Count topic frequency
                from collections import Counter
                topic_counts = Counter(all_topics)
                result['common_topics'] = [{'topic': t, 'count': c} for t, c in topic_counts.most_common(10)]

                return result


    def get_sentiment_report_data(self, sentiment_filter: str = 'negative') -> Dict[str, Any]:
        """
        Get actual sentiment data from the database for reporting.

        Args:
            sentiment_filter: 'negative', 'positive', 'all', or 'trends'
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                result = {}

                # Build sentiment filter
                if sentiment_filter == 'negative':
                    sentiment_clause = "LOWER(i.customer_sentiment) IN ('negative', 'frustrated', 'angry', 'upset')"
                elif sentiment_filter == 'positive':
                    sentiment_clause = "LOWER(i.customer_sentiment) IN ('positive', 'satisfied', 'happy')"
                else:
                    sentiment_clause = "i.customer_sentiment IS NOT NULL"

                # Overall sentiment distribution
                cur.execute("""
                    SELECT
                        i.customer_sentiment,
                        COUNT(*) as count
                    FROM insights i
                    WHERE i.customer_sentiment IS NOT NULL
                    GROUP BY i.customer_sentiment
                    ORDER BY count DESC
                """)
                result['sentiment_distribution'] = {row['customer_sentiment']: row['count'] for row in cur.fetchall()}

                # Calls matching the filter with full details
                # Only include calls with valid dates and at least some identifying info
                cur.execute(f"""
                    SELECT
                        t.recording_id,
                        t.call_date,
                        t.from_number,
                        t.to_number,
                        t.customer_name,
                        t.customer_company,
                        t.employee_name,
                        i.customer_sentiment,
                        i.sentiment_reasoning,
                        i.call_quality_score,
                        i.overall_call_rating,
                        i.call_type,
                        i.summary,
                        i.key_topics,
                        i.coaching_notes,
                        cr.churn_risk,
                        cr.improvement_suggestions
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    LEFT JOIN call_resolutions cr ON t.recording_id = cr.recording_id
                    WHERE {sentiment_clause}
                      AND t.call_date IS NOT NULL
                    ORDER BY
                        CASE
                            WHEN LOWER(i.customer_sentiment) IN ('negative', 'frustrated', 'angry') THEN 1
                            WHEN LOWER(i.customer_sentiment) = 'neutral' THEN 2
                            ELSE 3
                        END,
                        i.call_quality_score ASC NULLS LAST,
                        t.call_date DESC
                    LIMIT 30
                """)

                calls = []
                for row in cur.fetchall():
                    calls.append({
                        'call_id': row['recording_id'],
                        'call_date': str(row['call_date']),
                        'from_number': row['from_number'] or 'N/A',
                        'to_number': row['to_number'] or 'N/A',
                        'customer_name': row['customer_name'] or 'Unknown',
                        'customer_company': row['customer_company'] or 'Unknown',
                        'employee_name': row['employee_name'] or 'Unknown',
                        'sentiment': row['customer_sentiment'],
                        'sentiment_reasoning': row['sentiment_reasoning'] or 'No reasoning provided',
                        'quality_score': row['call_quality_score'],
                        'overall_rating': row['overall_call_rating'],
                        'call_type': row['call_type'] or 'Unknown',
                        'summary': row['summary'] or 'No summary',
                        'topics': row['key_topics'] or [],
                        'coaching_notes': row['coaching_notes'] or 'None',
                        'churn_risk': row['churn_risk'] or 'unknown',
                        'issues': row['improvement_suggestions'] or []
                    })

                result['calls'] = calls
                result['total_matching'] = len(calls)

                # Sentiment by agent
                cur.execute(f"""
                    SELECT
                        COALESCE(NULLIF(t.employee_name, ''), 'Unknown Agent') as employee_name,
                        COUNT(*) as call_count,
                        SUM(CASE WHEN LOWER(i.customer_sentiment) IN ('negative', 'frustrated', 'angry') THEN 1 ELSE 0 END) as negative_count,
                        SUM(CASE WHEN LOWER(i.customer_sentiment) IN ('positive', 'satisfied', 'happy') THEN 1 ELSE 0 END) as positive_count,
                        ROUND(AVG(i.call_quality_score)::numeric, 1) as avg_quality
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    GROUP BY COALESCE(NULLIF(t.employee_name, ''), 'Unknown Agent')
                    HAVING COUNT(*) >= 5
                    ORDER BY
                        SUM(CASE WHEN LOWER(i.customer_sentiment) IN ('negative', 'frustrated', 'angry') THEN 1 ELSE 0 END) DESC
                    LIMIT 15
                """)
                result['sentiment_by_agent'] = [
                    {
                        'agent': row['employee_name'],
                        'total_calls': row['call_count'],
                        'negative_calls': row['negative_count'],
                        'positive_calls': row['positive_count'],
                        'avg_quality': float(row['avg_quality']) if row['avg_quality'] else 0
                    }
                    for row in cur.fetchall()
                ]

                # Sentiment by company (customers)
                cur.execute(f"""
                    SELECT
                        t.customer_company,
                        COUNT(*) as call_count,
                        SUM(CASE WHEN LOWER(i.customer_sentiment) IN ('negative', 'frustrated', 'angry') THEN 1 ELSE 0 END) as negative_count,
                        SUM(CASE WHEN LOWER(i.customer_sentiment) IN ('positive', 'satisfied', 'happy') THEN 1 ELSE 0 END) as positive_count
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE t.customer_company IS NOT NULL
                      AND t.customer_company != ''
                      AND t.customer_company != 'Unknown'
                      AND LOWER(t.customer_company) NOT LIKE '%%pc recruiter%%'
                      AND LOWER(t.customer_company) NOT LIKE '%%main sequence%%'
                    GROUP BY t.customer_company
                    HAVING SUM(CASE WHEN LOWER(i.customer_sentiment) IN ('negative', 'frustrated', 'angry') THEN 1 ELSE 0 END) > 0
                    ORDER BY
                        SUM(CASE WHEN LOWER(i.customer_sentiment) IN ('negative', 'frustrated', 'angry') THEN 1 ELSE 0 END) DESC
                    LIMIT 10
                """)
                result['sentiment_by_customer'] = [
                    {
                        'company': row['customer_company'],
                        'total_calls': row['call_count'],
                        'negative_calls': row['negative_count'],
                        'positive_calls': row['positive_count']
                    }
                    for row in cur.fetchall()
                ]

                # Common topics in negative calls
                cur.execute("""
                    SELECT i.key_topics
                    FROM insights i
                    WHERE LOWER(i.customer_sentiment) IN ('negative', 'frustrated', 'angry')
                      AND i.key_topics IS NOT NULL
                    LIMIT 50
                """)

                all_topics = []
                for row in cur.fetchall():
                    if row['key_topics'] and isinstance(row['key_topics'], list):
                        all_topics.extend(row['key_topics'])

                from collections import Counter
                topic_counts = Counter(all_topics)
                result['negative_sentiment_topics'] = [{'topic': t, 'count': c} for t, c in topic_counts.most_common(15)]

                # Common call types in negative calls
                cur.execute("""
                    SELECT
                        i.call_type,
                        COUNT(*) as count
                    FROM insights i
                    WHERE LOWER(i.customer_sentiment) IN ('negative', 'frustrated', 'angry')
                      AND i.call_type IS NOT NULL
                    GROUP BY i.call_type
                    ORDER BY count DESC
                    LIMIT 10
                """)
                result['negative_call_types'] = {row['call_type']: row['count'] for row in cur.fetchall()}

                # Trend data (by week)
                cur.execute("""
                    SELECT
                        DATE_TRUNC('week', t.call_date) as week,
                        COUNT(*) as total_calls,
                        SUM(CASE WHEN LOWER(i.customer_sentiment) IN ('negative', 'frustrated', 'angry') THEN 1 ELSE 0 END) as negative,
                        SUM(CASE WHEN LOWER(i.customer_sentiment) IN ('positive', 'satisfied', 'happy') THEN 1 ELSE 0 END) as positive,
                        SUM(CASE WHEN LOWER(i.customer_sentiment) = 'neutral' THEN 1 ELSE 0 END) as neutral
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE t.call_date >= CURRENT_DATE - INTERVAL '90 days'
                    GROUP BY DATE_TRUNC('week', t.call_date)
                    ORDER BY week DESC
                    LIMIT 12
                """)
                result['weekly_trends'] = [
                    {
                        'week': str(row['week'].date()) if row['week'] else 'Unknown',
                        'total': row['total_calls'],
                        'negative': row['negative'],
                        'positive': row['positive'],
                        'neutral': row['neutral']
                    }
                    for row in cur.fetchall()
                ]

                return result


    def get_quality_report_data(self, focus: str = 'low_quality') -> Dict[str, Any]:
        """
        Get call quality data from the database for reporting.

        Args:
            focus: 'low_quality', 'trends', or 'by_type'
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                result = {}

                # Overall quality distribution
                cur.execute("""
                    SELECT
                        CASE
                            WHEN call_quality_score >= 8 THEN 'Excellent (8-10)'
                            WHEN call_quality_score >= 6 THEN 'Good (6-7)'
                            WHEN call_quality_score >= 4 THEN 'Fair (4-5)'
                            ELSE 'Poor (1-3)'
                        END as quality_tier,
                        COUNT(*) as count
                    FROM insights
                    WHERE call_quality_score IS NOT NULL
                    GROUP BY
                        CASE
                            WHEN call_quality_score >= 8 THEN 'Excellent (8-10)'
                            WHEN call_quality_score >= 6 THEN 'Good (6-7)'
                            WHEN call_quality_score >= 4 THEN 'Fair (4-5)'
                            ELSE 'Poor (1-3)'
                        END
                    ORDER BY
                        CASE
                            WHEN call_quality_score >= 8 THEN 1
                            WHEN call_quality_score >= 6 THEN 2
                            WHEN call_quality_score >= 4 THEN 3
                            ELSE 4
                        END
                """)
                result['quality_distribution'] = {row['quality_tier']: row['count'] for row in cur.fetchall()}

                # Average quality score
                cur.execute("""
                    SELECT
                        ROUND(AVG(call_quality_score)::numeric, 2) as avg_quality,
                        COUNT(*) as total_calls
                    FROM insights
                    WHERE call_quality_score IS NOT NULL
                """)
                row = cur.fetchone()
                result['avg_quality'] = float(row['avg_quality']) if row and row['avg_quality'] else 0
                result['total_calls_with_quality'] = row['total_calls'] if row else 0

                # Low quality calls (score < 5) with full details
                # Only include calls with valid dates and employee names
                cur.execute("""
                    SELECT
                        t.recording_id,
                        t.call_date,
                        t.from_number,
                        t.to_number,
                        t.customer_name,
                        t.customer_company,
                        t.employee_name,
                        i.call_quality_score,
                        i.quality_reasoning,
                        i.customer_sentiment,
                        i.call_type,
                        i.summary,
                        i.key_topics,
                        i.coaching_notes,
                        cr.improvement_suggestions,
                        rec.employee_improvements
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    LEFT JOIN call_resolutions cr ON t.recording_id = cr.recording_id
                    LEFT JOIN call_recommendations rec ON t.recording_id = rec.recording_id
                    WHERE i.call_quality_score IS NOT NULL
                      AND i.call_quality_score < 5
                      AND t.call_date IS NOT NULL
                    ORDER BY i.call_quality_score ASC, t.call_date DESC
                    LIMIT 25
                """)

                low_quality_calls = []
                for row in cur.fetchall():
                    improvements = []
                    if row['improvement_suggestions'] and isinstance(row['improvement_suggestions'], list):
                        improvements.extend(row['improvement_suggestions'])
                    if row['employee_improvements'] and isinstance(row['employee_improvements'], list):
                        improvements.extend(row['employee_improvements'])

                    low_quality_calls.append({
                        'call_id': row['recording_id'],
                        'call_date': str(row['call_date']),
                        'from_number': row['from_number'] or 'N/A',
                        'to_number': row['to_number'] or 'N/A',
                        'customer_name': row['customer_name'] or 'Unknown',
                        'customer_company': row['customer_company'] or 'Unknown',
                        'employee_name': row['employee_name'] or 'Unknown',
                        'quality_score': row['call_quality_score'],
                        'quality_reasoning': row['quality_reasoning'] or 'No reasoning provided',
                        'sentiment': row['customer_sentiment'],
                        'call_type': row['call_type'] or 'Unknown',
                        'summary': row['summary'] or 'No summary',
                        'topics': row['key_topics'] or [],
                        'coaching_notes': row['coaching_notes'] or 'None',
                        'improvements': improvements[:5]
                    })

                result['low_quality_calls'] = low_quality_calls
                result['total_low_quality'] = len(low_quality_calls)

                # Quality by agent
                cur.execute("""
                    SELECT
                        COALESCE(NULLIF(t.employee_name, ''), 'Unknown Agent') as employee_name,
                        COUNT(*) as total_calls,
                        ROUND(AVG(i.call_quality_score)::numeric, 1) as avg_quality,
                        SUM(CASE WHEN i.call_quality_score < 5 THEN 1 ELSE 0 END) as low_quality_count,
                        SUM(CASE WHEN i.call_quality_score >= 8 THEN 1 ELSE 0 END) as high_quality_count
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE i.call_quality_score IS NOT NULL
                    GROUP BY COALESCE(NULLIF(t.employee_name, ''), 'Unknown Agent')
                    HAVING COUNT(*) >= 5
                    ORDER BY AVG(i.call_quality_score) ASC
                    LIMIT 15
                """)
                result['quality_by_agent'] = [
                    {
                        'agent': row['employee_name'],
                        'total_calls': row['total_calls'],
                        'avg_quality': float(row['avg_quality']) if row['avg_quality'] else 0,
                        'low_quality_count': row['low_quality_count'],
                        'high_quality_count': row['high_quality_count']
                    }
                    for row in cur.fetchall()
                ]

                # Quality by call type
                cur.execute("""
                    SELECT
                        i.call_type,
                        COUNT(*) as total_calls,
                        ROUND(AVG(i.call_quality_score)::numeric, 1) as avg_quality,
                        SUM(CASE WHEN i.call_quality_score < 5 THEN 1 ELSE 0 END) as low_quality_count
                    FROM insights i
                    WHERE i.call_type IS NOT NULL
                      AND i.call_quality_score IS NOT NULL
                    GROUP BY i.call_type
                    ORDER BY AVG(i.call_quality_score) ASC
                    LIMIT 10
                """)
                result['quality_by_call_type'] = [
                    {
                        'call_type': row['call_type'],
                        'total_calls': row['total_calls'],
                        'avg_quality': float(row['avg_quality']) if row['avg_quality'] else 0,
                        'low_quality_count': row['low_quality_count']
                    }
                    for row in cur.fetchall()
                ]

                # Weekly quality trends
                cur.execute("""
                    SELECT
                        DATE_TRUNC('week', t.call_date) as week,
                        COUNT(*) as total_calls,
                        ROUND(AVG(i.call_quality_score)::numeric, 2) as avg_quality,
                        SUM(CASE WHEN i.call_quality_score < 5 THEN 1 ELSE 0 END) as low_quality,
                        SUM(CASE WHEN i.call_quality_score >= 8 THEN 1 ELSE 0 END) as high_quality
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE t.call_date >= CURRENT_DATE - INTERVAL '90 days'
                      AND i.call_quality_score IS NOT NULL
                    GROUP BY DATE_TRUNC('week', t.call_date)
                    ORDER BY week DESC
                    LIMIT 12
                """)
                result['weekly_trends'] = [
                    {
                        'week': str(row['week'].date()) if row['week'] else 'Unknown',
                        'total': row['total_calls'],
                        'avg_quality': float(row['avg_quality']) if row['avg_quality'] else 0,
                        'low_quality': row['low_quality'],
                        'high_quality': row['high_quality']
                    }
                    for row in cur.fetchall()
                ]

                # Common issues in low quality calls
                cur.execute("""
                    SELECT i.key_topics
                    FROM insights i
                    WHERE i.call_quality_score IS NOT NULL
                      AND i.call_quality_score < 5
                      AND i.key_topics IS NOT NULL
                    LIMIT 50
                """)

                all_topics = []
                for row in cur.fetchall():
                    if row['key_topics'] and isinstance(row['key_topics'], list):
                        all_topics.extend(row['key_topics'])

                from collections import Counter
                topic_counts = Counter(all_topics)
                result['low_quality_topics'] = [{'topic': t, 'count': c} for t, c in topic_counts.most_common(15)]

                return result


if __name__ == "__main__":
    # Test the database reader
    reader = DatabaseReader()

    if reader.test_connection():
        print("Database connection successful!")

        stats = reader.get_statistics()
        print(f"\nDatabase Statistics:")
        print(f"  Total transcripts: {stats['total_transcripts']}")
        print(f"  With insights: {stats['with_insights']}")
        print(f"  With resolutions: {stats['with_resolutions']}")
        print(f"  Date range: {stats['earliest_date']} to {stats['latest_date']}")
    else:
        print("Database connection failed!")
