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
