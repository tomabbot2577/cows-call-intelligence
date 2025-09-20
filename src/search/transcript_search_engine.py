"""
Transcript Search Engine
Advanced search and indexing for call transcripts
"""

import json
import sqlite3
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Search result with metadata"""
    transcript_id: str
    score: float
    snippet: str
    metadata: Dict[str, Any]
    highlights: List[str]


class TranscriptSearchEngine:
    """
    Full-text search engine for call transcripts
    Optimized for AI/LLM retrieval and analysis
    """

    def __init__(
        self,
        index_directory: str = "/var/www/call-recording-system/data/structured/indexes",
        db_path: str = "/var/www/call-recording-system/data/structured/search.db"
    ):
        """
        Initialize search engine

        Args:
            index_directory: Directory for search indexes
            db_path: Path to SQLite database for search
        """
        self.index_dir = Path(index_directory)
        self.db_path = db_path

        # Initialize database
        self._initialize_database()

        # Load indexes into memory
        self.indexes = self._load_indexes()

    def _initialize_database(self):
        """Initialize SQLite database for full-text search"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create main transcript table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transcripts (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                metadata JSON,
                created_at TIMESTAMP,
                indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create FTS5 table for full-text search
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS transcript_fts
            USING fts5(
                id UNINDEXED,
                content,
                from_number,
                to_number,
                from_name,
                to_name,
                keywords,
                entities,
                tokenize = 'porter unicode61'
            )
        """)

        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_transcripts_created
            ON transcripts(created_at DESC)
        """)

        # Create metadata tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS phone_index (
                phone_number TEXT,
                transcript_id TEXT,
                role TEXT,
                FOREIGN KEY (transcript_id) REFERENCES transcripts(id)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_phone_number
            ON phone_index(phone_number)
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entity_index (
                entity_type TEXT,
                entity_value TEXT,
                transcript_id TEXT,
                position INTEGER,
                FOREIGN KEY (transcript_id) REFERENCES transcripts(id)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_value
            ON entity_index(entity_type, entity_value)
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS temporal_index (
                transcript_id TEXT,
                year INTEGER,
                month INTEGER,
                day INTEGER,
                hour INTEGER,
                day_of_week TEXT,
                is_business_hours BOOLEAN,
                FOREIGN KEY (transcript_id) REFERENCES transcripts(id)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_temporal
            ON temporal_index(year, month, day)
        """)

        conn.commit()
        conn.close()

    def index_transcript(self, document: Dict[str, Any]) -> bool:
        """
        Index a transcript document for search

        Args:
            document: Structured transcript document

        Returns:
            Success status
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Extract data
            transcript_id = document['id']
            content = document['content']['text']
            call_info = document['call_info']
            features = document['features']
            temporal = document.get('temporal', {})

            # Insert main transcript
            cursor.execute("""
                INSERT OR REPLACE INTO transcripts (id, content, metadata, created_at)
                VALUES (?, ?, ?, ?)
            """, (
                transcript_id,
                content,
                json.dumps(document['metadata']),
                call_info.get('start_time')
            ))

            # Insert into FTS table
            from_participant = call_info['participants']['from']
            to_participant = call_info['participants']['to']

            cursor.execute("""
                INSERT OR REPLACE INTO transcript_fts
                (id, content, from_number, to_number, from_name, to_name, keywords, entities)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                transcript_id,
                content,
                from_participant.get('number', ''),
                to_participant.get('number', ''),
                from_participant.get('name', ''),
                to_participant.get('name', ''),
                ' '.join(features.get('keywords', [])),
                json.dumps(features.get('entities', {}))
            ))

            # Index phone numbers
            for role, participant in [('from', from_participant), ('to', to_participant)]:
                if participant.get('number'):
                    cursor.execute("""
                        INSERT INTO phone_index (phone_number, transcript_id, role)
                        VALUES (?, ?, ?)
                    """, (participant['number'], transcript_id, role))

            # Index entities
            for entity_type, entity_values in features.get('entities', {}).items():
                for i, value in enumerate(entity_values):
                    cursor.execute("""
                        INSERT INTO entity_index (entity_type, entity_value, transcript_id, position)
                        VALUES (?, ?, ?, ?)
                    """, (entity_type, str(value), transcript_id, i))

            # Index temporal data
            if temporal:
                cursor.execute("""
                    INSERT OR REPLACE INTO temporal_index
                    (transcript_id, year, month, day, hour, day_of_week, is_business_hours)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    transcript_id,
                    temporal.get('year'),
                    temporal.get('month'),
                    temporal.get('day'),
                    temporal.get('hour'),
                    temporal.get('day_of_week'),
                    temporal.get('is_business_hours', False)
                ))

            conn.commit()
            conn.close()

            logger.info(f"Indexed transcript: {transcript_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to index transcript: {e}")
            return False

    def search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[SearchResult]:
        """
        Search transcripts with optional filters

        Args:
            query: Search query
            filters: Optional filters (phone, date, entities, etc.)
            limit: Maximum results
            offset: Result offset

        Returns:
            List of search results
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        results = []

        try:
            # Build search query
            if query:
                # Full-text search
                base_query = """
                    SELECT
                        t.id,
                        t.content,
                        t.metadata,
                        t.created_at,
                        snippet(transcript_fts, 1, '<mark>', '</mark>', '...', 20) as snippet,
                        rank
                    FROM transcripts t
                    JOIN transcript_fts f ON t.id = f.id
                    WHERE transcript_fts MATCH ?
                """

                params = [query]

            else:
                # Browse without search query
                base_query = """
                    SELECT
                        t.id,
                        t.content,
                        t.metadata,
                        t.created_at,
                        substr(t.content, 1, 200) as snippet,
                        0 as rank
                    FROM transcripts t
                    WHERE 1=1
                """
                params = []

            # Apply filters
            filter_conditions = []

            if filters:
                # Phone filter
                if 'phone' in filters:
                    filter_conditions.append("""
                        EXISTS (
                            SELECT 1 FROM phone_index p
                            WHERE p.transcript_id = t.id
                            AND p.phone_number LIKE ?
                        )
                    """)
                    params.append(f"%{filters['phone']}%")

                # Date range filter
                if 'date_from' in filters:
                    filter_conditions.append("t.created_at >= ?")
                    params.append(filters['date_from'])

                if 'date_to' in filters:
                    filter_conditions.append("t.created_at <= ?")
                    params.append(filters['date_to'])

                # Entity filter
                if 'has_email' in filters and filters['has_email']:
                    filter_conditions.append("""
                        EXISTS (
                            SELECT 1 FROM entity_index e
                            WHERE e.transcript_id = t.id
                            AND e.entity_type = 'emails'
                        )
                    """)

                if 'has_amount' in filters and filters['has_amount']:
                    filter_conditions.append("""
                        EXISTS (
                            SELECT 1 FROM entity_index e
                            WHERE e.transcript_id = t.id
                            AND e.entity_type = 'amounts'
                        )
                    """)

                # Customer name filter
                if 'customer_name' in filters:
                    if query:
                        base_query = base_query.replace(
                            "WHERE transcript_fts MATCH ?",
                            "WHERE transcript_fts MATCH ? AND (f.from_name LIKE ? OR f.to_name LIKE ?)"
                        )
                    else:
                        filter_conditions.append("(f.from_name LIKE ? OR f.to_name LIKE ?)")

                    params.extend([f"%{filters['customer_name']}%"] * 2)

            # Add filter conditions
            if filter_conditions:
                if "WHERE" in base_query:
                    base_query += " AND " + " AND ".join(filter_conditions)
                else:
                    base_query += " WHERE " + " AND ".join(filter_conditions)

            # Add ordering and pagination
            if query:
                base_query += " ORDER BY rank DESC, t.created_at DESC"
            else:
                base_query += " ORDER BY t.created_at DESC"

            base_query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            # Execute search
            cursor.execute(base_query, params)

            for row in cursor.fetchall():
                transcript_id, content, metadata_json, created_at, snippet, rank = row

                # Parse metadata
                metadata = json.loads(metadata_json) if metadata_json else {}

                # Extract highlights
                highlights = re.findall(r'<mark>(.*?)</mark>', snippet) if query else []

                result = SearchResult(
                    transcript_id=transcript_id,
                    score=abs(rank) if query else 0,  # FTS5 rank is negative
                    snippet=snippet.replace('<mark>', '').replace('</mark>', ''),
                    metadata=metadata,
                    highlights=highlights
                )

                results.append(result)

        except Exception as e:
            logger.error(f"Search failed: {e}")

        finally:
            conn.close()

        return results

    def search_by_phone(self, phone_number: str) -> List[Dict[str, Any]]:
        """
        Search transcripts by phone number

        Args:
            phone_number: Phone number to search

        Returns:
            List of transcript metadata
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Normalize phone number for search
        normalized = re.sub(r'\D', '', phone_number)

        cursor.execute("""
            SELECT DISTINCT t.id, t.metadata, t.created_at, p.role
            FROM transcripts t
            JOIN phone_index p ON t.id = p.transcript_id
            WHERE p.phone_number LIKE ?
            ORDER BY t.created_at DESC
        """, (f"%{normalized}%",))

        results = []
        for row in cursor.fetchall():
            transcript_id, metadata_json, created_at, role = row
            metadata = json.loads(metadata_json) if metadata_json else {}

            results.append({
                'transcript_id': transcript_id,
                'created_at': created_at,
                'role': role,
                'metadata': metadata
            })

        conn.close()
        return results

    def search_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """
        Search transcripts by date range

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            List of transcript metadata
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT t.id, t.metadata, t.created_at
            FROM transcripts t
            JOIN temporal_index ti ON t.id = ti.transcript_id
            WHERE t.created_at >= ? AND t.created_at <= ?
            ORDER BY t.created_at DESC
        """, (start_date.isoformat(), end_date.isoformat()))

        results = []
        for row in cursor.fetchall():
            transcript_id, metadata_json, created_at = row
            metadata = json.loads(metadata_json) if metadata_json else {}

            results.append({
                'transcript_id': transcript_id,
                'created_at': created_at,
                'metadata': metadata
            })

        conn.close()
        return results

    def get_analytics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Get analytics and aggregations

        Args:
            start_date: Optional start date
            end_date: Optional end date

        Returns:
            Analytics data
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        analytics = {}

        # Date filter
        date_filter = ""
        params = []
        if start_date:
            date_filter = "WHERE created_at >= ?"
            params.append(start_date.isoformat())
        if end_date:
            if date_filter:
                date_filter += " AND created_at <= ?"
            else:
                date_filter = "WHERE created_at <= ?"
            params.append(end_date.isoformat())

        # Total transcripts
        cursor.execute(f"SELECT COUNT(*) FROM transcripts {date_filter}", params)
        analytics['total_transcripts'] = cursor.fetchone()[0]

        # Top phone numbers
        cursor.execute("""
            SELECT phone_number, COUNT(*) as count
            FROM phone_index p
            JOIN transcripts t ON p.transcript_id = t.id
            """ + date_filter.replace("WHERE", "WHERE" if not date_filter else " AND") + """
            GROUP BY phone_number
            ORDER BY count DESC
            LIMIT 10
        """, params)

        analytics['top_phone_numbers'] = [
            {'phone': row[0], 'count': row[1]} for row in cursor.fetchall()
        ]

        # Entity statistics
        cursor.execute("""
            SELECT entity_type, COUNT(DISTINCT transcript_id) as count
            FROM entity_index e
            JOIN transcripts t ON e.transcript_id = t.id
            """ + date_filter.replace("WHERE", "WHERE" if not date_filter else " AND") + """
            GROUP BY entity_type
        """, params)

        analytics['entity_stats'] = {
            row[0]: row[1] for row in cursor.fetchall()
        }

        # Temporal distribution
        cursor.execute("""
            SELECT
                day_of_week,
                COUNT(*) as count,
                AVG(CASE WHEN is_business_hours THEN 1 ELSE 0 END) as business_hours_ratio
            FROM temporal_index ti
            JOIN transcripts t ON ti.transcript_id = t.id
            """ + date_filter.replace("WHERE", "WHERE" if not date_filter else " AND") + """
            GROUP BY day_of_week
        """, params)

        analytics['temporal_distribution'] = [
            {
                'day': row[0],
                'count': row[1],
                'business_hours_ratio': row[2]
            }
            for row in cursor.fetchall()
        ]

        conn.close()
        return analytics

    def export_for_llm(
        self,
        filters: Optional[Dict[str, Any]] = None,
        format: str = 'jsonl'
    ) -> str:
        """
        Export transcripts for LLM training/analysis

        Args:
            filters: Optional filters
            format: Export format (jsonl, csv, parquet)

        Returns:
            Path to exported file
        """
        # Get filtered transcripts
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = "SELECT id, content, metadata FROM transcripts"
        params = []

        if filters:
            conditions = []
            if 'date_from' in filters:
                conditions.append("created_at >= ?")
                params.append(filters['date_from'])
            if 'date_to' in filters:
                conditions.append("created_at <= ?")
                params.append(filters['date_to'])

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

        cursor.execute(query, params)

        # Export based on format
        export_path = self.index_dir.parent / 'exports' / f"llm_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.{format}"

        if format == 'jsonl':
            with open(export_path, 'w') as f:
                for row in cursor.fetchall():
                    transcript_id, content, metadata_json = row
                    metadata = json.loads(metadata_json) if metadata_json else {}

                    llm_doc = {
                        'id': transcript_id,
                        'text': content,
                        'metadata': metadata
                    }

                    f.write(json.dumps(llm_doc) + '\n')

        conn.close()
        return str(export_path)

    def _load_indexes(self) -> Dict[str, Any]:
        """Load existing indexes from disk"""
        indexes = {}

        for index_file in self.index_dir.glob('*.json'):
            try:
                with open(index_file, 'r') as f:
                    index_name = index_file.stem
                    indexes[index_name] = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load index {index_file}: {e}")

        return indexes

    def rebuild_indexes(self) -> Dict[str, Any]:
        """
        Rebuild all search indexes

        Returns:
            Rebuild statistics
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get all transcripts
        cursor.execute("SELECT COUNT(*) FROM transcripts")
        total_count = cursor.fetchone()[0]

        # Rebuild FTS index
        cursor.execute("INSERT INTO transcript_fts(transcript_fts) VALUES('rebuild')")

        conn.commit()
        conn.close()

        return {
            'success': True,
            'total_documents': total_count,
            'indexes_rebuilt': ['fts', 'phone', 'entity', 'temporal']
        }