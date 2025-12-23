"""
Simple Knowledge Base Service
Searches RAG for Q&A pairs from Layer 5 data, logs searches, collects feedback
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class SimpleKBService:
    """Simple Knowledge Base - searches RAG, logs everything, collects feedback."""

    def __init__(self, connection_string: str = None):
        """Initialize with database connection"""
        import os
        self.connection_string = connection_string or os.getenv(
            "RAG_DATABASE_URL",
            
        )

    @contextmanager
    def get_connection(self):
        """Get database connection"""
        conn = psycopg2.connect(self.connection_string)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def search(self, query: str, agent_id: str = None) -> Dict:
        """
        Search RAG for Q&A matches from Layer 5 data.
        Logs the search and returns results with source info.
        """
        import os
        from .gemini_file_search import GeminiFileSearchService

        gemini_api_key = os.getenv('GEMINI_API_KEY')
        gemini_store = os.getenv('GEMINI_FILE_SEARCH_STORE', 'mst_call_intelligence')

        # Build a Q&A-focused RAG query
        rag_query = f"""
Search the call transcripts for solutions to this question: "{query}"

Find Q&A pairs from call resolutions where similar problems were solved.
For each result, provide:
1. The original problem/question that was asked
2. The solution/answer that resolved it
3. Who provided the solution (employee name)
4. The customer who had the issue
5. When it was resolved (call date)

Return the most relevant solutions with specific details.
Format each result clearly with Problem, Solution, Resolved By, Customer, and Date.
"""

        try:
            # Use Gemini for semantic search
            gemini = GeminiFileSearchService(
                gemini_api_key,
                gemini_store
            ) if gemini_api_key else None

            # Also search the database directly for structured Q&A
            db_results = self._search_database(query)

            # Query RAG if available
            rag_response = ''
            if gemini:
                try:
                    rag_result = gemini.query(rag_query)
                    rag_response = rag_result.get('response', '')
                except Exception as e:
                    logger.warning(f"Gemini query failed: {e}")

            # Combine results with deduplication
            results = []
            seen_questions = set()  # Track unique question+person combinations

            def normalize_question(q):
                """Normalize question for deduplication."""
                if not q:
                    return ''
                # Lowercase, strip whitespace, remove punctuation
                import re
                return re.sub(r'[^\w\s]', '', q.lower().strip())

            def get_dedup_key(question, person):
                """Create deduplication key from question and person."""
                norm_q = normalize_question(question)
                norm_p = (person or 'unknown').lower().strip()
                return f"{norm_q}|{norm_p}"

            # Add database results first (these have structured data)
            for row in db_results[:20]:  # Process more to allow for dedup filtering
                source_type = row.get('source_type', 'call')
                question = row['problem_statement']
                person = row['employee_name'] or 'Unknown'

                # Check for duplicates
                dedup_key = get_dedup_key(question, person)
                if dedup_key in seen_questions:
                    continue  # Skip duplicate
                seen_questions.add(dedup_key)

                result = {
                    'question': question,
                    'answer': row['resolution_details'],
                    'resolved_by': person,
                    'customer': row['customer_name'] or 'Unknown',
                    'company': row['customer_company'] or 'Unknown',
                    'date': str(row['call_date']) if row['call_date'] else 'Unknown',
                    'call_id': row['recording_id'],
                    'source': source_type,
                    'quality_score': row.get('call_quality_score'),
                    'resolution_status': row.get('resolution_status'),
                    'avg_rating': float(row.get('avg_rating') or 0),
                    'rating_count': int(row.get('rating_count') or 0)
                }
                # Add source-specific fields and labels
                if source_type == 'freshdesk':
                    result['ticket_id'] = row.get('ticket_id')
                    result['source_label'] = 'Freshdesk Ticket'
                    result['source_icon'] = 'bi-ticket-detailed'
                elif source_type == 'video':
                    result['video_meeting_id'] = row.get('video_meeting_id')
                    result['video_title'] = row.get('video_title')
                    result['source_label'] = 'Video Meeting'
                    result['source_icon'] = 'bi-camera-video'
                else:
                    result['source_label'] = 'Call Recording'
                    result['source_icon'] = 'bi-telephone'
                results.append(result)

                if len(results) >= 10:  # Limit final results
                    break

            # If we got RAG results, add summary
            rag_summary = None
            if rag_response:
                rag_summary = rag_response

            # Log the search
            search_id = self._log_search(query, agent_id, results, rag_summary)

            return {
                'search_id': search_id,
                'query': query,
                'results': results,
                'rag_summary': rag_summary,
                'result_count': len(results)
            }

        except Exception as e:
            logger.error(f"KB search error: {e}")
            # Fall back to database-only search
            db_results = self._search_database(query)
            results = [{
                'question': row['problem_statement'],
                'answer': row['resolution_details'],
                'resolved_by': row['employee_name'] or 'Unknown',
                'customer': row['customer_name'] or 'Unknown',
                'company': row['customer_company'] or 'Unknown',
                'date': str(row['call_date']) if row['call_date'] else 'Unknown',
                'call_id': row['recording_id'],
                'source': 'database'
            } for row in db_results[:10]]

            search_id = self._log_search(query, agent_id, results, None)

            return {
                'search_id': search_id,
                'query': query,
                'results': results,
                'rag_summary': None,
                'result_count': len(results),
                'error': str(e)
            }

    def _search_database(self, query: str, limit: int = 20) -> List[Dict]:
        """Search the database directly using full-text search - includes call resolutions AND Freshdesk Q&A.
        Results are ranked by a combination of text relevance and user ratings."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Search call resolutions with ratings
                cur.execute("""
                    SELECT
                        cr.recording_id,
                        cr.problem_statement,
                        cr.resolution_details,
                        cr.resolution_status,
                        t.employee_name,
                        t.customer_name,
                        t.customer_company,
                        t.call_date,
                        i.call_quality_score,
                        'call' as source_type,
                        ts_rank(
                            to_tsvector('english', COALESCE(cr.problem_statement, '') || ' ' || COALESCE(cr.resolution_details, '')),
                            plainto_tsquery('english', %s)
                        ) as rank,
                        COALESCE(r.avg_rating, 0) as avg_rating,
                        COALESCE(r.rating_count, 0) as rating_count
                    FROM call_resolutions cr
                    JOIN transcripts t ON cr.recording_id = t.recording_id
                    LEFT JOIN insights i ON cr.recording_id = i.recording_id
                    LEFT JOIN (
                        SELECT qa_id, AVG(rating)::DECIMAL(3,2) as avg_rating, COUNT(*) as rating_count
                        FROM kb_ratings
                        WHERE source_type = 'call'
                        GROUP BY qa_id
                    ) r ON r.qa_id = 'call_' || cr.recording_id
                    WHERE cr.problem_statement IS NOT NULL
                      AND cr.problem_statement != 'Unable to determine'
                      AND cr.resolution_details IS NOT NULL
                      AND cr.resolution_details != ''
                      AND (
                          to_tsvector('english', COALESCE(cr.problem_statement, '') || ' ' || COALESCE(cr.resolution_details, ''))
                          @@ plainto_tsquery('english', %s)
                          OR cr.problem_statement ILIKE %s
                          OR cr.resolution_details ILIKE %s
                      )
                    ORDER BY rank DESC, t.call_date DESC
                    LIMIT %s
                """, (query, query, f'%{query}%', f'%{query}%', limit))

                call_results = [dict(row) for row in cur.fetchall()]

                # Search Freshdesk Q&A with ratings
                freshdesk_results = []
                try:
                    cur.execute("""
                        SELECT
                            f.qa_id as recording_id,
                            f.question as problem_statement,
                            f.answer as resolution_details,
                            'resolved' as resolution_status,
                            f.agent_name as employee_name,
                            f.requester_email as customer_name,
                            f.category as customer_company,
                            f.resolved_at as call_date,
                            NULL as call_quality_score,
                            'freshdesk' as source_type,
                            f.ticket_id,
                            ts_rank(f.search_vector, plainto_tsquery('english', %s)) as rank,
                            COALESCE(f.avg_rating, 0) as avg_rating,
                            COALESCE(f.rating_count, 0) as rating_count
                        FROM kb_freshdesk_qa f
                        WHERE f.search_vector @@ plainto_tsquery('english', %s)
                           OR f.question ILIKE %s
                           OR f.answer ILIKE %s
                        ORDER BY rank DESC, f.resolved_at DESC
                        LIMIT %s
                    """, (query, query, f'%{query}%', f'%{query}%', limit))
                    freshdesk_results = [dict(row) for row in cur.fetchall()]
                except Exception as e:
                    logger.warning(f"Freshdesk search failed (table may not exist): {e}")

                # Search Video Meeting Q&A pairs
                video_results = []
                try:
                    cur.execute("""
                        SELECT
                            'video_' || vq.id as recording_id,
                            vq.question as problem_statement,
                            vq.answer as resolution_details,
                            'complete' as resolution_status,
                            vm.host_name as employee_name,
                            NULL as customer_name,
                            vq.category as customer_company,
                            vm.start_time as call_date,
                            vm.meeting_quality_score as call_quality_score,
                            'video' as source_type,
                            vm.id as video_meeting_id,
                            vm.title as video_title,
                            ts_rank(
                                to_tsvector('english', COALESCE(vq.question, '') || ' ' || COALESCE(vq.answer, '')),
                                plainto_tsquery('english', %s)
                            ) as rank,
                            0 as avg_rating,
                            0 as rating_count
                        FROM video_meeting_qa_pairs vq
                        JOIN video_meetings vm ON vq.video_meeting_id = vm.id
                        WHERE (
                            to_tsvector('english', COALESCE(vq.question, '') || ' ' || COALESCE(vq.answer, ''))
                            @@ plainto_tsquery('english', %s)
                            OR vq.question ILIKE %s
                            OR vq.answer ILIKE %s
                        )
                        ORDER BY rank DESC, vm.start_time DESC
                        LIMIT %s
                    """, (query, query, f'%{query}%', f'%{query}%', limit))
                    video_results = [dict(row) for row in cur.fetchall()]
                except Exception as e:
                    logger.warning(f"Video Q&A search failed (table may not exist): {e}")

                # Combine and sort by weighted score: rank + rating boost
                # Higher rated answers get boosted in results
                all_results = call_results + freshdesk_results + video_results

                def calculate_score(result):
                    base_rank = float(result.get('rank', 0) or 0)
                    avg_rating = float(result.get('avg_rating', 0) or 0)
                    rating_count = int(result.get('rating_count', 0) or 0)

                    # Relevance is primary, but stars boost the score
                    # 1-star = 1.1x, 2-star = 1.2x, ... 5-star = 1.5x
                    if rating_count > 0 and avg_rating > 0:
                        rating_multiplier = 1.0 + (avg_rating / 10.0)  # 1.1x to 1.5x
                        return base_rank * rating_multiplier
                    else:
                        return base_rank

                all_results.sort(key=calculate_score, reverse=True)

                # Deduplicate by question + employee (keep first/highest ranked)
                import re
                seen = set()
                deduped = []
                for r in all_results:
                    q = r.get('problem_statement', '') or ''
                    e = r.get('employee_name', '') or 'unknown'
                    # Normalize for comparison
                    key = f"{re.sub(r'[^a-z0-9]', '', q.lower())}|{e.lower().strip()}"
                    if key not in seen:
                        seen.add(key)
                        deduped.append(r)

                return deduped[:limit]

    def _log_search(
        self,
        query: str,
        agent_id: str,
        results: List[Dict],
        rag_summary: str = None
    ) -> int:
        """Log search to database"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO kb_searches (query, agent_id, results_json, result_count, rag_summary)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (query, agent_id, json.dumps(results), len(results), rag_summary))
                return cur.fetchone()[0]

    def submit_feedback(
        self,
        search_id: int,
        helpful: bool,
        result_index: int = None,
        comment: str = None,
        agent_id: str = None
    ) -> Dict:
        """Submit feedback on search results"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO kb_feedback (search_id, helpful, result_index, comment, agent_id)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (search_id, helpful, result_index, comment, agent_id))
                feedback_id = cur.fetchone()[0]

        return {'status': 'saved', 'feedback_id': feedback_id}

    def get_stats(self, days: int = 30) -> Dict:
        """Get KB usage statistics"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Total searches
                cur.execute("""
                    SELECT COUNT(*) as total,
                           COUNT(DISTINCT agent_id) as unique_agents
                    FROM kb_searches
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                """, (days,))
                search_stats = cur.fetchone()

                # Helpful rate
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE helpful = TRUE) as helpful,
                        COUNT(*) FILTER (WHERE helpful = FALSE) as not_helpful
                    FROM kb_feedback
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                """, (days,))
                feedback_stats = cur.fetchone()

                helpful_rate = 0
                if feedback_stats['total'] > 0:
                    helpful_rate = round(feedback_stats['helpful'] / feedback_stats['total'] * 100, 1)

                # Top searches
                cur.execute("""
                    SELECT query, COUNT(*) as count
                    FROM kb_searches
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    GROUP BY query
                    ORDER BY count DESC
                    LIMIT 10
                """, (days,))
                top_searches = [dict(row) for row in cur.fetchall()]

                # Low-rated queries (need improvement)
                cur.execute("""
                    SELECT
                        s.query,
                        COUNT(*) as search_count,
                        ROUND(AVG(CASE WHEN f.helpful THEN 1.0 ELSE 0.0 END) * 100, 1) as helpful_rate
                    FROM kb_searches s
                    JOIN kb_feedback f ON s.id = f.search_id
                    WHERE s.created_at >= NOW() - INTERVAL '%s days'
                    GROUP BY s.query
                    HAVING AVG(CASE WHEN f.helpful THEN 1.0 ELSE 0.0 END) < 0.5
                       AND COUNT(*) >= 2
                    ORDER BY COUNT(*) DESC
                    LIMIT 10
                """, (days,))
                low_rated = [dict(row) for row in cur.fetchall()]

                # Recent feedback with comments
                cur.execute("""
                    SELECT
                        f.helpful,
                        f.comment,
                        s.query,
                        f.created_at
                    FROM kb_feedback f
                    JOIN kb_searches s ON f.search_id = s.id
                    WHERE f.comment IS NOT NULL AND f.comment != ''
                    ORDER BY f.created_at DESC
                    LIMIT 10
                """, ())
                recent_feedback = [dict(row) for row in cur.fetchall()]

                # Searches without results (knowledge gaps)
                cur.execute("""
                    SELECT query, COUNT(*) as count
                    FROM kb_searches
                    WHERE result_count = 0
                      AND created_at >= NOW() - INTERVAL '%s days'
                    GROUP BY query
                    ORDER BY count DESC
                    LIMIT 10
                """, (days,))
                knowledge_gaps = [dict(row) for row in cur.fetchall()]

                return {
                    'period_days': days,
                    'total_searches': search_stats['total'],
                    'unique_agents': search_stats['unique_agents'],
                    'total_feedback': feedback_stats['total'],
                    'helpful_count': feedback_stats['helpful'],
                    'not_helpful_count': feedback_stats['not_helpful'],
                    'helpful_rate': helpful_rate,
                    'top_searches': top_searches,
                    'low_rated_queries': low_rated,
                    'recent_feedback': recent_feedback,
                    'knowledge_gaps': knowledge_gaps
                }

    def get_recent_searches(self, limit: int = 20) -> List[Dict]:
        """Get recent searches for review"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        s.id,
                        s.query,
                        s.agent_id,
                        s.result_count,
                        s.created_at,
                        COUNT(f.id) as feedback_count,
                        BOOL_OR(f.helpful) as was_helpful
                    FROM kb_searches s
                    LEFT JOIN kb_feedback f ON s.id = f.search_id
                    GROUP BY s.id, s.query, s.agent_id, s.result_count, s.created_at
                    ORDER BY s.created_at DESC
                    LIMIT %s
                """, (limit,))
                return [dict(row) for row in cur.fetchall()]
