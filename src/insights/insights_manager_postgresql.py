"""
Enhanced Insights Manager for PostgreSQL
Provides comprehensive querying capabilities for the new database schema
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import json
import logging

logger = logging.getLogger(__name__)

class PostgreSQLInsightsManager:
    """Manages call insights using PostgreSQL with comprehensive tracking"""

    def __init__(self):
        """Initialize the PostgreSQL connection"""
        self.db_config = {
            'dbname': 'call_insights',
            'user': 'call_insights_user',
            'password': os.getenv('PG_PASSWORD', ''),
            'host': 'localhost',
            'port': 5432
        }
        logger.info("PostgreSQL Insights Manager initialized")

    def get_connection(self):
        """Get a new database connection"""
        return psycopg2.connect(**self.db_config, cursor_factory=RealDictCursor)

    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Get comprehensive dashboard statistics"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # Overall statistics
            cursor.execute("""
                SELECT
                    COUNT(*) as total_recordings,
                    SUM(CASE WHEN pipeline_stage = 'downloaded' THEN 1 ELSE 0 END) as downloaded,
                    SUM(CASE WHEN pipeline_stage = 'transcribed' THEN 1 ELSE 0 END) as transcribed,
                    SUM(CASE WHEN pipeline_stage = 'insights_generated' THEN 1 ELSE 0 END) as with_insights,
                    SUM(CASE WHEN pipeline_stage = 'uploaded' THEN 1 ELSE 0 END) as uploaded,
                    SUM(CASE WHEN audio_file_size IS NOT NULL THEN audio_file_size ELSE 0 END) as total_bytes,
                    SUM(CASE WHEN audio_deleted = true THEN 1 ELSE 0 END) as audio_deleted,
                    AVG(CASE WHEN word_count > 0 THEN word_count ELSE NULL END) as avg_word_count
                FROM transcripts
            """)
            overall_stats = cursor.fetchone()

            # Processing queue status
            cursor.execute("""
                SELECT
                    current_stage,
                    COUNT(*) as count
                FROM processing_status
                GROUP BY current_stage
            """)
            queue_stats = cursor.fetchall()

            # Recent activity
            cursor.execute("""
                SELECT
                    DATE(created_at) as date,
                    COUNT(*) as recordings_added
                FROM transcripts
                WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
                GROUP BY DATE(created_at)
                ORDER BY date DESC
            """)
            recent_activity = cursor.fetchall()

            # Quality metrics
            cursor.execute("""
                SELECT
                    AVG(call_quality_score) as avg_quality,
                    AVG(customer_satisfaction_score) as avg_satisfaction,
                    COUNT(CASE WHEN customer_sentiment = 'positive' THEN 1 END) as positive_calls,
                    COUNT(CASE WHEN customer_sentiment = 'neutral' THEN 1 END) as neutral_calls,
                    COUNT(CASE WHEN customer_sentiment = 'negative' THEN 1 END) as negative_calls
                FROM insights
            """)
            quality_metrics = cursor.fetchone()

            return {
                'overall': overall_stats,
                'queue': queue_stats,
                'recent_activity': recent_activity,
                'quality_metrics': quality_metrics,
                'last_updated': datetime.now().isoformat()
            }

        finally:
            cursor.close()
            conn.close()

    def query_insights(self,
                       start_date: Optional[str] = None,
                       end_date: Optional[str] = None,
                       customer_name: Optional[str] = None,
                       employee_name: Optional[str] = None,
                       sentiment: Optional[str] = None,
                       call_type: Optional[str] = None,
                       search_term: Optional[str] = None,
                       min_quality_score: Optional[float] = None,
                       sort_by: Optional[str] = None,
                       sort_order: str = 'DESC',
                       limit: int = 100) -> List[Dict[str, Any]]:
        """Query insights with comprehensive filtering"""

        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # Build the query
            query = """
                SELECT
                    t.recording_id,
                    t.customer_name,
                    t.employee_name,
                    t.call_date,
                    t.duration_seconds,
                    t.word_count,
                    t.pipeline_stage,
                    i.customer_sentiment,
                    i.call_quality_score,
                    i.customer_satisfaction_score,
                    i.call_type,
                    i.issue_category,
                    i.summary,
                    i.key_topics,
                    i.action_items,
                    t.google_drive_url,
                    ps.transcribed,
                    ps.insights_generated,
                    ps.uploaded_to_gdrive
                FROM transcripts t
                LEFT JOIN insights i ON t.recording_id = i.recording_id
                LEFT JOIN processing_status ps ON t.recording_id = ps.recording_id
                WHERE 1=1
            """

            params = []

            # Date filtering
            if start_date:
                query += " AND t.call_date >= %s"
                params.append(start_date)
            if end_date:
                query += " AND t.call_date <= %s"
                params.append(end_date)

            # Customer/Employee filtering
            if customer_name:
                query += " AND t.customer_name ILIKE %s"
                params.append(f"%{customer_name}%")
            if employee_name:
                query += " AND t.employee_name ILIKE %s"
                params.append(f"%{employee_name}%")

            # Quality filtering
            if sentiment:
                query += " AND i.customer_sentiment = %s"
                params.append(sentiment)
            if call_type:
                query += " AND i.call_type = %s"
                params.append(call_type)
            if min_quality_score:
                query += " AND i.call_quality_score >= %s"
                params.append(min_quality_score)

            # Full-text search
            if search_term:
                query += """ AND (
                    t.transcript_text ILIKE %s OR
                    i.summary ILIKE %s OR
                    array_to_string(i.key_topics, ' ') ILIKE %s
                )"""
                search_pattern = f"%{search_term}%"
                params.extend([search_pattern, search_pattern, search_pattern])

            # Sorting
            sort_column = {
                'date': 't.call_date',
                'duration': 't.duration_seconds',
                'quality': 'i.call_quality_score',
                'satisfaction': 'i.customer_satisfaction_score',
                'words': 't.word_count'
            }.get(sort_by, 't.call_date')

            query += f" ORDER BY {sort_column} {sort_order} NULLS LAST"
            query += f" LIMIT {limit}"

            cursor.execute(query, params)
            results = cursor.fetchall()

            # Convert to list of dicts and format
            insights = []
            for row in results:
                insight = dict(row)
                # Format dates
                if insight.get('call_date'):
                    insight['call_date'] = insight['call_date'].isoformat()
                insights.append(insight)

            return insights

        finally:
            cursor.close()
            conn.close()

    def get_pipeline_status(self) -> Dict[str, Any]:
        """Get detailed pipeline processing status"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT
                    ps.current_stage,
                    COUNT(*) as count,
                    SUM(CASE WHEN ps.downloaded THEN 1 ELSE 0 END) as downloaded,
                    SUM(CASE WHEN ps.transcribed THEN 1 ELSE 0 END) as transcribed,
                    SUM(CASE WHEN ps.insights_generated THEN 1 ELSE 0 END) as insights_generated,
                    SUM(CASE WHEN ps.uploaded_to_gdrive THEN 1 ELSE 0 END) as uploaded,
                    SUM(CASE WHEN ps.audio_deleted THEN 1 ELSE 0 END) as audio_deleted,
                    ROUND(SUM(ps.audio_file_size)/1024/1024/1024.0, 2) as gb_used
                FROM processing_status ps
                GROUP BY ps.current_stage
                ORDER BY
                    CASE ps.current_stage
                        WHEN 'downloaded' THEN 1
                        WHEN 'transcribed' THEN 2
                        WHEN 'insights_generated' THEN 3
                        WHEN 'uploaded' THEN 4
                        ELSE 5
                    END
            """)

            pipeline_data = cursor.fetchall()

            # Get queue sizes
            cursor.execute("""
                SELECT
                    (SELECT COUNT(*) FROM processing_status WHERE downloaded = true AND transcribed = false) as transcription_queue,
                    (SELECT COUNT(*) FROM processing_status WHERE transcribed = true AND insights_generated = false) as insights_queue,
                    (SELECT COUNT(*) FROM processing_status WHERE insights_generated = true AND uploaded_to_gdrive = false) as upload_queue,
                    (SELECT COUNT(*) FROM processing_status WHERE error_count > 0) as error_count
            """)

            queue_sizes = cursor.fetchone()

            return {
                'stages': pipeline_data,
                'queues': queue_sizes,
                'timestamp': datetime.now().isoformat()
            }

        finally:
            cursor.close()
            conn.close()

    def get_recent_recordings(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get most recent recordings with their status"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT
                    t.recording_id,
                    t.customer_name,
                    t.employee_name,
                    t.call_date,
                    t.duration_seconds,
                    t.word_count,
                    t.pipeline_stage,
                    t.created_at,
                    ps.current_stage,
                    ps.transcribed,
                    ps.insights_generated,
                    ps.uploaded_to_gdrive,
                    i.customer_sentiment,
                    i.call_quality_score
                FROM transcripts t
                LEFT JOIN processing_status ps ON t.recording_id = ps.recording_id
                LEFT JOIN insights i ON t.recording_id = i.recording_id
                ORDER BY t.created_at DESC
                LIMIT %s
            """, (limit,))

            results = cursor.fetchall()

            recordings = []
            for row in results:
                rec = dict(row)
                # Format dates
                if rec.get('call_date'):
                    rec['call_date'] = rec['call_date'].isoformat()
                if rec.get('created_at'):
                    rec['created_at'] = rec['created_at'].isoformat()
                recordings.append(rec)

            return recordings

        finally:
            cursor.close()
            conn.close()

    def get_analytics(self, days: int = 30) -> Dict[str, Any]:
        """Get analytics data for charts and graphs"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # Daily volume
            cursor.execute("""
                SELECT
                    DATE(created_at) as date,
                    COUNT(*) as recordings,
                    SUM(CASE WHEN pipeline_stage = 'transcribed' THEN 1 ELSE 0 END) as transcribed,
                    SUM(CASE WHEN has_ai_insights THEN 1 ELSE 0 END) as with_insights
                FROM transcripts
                WHERE created_at >= CURRENT_DATE - INTERVAL '%s days'
                GROUP BY DATE(created_at)
                ORDER BY date
            """, (days,))
            daily_volume = cursor.fetchall()

            # Sentiment distribution
            cursor.execute("""
                SELECT
                    customer_sentiment,
                    COUNT(*) as count
                FROM insights
                WHERE customer_sentiment IS NOT NULL
                GROUP BY customer_sentiment
            """)
            sentiment_dist = cursor.fetchall()

            # Call types
            cursor.execute("""
                SELECT
                    call_type,
                    COUNT(*) as count
                FROM insights
                WHERE call_type IS NOT NULL
                GROUP BY call_type
                ORDER BY count DESC
                LIMIT 10
            """)
            call_types = cursor.fetchall()

            # Top employees by volume
            cursor.execute("""
                SELECT
                    employee_name,
                    COUNT(*) as call_count,
                    AVG(i.call_quality_score) as avg_quality
                FROM transcripts t
                LEFT JOIN insights i ON t.recording_id = i.recording_id
                WHERE employee_name IS NOT NULL
                GROUP BY employee_name
                ORDER BY call_count DESC
                LIMIT 10
            """)
            top_employees = cursor.fetchall()

            return {
                'daily_volume': daily_volume,
                'sentiment_distribution': sentiment_dist,
                'call_types': call_types,
                'top_employees': top_employees
            }

        finally:
            cursor.close()
            conn.close()

    def search_transcripts(self, search_query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Full-text search across transcripts"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT
                    t.recording_id,
                    t.customer_name,
                    t.employee_name,
                    t.call_date,
                    ts_headline('english', t.transcript_text, query, 'MaxWords=50') as excerpt,
                    t.word_count,
                    i.customer_sentiment,
                    i.summary
                FROM transcripts t
                LEFT JOIN insights i ON t.recording_id = i.recording_id,
                to_tsquery('english', %s) query
                WHERE to_tsvector('english', t.transcript_text) @@ query
                ORDER BY ts_rank(to_tsvector('english', t.transcript_text), query) DESC
                LIMIT %s
            """, (search_query.replace(' ', ' & '), limit))

            results = cursor.fetchall()

            search_results = []
            for row in results:
                result = dict(row)
                if result.get('call_date'):
                    result['call_date'] = result['call_date'].isoformat()
                search_results.append(result)

            return search_results

        finally:
            cursor.close()
            conn.close()

    def get_transcript(self, recording_id: str) -> Optional[Dict[str, Any]]:
        """Get the full transcript for a recording"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT
                    t.recording_id,
                    t.transcript_text,
                    t.customer_name,
                    t.employee_name,
                    t.call_date,
                    t.duration_seconds,
                    t.word_count,
                    t.pipeline_stage,
                    t.created_at,
                    i.summary,
                    i.customer_sentiment,
                    i.call_quality_score
                FROM transcripts t
                LEFT JOIN insights i ON t.recording_id = i.recording_id
                WHERE t.recording_id = %s
            """, (recording_id,))

            result = cursor.fetchone()

            if result:
                transcript = dict(result)
                # Format dates
                if transcript.get('call_date'):
                    transcript['call_date'] = transcript['call_date'].isoformat()
                if transcript.get('created_at'):
                    transcript['created_at'] = transcript['created_at'].isoformat()
                return transcript

            return None

        finally:
            cursor.close()
            conn.close()

# Singleton instance
_insights_manager = None

def get_postgresql_insights_manager():
    """Get or create the PostgreSQL insights manager instance"""
    global _insights_manager
    if _insights_manager is None:
        _insights_manager = PostgreSQLInsightsManager()
    return _insights_manager