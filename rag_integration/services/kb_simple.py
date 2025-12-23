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

    def search(self, query: str, agent_id: str = None, filters: Dict = None, limit: int = 50, offset: int = 0, sort: str = None) -> Dict:
        """
        Search RAG for Q&A matches from Layer 5 data.
        Logs the search and returns results with source info.

        Args:
            query: Search query string
            agent_id: Optional agent identifier
            filters: Optional dict with filter criteria:
                - source: 'call', 'freshdesk', 'video'
                - employee: employee name
                - category: category name
            limit: Maximum results to return (default 50)
            offset: Number of results to skip for pagination
            sort: Sort order - 'recent' (by date), 'rating' (by avg_rating), or None (by relevance)
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
            # Get extra results to allow for dedup and pagination
            db_results, total_counts, facets = self._search_database(query, limit=limit + offset + 50, filters=filters, sort=sort)

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

            # Import employee name canonicalization
            from rag_integration.config.employee_names import canonicalize_employee_name

            # Add database results first (these have structured data)
            # Process all results to build deduped list, then apply pagination
            all_results = []
            for row in db_results:
                source_type = row.get('source_type', 'call')
                question = row['problem_statement']
                # Normalize employee name to canonical form (e.g., "Robin" → "Robin Montoni")
                raw_person = row['employee_name'] or 'Unknown'
                person = canonicalize_employee_name(raw_person) or raw_person

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
                all_results.append(result)

                # Stop once we have enough for pagination (offset + limit + buffer)
                if len(all_results) >= offset + limit + 10:
                    break

            # Apply pagination - skip offset and take limit
            results = all_results[offset:offset + limit]

            # If we got RAG results, add summary
            rag_summary = None
            if rag_response:
                rag_summary = rag_response

            # Log the search
            search_id = self._log_search(query, agent_id, results, rag_summary)

            # Calculate total across all sources
            total_matches = sum(total_counts.values())

            # Check if there are more results beyond what we're showing
            has_more = total_matches > len(results)

            # Generate narrowing suggestions if too many results (always show if > limit)
            narrowing_suggestions = []
            if total_matches > limit:
                # Suggest filtering by top employees (exclude already-filtered employee)
                current_employee = filters.get('employee') if filters else None
                if facets.get('employees'):
                    available_employees = [(e, c) for e, c in facets['employees']
                                          if not current_employee or e.lower() != current_employee.lower()]
                    if available_employees:
                        top_employees = [e for e, c in available_employees[:3]]
                        narrowing_suggestions.append({
                            'type': 'employee',
                            'message': f"Narrow by employee: {', '.join(top_employees)}",
                            'options': [{'value': e, 'count': c} for e, c in available_employees[:5]]
                        })

                # Suggest filtering by source (exclude already-filtered source)
                current_source = filters.get('source') if filters else None
                available_sources = [(s, c) for s, c in total_counts.items()
                                    if c > 0 and (not current_source or s != current_source)]
                if len(available_sources) > 1 or (len(available_sources) == 1 and not current_source):
                    narrowing_suggestions.append({
                        'type': 'source',
                        'message': 'Narrow by source type',
                        'options': [{'value': s, 'count': c} for s, c in available_sources if c > 0]
                    })

                # Suggest filtering by category (exclude already-filtered category)
                current_category = filters.get('category') if filters else None
                if facets.get('categories'):
                    available_categories = [(cat, c) for cat, c in facets['categories']
                                           if not current_category or cat.lower() != current_category.lower()]
                    if available_categories:
                        narrowing_suggestions.append({
                            'type': 'category',
                            'message': 'Narrow by category',
                            'options': [{'value': cat, 'count': c} for cat, c in available_categories[:5]]
                        })

            # Extract keyword suggestions from results
            keyword_suggestions = self._extract_keyword_suggestions(results, query)

            return {
                'search_id': search_id,
                'query': query,
                'results': results,
                'rag_summary': rag_summary,
                'result_count': len(results),
                'total_matches': total_matches,
                'total_by_source': total_counts,
                'facets': facets,
                'narrowing_suggestions': narrowing_suggestions,
                'keyword_suggestions': keyword_suggestions,
                'has_more': has_more,
                'offset': offset,
                'limit': limit
            }

        except Exception as e:
            logger.error(f"KB search error: {e}")
            # Fall back to database-only search
            try:
                db_results, total_counts, facets = self._search_database(query, limit=limit)
            except:
                db_results = []
                total_counts = {}
                facets = {}

            results = [{
                'question': row['problem_statement'],
                'answer': row['resolution_details'],
                'resolved_by': row['employee_name'] or 'Unknown',
                'customer': row['customer_name'] or 'Unknown',
                'company': row['customer_company'] or 'Unknown',
                'date': str(row['call_date']) if row['call_date'] else 'Unknown',
                'call_id': row['recording_id'],
                'source': row.get('source_type', 'database')
            } for row in db_results[:limit]]

            search_id = self._log_search(query, agent_id, results, None)

            total_matches = sum(total_counts.values()) if total_counts else len(results)
            return {
                'search_id': search_id,
                'query': query,
                'results': results,
                'rag_summary': None,
                'result_count': len(results),
                'total_matches': total_matches,
                'total_by_source': total_counts,
                'facets': facets,
                'narrowing_suggestions': [],
                'keyword_suggestions': [],
                'has_more': total_matches > len(results),
                'offset': offset,
                'limit': limit,
                'error': str(e)
            }

    def _extract_keyword_suggestions(self, results: list, query: str) -> list:
        """Extract service-related keyword suggestions from Q&A pairs."""
        import re
        from collections import Counter

        query_words = set(query.lower().split())

        # Known product/feature terms to prioritize
        product_terms = {
            'pcr', 'pcrecruiter', 'email', 'calendar', 'sync', 'import', 'export',
            'login', 'password', 'reset', 'invoice', 'payment', 'subscription',
            'database', 'backup', 'restore', 'integration', 'api', 'webhook',
            'report', 'dashboard', 'search', 'filter', 'candidate', 'job',
            'resume', 'parsing', 'template', 'workflow', 'automation', 'trigger',
            'notification', 'alert', 'permission', 'user', 'admin', 'settings',
            'outlook', 'gmail', 'chrome', 'extension', 'mobile', 'app',
            'error', 'issue', 'problem', 'fix', 'solution', 'update', 'upgrade'
        }

        # Words to exclude
        exclude_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
            'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'can', 'this', 'that', 'these',
            'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'what', 'which',
            'who', 'when', 'where', 'why', 'how', 'all', 'each', 'every', 'both',
            'customer', 'client', 'user', 'person', 'people', 'company', 'business',
            'hi', 'hello', 'thanks', 'thank', 'please', 'sorry', 'okay', 'ok',
            'need', 'help', 'want', 'like', 'get', 'got', 'make', 'made', 'let',
            'see', 'look', 'going', 'go', 'come', 'came', 'take', 'took', 'know',
            'think', 'say', 'said', 'try', 'call', 'called', 'told', 'asked',
            'unknown', 'n/a', 'na', 'none', 'null', 'yes', 'no', 'maybe'
        }

        word_counts = Counter()

        for result in results[:25]:
            # Combine question and answer text
            text = (result.get('question', '') or '') + ' ' + (result.get('answer', '') or '')
            text = text.lower()

            # Extract words
            words = re.findall(r'\b[a-z]{3,15}\b', text)

            for word in words:
                if word in exclude_words or word in query_words:
                    continue
                # Prioritize known product terms
                if word in product_terms:
                    word_counts[word] += 5
                # Also count other meaningful words that appear frequently
                elif len(word) >= 4:
                    word_counts[word] += 1

            # Look for multi-word technical phrases
            phrases = re.findall(r'\b(email sync|calendar sync|password reset|data import|data export|job posting|resume parsing|api key|webhook|error message)\b', text)
            for phrase in phrases:
                if phrase not in query.lower():
                    word_counts[phrase] += 10

        # Get top suggestions, excluding query terms
        suggestions = []
        for word, count in word_counts.most_common(12):
            if len(suggestions) >= 5:
                break
            # Skip if already in query or too similar
            if word in query.lower() or any(word in q or q in word for q in query_words):
                continue
            # Skip single common words with low counts
            if count < 3 and word not in product_terms:
                continue
            suggestions.append(word)

        return suggestions

    def _search_database(self, query: str, limit: int = 50, filters: Dict = None, sort: str = None):
        """Search the database directly using full-text search - includes call resolutions AND Freshdesk Q&A.
        Results are ranked by a combination of text relevance and user ratings.

        Args:
            sort: 'recent' for date desc, 'rating' for avg_rating desc, None for relevance

        Returns:
            Tuple of (results, total_counts, facets)
            - results: List of matching Q&A pairs
            - total_counts: Dict with count per source type
            - facets: Dict with top employees, categories for filtering
        """
        filters = filters or {}
        source_filter = filters.get('source')
        employee_filter = filters.get('employee')
        category_filter = filters.get('category')

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get total counts per source for faceting
                total_counts = {}
                facets = {'employees': [], 'categories': []}

                # Count call resolutions (with filters applied)
                call_count_sql = """
                    SELECT COUNT(*) as cnt
                    FROM call_resolutions cr
                    JOIN transcripts t ON cr.recording_id = t.recording_id
                    WHERE cr.search_vector @@ plainto_tsquery('english', %s)
                      AND cr.problem_statement IS NOT NULL
                      AND cr.problem_statement != 'Unable to determine'
                      AND LENGTH(cr.resolution_details) >= 30
                """
                call_count_params = [query]
                if employee_filter:
                    call_count_sql += " AND t.employee_name ILIKE %s"
                    call_count_params.append(f'%{employee_filter}%')
                if source_filter and source_filter != 'call':
                    total_counts['call'] = 0
                else:
                    cur.execute(call_count_sql, tuple(call_count_params))
                    total_counts['call'] = cur.fetchone()['cnt']

                # Count Freshdesk (with filters applied)
                try:
                    if source_filter and source_filter != 'freshdesk':
                        total_counts['freshdesk'] = 0
                    else:
                        fd_count_sql = """
                            SELECT COUNT(*) as cnt
                            FROM kb_freshdesk_qa f
                            WHERE f.search_vector @@ plainto_tsquery('english', %s)
                              AND LENGTH(f.answer) >= 50
                              AND f.answer NOT ILIKE '%%shift+close%%'
                              AND LENGTH(f.question) < 2000
                        """
                        fd_count_params = [query]
                        if employee_filter:
                            fd_count_sql += " AND f.agent_name ILIKE %s"
                            fd_count_params.append(f'%{employee_filter}%')
                        if category_filter:
                            fd_count_sql += " AND f.category ILIKE %s"
                            fd_count_params.append(f'%{category_filter}%')
                        cur.execute(fd_count_sql, tuple(fd_count_params))
                        total_counts['freshdesk'] = cur.fetchone()['cnt']
                except:
                    total_counts['freshdesk'] = 0

                # Count Video (with filters applied)
                try:
                    if source_filter and source_filter != 'video':
                        total_counts['video'] = 0
                    else:
                        video_count_sql = """
                            SELECT COUNT(*) as cnt
                            FROM video_meeting_qa_pairs vq
                            JOIN video_meetings vm ON vq.video_meeting_id = vm.id
                            WHERE vq.search_vector @@ plainto_tsquery('english', %s)
                              AND LENGTH(vq.answer) >= 20
                              AND vq.quality != 'incomplete'
                        """
                        video_count_params = [query]
                        if employee_filter:
                            video_count_sql += " AND vm.host_name ILIKE %s"
                            video_count_params.append(f'%{employee_filter}%')
                        cur.execute(video_count_sql, tuple(video_count_params))
                        total_counts['video'] = cur.fetchone()['cnt']
                except:
                    total_counts['video'] = 0

                # Get top employees across all sources for faceting
                # Fetch raw names, then normalize and aggregate in Python
                from rag_integration.config.employee_names import canonicalize_employee_name

                cur.execute("""
                    SELECT employee_name, COUNT(*) as cnt FROM (
                        SELECT t.employee_name
                        FROM call_resolutions cr
                        JOIN transcripts t ON cr.recording_id = t.recording_id
                        WHERE cr.search_vector @@ plainto_tsquery('english', %s)
                          AND t.employee_name IS NOT NULL
                        UNION ALL
                        SELECT f.agent_name as employee_name
                        FROM kb_freshdesk_qa f
                        WHERE f.search_vector @@ plainto_tsquery('english', %s)
                          AND f.agent_name IS NOT NULL
                    ) combined
                    GROUP BY employee_name
                """, (query, query))

                # Normalize employee names and aggregate counts
                employee_counts = {}
                for row in cur.fetchall():
                    raw_name = row['employee_name']
                    canonical_name = canonicalize_employee_name(raw_name) or raw_name
                    employee_counts[canonical_name] = employee_counts.get(canonical_name, 0) + row['cnt']

                # Sort by count descending and take top 10
                facets['employees'] = sorted(employee_counts.items(), key=lambda x: x[1], reverse=True)[:10]

                # Get top categories
                try:
                    cur.execute("""
                        SELECT category, COUNT(*) as cnt
                        FROM kb_freshdesk_qa f
                        WHERE f.search_vector @@ plainto_tsquery('english', %s)
                          AND f.category IS NOT NULL
                          AND f.category != ''
                        GROUP BY category
                        ORDER BY cnt DESC
                        LIMIT 10
                    """, (query,))
                    facets['categories'] = [(r['category'], r['cnt']) for r in cur.fetchall()]
                except:
                    facets['categories'] = []

                # Now get the actual results with optional filters
                # Search call resolutions using pre-built search_vector with weighted ranking
                call_results = []
                if not source_filter or source_filter == 'call':
                    call_sql = """
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
                        ts_rank(cr.search_vector, plainto_tsquery('english', %s)) as rank,
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
                      AND LENGTH(cr.resolution_details) >= 30
                      AND (
                          cr.search_vector @@ plainto_tsquery('english', %s)
                          OR cr.problem_statement ILIKE %s
                          OR cr.resolution_details ILIKE %s
                      )
                    """
                    call_params = [query, query, f'%{query}%', f'%{query}%']

                    if employee_filter:
                        call_sql += " AND t.employee_name ILIKE %s"
                        call_params.append(f'%{employee_filter}%')

                    # Apply sorting
                    if sort == 'recent':
                        call_sql += " ORDER BY t.call_date DESC NULLS LAST, rank DESC LIMIT %s"
                    elif sort == 'rating':
                        call_sql += " ORDER BY avg_rating DESC NULLS LAST, rank DESC LIMIT %s"
                    else:
                        call_sql += " ORDER BY rank DESC, t.call_date DESC LIMIT %s"
                    call_params.append(limit)

                    cur.execute(call_sql, tuple(call_params))
                    call_results = [dict(row) for row in cur.fetchall()]

                # Search Freshdesk Q&A with ratings and quality filtering
                freshdesk_results = []
                if not source_filter or source_filter == 'freshdesk':
                    try:
                        fd_sql = """
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
                                COALESCE(f.rating_count, 0) as rating_count,
                                LENGTH(f.answer) as answer_length
                            FROM kb_freshdesk_qa f
                            WHERE (f.search_vector @@ plainto_tsquery('english', %s)
                               OR f.question ILIKE %s
                               OR f.answer ILIKE %s)
                              AND LENGTH(f.answer) >= 50
                              AND f.answer NOT ILIKE '%%shift+close%%'
                              AND LENGTH(f.question) < 2000
                        """
                        fd_params = [query, query, f'%{query}%', f'%{query}%']

                        if employee_filter:
                            fd_sql += " AND f.agent_name ILIKE %s"
                            fd_params.append(f'%{employee_filter}%')
                        if category_filter:
                            fd_sql += " AND f.category ILIKE %s"
                            fd_params.append(f'%{category_filter}%')

                        # Apply sorting
                        if sort == 'recent':
                            fd_sql += " ORDER BY f.resolved_at DESC NULLS LAST, rank DESC LIMIT %s"
                        elif sort == 'rating':
                            fd_sql += " ORDER BY avg_rating DESC NULLS LAST, rank DESC LIMIT %s"
                        else:
                            fd_sql += " ORDER BY rank DESC, f.resolved_at DESC LIMIT %s"
                        fd_params.append(limit)

                        cur.execute(fd_sql, tuple(fd_params))
                        freshdesk_results = [dict(row) for row in cur.fetchall()]
                    except Exception as e:
                        logger.warning(f"Freshdesk search failed (table may not exist): {e}")

                # Search Video Meeting Q&A pairs using pre-built search_vector
                video_results = []
                if not source_filter or source_filter == 'video':
                    try:
                        video_sql = """
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
                                ts_rank(vq.search_vector, plainto_tsquery('english', %s)) as rank,
                                0 as avg_rating,
                                0 as rating_count
                            FROM video_meeting_qa_pairs vq
                            JOIN video_meetings vm ON vq.video_meeting_id = vm.id
                            WHERE (
                                vq.search_vector @@ plainto_tsquery('english', %s)
                                OR vq.question ILIKE %s
                                OR vq.answer ILIKE %s
                            )
                            AND LENGTH(vq.answer) >= 20
                            AND vq.quality != 'incomplete'
                        """
                        video_params = [query, query, f'%{query}%', f'%{query}%']

                        if employee_filter:
                            video_sql += " AND vm.host_name ILIKE %s"
                            video_params.append(f'%{employee_filter}%')

                        # Apply sorting
                        if sort == 'recent':
                            video_sql += " ORDER BY vm.start_time DESC NULLS LAST, rank DESC LIMIT %s"
                        elif sort == 'rating':
                            video_sql += " ORDER BY avg_rating DESC NULLS LAST, rank DESC LIMIT %s"
                        else:
                            video_sql += " ORDER BY rank DESC, vm.start_time DESC LIMIT %s"
                        video_params.append(limit)

                        cur.execute(video_sql, tuple(video_params))
                        video_results = [dict(row) for row in cur.fetchall()]
                    except Exception as e:
                        logger.warning(f"Video Q&A search failed (table may not exist): {e}")

                # Normalize ranks within each source to ensure fair comparison
                # All sources now use pre-built search_vector columns with similar rank ranges
                def normalize_ranks(results):
                    if not results:
                        return results
                    max_rank = max(float(r.get('rank', 0) or 0.001) for r in results)
                    for r in results:
                        raw_rank = float(r.get('rank', 0) or 0)
                        r['normalized_rank'] = raw_rank / max_rank if max_rank > 0 else 0
                    return results

                call_results = normalize_ranks(call_results)
                freshdesk_results = normalize_ranks(freshdesk_results)
                video_results = normalize_ranks(video_results)

                # Combine all results
                all_results = call_results + freshdesk_results + video_results

                def get_sort_key(result):
                    # Primary: normalized relevance rank (0-1 scale, higher is better)
                    rank = float(result.get('normalized_rank', 0) or 0)

                    # Secondary: answer quality score based on length
                    # Short answers (<100 chars) get penalized, longer answers get boosted
                    answer = result.get('resolution_details', '') or ''
                    answer_len = len(answer)
                    if answer_len < 100:
                        quality = 0.5  # Penalty for very short
                    elif answer_len < 200:
                        quality = 0.8  # Slight penalty
                    elif answer_len < 500:
                        quality = 1.0  # Normal
                    else:
                        quality = 1.2  # Boost for comprehensive answers

                    # Tertiary: star rating as final tiebreaker
                    avg_rating = float(result.get('avg_rating', 0) or 0)

                    # Combined score: rank * quality, then rating
                    return (rank * quality, avg_rating)

                all_results.sort(key=get_sort_key, reverse=True)

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

                # Ensure source diversity - interleave results from different sources
                # to prevent any single source from dominating results
                source_buckets = {}
                for r in deduped:
                    src = r.get('source_type', 'call')
                    if src not in source_buckets:
                        source_buckets[src] = []
                    source_buckets[src].append(r)

                # If we have multiple sources, interleave them
                if len(source_buckets) > 1:
                    diverse_results = []
                    max_per_round = 3  # Take top 3 from each source per round
                    round_num = 0
                    while len(diverse_results) < limit:
                        added_this_round = False
                        for src in source_buckets:
                            start_idx = round_num * max_per_round
                            bucket = source_buckets[src]
                            for r in bucket[start_idx:start_idx + max_per_round]:
                                if r not in diverse_results:
                                    diverse_results.append(r)
                                    added_this_round = True
                                    if len(diverse_results) >= limit:
                                        break
                            if len(diverse_results) >= limit:
                                break
                        if not added_this_round:
                            break
                        round_num += 1
                    return diverse_results[:limit], total_counts, facets
                else:
                    return deduped[:limit], total_counts, facets

    def _log_search(
        self,
        query: str,
        agent_id: str,
        results: List[Dict],
        rag_summary: str = None
    ) -> int:
        """Log search to database"""
        from decimal import Decimal

        def json_serializer(obj):
            if isinstance(obj, Decimal):
                return float(obj)
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO kb_searches (query, agent_id, results_json, result_count, rag_summary)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (query, agent_id, json.dumps(results, default=json_serializer), len(results), rag_summary))
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
