"""
Knowledge Base Service
Comprehensive Q&A knowledge base with search, tracking, and analytics
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, date
import json
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    """Service for managing the Knowledge Base"""

    def __init__(self, connection_string: str = None):
        """Initialize with database connection"""
        from ..config.settings import get_settings
        settings = get_settings()
        self.connection_string = connection_string or settings.database_url

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

    # ==========================================
    # ARTICLE OPERATIONS
    # ==========================================

    def search_articles(
        self,
        query: str,
        category: str = None,
        tags: List[str] = None,
        limit: int = 20,
        user_id: str = None,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Search the knowledge base for articles matching the query.
        Tracks the search for analytics.
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Build the search query
                search_conditions = ["a.status = 'active'"]
                params = []

                # Full-text search
                if query:
                    search_conditions.append("""
                        (a.search_vector @@ plainto_tsquery('english', %s)
                         OR a.title ILIKE %s
                         OR a.problem ILIKE %s
                         OR a.solution ILIKE %s)
                    """)
                    like_pattern = f"%{query}%"
                    params.extend([query, like_pattern, like_pattern, like_pattern])

                # Category filter
                if category:
                    search_conditions.append("a.category = %s")
                    params.append(category)

                # Tags filter
                if tags:
                    search_conditions.append("a.tags && %s")
                    params.append(tags)

                # Execute search
                sql = f"""
                    SELECT
                        a.id,
                        a.title,
                        a.problem,
                        a.solution,
                        a.category,
                        a.tags,
                        a.source_type,
                        a.source_id,
                        a.resolved_by,
                        a.asked_by,
                        a.customer_company,
                        a.resolved_date,
                        a.verified,
                        a.view_count,
                        a.helpful_count,
                        a.not_helpful_count,
                        a.times_cited,
                        c.display_name as category_name,
                        c.icon as category_icon,
                        c.color as category_color,
                        ts_rank(a.search_vector, plainto_tsquery('english', %s)) as relevance
                    FROM knowledge_base_articles a
                    LEFT JOIN knowledge_base_categories c ON a.category = c.name
                    WHERE {' AND '.join(search_conditions)}
                    ORDER BY relevance DESC, a.times_cited DESC, a.helpful_count DESC
                    LIMIT %s
                """
                params_with_rank = [query if query else ''] + params + [limit]
                cur.execute(sql, params_with_rank)
                articles = [dict(row) for row in cur.fetchall()]

                # Track the query
                article_ids = [a['id'] for a in articles]
                query_id = self._track_query(
                    cur, query, 'search', user_id, session_id,
                    len(articles), article_ids
                )

                return {
                    'query': query,
                    'query_id': query_id,
                    'results_count': len(articles),
                    'articles': articles
                }

    def get_article(self, article_id: int, user_id: str = None) -> Optional[Dict]:
        """Get a single article by ID and increment view count"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Increment view count
                cur.execute("""
                    UPDATE knowledge_base_articles
                    SET view_count = view_count + 1
                    WHERE id = %s
                    RETURNING *
                """, (article_id,))
                article = cur.fetchone()

                if not article:
                    return None

                # Get category info
                cur.execute("""
                    SELECT display_name, icon, color
                    FROM knowledge_base_categories
                    WHERE name = %s
                """, (article['category'],))
                cat = cur.fetchone()

                result = dict(article)
                if cat:
                    result['category_name'] = cat['display_name']
                    result['category_icon'] = cat['icon']
                    result['category_color'] = cat['color']

                # Get related articles
                if article.get('related_articles'):
                    cur.execute("""
                        SELECT id, title, category
                        FROM knowledge_base_articles
                        WHERE id = ANY(%s) AND status = 'active'
                    """, (article['related_articles'],))
                    result['related'] = [dict(r) for r in cur.fetchall()]

                return result

    def create_article(
        self,
        title: str,
        problem: str,
        solution: str,
        category: str = 'general',
        tags: List[str] = None,
        source_type: str = 'manual',
        source_id: str = None,
        resolved_by: str = None,
        asked_by: str = None,
        customer_company: str = None,
        resolved_date: date = None,
        created_by: str = None
    ) -> int:
        """Create a new knowledge base article"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Extract keywords from problem and solution
                keywords = self._extract_keywords(f"{problem} {solution}")

                cur.execute("""
                    INSERT INTO knowledge_base_articles (
                        title, problem, solution, category, tags, keywords,
                        source_type, source_id, resolved_by, asked_by,
                        customer_company, resolved_date, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
                    RETURNING id
                """, (
                    title, problem, solution, category, tags or [], keywords,
                    source_type, source_id, resolved_by, asked_by,
                    customer_company, resolved_date
                ))
                article_id = cur.fetchone()[0]

                # Log history
                self._log_history(cur, article_id, 'created', created_by=created_by)

                # Update category count
                cur.execute("""
                    UPDATE knowledge_base_categories
                    SET article_count = article_count + 1
                    WHERE name = %s
                """, (category,))

                return article_id

    def update_article(
        self,
        article_id: int,
        updates: Dict[str, Any],
        updated_by: str = None,
        reason: str = None
    ) -> bool:
        """Update an existing article"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get current values for history
                cur.execute("SELECT * FROM knowledge_base_articles WHERE id = %s", (article_id,))
                current = cur.fetchone()
                if not current:
                    return False

                # Build update query
                set_clauses = []
                params = []
                for field, value in updates.items():
                    if field in ['title', 'problem', 'solution', 'category', 'tags', 'status']:
                        set_clauses.append(f"{field} = %s")
                        params.append(value)

                        # Log history for each change
                        old_value = current.get(field)
                        if str(old_value) != str(value):
                            self._log_history(
                                cur, article_id, 'updated',
                                field_changed=field,
                                old_value=str(old_value),
                                new_value=str(value),
                                changed_by=updated_by,
                                change_reason=reason
                            )

                if set_clauses:
                    # Re-extract keywords if content changed
                    if 'problem' in updates or 'solution' in updates:
                        problem = updates.get('problem', current['problem'])
                        solution = updates.get('solution', current['solution'])
                        keywords = self._extract_keywords(f"{problem} {solution}")
                        set_clauses.append("keywords = %s")
                        params.append(keywords)

                    params.append(article_id)
                    cur.execute(f"""
                        UPDATE knowledge_base_articles
                        SET {', '.join(set_clauses)}
                        WHERE id = %s
                    """, params)

                return True

    def record_article_cited(self, article_id: int, query_id: int = None):
        """Record that an article was used to answer a query"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE knowledge_base_articles
                    SET times_cited = times_cited + 1
                    WHERE id = %s
                """, (article_id,))

                if query_id:
                    cur.execute("""
                        UPDATE knowledge_base_queries
                        SET was_answered = TRUE, clicked_article_id = %s
                        WHERE id = %s
                    """, (article_id, query_id))

    # ==========================================
    # FEEDBACK & CONTRIBUTIONS
    # ==========================================

    def submit_feedback(
        self,
        article_id: int,
        helpful: bool,
        rating: int = None,
        feedback_text: str = None,
        issue_type: str = None,
        user_id: str = None,
        query_id: int = None
    ):
        """Submit feedback for an article"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Insert feedback
                cur.execute("""
                    INSERT INTO knowledge_base_feedback (
                        article_id, query_id, helpful, rating,
                        feedback_text, issue_type, user_identifier
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (article_id, query_id, helpful, rating, feedback_text, issue_type, user_id))

                # Update article counts
                if helpful:
                    cur.execute("""
                        UPDATE knowledge_base_articles
                        SET helpful_count = helpful_count + 1
                        WHERE id = %s
                    """, (article_id,))
                else:
                    cur.execute("""
                        UPDATE knowledge_base_articles
                        SET not_helpful_count = not_helpful_count + 1
                        WHERE id = %s
                    """, (article_id,))

    def submit_contribution(
        self,
        contribution_type: str,
        contributed_by: str,
        article_id: int = None,
        new_content: str = None,
        field_modified: str = None,
        suggested_title: str = None,
        suggested_problem: str = None,
        suggested_solution: str = None,
        suggested_category: str = None,
        suggested_tags: List[str] = None,
        contribution_reason: str = None
    ) -> int:
        """Submit a contribution (new article or edit suggestion)"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Get original content if editing
                original_content = None
                if article_id and field_modified:
                    cur.execute(f"""
                        SELECT {field_modified} FROM knowledge_base_articles WHERE id = %s
                    """, (article_id,))
                    row = cur.fetchone()
                    if row:
                        original_content = str(row[0])

                cur.execute("""
                    INSERT INTO knowledge_base_contributions (
                        contribution_type, article_id, original_content, new_content,
                        field_modified, suggested_title, suggested_problem, suggested_solution,
                        suggested_category, suggested_tags, contributed_by, contribution_reason
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    contribution_type, article_id, original_content, new_content,
                    field_modified, suggested_title, suggested_problem, suggested_solution,
                    suggested_category, suggested_tags, contributed_by, contribution_reason
                ))
                return cur.fetchone()[0]

    def get_pending_contributions(self, limit: int = 50) -> List[Dict]:
        """Get contributions pending review"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT c.*,
                           a.title as article_title
                    FROM knowledge_base_contributions c
                    LEFT JOIN knowledge_base_articles a ON c.article_id = a.id
                    WHERE c.status = 'pending'
                    ORDER BY c.created_at ASC
                    LIMIT %s
                """, (limit,))
                return [dict(row) for row in cur.fetchall()]

    def review_contribution(
        self,
        contribution_id: int,
        approved: bool,
        reviewed_by: str,
        review_notes: str = None
    ) -> Optional[int]:
        """Review and approve/reject a contribution"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get the contribution
                cur.execute("""
                    SELECT * FROM knowledge_base_contributions WHERE id = %s
                """, (contribution_id,))
                contrib = cur.fetchone()
                if not contrib:
                    return None

                status = 'approved' if approved else 'rejected'
                resulting_article_id = None

                if approved:
                    if contrib['contribution_type'] == 'new_article':
                        # Create the new article
                        resulting_article_id = self.create_article(
                            title=contrib['suggested_title'],
                            problem=contrib['suggested_problem'],
                            solution=contrib['suggested_solution'],
                            category=contrib['suggested_category'] or 'general',
                            tags=contrib['suggested_tags'],
                            source_type='contribution',
                            created_by=contrib['contributed_by']
                        )
                    elif contrib['contribution_type'] in ['edit', 'correction', 'addition']:
                        # Update the existing article
                        if contrib['field_modified'] and contrib['new_content']:
                            self.update_article(
                                contrib['article_id'],
                                {contrib['field_modified']: contrib['new_content']},
                                updated_by=reviewed_by,
                                reason=f"Contribution #{contribution_id} approved"
                            )
                        resulting_article_id = contrib['article_id']

                # Update contribution status
                cur.execute("""
                    UPDATE knowledge_base_contributions
                    SET status = %s, reviewed_by = %s, reviewed_at = NOW(),
                        review_notes = %s, resulting_article_id = %s
                    WHERE id = %s
                """, (status, reviewed_by, review_notes, resulting_article_id, contribution_id))

                return resulting_article_id

    # ==========================================
    # KNOWLEDGE GAPS
    # ==========================================

    def record_unanswered_query(
        self,
        question: str,
        user_id: str = None,
        category_guess: str = None
    ):
        """Record an unanswered question as a knowledge gap"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Normalize the question for deduplication
                normalized = self._normalize_question(question)

                # Check if similar gap exists
                cur.execute("""
                    SELECT id, asked_by FROM knowledge_base_gaps
                    WHERE normalized_question = %s AND status IN ('open', 'in_progress')
                """, (normalized,))
                existing = cur.fetchone()

                if existing:
                    # Update existing gap
                    asked_by = existing['asked_by'] or []
                    if user_id and user_id not in asked_by:
                        asked_by.append(user_id)

                    cur.execute("""
                        UPDATE knowledge_base_gaps
                        SET times_asked = times_asked + 1,
                            last_asked_at = NOW(),
                            asked_by = %s
                        WHERE id = %s
                    """, (asked_by, existing['id']))
                else:
                    # Create new gap
                    cur.execute("""
                        INSERT INTO knowledge_base_gaps (
                            question, normalized_question, category_guess,
                            asked_by
                        ) VALUES (%s, %s, %s, %s)
                    """, (question, normalized, category_guess, [user_id] if user_id else []))

    def get_knowledge_gaps(
        self,
        status: str = 'open',
        priority: str = None,
        limit: int = 50
    ) -> List[Dict]:
        """Get knowledge gaps needing attention"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                conditions = []
                params = []

                if status:
                    conditions.append("status = %s")
                    params.append(status)

                where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

                cur.execute(f"""
                    SELECT *,
                        CASE
                            WHEN times_asked >= 10 THEN 'critical'
                            WHEN times_asked >= 5 THEN 'high'
                            WHEN times_asked >= 3 THEN 'normal'
                            ELSE 'low'
                        END as calculated_priority,
                        EXTRACT(DAY FROM NOW() - first_asked_at) as days_open
                    FROM knowledge_base_gaps
                    {where_clause}
                    ORDER BY times_asked DESC, first_asked_at ASC
                    LIMIT %s
                """, params + [limit])
                return [dict(row) for row in cur.fetchall()]

    def resolve_gap(
        self,
        gap_id: int,
        article_id: int,
        resolved_by: str,
        resolution_notes: str = None
    ):
        """Mark a knowledge gap as resolved by linking to an article"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE knowledge_base_gaps
                    SET status = 'resolved',
                        resolved_article_id = %s,
                        resolved_by = %s,
                        resolution_notes = %s,
                        resolved_at = NOW()
                    WHERE id = %s
                """, (article_id, resolved_by, resolution_notes, gap_id))

    # ==========================================
    # ANALYTICS
    # ==========================================

    def get_analytics_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get comprehensive analytics for the knowledge base"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                result = {}

                # Query metrics
                cur.execute("""
                    SELECT
                        COUNT(*) as total_queries,
                        COUNT(DISTINCT user_identifier) as unique_users,
                        COUNT(CASE WHEN was_answered = TRUE THEN 1 END) as answered,
                        COUNT(CASE WHEN was_answered = FALSE THEN 1 END) as unanswered,
                        ROUND(
                            COUNT(CASE WHEN was_answered = TRUE THEN 1 END)::NUMERIC /
                            NULLIF(COUNT(*), 0) * 100, 1
                        ) as answer_rate
                    FROM knowledge_base_queries
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                """, (days,))
                result['queries'] = dict(cur.fetchone())

                # Article metrics
                cur.execute("""
                    SELECT
                        COUNT(*) as total_articles,
                        COUNT(CASE WHEN verified = TRUE THEN 1 END) as verified_articles,
                        SUM(view_count) as total_views,
                        SUM(helpful_count) as total_helpful,
                        SUM(not_helpful_count) as total_not_helpful
                    FROM knowledge_base_articles
                    WHERE status = 'active'
                """)
                result['articles'] = dict(cur.fetchone())

                # Gap metrics
                cur.execute("""
                    SELECT
                        COUNT(*) as total_gaps,
                        COUNT(CASE WHEN status = 'open' THEN 1 END) as open_gaps,
                        COUNT(CASE WHEN status = 'resolved' THEN 1 END) as resolved_gaps,
                        SUM(times_asked) as total_gap_queries
                    FROM knowledge_base_gaps
                """)
                result['gaps'] = dict(cur.fetchone())

                # Top queries (unanswered)
                cur.execute("""
                    SELECT query_text, COUNT(*) as count
                    FROM knowledge_base_queries
                    WHERE was_answered = FALSE
                      AND created_at >= NOW() - INTERVAL '%s days'
                    GROUP BY query_text
                    ORDER BY count DESC
                    LIMIT 10
                """, (days,))
                result['top_unanswered_queries'] = [dict(row) for row in cur.fetchall()]

                # Top articles
                cur.execute("""
                    SELECT id, title, view_count, helpful_count, times_cited
                    FROM knowledge_base_articles
                    WHERE status = 'active'
                    ORDER BY times_cited DESC, view_count DESC
                    LIMIT 10
                """)
                result['top_articles'] = [dict(row) for row in cur.fetchall()]

                # Category breakdown
                cur.execute("""
                    SELECT
                        c.name,
                        c.display_name,
                        c.icon,
                        c.color,
                        COUNT(a.id) as article_count
                    FROM knowledge_base_categories c
                    LEFT JOIN knowledge_base_articles a ON c.name = a.category AND a.status = 'active'
                    WHERE c.active = TRUE
                    GROUP BY c.id, c.name, c.display_name, c.icon, c.color
                    ORDER BY article_count DESC
                """)
                result['categories'] = [dict(row) for row in cur.fetchall()]

                # Daily query trend
                cur.execute("""
                    SELECT
                        DATE_TRUNC('day', created_at)::DATE as date,
                        COUNT(*) as queries,
                        COUNT(CASE WHEN was_answered = TRUE THEN 1 END) as answered
                    FROM knowledge_base_queries
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    GROUP BY DATE_TRUNC('day', created_at)::DATE
                    ORDER BY date
                """, (days,))
                result['daily_trend'] = [dict(row) for row in cur.fetchall()]

                # Pending contributions
                cur.execute("""
                    SELECT COUNT(*) as pending
                    FROM knowledge_base_contributions
                    WHERE status = 'pending'
                """)
                result['pending_contributions'] = cur.fetchone()['pending']

                return result

    def get_categories(self) -> List[Dict]:
        """Get all active categories"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM knowledge_base_categories
                    WHERE active = TRUE
                    ORDER BY sort_order, display_name
                """)
                return [dict(row) for row in cur.fetchall()]

    # ==========================================
    # IMPORT FROM CALL DATA
    # ==========================================

    def import_from_call_resolutions(self, limit: int = None) -> Dict[str, int]:
        """Import Q&A pairs from call resolutions into knowledge base"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get resolutions with problems and solutions that aren't imported yet
                limit_clause = f"LIMIT {limit}" if limit else ""

                cur.execute(f"""
                    SELECT
                        cr.recording_id,
                        cr.problem_statement,
                        cr.resolution_details,
                        cr.resolution_status,
                        cr.problem_complexity,
                        t.employee_name,
                        t.customer_name,
                        t.customer_company,
                        t.call_date,
                        i.summary,
                        i.key_topics,
                        i.call_type,
                        rec.knowledge_base_updates
                    FROM call_resolutions cr
                    JOIN transcripts t ON cr.recording_id = t.recording_id
                    LEFT JOIN insights i ON cr.recording_id = i.recording_id
                    LEFT JOIN call_recommendations rec ON cr.recording_id = rec.recording_id
                    WHERE cr.problem_statement IS NOT NULL
                      AND cr.problem_statement != 'Unable to determine'
                      AND cr.resolution_details IS NOT NULL
                      AND cr.resolution_details != ''
                      AND NOT EXISTS (
                          SELECT 1 FROM knowledge_base_articles
                          WHERE source_type = 'call' AND source_id = cr.recording_id
                      )
                    ORDER BY t.call_date DESC
                    {limit_clause}
                """)

                rows = cur.fetchall()
                imported = 0
                skipped = 0

                for row in rows:
                    try:
                        # Generate title from problem
                        title = self._generate_title(row['problem_statement'])

                        # Determine category from call type
                        category = self._map_call_type_to_category(row.get('call_type'))

                        # Extract tags from topics
                        tags = row.get('key_topics', []) or []
                        if row.get('problem_complexity'):
                            tags.append(f"complexity:{row['problem_complexity']}")

                        self.create_article(
                            title=title,
                            problem=row['problem_statement'],
                            solution=row['resolution_details'],
                            category=category,
                            tags=tags[:10],  # Limit tags
                            source_type='call',
                            source_id=row['recording_id'],
                            resolved_by=row.get('employee_name'),
                            asked_by=row.get('customer_name'),
                            customer_company=row.get('customer_company'),
                            resolved_date=row.get('call_date'),
                            created_by='system_import'
                        )
                        imported += 1
                    except Exception as e:
                        logger.error(f"Error importing {row['recording_id']}: {e}")
                        skipped += 1

                return {'imported': imported, 'skipped': skipped}

    # ==========================================
    # HELPER METHODS
    # ==========================================

    def _track_query(
        self,
        cursor,
        query_text: str,
        query_type: str,
        user_id: str,
        session_id: str,
        results_count: int,
        article_ids: List[int]
    ) -> int:
        """Track a search query for analytics"""
        cursor.execute("""
            INSERT INTO knowledge_base_queries (
                query_text, query_type, user_identifier, session_id,
                results_count, article_ids_returned,
                top_result_id, was_answered
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            query_text, query_type, user_id, session_id,
            results_count, article_ids,
            article_ids[0] if article_ids else None,
            results_count > 0
        ))
        return cursor.fetchone()[0]

    def _log_history(
        self,
        cursor,
        article_id: int,
        action: str,
        field_changed: str = None,
        old_value: str = None,
        new_value: str = None,
        changed_by: str = None,
        change_reason: str = None
    ):
        """Log a change to article history"""
        cursor.execute("""
            INSERT INTO knowledge_base_history (
                article_id, action, field_changed, old_value, new_value,
                changed_by, change_reason
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (article_id, action, field_changed, old_value, new_value, changed_by, change_reason))

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text"""
        # Simple keyword extraction - remove common words
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
            'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
            'that', 'this', 'these', 'those', 'i', 'you', 'he', 'she', 'it',
            'we', 'they', 'what', 'which', 'who', 'whom', 'when', 'where', 'why',
            'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other',
            'some', 'such', 'no', 'not', 'only', 'same', 'so', 'than', 'too',
            'very', 'just', 'also', 'now', 'here', 'there', 'then', 'once'
        }

        words = re.findall(r'\b[a-z]{3,}\b', text.lower())
        keywords = [w for w in words if w not in stop_words]

        # Get unique keywords, preserving order
        seen = set()
        unique = []
        for k in keywords:
            if k not in seen:
                seen.add(k)
                unique.append(k)

        return unique[:20]  # Limit to 20 keywords

    def _normalize_question(self, question: str) -> str:
        """Normalize a question for deduplication"""
        # Lowercase, remove punctuation, collapse whitespace
        normalized = question.lower()
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized

    def _generate_title(self, problem: str) -> str:
        """Generate a concise title from a problem statement"""
        # Take first sentence or first 100 chars
        sentences = problem.split('.')
        title = sentences[0].strip()
        if len(title) > 100:
            title = title[:97] + '...'
        return title

    def _map_call_type_to_category(self, call_type: str) -> str:
        """Map call type to knowledge base category"""
        if not call_type:
            return 'general'

        call_type = call_type.lower()
        mappings = {
            'technical': 'technical',
            'support': 'technical',
            'billing': 'billing',
            'payment': 'billing',
            'sales': 'general',
            'training': 'training',
            'how-to': 'training',
            'integration': 'integration',
            'api': 'integration',
            'pcr': 'pcr',
            'pc recruiter': 'pcr'
        }

        for key, category in mappings.items():
            if key in call_type:
                return category

        return 'general'
