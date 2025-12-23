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


def get_employee_search_patterns(employee_name: str) -> List[str]:
    """
    Get all search patterns for an employee name.
    Returns LIKE patterns for all name variations.

    Args:
        employee_name: Canonical employee name (e.g., "Robin Montoni")

    Returns:
        List of LIKE patterns (e.g., ["%robin%", "%robin montoni%", "%montoni%"])
    """
    from ..config.employee_names import canonicalize_employee_name, NAME_VARIATIONS

    canonical = canonicalize_employee_name(employee_name) or employee_name

    # Start with the canonical name
    name_variations = set()
    name_variations.add(canonical.lower())

    # Add all known variations that map to this canonical name
    for variation, canon in NAME_VARIATIONS.items():
        if canon == canonical:
            name_variations.add(variation.lower())

    # Also add first name and last name separately
    parts = canonical.split()
    if len(parts) >= 2:
        name_variations.add(parts[0].lower())  # First name
        name_variations.add(parts[-1].lower())  # Last name

    # Create LIKE patterns
    patterns = [f"%{v}%" for v in name_variations]

    return patterns


class DatabaseReader:
    """Read-only access to call recording database."""

    def __init__(self, database_url: Optional[str] = None):
        # Use RAG-specific database URL or default to call_insights
        self.database_url = database_url or os.getenv(
            "RAG_DATABASE_URL",
            
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

    def _build_date_filter(
        self,
        date_range: str = None,
        start_date: str = None,
        end_date: str = None,
        table_alias: str = "t"
    ) -> str:
        """Build SQL date filter clause for queries.

        Args:
            date_range: Preset range ('last_30', 'this_month', 'this_quarter', 'this_year')
            start_date: Custom start date (YYYY-MM-DD)
            end_date: Custom end date (YYYY-MM-DD)
            table_alias: Table alias to use (default 't' for transcripts)

        Returns:
            SQL WHERE clause fragment (e.g., "AND t.call_date >= ...")
        """
        if start_date and end_date:
            return f"AND {table_alias}.call_date >= '{start_date}'::date AND {table_alias}.call_date < '{end_date}'::date + INTERVAL '1 day'"

        if date_range == 'last_30':
            return f"AND {table_alias}.call_date >= CURRENT_DATE - INTERVAL '30 days'"
        elif date_range == 'this_month':
            return f"AND {table_alias}.call_date >= DATE_TRUNC('month', CURRENT_DATE)"
        elif date_range == 'this_quarter':
            return f"AND {table_alias}.call_date >= DATE_TRUNC('quarter', CURRENT_DATE)"
        elif date_range == 'this_year':
            return f"AND {table_alias}.call_date >= DATE_TRUNC('year', CURRENT_DATE)"

        return ""

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
                recent_calls = [
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
                        'call_type': row['call_type'],
                        'source_type': 'call',
                        'source_label': 'Call Recording'
                    }
                    for row in cur.fetchall()
                ]

                # Also get video meetings hosted by this agent
                video_date_filter = date_filter.replace('t.call_date', 'vm.start_time')
                try:
                    cur.execute(f"""
                        SELECT
                            vm.id as video_id,
                            vm.title,
                            vm.start_time,
                            vm.participant_count,
                            vm.overall_sentiment,
                            vm.meeting_quality_score,
                            vm.learning_score,
                            vm.learning_state,
                            vm.churn_risk_level
                        FROM video_meetings vm
                        WHERE (LOWER(vm.host_name) LIKE ANY(%s))
                          AND vm.layer1_complete = TRUE
                        {video_date_filter}
                        ORDER BY vm.start_time DESC
                        LIMIT 10
                    """, (name_patterns,))
                    for row in cur.fetchall():
                        recent_calls.append({
                            'call_id': f"video_{row['video_id']}",
                            'video_id': row['video_id'],
                            'date': str(row['start_time'].date()) if row['start_time'] else 'Unknown',
                            'from_number': 'N/A',
                            'to_number': 'N/A',
                            'customer_name': f"{row['participant_count'] or 0} participants",
                            'company': row['title'] or 'Video Meeting',
                            'summary': f"Learning: {row['learning_state'] or 'N/A'}, Score: {row['learning_score'] or 'N/A'}",
                            'quality': row['meeting_quality_score'],
                            'sentiment': row['overall_sentiment'],
                            'call_type': 'training',
                            'source_type': 'video',
                            'source_label': 'Video Meeting',
                            'learning_score': row['learning_score'],
                            'learning_state': row['learning_state'],
                            'churn_risk': row['churn_risk_level']
                        })
                except Exception as e:
                    logger.warning(f"Video meeting agent query failed: {e}")

                # Sort by date descending
                recent_calls.sort(key=lambda x: x['date'], reverse=True)
                result['recent_calls'] = recent_calls[:15]

                # Get video meeting stats for this agent
                try:
                    cur.execute(f"""
                        SELECT
                            COUNT(*) as total_video_meetings,
                            AVG(vm.meeting_quality_score) as avg_video_quality,
                            AVG(vm.learning_score) as avg_learning_score,
                            COUNT(*) FILTER (WHERE vm.learning_state = 'aha_zone') as aha_moments,
                            COUNT(*) FILTER (WHERE vm.learning_state = 'struggling') as struggling_sessions,
                            COUNT(*) FILTER (WHERE vm.churn_risk_level = 'high') as high_risk_sessions
                        FROM video_meetings vm
                        WHERE (LOWER(vm.host_name) LIKE ANY(%s))
                          AND vm.layer1_complete = TRUE
                        {video_date_filter}
                    """, (name_patterns,))
                    video_stats = cur.fetchone()
                    result['video_meetings'] = {
                        'total': video_stats['total_video_meetings'] or 0,
                        'avg_quality': float(video_stats['avg_video_quality']) if video_stats['avg_video_quality'] else 0,
                        'avg_learning_score': float(video_stats['avg_learning_score']) if video_stats['avg_learning_score'] else 0,
                        'aha_moments': video_stats['aha_moments'] or 0,
                        'struggling_sessions': video_stats['struggling_sessions'] or 0,
                        'high_risk_sessions': video_stats['high_risk_sessions'] or 0
                    }

                    # Learning state distribution for video meetings
                    cur.execute(f"""
                        SELECT vm.learning_state, COUNT(*) as count
                        FROM video_meetings vm
                        WHERE (LOWER(vm.host_name) LIKE ANY(%s))
                          AND vm.learning_state IS NOT NULL
                          AND vm.layer1_complete = TRUE
                        {video_date_filter}
                        GROUP BY vm.learning_state
                    """, (name_patterns,))
                    result['learning_state_distribution'] = {row['learning_state']: row['count'] for row in cur.fetchall()}
                except Exception as e:
                    logger.warning(f"Video meeting stats query failed: {e}")
                    result['video_meetings'] = {'total': 0}
                    result['learning_state_distribution'] = {}

                # Update total calls to include video meetings
                result['total_calls'] = result['total_calls'] + result['video_meetings'].get('total', 0)

                result['agent_name'] = canonical
                result['date_range'] = date_range or 'all_time'

                return result

    def get_churn_risk_data(self, risk_level: str = 'high', date_range: str = None, start_date: str = None, end_date: str = None, employee_filter: str = None) -> Dict[str, Any]:
        """
        Get actual churn risk data from the database.

        Args:
            risk_level: Risk level to filter - 'high', 'medium', or 'all'
            date_range: 'last_30', 'mtd', 'qtd', 'ytd', or None for all time
            start_date: Custom start date (YYYY-MM-DD)
            end_date: Custom end date (YYYY-MM-DD)
            employee_filter: Canonical employee name to filter by (None for admin/all)
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                result = {}

                # Build date filter
                date_filter = ""
                if start_date and end_date:
                    date_filter = f"AND t.call_date >= '{start_date}'::date AND t.call_date < '{end_date}'::date + INTERVAL '1 day'"
                    result['date_range'] = f"{start_date} to {end_date}"
                elif date_range == 'last_30':
                    date_filter = "AND t.call_date >= CURRENT_DATE - INTERVAL '30 days'"
                    result['date_range'] = 'last_30'
                elif date_range == 'mtd':
                    date_filter = "AND t.call_date >= DATE_TRUNC('month', CURRENT_DATE)"
                    result['date_range'] = 'mtd'
                elif date_range == 'qtd':
                    date_filter = "AND t.call_date >= DATE_TRUNC('quarter', CURRENT_DATE)"
                    result['date_range'] = 'qtd'
                elif date_range == 'ytd':
                    date_filter = "AND t.call_date >= DATE_TRUNC('year', CURRENT_DATE)"
                    result['date_range'] = 'ytd'
                else:
                    result['date_range'] = 'all_time'

                # Build employee filter using all name variations
                employee_filter_clause = ""
                employee_params = []
                if employee_filter:
                    employee_patterns = get_employee_search_patterns(employee_filter)
                    employee_filter_clause = "AND (LOWER(t.employee_name) LIKE ANY(%s))"
                    employee_params = [employee_patterns]
                    result['filtered_by'] = employee_filter

                # Build risk filter
                if risk_level == 'high':
                    risk_filter = "cr.churn_risk = 'high'"
                elif risk_level == 'medium':
                    risk_filter = "cr.churn_risk IN ('high', 'medium')"
                else:
                    risk_filter = "cr.churn_risk IS NOT NULL AND cr.churn_risk != 'none' AND cr.churn_risk != 'low'"

                # High risk calls with details (including phone numbers)
                query = f"""
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
                      {date_filter}
                      {employee_filter_clause}
                    ORDER BY
                        CASE cr.churn_risk
                            WHEN 'high' THEN 1
                            WHEN 'medium' THEN 2
                            ELSE 3
                        END,
                        t.call_date DESC
                    LIMIT 50
                """
                cur.execute(query, employee_params if employee_params else None)

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
                        'sentiment': row['customer_sentiment'] or 'unknown',
                        'source_type': 'call',
                        'source_label': 'Call Recording'
                    })

                # Also get video meetings with churn risk
                video_risk_filter = "vm.churn_risk_level = 'high'" if risk_level == 'high' else "vm.churn_risk_level IN ('high', 'medium')" if risk_level == 'medium' else "vm.churn_risk_level IS NOT NULL AND vm.churn_risk_level NOT IN ('none', 'low')"
                video_date_filter = date_filter.replace('t.call_date', 'vm.start_time')
                video_employee_filter = employee_filter_clause.replace('t.employee_name', 'vm.host_name')

                video_query = f"""
                    SELECT
                        vm.id as video_id,
                        vm.title,
                        vm.start_time,
                        vm.host_name,
                        vm.overall_sentiment,
                        vm.sentiment_score,
                        vm.meeting_quality_score,
                        vm.churn_risk_level,
                        vm.learning_state,
                        vm.participant_count
                    FROM video_meetings vm
                    WHERE {video_risk_filter}
                      AND vm.start_time IS NOT NULL
                      AND vm.layer1_complete = TRUE
                      {video_date_filter}
                      {video_employee_filter}
                    ORDER BY
                        CASE vm.churn_risk_level
                            WHEN 'high' THEN 1
                            WHEN 'medium' THEN 2
                            ELSE 3
                        END,
                        vm.start_time DESC
                    LIMIT 50
                """
                try:
                    cur.execute(video_query, employee_params if employee_params else None)
                    for row in cur.fetchall():
                        high_risk_calls.append({
                            'call_id': f"video_{row['video_id']}",
                            'video_id': row['video_id'],
                            'call_date': str(row['start_time'].date()) if row['start_time'] else 'Unknown',
                            'from_number': 'N/A',
                            'to_number': 'N/A',
                            'customer_name': f"{row['participant_count'] or 0} participants",
                            'customer_company': row['title'] or 'Video Meeting',
                            'agent': row['host_name'] or 'Unknown',
                            'quality_score': row['meeting_quality_score'],
                            'risk_level': row['churn_risk_level'] or 'unknown',
                            'summary': f"Video meeting: {row['title']}. Learning state: {row['learning_state'] or 'unknown'}",
                            'topics': [],
                            'issues': [],
                            'sentiment': row['overall_sentiment'] or 'unknown',
                            'source_type': 'video',
                            'source_label': 'Video Meeting'
                        })
                except Exception as e:
                    logger.warning(f"Video meeting churn query failed: {e}")

                # Sort combined results by risk level and date
                high_risk_calls.sort(key=lambda x: (
                    0 if x['risk_level'] == 'high' else 1 if x['risk_level'] == 'medium' else 2,
                    x['call_date']
                ), reverse=False)

                result['high_risk_calls'] = high_risk_calls[:50]  # Limit total
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

    def get_customer_report(self, company_name: str, date_range: str = None, start_date: str = None, end_date: str = None, employee_filter: str = None) -> Dict[str, Any]:
        """
        Get comprehensive report data for a customer company.

        Args:
            company_name: Company name to search for
            date_range: 'last_30', 'mtd', 'qtd', 'ytd', or None for all time
            start_date: Custom start date (YYYY-MM-DD)
            end_date: Custom end date (YYYY-MM-DD)
            employee_filter: Canonical employee name to filter by (None for admin/all)
        """
        from ..config.company_names import get_company_search_patterns, canonicalize_company_name

        patterns = get_company_search_patterns(company_name)
        canonical = canonicalize_company_name(company_name) or company_name

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                result = {'company_name': canonical}

                # Build date filter based on date_range or custom dates
                date_filter = ""
                if start_date and end_date:
                    date_filter = f"AND call_date >= '{start_date}'::date AND call_date < '{end_date}'::date + INTERVAL '1 day'"
                    result['date_range'] = f"{start_date} to {end_date}"
                elif date_range == 'last_30':
                    date_filter = "AND call_date >= CURRENT_DATE - INTERVAL '30 days'"
                    result['date_range'] = 'last_30'
                elif date_range == 'mtd':
                    date_filter = "AND call_date >= DATE_TRUNC('month', CURRENT_DATE)"
                    result['date_range'] = 'mtd'
                elif date_range == 'qtd':
                    date_filter = "AND call_date >= DATE_TRUNC('quarter', CURRENT_DATE)"
                    result['date_range'] = 'qtd'
                elif date_range == 'ytd':
                    date_filter = "AND call_date >= DATE_TRUNC('year', CURRENT_DATE)"
                    result['date_range'] = 'ytd'
                else:
                    result['date_range'] = 'all'

                # Build employee filter using all name variations
                employee_filter_clause = ""
                employee_filter_clause_t = ""
                employee_patterns = None
                if employee_filter:
                    employee_patterns = get_employee_search_patterns(employee_filter)
                    employee_filter_clause = "AND (LOWER(employee_name) LIKE ANY(%s))"
                    employee_filter_clause_t = "AND (LOWER(t.employee_name) LIKE ANY(%s))"
                    result['filtered_by'] = employee_filter

                # Date filter with t. prefix for joined queries
                date_filter_t = date_filter.replace("AND call_date", "AND t.call_date") if date_filter else ""

                # Total calls and contacts
                if employee_patterns:
                    cur.execute(f"""
                        SELECT
                            COUNT(*) as total_calls,
                            COUNT(DISTINCT customer_name) as unique_contacts,
                            MIN(call_date) as first_call,
                            MAX(call_date) as last_call
                        FROM transcripts
                        WHERE LOWER(customer_company) LIKE ANY(%s)
                        {date_filter}
                        {employee_filter_clause}
                    """, (patterns, employee_patterns))
                else:
                    cur.execute(f"""
                        SELECT
                            COUNT(*) as total_calls,
                            COUNT(DISTINCT customer_name) as unique_contacts,
                            MIN(call_date) as first_call,
                            MAX(call_date) as last_call
                        FROM transcripts
                        WHERE LOWER(customer_company) LIKE ANY(%s)
                        {date_filter}
                    """, (patterns,))
                row = cur.fetchone()
                result['total_calls'] = row['total_calls'] if row else 0
                result['unique_contacts'] = row['unique_contacts'] if row else 0
                result['first_call'] = str(row['first_call']) if row and row['first_call'] else None
                result['last_call'] = str(row['last_call']) if row and row['last_call'] else None

                if result['total_calls'] == 0:
                    return result

                # Contact list
                cur.execute(f"""
                    SELECT
                        customer_name,
                        COUNT(*) as call_count,
                        MAX(call_date) as last_call
                    FROM transcripts
                    WHERE LOWER(customer_company) LIKE ANY(%s)
                      AND customer_name IS NOT NULL
                      AND customer_name != ''
                      {date_filter}
                    GROUP BY customer_name
                    ORDER BY call_count DESC
                    LIMIT 10
                """, (patterns,))
                result['contacts'] = [dict(row) for row in cur.fetchall()]

                # Sentiment distribution
                cur.execute(f"""
                    SELECT
                        i.customer_sentiment,
                        COUNT(*) as count
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE LOWER(t.customer_company) LIKE ANY(%s)
                      AND i.customer_sentiment IS NOT NULL
                      {date_filter_t}
                    GROUP BY i.customer_sentiment
                """, (patterns,))
                result['sentiment_distribution'] = {row['customer_sentiment']: row['count'] for row in cur.fetchall()}

                # Quality metrics
                cur.execute(f"""
                    SELECT
                        ROUND(AVG(i.call_quality_score)::numeric, 1) as avg_quality,
                        ROUND(AVG(i.customer_satisfaction_score)::numeric, 1) as avg_satisfaction
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE LOWER(t.customer_company) LIKE ANY(%s)
                    {date_filter_t}
                """, (patterns,))
                row = cur.fetchone()
                result['avg_quality'] = float(row['avg_quality']) if row and row['avg_quality'] else 0
                result['avg_satisfaction'] = float(row['avg_satisfaction']) if row and row['avg_satisfaction'] else 0

                # Churn risk
                cur.execute(f"""
                    SELECT
                        cr.churn_risk,
                        COUNT(*) as count
                    FROM transcripts t
                    JOIN call_resolutions cr ON t.recording_id = cr.recording_id
                    WHERE LOWER(t.customer_company) LIKE ANY(%s)
                      AND cr.churn_risk IS NOT NULL
                      {date_filter_t}
                    GROUP BY cr.churn_risk
                """, (patterns,))
                result['churn_risk_distribution'] = {row['churn_risk']: row['count'] for row in cur.fetchall()}

                # Call types
                cur.execute(f"""
                    SELECT
                        i.call_type,
                        COUNT(*) as count
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE LOWER(t.customer_company) LIKE ANY(%s)
                      AND i.call_type IS NOT NULL
                      {date_filter_t}
                    GROUP BY i.call_type
                    ORDER BY count DESC
                """, (patterns,))
                result['call_types'] = {row['call_type']: row['count'] for row in cur.fetchall()}

                # Agents who handled their calls
                cur.execute(f"""
                    SELECT
                        COALESCE(NULLIF(t.employee_name, ''), 'Unknown Agent') as employee_name,
                        COUNT(*) as call_count
                    FROM transcripts t
                    WHERE LOWER(t.customer_company) LIKE ANY(%s)
                      {date_filter_t}
                    GROUP BY COALESCE(NULLIF(t.employee_name, ''), 'Unknown Agent')
                    ORDER BY call_count DESC
                    LIMIT 5
                """, (patterns,))
                result['agents'] = [
                    {'name': row['employee_name'], 'calls': row['call_count']}
                    for row in cur.fetchall()
                ]

                # Recent calls with summaries
                cur.execute(f"""
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
                    {date_filter_t}
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
                cur.execute(f"""
                    SELECT i.key_topics
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE LOWER(t.customer_company) LIKE ANY(%s)
                      AND i.key_topics IS NOT NULL
                      {date_filter_t}
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


    def get_sentiment_report_data(self, sentiment_filter: str = 'negative', date_range: str = None, start_date: str = None, end_date: str = None, employee_filter: str = None) -> Dict[str, Any]:
        """
        Get actual sentiment data from the database for reporting.

        Args:
            sentiment_filter: 'negative', 'positive', 'all', or 'trends'
            date_range: 'last_30', 'mtd', 'qtd', 'ytd', or None for all time
            start_date: Custom start date (YYYY-MM-DD)
            end_date: Custom end date (YYYY-MM-DD)
            employee_filter: Canonical employee name to filter by (None for admin/all)
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                result = {}

                # Build date filter based on date_range or custom dates
                date_filter = ""
                date_filter_with_t = ""
                if start_date and end_date:
                    date_filter = f"AND i.created_at >= '{start_date}'::date AND i.created_at < '{end_date}'::date + INTERVAL '1 day'"
                    date_filter_with_t = f"AND t.call_date >= '{start_date}'::date AND t.call_date < '{end_date}'::date + INTERVAL '1 day'"
                    result['date_range'] = f"{start_date} to {end_date}"
                elif date_range == 'last_30':
                    date_filter = "AND i.created_at >= CURRENT_DATE - INTERVAL '30 days'"
                    date_filter_with_t = "AND t.call_date >= CURRENT_DATE - INTERVAL '30 days'"
                    result['date_range'] = 'last_30'
                elif date_range == 'mtd':
                    date_filter = "AND i.created_at >= DATE_TRUNC('month', CURRENT_DATE)"
                    date_filter_with_t = "AND t.call_date >= DATE_TRUNC('month', CURRENT_DATE)"
                    result['date_range'] = 'mtd'
                elif date_range == 'qtd':
                    date_filter = "AND i.created_at >= DATE_TRUNC('quarter', CURRENT_DATE)"
                    date_filter_with_t = "AND t.call_date >= DATE_TRUNC('quarter', CURRENT_DATE)"
                    result['date_range'] = 'qtd'
                elif date_range == 'ytd':
                    date_filter = "AND i.created_at >= DATE_TRUNC('year', CURRENT_DATE)"
                    date_filter_with_t = "AND t.call_date >= DATE_TRUNC('year', CURRENT_DATE)"
                    result['date_range'] = 'ytd'
                else:
                    result['date_range'] = 'all_time'

                # Build employee filter using all name variations
                employee_filter_clause = ""
                employee_patterns = None
                if employee_filter:
                    employee_patterns = get_employee_search_patterns(employee_filter)
                    employee_filter_clause = "AND (LOWER(t.employee_name) LIKE ANY(%s))"
                    result['filtered_by'] = employee_filter

                # Build sentiment filter
                if sentiment_filter == 'negative':
                    sentiment_clause = "LOWER(i.customer_sentiment) IN ('negative', 'frustrated', 'angry', 'upset')"
                elif sentiment_filter == 'positive':
                    sentiment_clause = "LOWER(i.customer_sentiment) IN ('positive', 'satisfied', 'happy')"
                else:
                    sentiment_clause = "i.customer_sentiment IS NOT NULL"

                # Overall sentiment distribution
                cur.execute(f"""
                    SELECT
                        i.customer_sentiment,
                        COUNT(*) as count
                    FROM insights i
                    WHERE i.customer_sentiment IS NOT NULL
                    {date_filter}
                    GROUP BY i.customer_sentiment
                    ORDER BY count DESC
                """)
                result['sentiment_distribution'] = {row['customer_sentiment']: row['count'] for row in cur.fetchall()}

                # Calls matching the filter with full details
                query = f"""
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
                      {date_filter_with_t}
                      {employee_filter_clause}
                    ORDER BY
                        CASE
                            WHEN LOWER(i.customer_sentiment) IN ('negative', 'frustrated', 'angry') THEN 1
                            WHEN LOWER(i.customer_sentiment) = 'neutral' THEN 2
                            ELSE 3
                        END,
                        i.call_quality_score ASC NULLS LAST,
                        t.call_date DESC
                    LIMIT 30
                """
                cur.execute(query, [employee_patterns] if employee_patterns else None)

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
                        'issues': row['improvement_suggestions'] or [],
                        'source_type': 'call',
                        'source_label': 'Call Recording'
                    })

                # Add video meetings with matching sentiment
                video_sentiment_clause = "vm.overall_sentiment = 'negative'" if sentiment_filter == 'negative' else "vm.overall_sentiment = 'positive'" if sentiment_filter == 'positive' else "vm.overall_sentiment IS NOT NULL"
                video_date_filter = date_filter_with_t.replace('t.call_date', 'vm.start_time')
                video_employee_filter = employee_filter_clause.replace('t.employee_name', 'vm.host_name')

                try:
                    video_query = f"""
                        SELECT
                            vm.id as video_id,
                            vm.title,
                            vm.start_time,
                            vm.host_name,
                            vm.overall_sentiment,
                            vm.sentiment_score,
                            vm.meeting_quality_score,
                            vm.learning_score,
                            vm.learning_state,
                            vm.churn_risk_level,
                            vm.participant_count
                        FROM video_meetings vm
                        WHERE {video_sentiment_clause}
                          AND vm.start_time IS NOT NULL
                          AND vm.layer1_complete = TRUE
                          {video_date_filter}
                          {video_employee_filter}
                        ORDER BY vm.start_time DESC
                        LIMIT 20
                    """
                    cur.execute(video_query, [employee_patterns] if employee_patterns else None)
                    for row in cur.fetchall():
                        calls.append({
                            'call_id': f"video_{row['video_id']}",
                            'video_id': row['video_id'],
                            'call_date': str(row['start_time'].date()) if row['start_time'] else 'Unknown',
                            'from_number': 'N/A',
                            'to_number': 'N/A',
                            'customer_name': f"{row['participant_count'] or 0} participants",
                            'customer_company': row['title'] or 'Video Meeting',
                            'employee_name': row['host_name'] or 'Unknown',
                            'sentiment': row['overall_sentiment'],
                            'sentiment_reasoning': f"Sentiment score: {row['sentiment_score'] or 'N/A'}",
                            'quality_score': row['meeting_quality_score'],
                            'overall_rating': row['sentiment_score'],
                            'call_type': 'training',
                            'summary': f"Learning state: {row['learning_state'] or 'N/A'}, Score: {row['learning_score'] or 'N/A'}",
                            'topics': [],
                            'coaching_notes': f"Learning score: {row['learning_score'] or 'N/A'}",
                            'churn_risk': row['churn_risk_level'] or 'unknown',
                            'issues': [],
                            'source_type': 'video',
                            'source_label': 'Video Meeting',
                            'learning_score': row['learning_score'],
                            'learning_state': row['learning_state']
                        })
                except Exception as e:
                    logger.warning(f"Video meeting sentiment query failed: {e}")

                # Sort combined results by date
                calls.sort(key=lambda x: x['call_date'], reverse=True)
                result['calls'] = calls[:50]
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
                    WHERE 1=1 {date_filter_with_t}
                    GROUP BY COALESCE(NULLIF(t.employee_name, ''), 'Unknown Agent')
                    HAVING COUNT(*) >= 3
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
                      {date_filter_with_t}
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
                cur.execute(f"""
                    SELECT i.key_topics
                    FROM insights i
                    WHERE LOWER(i.customer_sentiment) IN ('negative', 'frustrated', 'angry')
                      AND i.key_topics IS NOT NULL
                      {date_filter}
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
                cur.execute(f"""
                    SELECT
                        i.call_type,
                        COUNT(*) as count
                    FROM insights i
                    WHERE LOWER(i.customer_sentiment) IN ('negative', 'frustrated', 'angry')
                      AND i.call_type IS NOT NULL
                      {date_filter}
                    GROUP BY i.call_type
                    ORDER BY count DESC
                    LIMIT 10
                """)
                result['negative_call_types'] = {row['call_type']: row['count'] for row in cur.fetchall()}

                # Trend data (by week) - adjust based on date range
                trend_date_filter = date_filter_with_t if date_range else "AND t.call_date >= CURRENT_DATE - INTERVAL '90 days'"
                cur.execute(f"""
                    SELECT
                        DATE_TRUNC('week', t.call_date) as week,
                        COUNT(*) as total_calls,
                        SUM(CASE WHEN LOWER(i.customer_sentiment) IN ('negative', 'frustrated', 'angry') THEN 1 ELSE 0 END) as negative,
                        SUM(CASE WHEN LOWER(i.customer_sentiment) IN ('positive', 'satisfied', 'happy') THEN 1 ELSE 0 END) as positive,
                        SUM(CASE WHEN LOWER(i.customer_sentiment) = 'neutral' THEN 1 ELSE 0 END) as neutral
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE 1=1 {trend_date_filter}
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


    def get_quality_report_data(self, focus: str = 'low_quality', date_range: str = None, start_date: str = None, end_date: str = None, employee_filter: str = None) -> Dict[str, Any]:
        """
        Get call quality data from the database for reporting.

        Args:
            focus: 'low_quality', 'trends', or 'by_type'
            date_range: 'last_30', 'mtd', 'qtd', 'ytd', or None for all time
            start_date: Custom start date (YYYY-MM-DD)
            end_date: Custom end date (YYYY-MM-DD)
            employee_filter: Canonical employee name to filter by (None for admin/all)
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                result = {}

                # Build date filter based on date_range or custom dates
                date_filter = ""
                date_filter_with_t = ""
                if start_date and end_date:
                    date_filter = f"AND i.created_at >= '{start_date}'::date AND i.created_at < '{end_date}'::date + INTERVAL '1 day'"
                    date_filter_with_t = f"AND t.call_date >= '{start_date}'::date AND t.call_date < '{end_date}'::date + INTERVAL '1 day'"
                    result['date_range'] = f"{start_date} to {end_date}"
                elif date_range == 'last_30':
                    date_filter = "AND i.created_at >= CURRENT_DATE - INTERVAL '30 days'"
                    date_filter_with_t = "AND t.call_date >= CURRENT_DATE - INTERVAL '30 days'"
                    result['date_range'] = 'last_30'
                elif date_range == 'mtd':
                    date_filter = "AND i.created_at >= DATE_TRUNC('month', CURRENT_DATE)"
                    date_filter_with_t = "AND t.call_date >= DATE_TRUNC('month', CURRENT_DATE)"
                    result['date_range'] = 'mtd'
                elif date_range == 'qtd':
                    date_filter = "AND i.created_at >= DATE_TRUNC('quarter', CURRENT_DATE)"
                    date_filter_with_t = "AND t.call_date >= DATE_TRUNC('quarter', CURRENT_DATE)"
                    result['date_range'] = 'qtd'
                elif date_range == 'ytd':
                    date_filter = "AND i.created_at >= DATE_TRUNC('year', CURRENT_DATE)"
                    date_filter_with_t = "AND t.call_date >= DATE_TRUNC('year', CURRENT_DATE)"
                    result['date_range'] = 'ytd'
                else:
                    result['date_range'] = 'all_time'

                # Build employee filter using all name variations
                employee_filter_clause = ""
                employee_patterns = None
                if employee_filter:
                    employee_patterns = get_employee_search_patterns(employee_filter)
                    employee_filter_clause = "AND (LOWER(t.employee_name) LIKE ANY(%s))"
                    result['filtered_by'] = employee_filter

                # Overall quality distribution
                cur.execute(f"""
                    SELECT
                        CASE
                            WHEN call_quality_score >= 8 THEN 'Excellent (8-10)'
                            WHEN call_quality_score >= 6 THEN 'Good (6-7)'
                            WHEN call_quality_score >= 4 THEN 'Fair (4-5)'
                            ELSE 'Poor (1-3)'
                        END as quality_tier,
                        COUNT(*) as count,
                        MIN(call_quality_score) as min_score
                    FROM insights i
                    WHERE call_quality_score IS NOT NULL
                    {date_filter}
                    GROUP BY
                        CASE
                            WHEN call_quality_score >= 8 THEN 'Excellent (8-10)'
                            WHEN call_quality_score >= 6 THEN 'Good (6-7)'
                            WHEN call_quality_score >= 4 THEN 'Fair (4-5)'
                            ELSE 'Poor (1-3)'
                        END
                    ORDER BY min_score DESC
                """)
                result['quality_distribution'] = {row['quality_tier']: row['count'] for row in cur.fetchall()}

                # Average quality score
                cur.execute(f"""
                    SELECT
                        ROUND(AVG(call_quality_score)::numeric, 2) as avg_quality,
                        COUNT(*) as total_calls
                    FROM insights i
                    WHERE call_quality_score IS NOT NULL
                    {date_filter}
                """)
                row = cur.fetchone()
                result['avg_quality'] = float(row['avg_quality']) if row and row['avg_quality'] else 0
                result['total_calls_with_quality'] = row['total_calls'] if row else 0

                # Low quality calls (score < 5) with full details
                query = f"""
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
                      {date_filter_with_t}
                      {employee_filter_clause}
                    ORDER BY i.call_quality_score ASC, t.call_date DESC
                    LIMIT 25
                """
                cur.execute(query, [employee_patterns] if employee_patterns else None)

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
                        'improvements': improvements[:5],
                        'source_type': 'call',
                        'source_label': 'Call Recording'
                    })

                # Add low quality video meetings
                video_date_filter = date_filter_with_t.replace('t.call_date', 'vm.start_time')
                video_employee_filter = employee_filter_clause.replace('t.employee_name', 'vm.host_name')

                try:
                    video_query = f"""
                        SELECT
                            vm.id as video_id,
                            vm.title,
                            vm.start_time,
                            vm.host_name,
                            vm.overall_sentiment,
                            vm.meeting_quality_score,
                            vm.learning_score,
                            vm.learning_state,
                            vm.churn_risk_level,
                            vm.participant_count
                        FROM video_meetings vm
                        WHERE vm.meeting_quality_score IS NOT NULL
                          AND vm.meeting_quality_score < 5
                          AND vm.start_time IS NOT NULL
                          AND vm.layer1_complete = TRUE
                          {video_date_filter}
                          {video_employee_filter}
                        ORDER BY vm.meeting_quality_score ASC, vm.start_time DESC
                        LIMIT 15
                    """
                    cur.execute(video_query, [employee_patterns] if employee_patterns else None)
                    for row in cur.fetchall():
                        low_quality_calls.append({
                            'call_id': f"video_{row['video_id']}",
                            'video_id': row['video_id'],
                            'call_date': str(row['start_time'].date()) if row['start_time'] else 'Unknown',
                            'from_number': 'N/A',
                            'to_number': 'N/A',
                            'customer_name': f"{row['participant_count'] or 0} participants",
                            'customer_company': row['title'] or 'Video Meeting',
                            'employee_name': row['host_name'] or 'Unknown',
                            'quality_score': row['meeting_quality_score'],
                            'quality_reasoning': f"Learning state: {row['learning_state'] or 'N/A'}",
                            'sentiment': row['overall_sentiment'],
                            'call_type': 'training',
                            'summary': f"Learning score: {row['learning_score'] or 'N/A'}, State: {row['learning_state'] or 'N/A'}",
                            'topics': [],
                            'coaching_notes': f"Churn risk: {row['churn_risk_level'] or 'N/A'}",
                            'improvements': [],
                            'source_type': 'video',
                            'source_label': 'Video Meeting',
                            'learning_score': row['learning_score'],
                            'learning_state': row['learning_state']
                        })
                except Exception as e:
                    logger.warning(f"Video meeting quality query failed: {e}")

                # Sort by quality score ascending
                low_quality_calls.sort(key=lambda x: x['quality_score'] or 0)
                result['low_quality_calls'] = low_quality_calls[:40]
                result['total_low_quality'] = len(low_quality_calls)

                # Quality by agent
                cur.execute(f"""
                    SELECT
                        COALESCE(NULLIF(t.employee_name, ''), 'Unknown Agent') as employee_name,
                        COUNT(*) as total_calls,
                        ROUND(AVG(i.call_quality_score)::numeric, 1) as avg_quality,
                        SUM(CASE WHEN i.call_quality_score < 5 THEN 1 ELSE 0 END) as low_quality_count,
                        SUM(CASE WHEN i.call_quality_score >= 8 THEN 1 ELSE 0 END) as high_quality_count
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE i.call_quality_score IS NOT NULL
                    {date_filter_with_t}
                    GROUP BY COALESCE(NULLIF(t.employee_name, ''), 'Unknown Agent')
                    HAVING COUNT(*) >= 3
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
                cur.execute(f"""
                    SELECT
                        i.call_type,
                        COUNT(*) as total_calls,
                        ROUND(AVG(i.call_quality_score)::numeric, 1) as avg_quality,
                        SUM(CASE WHEN i.call_quality_score < 5 THEN 1 ELSE 0 END) as low_quality_count
                    FROM insights i
                    WHERE i.call_type IS NOT NULL
                      AND i.call_quality_score IS NOT NULL
                      {date_filter}
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

                # Weekly quality trends - adjust based on date range
                trend_date_filter = date_filter_with_t if date_range else "AND t.call_date >= CURRENT_DATE - INTERVAL '90 days'"
                cur.execute(f"""
                    SELECT
                        DATE_TRUNC('week', t.call_date) as week,
                        COUNT(*) as total_calls,
                        ROUND(AVG(i.call_quality_score)::numeric, 2) as avg_quality,
                        SUM(CASE WHEN i.call_quality_score < 5 THEN 1 ELSE 0 END) as low_quality,
                        SUM(CASE WHEN i.call_quality_score >= 8 THEN 1 ELSE 0 END) as high_quality
                    FROM transcripts t
                    JOIN insights i ON t.recording_id = i.recording_id
                    WHERE i.call_quality_score IS NOT NULL
                      {trend_date_filter}
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
                cur.execute(f"""
                    SELECT i.key_topics
                    FROM insights i
                    WHERE i.call_quality_score IS NOT NULL
                      AND i.call_quality_score < 5
                      AND i.key_topics IS NOT NULL
                      {date_filter}
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

    # ==========================================
    # SALES INTELLIGENCE REPORTS (Layer 5 Data)
    # ==========================================

    def get_sales_pipeline_data(
        self,
        min_score: int = 5,
        date_range: str = None,
        start_date: str = None,
        end_date: str = None,
        employee_filter: str = None
    ) -> Dict[str, Any]:
        """Get sales pipeline data from Layer 5 buying signals."""
        result = {
            'total_opportunities': 0,
            'hot_opportunities': 0,
            'warm_opportunities': 0,
            'opportunities': [],
            'by_signal_strength': {},
            'date_range': date_range or 'all'
        }

        date_filter = self._build_date_filter(date_range, start_date, end_date)
        employee_clause = f"AND t.employee_name ILIKE '%{employee_filter}%'" if employee_filter else ""

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get opportunities with buying signals
                cur.execute(f"""
                    SELECT
                        t.recording_id,
                        t.call_date,
                        t.customer_name,
                        t.customer_company,
                        t.employee_name,
                        t.from_number,
                        i.summary,
                        i.key_topics,
                        m.buying_signals,
                        m.sales_opportunity_score,
                        m.key_quotes
                    FROM transcripts t
                    JOIN call_advanced_metrics m ON t.recording_id = m.recording_id
                    LEFT JOIN insights i ON t.recording_id = i.recording_id
                    WHERE m.sales_opportunity_score >= %s
                    AND t.call_date IS NOT NULL
                    {date_filter}
                    {employee_clause}
                    ORDER BY m.sales_opportunity_score DESC, t.call_date DESC
                    LIMIT 100
                """, (min_score,))

                opportunities = []
                for row in cur.fetchall():
                    opp = dict(row)
                    opp['call_date'] = str(opp['call_date']) if opp['call_date'] else None

                    # Parse buying signals JSONB
                    signals = opp.get('buying_signals', [])
                    if isinstance(signals, str):
                        import json
                        try:
                            signals = json.loads(signals)
                        except:
                            signals = []

                    opp['buying_signals'] = signals if isinstance(signals, list) else []
                    opp['signal_count'] = len(opp['buying_signals'])
                    opportunities.append(opp)

                result['opportunities'] = opportunities
                result['total_opportunities'] = len(opportunities)
                result['hot_opportunities'] = len([o for o in opportunities if o['sales_opportunity_score'] >= 8])
                result['warm_opportunities'] = len([o for o in opportunities if 5 <= o['sales_opportunity_score'] < 8])

                # Distribution by score
                cur.execute(f"""
                    SELECT
                        CASE
                            WHEN sales_opportunity_score >= 8 THEN 'hot'
                            WHEN sales_opportunity_score >= 5 THEN 'warm'
                            ELSE 'cold'
                        END as category,
                        COUNT(*) as count
                    FROM call_advanced_metrics m
                    JOIN transcripts t ON m.recording_id = t.recording_id
                    WHERE t.call_date IS NOT NULL
                    {date_filter}
                    {employee_clause}
                    GROUP BY category
                """)
                result['by_signal_strength'] = {row['category']: row['count'] for row in cur.fetchall()}

                return result

    def get_competitor_intelligence_data(
        self,
        competitor: str = None,
        date_range: str = None,
        start_date: str = None,
        end_date: str = None,
        employee_filter: str = None
    ) -> Dict[str, Any]:
        """Get competitor intelligence from Layer 5 data."""
        result = {
            'total_mentions': 0,
            'competitor_counts': {},
            'mentions': [],
            'switching_analysis': {'from': {}, 'to': {}},
            'date_range': date_range or 'all'
        }

        date_filter = self._build_date_filter(date_range, start_date, end_date)
        employee_clause = f"AND t.employee_name ILIKE '%{employee_filter}%'" if employee_filter else ""

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get all mentions
                cur.execute(f"""
                    SELECT
                        t.recording_id,
                        t.call_date,
                        t.customer_name,
                        t.customer_company,
                        t.employee_name,
                        i.summary,
                        m.competitor_intelligence,
                        m.key_quotes
                    FROM transcripts t
                    JOIN call_advanced_metrics m ON t.recording_id = m.recording_id
                    LEFT JOIN insights i ON t.recording_id = i.recording_id
                    WHERE m.competitor_intelligence IS NOT NULL
                    AND m.competitor_intelligence != '{{}}'::jsonb
                    AND m.competitor_intelligence != '{{"competitors": []}}'::jsonb
                    AND t.call_date IS NOT NULL
                    {date_filter}
                    {employee_clause}
                    ORDER BY t.call_date DESC
                    LIMIT 100
                """)

                mentions = []
                competitor_counts = {}

                for row in cur.fetchall():
                    mention = dict(row)
                    mention['call_date'] = str(mention['call_date']) if mention['call_date'] else None

                    # Parse competitor_intelligence JSONB
                    intel = mention.get('competitor_intelligence', {})
                    if isinstance(intel, str):
                        import json
                        try:
                            intel = json.loads(intel)
                        except:
                            intel = {}

                    competitors_list = intel.get('competitors', [])
                    if competitors_list:
                        mention['competitors'] = competitors_list
                        mentions.append(mention)

                        # Count competitors
                        for comp in competitors_list:
                            if comp:
                                competitor_counts[comp] = competitor_counts.get(comp, 0) + 1

                result['mentions'] = mentions
                result['total_mentions'] = len(mentions)
                result['competitor_counts'] = dict(sorted(competitor_counts.items(), key=lambda x: x[1], reverse=True))

                return result

    def get_compliance_risk_data(
        self,
        max_score: int = 70,
        risk_level: str = None,
        date_range: str = None,
        start_date: str = None,
        end_date: str = None,
        employee_filter: str = None
    ) -> Dict[str, Any]:
        """Get compliance and risk data from Layer 5."""
        result = {
            'total_issues': 0,
            'critical_count': 0,
            'high_count': 0,
            'medium_count': 0,
            'issues': [],
            'by_agent': [],
            'avg_compliance_score': 0,
            'date_range': date_range or 'all'
        }

        date_filter = self._build_date_filter(date_range, start_date, end_date)
        employee_clause = f"AND t.employee_name ILIKE '%{employee_filter}%'" if employee_filter else ""

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get low compliance calls
                cur.execute(f"""
                    SELECT
                        t.recording_id,
                        t.call_date,
                        t.customer_name,
                        t.customer_company,
                        t.employee_name,
                        t.from_number,
                        i.summary,
                        m.compliance,
                        m.compliance_score,
                        m.key_quotes
                    FROM transcripts t
                    JOIN call_advanced_metrics m ON t.recording_id = m.recording_id
                    LEFT JOIN insights i ON t.recording_id = i.recording_id
                    WHERE m.compliance_score <= %s
                    AND m.compliance_score > 0
                    AND t.call_date IS NOT NULL
                    {date_filter}
                    {employee_clause}
                    ORDER BY m.compliance_score ASC, t.call_date DESC
                    LIMIT 100
                """, (max_score,))

                issues = []
                for row in cur.fetchall():
                    issue = dict(row)
                    issue['call_date'] = str(issue['call_date']) if issue['call_date'] else None

                    # Determine risk level
                    score = issue.get('compliance_score', 50)
                    if score < 40:
                        issue['risk_level'] = 'critical'
                    elif score < 60:
                        issue['risk_level'] = 'high'
                    else:
                        issue['risk_level'] = 'medium'

                    issues.append(issue)

                result['issues'] = issues
                result['total_issues'] = len(issues)
                result['critical_count'] = len([i for i in issues if i['risk_level'] == 'critical'])
                result['high_count'] = len([i for i in issues if i['risk_level'] == 'high'])
                result['medium_count'] = len([i for i in issues if i['risk_level'] == 'medium'])

                # Compliance by agent
                cur.execute(f"""
                    SELECT
                        t.employee_name as agent,
                        COUNT(*) as total_calls,
                        ROUND(AVG(m.compliance_score), 1) as avg_compliance,
                        COUNT(CASE WHEN m.compliance_score < 50 THEN 1 END) as low_compliance_count
                    FROM transcripts t
                    JOIN call_advanced_metrics m ON t.recording_id = m.recording_id
                    WHERE t.employee_name IS NOT NULL
                    AND t.employee_name != 'Unknown'
                    AND t.call_date IS NOT NULL
                    AND m.compliance_score > 0
                    {date_filter}
                    {employee_clause}
                    GROUP BY t.employee_name
                    HAVING COUNT(CASE WHEN m.compliance_score < 50 THEN 1 END) > 0
                    ORDER BY avg_compliance ASC
                    LIMIT 20
                """)
                result['by_agent'] = [dict(row) for row in cur.fetchall()]

                # Average compliance score
                cur.execute(f"""
                    SELECT ROUND(AVG(m.compliance_score), 1) as avg
                    FROM call_advanced_metrics m
                    JOIN transcripts t ON m.recording_id = t.recording_id
                    WHERE m.compliance_score > 0
                    AND t.call_date IS NOT NULL
                    {date_filter}
                    {employee_clause}
                """)
                row = cur.fetchone()
                result['avg_compliance_score'] = row['avg'] if row and row['avg'] else 0

                return result

    def get_urgency_queue_data(
        self,
        min_score: int = 7,
        sla_risk_only: bool = False,
        date_range: str = None,
        start_date: str = None,
        end_date: str = None,
        employee_filter: str = None
    ) -> Dict[str, Any]:
        """Get urgency queue data from Layer 5."""
        result = {
            'total_urgent': 0,
            'immediate_action': 0,
            'high_priority': 0,
            'urgent_calls': [],
            'by_urgency_level': {},
            'date_range': date_range or 'all'
        }

        date_filter = self._build_date_filter(date_range, start_date, end_date)
        employee_clause = f"AND t.employee_name ILIKE '%{employee_filter}%'" if employee_filter else ""

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get urgent calls
                cur.execute(f"""
                    SELECT
                        t.recording_id,
                        t.call_date,
                        t.call_time,
                        t.customer_name,
                        t.customer_company,
                        t.employee_name,
                        t.from_number,
                        i.summary,
                        i.follow_up_needed,
                        m.urgency,
                        m.urgency_score,
                        cr.resolution_status
                    FROM transcripts t
                    JOIN call_advanced_metrics m ON t.recording_id = m.recording_id
                    LEFT JOIN insights i ON t.recording_id = i.recording_id
                    LEFT JOIN call_resolutions cr ON t.recording_id = cr.recording_id
                    WHERE m.urgency_score >= %s
                    AND t.call_date IS NOT NULL
                    {date_filter}
                    {employee_clause}
                    ORDER BY m.urgency_score DESC, t.call_date DESC
                    LIMIT 100
                """, (min_score,))

                urgent_calls = []
                for row in cur.fetchall():
                    call = dict(row)
                    call['call_date'] = str(call['call_date']) if call['call_date'] else None
                    call['call_time'] = str(call['call_time']) if call['call_time'] else None

                    # Parse urgency JSONB
                    urgency = call.get('urgency', {})
                    if isinstance(urgency, str):
                        import json
                        try:
                            urgency = json.loads(urgency)
                        except:
                            urgency = {}

                    call['urgency_level'] = urgency.get('level', 'medium')
                    urgent_calls.append(call)

                result['urgent_calls'] = urgent_calls
                result['total_urgent'] = len(urgent_calls)
                result['immediate_action'] = len([c for c in urgent_calls if c['urgency_score'] >= 9])
                result['high_priority'] = len([c for c in urgent_calls if 7 <= c['urgency_score'] < 9])

                # Distribution by urgency level
                cur.execute(f"""
                    SELECT
                        CASE
                            WHEN urgency_score >= 9 THEN 'critical'
                            WHEN urgency_score >= 7 THEN 'high'
                            WHEN urgency_score >= 5 THEN 'medium'
                            ELSE 'low'
                        END as level,
                        COUNT(*) as count
                    FROM call_advanced_metrics m
                    JOIN transcripts t ON m.recording_id = t.recording_id
                    WHERE t.call_date IS NOT NULL
                    {date_filter}
                    {employee_clause}
                    GROUP BY level
                    ORDER BY count DESC
                """)
                result['by_urgency_level'] = {row['level']: row['count'] for row in cur.fetchall()}

                return result

    def get_key_quotes_data(
        self,
        search_term: str = None,
        quote_type: str = None,
        date_range: str = None,
        start_date: str = None,
        end_date: str = None,
        employee_filter: str = None
    ) -> Dict[str, Any]:
        """Get key quotes from Layer 5 data."""
        result = {
            'total_quotes': 0,
            'quotes': [],
            'by_type': {},
            'date_range': date_range or 'all'
        }

        date_filter = self._build_date_filter(date_range, start_date, end_date)
        employee_clause = f"AND t.employee_name ILIKE '%{employee_filter}%'" if employee_filter else ""
        search_clause = f"AND m.key_quotes::text ILIKE '%{search_term}%'" if search_term else ""

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get calls with key quotes
                cur.execute(f"""
                    SELECT
                        t.recording_id,
                        t.call_date,
                        t.customer_name,
                        t.customer_company,
                        t.employee_name,
                        i.summary,
                        i.customer_sentiment,
                        m.key_quotes,
                        m.buying_signals,
                        m.sales_opportunity_score
                    FROM transcripts t
                    JOIN call_advanced_metrics m ON t.recording_id = m.recording_id
                    LEFT JOIN insights i ON t.recording_id = i.recording_id
                    WHERE m.key_quotes IS NOT NULL
                    AND m.key_quotes != '[]'::jsonb
                    AND t.call_date IS NOT NULL
                    {date_filter}
                    {employee_clause}
                    {search_clause}
                    ORDER BY t.call_date DESC
                    LIMIT 100
                """)

                quotes_list = []
                for row in cur.fetchall():
                    record = dict(row)
                    record['call_date'] = str(record['call_date']) if record['call_date'] else None

                    # Parse key_quotes JSONB - handle both list and dict structures
                    quotes_raw = record.get('key_quotes', [])
                    if isinstance(quotes_raw, str):
                        import json
                        try:
                            quotes_raw = json.loads(quotes_raw)
                        except:
                            quotes_raw = []

                    # Extract quotes - can be a list directly or a dict with 'key_quotes' key
                    if isinstance(quotes_raw, dict):
                        quotes = quotes_raw.get('key_quotes', []) or quotes_raw.get('quotes', [])
                    elif isinstance(quotes_raw, list):
                        quotes = quotes_raw
                    else:
                        quotes = []

                    if quotes and isinstance(quotes, list):
                        for quote in quotes:
                            quote_entry = {
                                'recording_id': record['recording_id'],
                                'call_date': record['call_date'],
                                'customer_name': record['customer_name'],
                                'customer_company': record['customer_company'],
                                'employee_name': record['employee_name'],
                                'sentiment': record['customer_sentiment'],
                                'quote': quote if isinstance(quote, str) else str(quote)
                            }
                            quotes_list.append(quote_entry)

                result['quotes'] = quotes_list[:200]  # Limit to 200 quotes
                result['total_quotes'] = len(quotes_list)

                return result

    def get_qa_training_data(
        self,
        category: str = None,
        quality: str = None,
        faq_only: bool = False,
        date_range: str = None,
        start_date: str = None,
        end_date: str = None,
        employee_filter: str = None
    ) -> Dict[str, Any]:
        """Get Q&A training data from Layer 5."""
        result = {
            'total_qa_pairs': 0,
            'faq_candidates': 0,
            'unanswered': 0,
            'qa_pairs': [],
            'by_category': {},
            'potential_kb_articles': [],
            'date_range': date_range or 'all'
        }

        date_filter = self._build_date_filter(date_range, start_date, end_date)
        employee_clause = f"AND t.employee_name ILIKE '%{employee_filter}%'" if employee_filter else ""

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get calls with Q&A pairs
                cur.execute(f"""
                    SELECT
                        t.recording_id,
                        t.call_date,
                        t.customer_name,
                        t.customer_company,
                        t.employee_name,
                        m.qa_pairs
                    FROM transcripts t
                    JOIN call_advanced_metrics m ON t.recording_id = m.recording_id
                    WHERE m.qa_pairs IS NOT NULL
                    AND m.qa_pairs != '{{}}'::jsonb
                    AND t.call_date IS NOT NULL
                    {date_filter}
                    {employee_clause}
                    ORDER BY t.call_date DESC
                    LIMIT 200
                """)

                all_qa_pairs = []
                category_counts = {}
                kb_articles = {}

                for row in cur.fetchall():
                    record = dict(row)
                    record['call_date'] = str(record['call_date']) if record['call_date'] else None

                    # Parse qa_pairs JSONB
                    qa_data = record.get('qa_pairs', {})
                    if isinstance(qa_data, str):
                        import json
                        try:
                            qa_data = json.loads(qa_data)
                        except:
                            qa_data = {}

                    # Extract Q&A pairs - handle both 'qa_pairs' and 'pairs' keys
                    if isinstance(qa_data, dict):
                        pairs = qa_data.get('qa_pairs', []) or qa_data.get('pairs', [])
                    else:
                        pairs = []

                    for pair in pairs:
                        if isinstance(pair, dict) and pair.get('question') and pair.get('answer'):
                            qa_entry = {
                                'recording_id': record['recording_id'],
                                'call_date': record['call_date'],
                                'customer_company': record['customer_company'],
                                'employee_name': record['employee_name'],
                                'question': pair.get('question', ''),
                                'answer': pair.get('answer', ''),
                                'category': pair.get('category', pair.get('topic', 'other')),
                                'answer_quality': pair.get('answer_quality', 'unknown'),
                                'could_be_faq': pair.get('could_be_faq', False)
                            }

                            # Apply filters
                            if category and qa_entry['category'] != category:
                                continue
                            if quality and qa_entry['answer_quality'] != quality:
                                continue
                            if faq_only and not qa_entry['could_be_faq']:
                                continue

                            all_qa_pairs.append(qa_entry)

                            # Count categories
                            cat = qa_entry['category']
                            category_counts[cat] = category_counts.get(cat, 0) + 1

                    # Extract potential KB articles
                    kb_list = qa_data.get('potential_kb_articles', []) if isinstance(qa_data, dict) else []
                    for article in kb_list:
                        if article:
                            kb_articles[article] = kb_articles.get(article, 0) + 1

                result['qa_pairs'] = all_qa_pairs[:100]  # Limit to 100
                result['total_qa_pairs'] = len(all_qa_pairs)
                result['faq_candidates'] = len([q for q in all_qa_pairs if q.get('could_be_faq')])
                result['unanswered'] = len([q for q in all_qa_pairs if q.get('answer_quality') == 'unanswered'])
                result['by_category'] = category_counts
                result['potential_kb_articles'] = [
                    {'article': a, 'count': c}
                    for a, c in sorted(kb_articles.items(), key=lambda x: x[1], reverse=True)[:20]
                ]

                return result

    # ============================================================================
    # VIDEO MEETING METHODS
    # ============================================================================

    def get_video_meetings(
        self,
        limit: int = 50,
        offset: int = 0,
        meeting_type: str = None,
        trainer: str = None,
        sentiment: str = None,
        learning_state: str = None,
        date_range: str = None,
        start_date: str = None,
        end_date: str = None
    ) -> Dict[str, Any]:
        """Get video meetings with filters."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Build WHERE clause
                conditions = ["source = 'ringcentral'", "transcript_text IS NOT NULL"]
                params = []

                if meeting_type:
                    conditions.append("meeting_type = %s")
                    params.append(meeting_type)

                if trainer:
                    conditions.append("host_name ILIKE %s")
                    params.append(f"%{trainer}%")

                if sentiment:
                    conditions.append("overall_sentiment = %s")
                    params.append(sentiment)

                if learning_state:
                    conditions.append("learning_state = %s")
                    params.append(learning_state)

                # Date filter
                if start_date and end_date:
                    conditions.append("start_time >= %s AND start_time < %s + INTERVAL '1 day'")
                    params.extend([start_date, end_date])
                elif date_range == 'last_30':
                    conditions.append("start_time >= CURRENT_DATE - INTERVAL '30 days'")
                elif date_range == 'this_month':
                    conditions.append("start_time >= DATE_TRUNC('month', CURRENT_DATE)")

                where_clause = " AND ".join(conditions)

                # Get total count
                cur.execute(f"SELECT COUNT(*) FROM video_meetings WHERE {where_clause}", params)
                total = cur.fetchone()['count']

                # Get meetings
                query = f"""
                    SELECT id, title, host_name, host_email, start_time, duration_seconds,
                           meeting_type, participant_count, overall_sentiment, sentiment_score,
                           meeting_quality_score, churn_risk_level, learning_score, learning_state,
                           layer1_complete, layer2_complete, layer3_complete, layer4_complete,
                           layer5_complete, layer6_complete
                    FROM video_meetings
                    WHERE {where_clause}
                    ORDER BY start_time DESC
                    LIMIT %s OFFSET %s
                """
                params.extend([limit, offset])
                cur.execute(query, params)
                meetings = cur.fetchall()

                return {
                    'meetings': [dict(m) for m in meetings],
                    'total': total,
                    'limit': limit,
                    'offset': offset
                }

    def get_video_meeting_detail(self, meeting_id: int) -> Optional[Dict[str, Any]]:
        """Get full video meeting details including participants and analysis."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get meeting
                cur.execute("""
                    SELECT id, title, host_name, host_email, start_time, end_time,
                           duration_seconds, meeting_type, recording_url, transcript_text,
                           participant_count, internal_participant_count, external_participant_count,
                           overall_sentiment, sentiment_score, meeting_quality_score,
                           churn_risk_level, learning_score, learning_state,
                           ai_analysis_json, created_at, updated_at
                    FROM video_meetings
                    WHERE id = %s
                """, [meeting_id])
                meeting = cur.fetchone()

                if not meeting:
                    return None

                result = dict(meeting)

                # Get participants
                cur.execute("""
                    SELECT participant_name, participant_email, company_name, role_type,
                           is_internal, is_trainer, is_trainee, speaking_time_percentage,
                           questions_asked, engagement_level
                    FROM video_meeting_participants
                    WHERE meeting_id = %s
                    ORDER BY speaking_time_percentage DESC NULLS LAST
                """, [meeting_id])
                result['participants'] = [dict(p) for p in cur.fetchall()]

                # Get Q&A pairs
                cur.execute("""
                    SELECT question, answer, category, quality
                    FROM video_meeting_qa_pairs
                    WHERE video_meeting_id = %s
                    ORDER BY created_at
                """, [meeting_id])
                result['qa_pairs'] = [dict(qa) for qa in cur.fetchall()]

                return result

    def get_video_meeting_stats(self) -> Dict[str, Any]:
        """Get video meeting statistics."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) as total_meetings,
                        COUNT(*) FILTER (WHERE transcript_text IS NOT NULL) as transcribed,
                        COUNT(*) FILTER (WHERE layer1_complete = TRUE) as analyzed,
                        COUNT(*) FILTER (WHERE learning_state IS NOT NULL) as with_learning,
                        AVG(duration_seconds)::int as avg_duration,
                        AVG(sentiment_score) as avg_sentiment,
                        AVG(meeting_quality_score) as avg_quality,
                        AVG(learning_score) as avg_learning,
                        COUNT(DISTINCT host_name) as unique_hosts
                    FROM video_meetings
                    WHERE source = 'ringcentral'
                """)
                stats = dict(cur.fetchone())

                # Sentiment distribution
                cur.execute("""
                    SELECT overall_sentiment, COUNT(*) as count
                    FROM video_meetings
                    WHERE source = 'ringcentral' AND overall_sentiment IS NOT NULL
                    GROUP BY overall_sentiment
                """)
                stats['sentiment_distribution'] = {r['overall_sentiment']: r['count'] for r in cur.fetchall()}

                # Learning state distribution
                cur.execute("""
                    SELECT learning_state, COUNT(*) as count
                    FROM video_meetings
                    WHERE source = 'ringcentral' AND learning_state IS NOT NULL
                    GROUP BY learning_state
                """)
                stats['learning_distribution'] = {r['learning_state']: r['count'] for r in cur.fetchall()}

                # Top trainers
                cur.execute("""
                    SELECT host_name, COUNT(*) as meeting_count,
                           AVG(meeting_quality_score) as avg_quality
                    FROM video_meetings
                    WHERE source = 'ringcentral' AND host_name IS NOT NULL
                    GROUP BY host_name
                    ORDER BY meeting_count DESC
                    LIMIT 10
                """)
                stats['top_trainers'] = [dict(r) for r in cur.fetchall()]

                return stats

    def get_video_training_report(
        self,
        trainer: str = None,
        date_range: str = None,
        start_date: str = None,
        end_date: str = None
    ) -> Dict[str, Any]:
        """Get training effectiveness report from video meetings."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                conditions = ["source = 'ringcentral'", "layer6_complete = TRUE"]
                params = []

                if trainer:
                    conditions.append("host_name ILIKE %s")
                    params.append(f"%{trainer}%")

                if start_date and end_date:
                    conditions.append("start_time >= %s AND start_time < %s + INTERVAL '1 day'")
                    params.extend([start_date, end_date])
                elif date_range == 'last_30':
                    conditions.append("start_time >= CURRENT_DATE - INTERVAL '30 days'")

                where_clause = " AND ".join(conditions)

                # Overall metrics
                cur.execute(f"""
                    SELECT
                        COUNT(*) as total_sessions,
                        AVG(learning_score) as avg_learning_score,
                        AVG(meeting_quality_score) as avg_quality,
                        AVG(sentiment_score) as avg_satisfaction,
                        COUNT(*) FILTER (WHERE learning_state = 'aha_zone') as aha_moments,
                        COUNT(*) FILTER (WHERE learning_state = 'struggling') as struggling,
                        COUNT(*) FILTER (WHERE churn_risk_level = 'high') as high_risk
                    FROM video_meetings
                    WHERE {where_clause}
                """, params)
                metrics = dict(cur.fetchone())

                # Learning state breakdown
                cur.execute(f"""
                    SELECT learning_state, COUNT(*) as count
                    FROM video_meetings
                    WHERE {where_clause} AND learning_state IS NOT NULL
                    GROUP BY learning_state
                """, params)
                metrics['learning_states'] = {r['learning_state']: r['count'] for r in cur.fetchall()}

                # Recent sessions with issues
                cur.execute(f"""
                    SELECT id, title, host_name, start_time, learning_state,
                           learning_score, churn_risk_level
                    FROM video_meetings
                    WHERE {where_clause}
                      AND (learning_state IN ('struggling', 'overwhelmed') OR churn_risk_level = 'high')
                    ORDER BY start_time DESC
                    LIMIT 10
                """, params)
                metrics['attention_needed'] = [dict(r) for r in cur.fetchall()]

                # Q&A insights
                cur.execute(f"""
                    SELECT qa.category, COUNT(*) as count
                    FROM video_meeting_qa_pairs qa
                    JOIN video_meetings vm ON qa.video_meeting_id = vm.id
                    WHERE {where_clause.replace('source', 'vm.source').replace('layer6_complete', 'vm.layer6_complete').replace('host_name', 'vm.host_name').replace('start_time', 'vm.start_time')}
                    GROUP BY qa.category
                    ORDER BY count DESC
                    LIMIT 10
                """, params)
                metrics['top_question_categories'] = [dict(r) for r in cur.fetchall()]

                return metrics

    def get_learning_module_stats(self) -> Dict[str, Any]:
        """Get learning module statistics from video meetings."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Overall stats
                cur.execute("""
                    SELECT
                        COUNT(*) as total_sessions,
                        AVG(learning_score) as avg_learning_score,
                        COUNT(*) FILTER (WHERE learning_state = 'aha_zone') as aha_moments,
                        COUNT(*) FILTER (WHERE learning_state IN ('struggling', 'overwhelmed')) as struggling,
                        COUNT(*) FILTER (WHERE churn_risk_level = 'high') as high_churn_risk
                    FROM video_meetings
                    WHERE source = 'ringcentral' AND layer1_complete = TRUE
                """)
                stats = dict(cur.fetchone())

                # Q&A pair count
                cur.execute("""
                    SELECT COUNT(*) as qa_pairs
                    FROM video_meeting_qa_pairs
                """)
                stats['qa_pairs'] = cur.fetchone()['qa_pairs'] or 0

                # Learning state distribution
                cur.execute("""
                    SELECT learning_state, COUNT(*) as count
                    FROM video_meetings
                    WHERE source = 'ringcentral' AND learning_state IS NOT NULL
                    GROUP BY learning_state
                    ORDER BY count DESC
                """)
                stats['learning_distribution'] = {r['learning_state']: r['count'] for r in cur.fetchall()}

                # Top trainers by learning impact
                cur.execute("""
                    SELECT host_name,
                           COUNT(*) as session_count,
                           AVG(learning_score) as avg_learning,
                           AVG(meeting_quality_score) as avg_quality
                    FROM video_meetings
                    WHERE source = 'ringcentral'
                      AND host_name IS NOT NULL
                      AND learning_score IS NOT NULL
                    GROUP BY host_name
                    HAVING COUNT(*) >= 2
                    ORDER BY AVG(learning_score) DESC
                    LIMIT 10
                """)
                stats['top_trainers'] = [dict(r) for r in cur.fetchall()]

                # Top Q&A categories
                cur.execute("""
                    SELECT category, COUNT(*) as count
                    FROM video_meeting_qa_pairs
                    WHERE category IS NOT NULL
                    GROUP BY category
                    ORDER BY count DESC
                    LIMIT 8
                """)
                stats['top_categories'] = [dict(r) for r in cur.fetchall()]

                return stats

    def get_learning_attention_needed(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get video meetings that need attention (struggling, overwhelmed, high churn)."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, title, host_name, start_time, learning_state,
                           learning_score, churn_risk_level, overall_sentiment
                    FROM video_meetings
                    WHERE source = 'ringcentral'
                      AND layer1_complete = TRUE
                      AND (learning_state IN ('struggling', 'overwhelmed')
                           OR churn_risk_level = 'high')
                    ORDER BY start_time DESC
                    LIMIT %s
                """, [limit])
                return [dict(r) for r in cur.fetchall()]

    # ==========================================
    # COACHING & LEARNING FEED
    # ==========================================

    def get_coaching_feed(
        self,
        employee_name: str = None,
        limit: int = 50,
        include_calls: bool = True,
        include_video: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get combined coaching data from calls and video meetings.
        Returns a unified format with strengths, improvements, and suggested phrases.
        """
        results = []

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get call coaching data
                if include_calls:
                    employee_filter = ""
                    if employee_name:
                        patterns = get_employee_search_patterns(employee_name)
                        pattern_clauses = " OR ".join([f"t.employee_name ILIKE %s" for _ in patterns])
                        employee_filter = f"AND ({pattern_clauses})"

                    query = f"""
                        SELECT
                            t.recording_id,
                            t.call_date as interaction_date,
                            t.employee_name,
                            t.customer_name,
                            t.customer_company,
                            i.call_quality_score,
                            i.customer_sentiment,
                            i.summary,
                            rec.employee_strengths,
                            rec.employee_improvements,
                            rec.suggested_phrases,
                            rec.coaching_session_topics,
                            rec.communication_effectiveness_score,
                            rec.problem_solving_score,
                            rec.customer_advocacy_score,
                            res.customer_effort_score,
                            res.empathy_score,
                            res.active_listening_score,
                            res.done_well,
                            res.improvement_suggestions,
                            res.closure_score,
                            res.churn_risk
                        FROM transcripts t
                        LEFT JOIN insights i ON t.recording_id = i.recording_id
                        LEFT JOIN call_recommendations rec ON t.recording_id = rec.recording_id
                        LEFT JOIN call_resolutions res ON t.recording_id = res.recording_id
                        WHERE t.call_date IS NOT NULL
                          AND (rec.employee_strengths IS NOT NULL
                               OR rec.employee_improvements IS NOT NULL
                               OR res.done_well IS NOT NULL)
                          {employee_filter}
                        ORDER BY t.call_date DESC
                        LIMIT %s
                    """

                    params = []
                    if employee_name:
                        params.extend(patterns)
                    params.append(limit)

                    cur.execute(query, params)

                    for row in cur.fetchall():
                        # Combine strengths from both tables
                        strengths = []
                        if row['employee_strengths']:
                            strengths.extend(row['employee_strengths'])
                        if row['done_well']:
                            strengths.extend(row['done_well'])

                        # Combine improvements
                        improvements = []
                        if row['employee_improvements']:
                            improvements.extend(row['employee_improvements'])
                        if row['improvement_suggestions']:
                            improvements.extend(row['improvement_suggestions'])

                        results.append({
                            'id': row['recording_id'],
                            'source_type': 'call',
                            'source_label': 'Phone Call',
                            'date': str(row['interaction_date']) if row['interaction_date'] else None,
                            'employee_name': row['employee_name'],
                            'customer_name': row['customer_name'],
                            'customer_company': row['customer_company'],
                            'summary': row['summary'],
                            'quality_score': float(row['call_quality_score']) if row['call_quality_score'] else None,
                            'sentiment': row['customer_sentiment'],
                            'churn_risk': row['churn_risk'],
                            # Coaching data
                            'strengths': strengths[:5],  # Limit to top 5
                            'improvements': improvements[:3],  # Limit to 3 (growth-focused)
                            'suggested_phrases': row['suggested_phrases'] or [],
                            'coaching_topics': row['coaching_session_topics'] or [],
                            # Scores
                            'customer_effort_score': float(row['customer_effort_score']) if row['customer_effort_score'] else None,
                            'empathy_score': float(row['empathy_score']) if row['empathy_score'] else None,
                            'communication_score': float(row['communication_effectiveness_score']) if row['communication_effectiveness_score'] else None,
                            'problem_solving_score': float(row['problem_solving_score']) if row['problem_solving_score'] else None,
                            'closure_score': float(row['closure_score']) if row['closure_score'] else None,
                        })

                # Get video meeting coaching data
                if include_video:
                    video_employee_filter = ""
                    if employee_name:
                        patterns = get_employee_search_patterns(employee_name)
                        pattern_clauses = " OR ".join([f"host_name ILIKE %s" for _ in patterns])
                        video_employee_filter = f"AND ({pattern_clauses})"

                    video_query = f"""
                        SELECT
                            id,
                            title,
                            start_time as interaction_date,
                            host_name as employee_name,
                            overall_sentiment,
                            meeting_quality_score,
                            learning_score,
                            learning_state,
                            churn_risk_level,
                            ai_analysis_json
                        FROM video_meetings
                        WHERE source = 'ringcentral'
                          AND layer1_complete = TRUE
                          AND ai_analysis_json IS NOT NULL
                          {video_employee_filter}
                        ORDER BY start_time DESC
                        LIMIT %s
                    """

                    video_params = []
                    if employee_name:
                        video_params.extend(patterns)
                    video_params.append(limit)

                    cur.execute(video_query, video_params)

                    for row in cur.fetchall():
                        ai_data = row['ai_analysis_json'] or {}
                        layer6 = ai_data.get('layer6_learning', {})
                        layer4 = ai_data.get('layer4_recommendations', {})

                        coaching = layer6.get('coaching_recommendations', {})
                        trainer_coaching = layer4.get('trainer_coaching', {})

                        # Extract coaching data
                        strengths = trainer_coaching.get('strengths', [])
                        improvements = trainer_coaching.get('improvements', [])
                        for_trainer = coaching.get('for_trainer', [])
                        for_trainee = coaching.get('for_trainee', [])

                        # Combine all improvements
                        all_improvements = improvements + for_trainer + for_trainee

                        results.append({
                            'id': row['id'],
                            'source_type': 'video',
                            'source_label': 'Video Meeting',
                            'date': str(row['interaction_date']) if row['interaction_date'] else None,
                            'employee_name': row['employee_name'],
                            'title': row['title'],
                            'summary': ai_data.get('fathom_summary', ''),
                            'quality_score': float(row['meeting_quality_score']) if row['meeting_quality_score'] else None,
                            'sentiment': row['overall_sentiment'],
                            'churn_risk': row['churn_risk_level'],
                            'learning_score': float(row['learning_score']) if row['learning_score'] else None,
                            'learning_state': row['learning_state'],
                            # Coaching data
                            'strengths': strengths[:5],
                            'improvements': all_improvements[:3],
                            'suggested_phrases': [],
                            'coaching_topics': trainer_coaching.get('coaching_priorities', []),
                            # Teaching analysis scores
                            'teaching_clarity': layer6.get('trainer_teaching_analysis', {}).get('teaching_clarity'),
                            'pacing_score': layer6.get('trainer_teaching_analysis', {}).get('pacing_score'),
                            'scaffolding_quality': layer6.get('trainer_teaching_analysis', {}).get('scaffolding_quality'),
                        })

        # Sort combined results by date
        results.sort(key=lambda x: x['date'] or '', reverse=True)
        return results[:limit]

    def get_employee_coaching_progress(
        self,
        employee_name: str,
        period: str = 'mtd'
    ) -> Dict[str, Any]:
        """
        Track coaching metrics and improvement trends for an employee.
        """
        result = {
            'employee_name': employee_name,
            'period': period,
            'total_interactions': 0,
            'calls': 0,
            'video_meetings': 0,
            'avg_quality_score': None,
            'avg_effort_score': None,
            'avg_empathy_score': None,
            'churn_risk_distribution': {},
            'top_strengths': [],
            'areas_for_growth': [],
            'score_trends': []
        }

        # Build date filter based on period
        if period == 'today':
            date_filter = "AND call_date >= CURRENT_DATE"
            video_date_filter = "AND start_time >= CURRENT_DATE"
        elif period == 'wtd':
            date_filter = "AND call_date >= DATE_TRUNC('week', CURRENT_DATE)"
            video_date_filter = "AND start_time >= DATE_TRUNC('week', CURRENT_DATE)"
        elif period == 'mtd':
            date_filter = "AND call_date >= DATE_TRUNC('month', CURRENT_DATE)"
            video_date_filter = "AND start_time >= DATE_TRUNC('month', CURRENT_DATE)"
        elif period == 'qtd':
            date_filter = "AND call_date >= DATE_TRUNC('quarter', CURRENT_DATE)"
            video_date_filter = "AND start_time >= DATE_TRUNC('quarter', CURRENT_DATE)"
        else:  # 'all' or default
            date_filter = ""
            video_date_filter = ""

        patterns = get_employee_search_patterns(employee_name)

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Call metrics
                pattern_clauses = " OR ".join([f"t.employee_name ILIKE %s" for _ in patterns])

                cur.execute(f"""
                    SELECT
                        COUNT(*) as call_count,
                        AVG(i.call_quality_score) as avg_quality,
                        AVG(res.customer_effort_score) as avg_effort,
                        AVG(res.empathy_score) as avg_empathy,
                        AVG(rec.communication_effectiveness_score) as avg_communication
                    FROM transcripts t
                    LEFT JOIN insights i ON t.recording_id = i.recording_id
                    LEFT JOIN call_resolutions res ON t.recording_id = res.recording_id
                    LEFT JOIN call_recommendations rec ON t.recording_id = rec.recording_id
                    WHERE ({pattern_clauses})
                    {date_filter}
                """, patterns)

                call_stats = cur.fetchone()
                result['calls'] = call_stats['call_count'] or 0
                result['avg_quality_score'] = float(call_stats['avg_quality']) if call_stats['avg_quality'] else None
                result['avg_effort_score'] = float(call_stats['avg_effort']) if call_stats['avg_effort'] else None
                result['avg_empathy_score'] = float(call_stats['avg_empathy']) if call_stats['avg_empathy'] else None

                # Video meeting metrics
                video_pattern_clauses = " OR ".join([f"host_name ILIKE %s" for _ in patterns])

                cur.execute(f"""
                    SELECT
                        COUNT(*) as video_count,
                        AVG(meeting_quality_score) as avg_quality,
                        AVG(learning_score) as avg_learning
                    FROM video_meetings
                    WHERE source = 'ringcentral'
                      AND ({video_pattern_clauses})
                      {video_date_filter}
                """, patterns)

                video_stats = cur.fetchone()
                result['video_meetings'] = video_stats['video_count'] or 0
                result['total_interactions'] = result['calls'] + result['video_meetings']

                # Aggregate top strengths from calls
                cur.execute(f"""
                    SELECT rec.employee_strengths
                    FROM transcripts t
                    JOIN call_recommendations rec ON t.recording_id = rec.recording_id
                    WHERE ({pattern_clauses})
                      AND rec.employee_strengths IS NOT NULL
                    {date_filter}
                    LIMIT 20
                """, patterns)

                all_strengths = []
                for row in cur.fetchall():
                    if row['employee_strengths']:
                        all_strengths.extend(row['employee_strengths'])

                from collections import Counter
                strength_counts = Counter(all_strengths)
                result['top_strengths'] = [s for s, _ in strength_counts.most_common(5)]

                # Aggregate areas for growth
                cur.execute(f"""
                    SELECT rec.employee_improvements
                    FROM transcripts t
                    JOIN call_recommendations rec ON t.recording_id = rec.recording_id
                    WHERE ({pattern_clauses})
                      AND rec.employee_improvements IS NOT NULL
                    {date_filter}
                    LIMIT 20
                """, patterns)

                all_improvements = []
                for row in cur.fetchall():
                    if row['employee_improvements']:
                        all_improvements.extend(row['employee_improvements'])

                improvement_counts = Counter(all_improvements)
                result['areas_for_growth'] = [i for i, _ in improvement_counts.most_common(3)]

                # Churn risk distribution
                cur.execute(f"""
                    SELECT res.churn_risk, COUNT(*) as count
                    FROM transcripts t
                    JOIN call_resolutions res ON t.recording_id = res.recording_id
                    WHERE ({pattern_clauses})
                      AND res.churn_risk IS NOT NULL
                    {date_filter}
                    GROUP BY res.churn_risk
                """, patterns)

                result['churn_risk_distribution'] = {row['churn_risk']: row['count'] for row in cur.fetchall()}

                # Weekly score trends
                cur.execute(f"""
                    SELECT
                        DATE_TRUNC('week', t.call_date) as week,
                        AVG(i.call_quality_score) as avg_quality,
                        AVG(res.customer_effort_score) as avg_effort,
                        COUNT(*) as call_count
                    FROM transcripts t
                    LEFT JOIN insights i ON t.recording_id = i.recording_id
                    LEFT JOIN call_resolutions res ON t.recording_id = res.recording_id
                    WHERE ({pattern_clauses})
                      AND t.call_date >= CURRENT_DATE - INTERVAL '12 weeks'
                    GROUP BY DATE_TRUNC('week', t.call_date)
                    ORDER BY week DESC
                    LIMIT 12
                """, patterns)

                result['score_trends'] = [
                    {
                        'week': str(row['week'].date()) if row['week'] else None,
                        'avg_quality': float(row['avg_quality']) if row['avg_quality'] else None,
                        'avg_effort': float(row['avg_effort']) if row['avg_effort'] else None,
                        'count': row['call_count']
                    }
                    for row in cur.fetchall()
                ]

                return result

    def get_coaching_queue(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get interactions that need coaching attention.
        Includes low-quality calls, high customer effort, struggling learners.
        """
        results = []

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Low quality or high effort calls needing attention
                cur.execute("""
                    SELECT
                        t.recording_id as id,
                        'call' as source_type,
                        'Phone Call' as source_label,
                        t.call_date as interaction_date,
                        t.employee_name,
                        t.customer_name,
                        i.call_quality_score as quality_score,
                        res.customer_effort_score,
                        res.churn_risk,
                        i.customer_sentiment as sentiment,
                        rec.employee_improvements as improvements,
                        CASE
                            WHEN res.churn_risk = 'high' THEN 'High Churn Risk'
                            WHEN res.customer_effort_score > 7 THEN 'High Customer Effort'
                            WHEN i.call_quality_score < 5 THEN 'Low Quality Score'
                            ELSE 'Needs Review'
                        END as attention_reason
                    FROM transcripts t
                    LEFT JOIN insights i ON t.recording_id = i.recording_id
                    LEFT JOIN call_resolutions res ON t.recording_id = res.recording_id
                    LEFT JOIN call_recommendations rec ON t.recording_id = rec.recording_id
                    WHERE t.call_date >= CURRENT_DATE - INTERVAL '30 days'
                      AND (
                          res.churn_risk = 'high'
                          OR res.customer_effort_score > 7
                          OR i.call_quality_score < 5
                          OR i.customer_sentiment = 'negative'
                      )
                    ORDER BY t.call_date DESC
                    LIMIT %s
                """, [limit])

                for row in cur.fetchall():
                    results.append({
                        'id': row['id'],
                        'source_type': row['source_type'],
                        'source_label': row['source_label'],
                        'date': str(row['interaction_date']) if row['interaction_date'] else None,
                        'employee_name': row['employee_name'],
                        'customer_name': row['customer_name'],
                        'quality_score': float(row['quality_score']) if row['quality_score'] else None,
                        'customer_effort_score': float(row['customer_effort_score']) if row['customer_effort_score'] else None,
                        'churn_risk': row['churn_risk'],
                        'sentiment': row['sentiment'],
                        'attention_reason': row['attention_reason'],
                        'improvements': row['improvements'] or []
                    })

                # Struggling video meetings
                cur.execute("""
                    SELECT
                        id,
                        'video' as source_type,
                        'Video Meeting' as source_label,
                        start_time as interaction_date,
                        host_name as employee_name,
                        title,
                        meeting_quality_score as quality_score,
                        learning_score,
                        learning_state,
                        churn_risk_level as churn_risk,
                        overall_sentiment as sentiment,
                        CASE
                            WHEN churn_risk_level = 'high' THEN 'High Churn Risk'
                            WHEN learning_state = 'overwhelmed' THEN 'Trainee Overwhelmed'
                            WHEN learning_state = 'struggling' THEN 'Trainee Struggling'
                            WHEN meeting_quality_score < 5 THEN 'Low Quality Score'
                            ELSE 'Needs Review'
                        END as attention_reason
                    FROM video_meetings
                    WHERE source = 'ringcentral'
                      AND layer1_complete = TRUE
                      AND start_time >= CURRENT_DATE - INTERVAL '30 days'
                      AND (
                          churn_risk_level = 'high'
                          OR learning_state IN ('struggling', 'overwhelmed')
                          OR meeting_quality_score < 5
                          OR overall_sentiment = 'negative'
                      )
                    ORDER BY start_time DESC
                    LIMIT %s
                """, [limit])

                for row in cur.fetchall():
                    results.append({
                        'id': row['id'],
                        'source_type': row['source_type'],
                        'source_label': row['source_label'],
                        'date': str(row['interaction_date']) if row['interaction_date'] else None,
                        'employee_name': row['employee_name'],
                        'title': row['title'],
                        'quality_score': float(row['quality_score']) if row['quality_score'] else None,
                        'learning_score': float(row['learning_score']) if row['learning_score'] else None,
                        'learning_state': row['learning_state'],
                        'churn_risk': row['churn_risk'],
                        'sentiment': row['sentiment'],
                        'attention_reason': row['attention_reason']
                    })

        # Sort by date
        results.sort(key=lambda x: x['date'] or '', reverse=True)
        return results[:limit]

    def get_coaching_summary_stats(self) -> Dict[str, Any]:
        """Get overall coaching statistics combining calls and video meetings."""
        stats = {
            'total_interactions': 0,
            'total_calls': 0,
            'total_video_meetings': 0,
            'avg_quality_score': None,
            'avg_customer_effort': None,
            'needs_attention_count': 0,
            'high_performers_count': 0,
            'churn_risk_high': 0,
            'sentiment_distribution': {},
            'top_coaching_topics': []
        }

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Call stats
                cur.execute("""
                    SELECT
                        COUNT(*) as call_count,
                        AVG(i.call_quality_score) as avg_quality,
                        AVG(res.customer_effort_score) as avg_effort,
                        SUM(CASE WHEN res.churn_risk = 'high' THEN 1 ELSE 0 END) as high_churn,
                        SUM(CASE WHEN i.call_quality_score >= 8 THEN 1 ELSE 0 END) as high_performers,
                        SUM(CASE WHEN i.call_quality_score < 5 OR res.customer_effort_score > 7 THEN 1 ELSE 0 END) as needs_attention
                    FROM transcripts t
                    LEFT JOIN insights i ON t.recording_id = i.recording_id
                    LEFT JOIN call_resolutions res ON t.recording_id = res.recording_id
                    WHERE t.call_date >= CURRENT_DATE - INTERVAL '30 days'
                """)

                call_stats = cur.fetchone()
                stats['total_calls'] = call_stats['call_count'] or 0
                stats['avg_quality_score'] = float(call_stats['avg_quality']) if call_stats['avg_quality'] else None
                stats['avg_customer_effort'] = float(call_stats['avg_effort']) if call_stats['avg_effort'] else None
                stats['churn_risk_high'] = call_stats['high_churn'] or 0
                stats['high_performers_count'] = call_stats['high_performers'] or 0
                stats['needs_attention_count'] = call_stats['needs_attention'] or 0

                # Video meeting stats
                cur.execute("""
                    SELECT
                        COUNT(*) as video_count,
                        SUM(CASE WHEN churn_risk_level = 'high' THEN 1 ELSE 0 END) as high_churn,
                        SUM(CASE WHEN learning_state IN ('struggling', 'overwhelmed') THEN 1 ELSE 0 END) as struggling
                    FROM video_meetings
                    WHERE source = 'ringcentral'
                      AND layer1_complete = TRUE
                      AND start_time >= CURRENT_DATE - INTERVAL '30 days'
                """)

                video_stats = cur.fetchone()
                stats['total_video_meetings'] = video_stats['video_count'] or 0
                stats['churn_risk_high'] += video_stats['high_churn'] or 0
                stats['needs_attention_count'] += video_stats['struggling'] or 0
                stats['total_interactions'] = stats['total_calls'] + stats['total_video_meetings']

                # Sentiment distribution (calls only for now)
                cur.execute("""
                    SELECT customer_sentiment, COUNT(*) as count
                    FROM insights i
                    JOIN transcripts t ON i.recording_id = t.recording_id
                    WHERE t.call_date >= CURRENT_DATE - INTERVAL '30 days'
                      AND customer_sentiment IS NOT NULL
                    GROUP BY customer_sentiment
                """)

                stats['sentiment_distribution'] = {row['customer_sentiment']: row['count'] for row in cur.fetchall()}

                # Top coaching topics
                cur.execute("""
                    SELECT coaching_session_topics
                    FROM call_recommendations
                    WHERE coaching_session_topics IS NOT NULL
                      AND array_length(coaching_session_topics, 1) > 0
                    LIMIT 100
                """)

                all_topics = []
                for row in cur.fetchall():
                    if row['coaching_session_topics']:
                        all_topics.extend(row['coaching_session_topics'])

                from collections import Counter
                topic_counts = Counter(all_topics)
                stats['top_coaching_topics'] = [{'topic': t, 'count': c} for t, c in topic_counts.most_common(10)]

                return stats


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
