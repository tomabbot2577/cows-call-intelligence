"""
Embeddings Manager for Semantic Search
Generates and manages embeddings with comprehensive metadata using OpenRouter
"""

import os
import json
import requests
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from typing import List, Dict, Any, Optional
import numpy as np
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class EmbeddingsManager:
    """Manages embeddings generation and semantic search"""

    def __init__(self):
        """Initialize the embeddings manager"""
        self.db_config = {
            'dbname': 'call_insights',
            'user': 'call_insights_user',
            'password': 'call_insights_pass',
            'host': 'localhost',
            'port': 5432
        }

        # Try OpenAI directly if available, else fall back to OpenRouter
        self.openai_api_key = os.getenv('OPENAI_API_KEY', '')
        self.openrouter_api_key = os.getenv('OPENROUTER_API_KEY', '')

        # Use OpenAI if available
        self.use_openai_direct = bool(self.openai_api_key)

        # Using text-embedding-ada-002 (1536 dimensions) to match our database
        # This is compatible with the existing transcript_embeddings table
        self.embedding_model = "text-embedding-ada-002" if self.use_openai_direct else "openai/text-embedding-ada-002"
        self.embedding_dimensions = 1536

        logger.info("Embeddings Manager initialized")

    def get_connection(self):
        """Get database connection"""
        return psycopg2.connect(**self.db_config, cursor_factory=RealDictCursor)

    def _create_overlapping_chunks(self, text: str, max_chunk_size: int, overlap: int = 128) -> List[str]:
        """
        Create overlapping chunks from text with specified overlap

        Args:
            text: Text to chunk
            max_chunk_size: Maximum size of each chunk
            overlap: Number of characters to overlap between chunks

        Returns:
            List of overlapping text chunks
        """
        if len(text) <= max_chunk_size:
            return [text]

        chunks = []
        start = 0

        while start < len(text):
            # Calculate end position for this chunk
            end = start + max_chunk_size

            # If this would be the last chunk and it's very small, extend the previous chunk instead
            if end >= len(text):
                chunk = text[start:]
                if chunk.strip():  # Only add non-empty chunks
                    chunks.append(chunk)
                break

            # Find a good breaking point (space, period, etc.) near the end
            chunk_end = end
            break_chars = ['. ', '! ', '? ', '\n', ': ', '; ']

            # Look backward from end position for a good break
            for i in range(min(100, chunk_end - start)):  # Look back up to 100 chars
                pos = chunk_end - i
                if pos > start and text[pos-1:pos+1] in break_chars:
                    chunk_end = pos
                    break

            chunk = text[start:chunk_end]
            if chunk.strip():  # Only add non-empty chunks
                chunks.append(chunk)

            # Move start position forward, accounting for overlap
            start = max(start + 1, chunk_end - overlap)

        logger.info(f"Created {len(chunks)} overlapping chunks with {overlap} char overlap")
        return chunks

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text using OpenAI with OpenRouter fallback"""

        # Try OpenAI first if available
        if self.openai_api_key:
            try:
                response = requests.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={
                        "Authorization": f"Bearer {self.openai_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "text-embedding-ada-002",
                        "input": text
                    },
                    timeout=20
                )

                if response.status_code == 200:
                    data = response.json()
                    return data['data'][0]['embedding']
                else:
                    logger.warning(f"OpenAI embedding failed: {response.status_code} - {response.text}, trying OpenRouter")

            except Exception as e:
                logger.warning(f"OpenAI embedding error: {e}, trying OpenRouter")

        # OpenRouter currently has API issues, focusing on OpenAI only
        logger.error("OpenAI API failed and OpenRouter fallback is temporarily disabled")
        return None

    def store_transcript_embedding(self, recording_id: str, embedding: List[float],
                                  metadata: Dict[str, Any]) -> bool:
        """Store transcript embedding with all metadata"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # Convert embedding to PostgreSQL vector format
            embedding_str = '[' + ','.join(map(str, embedding)) + ']'

            cursor.execute("""
                INSERT INTO transcript_embeddings (
                    recording_id,
                    embedding,
                    transcript_text,
                    customer_name,
                    employee_name,
                    call_date,
                    duration_seconds,
                    word_count,
                    customer_sentiment,
                    call_quality_score,
                    customer_satisfaction_score,
                    call_type,
                    issue_category,
                    summary,
                    key_topics,
                    metadata,
                    embedding_model
                ) VALUES (
                    %s, %s::vector, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (recording_id) DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    transcript_text = EXCLUDED.transcript_text,
                    customer_name = EXCLUDED.customer_name,
                    employee_name = EXCLUDED.employee_name,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
            """, (
                recording_id,
                embedding_str,
                metadata.get('transcript_text', ''),
                metadata.get('customer_name'),
                metadata.get('employee_name'),
                metadata.get('call_date'),
                metadata.get('duration_seconds'),
                metadata.get('word_count'),
                metadata.get('customer_sentiment'),
                metadata.get('call_quality_score'),
                metadata.get('customer_satisfaction_score'),
                metadata.get('call_type'),
                metadata.get('issue_category'),
                metadata.get('summary'),
                metadata.get('key_topics', []),
                Json(metadata.get('additional_metadata', {})),
                self.embedding_model
            ))

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error storing embedding for {recording_id}: {e}")
            conn.rollback()
            return False
        finally:
            cursor.close()
            conn.close()

    def process_transcript(self, recording_id: str) -> bool:
        """Process a transcript and generate embedding with metadata"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # Get transcript and metadata
            cursor.execute("""
                SELECT
                    t.recording_id,
                    t.transcript_text,
                    t.customer_name,
                    t.employee_name,
                    t.call_date,
                    t.duration_seconds,
                    t.word_count,
                    i.customer_sentiment,
                    i.call_quality_score,
                    i.customer_satisfaction_score,
                    i.call_type,
                    i.issue_category,
                    i.summary,
                    i.key_topics
                FROM transcripts t
                LEFT JOIN insights i ON t.recording_id = i.recording_id
                WHERE t.recording_id = %s
            """, (recording_id,))

            record = cursor.fetchone()
            if not record:
                logger.warning(f"No transcript found for {recording_id}")
                return False

            # Create enhanced text for embedding (includes metadata for better search)
            enhanced_text = f"""
            Customer: {record.get('customer_name', 'Unknown')}
            Employee: {record.get('employee_name', 'Unknown')}
            Date: {record.get('call_date', '')}
            Sentiment: {record.get('customer_sentiment', '')}
            Call Type: {record.get('call_type', '')}
            Issue: {record.get('issue_category', '')}
            Summary: {record.get('summary', '')}

            Transcript:
            {record.get('transcript_text', '')}
            """

            # Check if text exceeds token limit and chunk if necessary
            if len(enhanced_text) > 1028:
                logger.info(f"Text too long ({len(enhanced_text)} chars), creating overlapping chunks")

                # Get metadata part and transcript part
                metadata_part = enhanced_text.split("Transcript:")[0] + "Transcript:\n"
                transcript_part = record.get('transcript_text', '')
                max_transcript_length = 1028 - len(metadata_part)

                if max_transcript_length <= 128:  # Not enough space for meaningful chunks
                    # Fallback to truncation
                    enhanced_text = enhanced_text[:1028]
                    embedding = self.generate_embedding(enhanced_text)
                else:
                    # Create overlapping chunks with 100+ character overlap
                    chunks = self._create_overlapping_chunks(transcript_part, max_transcript_length, overlap=128)
                    embeddings = []

                    for i, chunk in enumerate(chunks):
                        chunk_text = metadata_part + chunk
                        embedding = self.generate_embedding(chunk_text)
                        if embedding:
                            embeddings.append(embedding)
                            logger.info(f"Generated embedding for chunk {i+1}/{len(chunks)}")

                    if embeddings:
                        # Average all embeddings to create a single representative embedding
                        embedding = [sum(vals) / len(vals) for vals in zip(*embeddings)]
                        logger.info(f"Created averaged embedding from {len(embeddings)} chunks")
                    else:
                        embedding = None
            else:
                # Generate embedding for normal-sized text
                embedding = self.generate_embedding(enhanced_text)
            if not embedding:
                logger.error(f"Failed to generate embedding for {recording_id}")
                return False

            # Store embedding with metadata
            metadata = {
                'transcript_text': record.get('transcript_text'),
                'customer_name': record.get('customer_name'),
                'employee_name': record.get('employee_name'),
                'call_date': record.get('call_date'),
                'duration_seconds': record.get('duration_seconds'),
                'word_count': record.get('word_count'),
                'customer_sentiment': record.get('customer_sentiment'),
                'call_quality_score': record.get('call_quality_score'),
                'customer_satisfaction_score': record.get('customer_satisfaction_score'),
                'call_type': record.get('call_type'),
                'issue_category': record.get('issue_category'),
                'summary': record.get('summary'),
                'key_topics': record.get('key_topics', [])
            }

            return self.store_transcript_embedding(recording_id, embedding, metadata)

        except Exception as e:
            logger.error(f"Error processing transcript {recording_id}: {e}")
            return False
        finally:
            cursor.close()
            conn.close()

    def semantic_search(self, query: str, filters: Dict[str, Any] = None,
                       limit: int = 10) -> List[Dict[str, Any]]:
        """Perform semantic search with optional filters"""

        # Generate query embedding
        query_embedding = self.generate_embedding(query)
        if not query_embedding:
            logger.error("Failed to generate query embedding")
            return []

        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'

            # Build filter conditions
            filter_conditions = []
            params = [embedding_str]

            if filters:
                if filters.get('employee'):
                    filter_conditions.append("employee_name ILIKE %s")
                    params.append(f"%{filters['employee']}%")

                if filters.get('customer'):
                    filter_conditions.append("customer_name ILIKE %s")
                    params.append(f"%{filters['customer']}%")

                if filters.get('sentiment'):
                    filter_conditions.append("customer_sentiment = %s")
                    params.append(filters['sentiment'])

                if filters.get('date_from'):
                    filter_conditions.append("call_date >= %s")
                    params.append(filters['date_from'])

                if filters.get('date_to'):
                    filter_conditions.append("call_date <= %s")
                    params.append(filters['date_to'])

                if filters.get('min_quality'):
                    filter_conditions.append("call_quality_score >= %s")
                    params.append(filters['min_quality'])

            where_clause = ""
            if filter_conditions:
                where_clause = "WHERE " + " AND ".join(filter_conditions)

            params.append(limit)

            query = f"""
                SELECT
                    recording_id,
                    1 - (embedding <=> %s::vector) as similarity,
                    customer_name,
                    employee_name,
                    call_date,
                    customer_sentiment,
                    call_quality_score,
                    customer_satisfaction_score,
                    summary,
                    call_type,
                    issue_category,
                    key_topics,
                    duration_seconds,
                    word_count,
                    transcript_text,
                    metadata
                FROM transcript_embeddings
                {where_clause}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """

            # Add embedding parameter again for ORDER BY
            params.insert(len(params)-1, embedding_str)

            cursor.execute(query, params)
            results = cursor.fetchall()

            return [dict(row) for row in results]

        except Exception as e:
            logger.error(f"Semantic search error: {e}")
            return []
        finally:
            cursor.close()
            conn.close()

    def process_all_transcripts(self, batch_size: int = 10) -> Dict[str, int]:
        """Process all transcripts and generate embeddings"""
        conn = self.get_connection()
        cursor = conn.cursor()

        stats = {'processed': 0, 'failed': 0, 'skipped': 0}

        try:
            # Get all transcripts without embeddings
            cursor.execute("""
                SELECT t.recording_id
                FROM transcripts t
                LEFT JOIN transcript_embeddings e ON t.recording_id = e.recording_id
                WHERE e.recording_id IS NULL
                    AND t.transcript_text IS NOT NULL
                    AND t.transcript_text != ''
                LIMIT %s
            """, (batch_size,))

            recordings = cursor.fetchall()

            for record in recordings:
                recording_id = record['recording_id']
                print(f"Processing {recording_id}...")

                if self.process_transcript(recording_id):
                    stats['processed'] += 1
                    print(f"  ✅ Processed {recording_id}")
                else:
                    stats['failed'] += 1
                    print(f"  ❌ Failed {recording_id}")

            # Count existing embeddings
            cursor.execute("SELECT COUNT(*) as count FROM transcript_embeddings")
            total = cursor.fetchone()['count']
            stats['total'] = total

            return stats

        except Exception as e:
            logger.error(f"Error processing transcripts: {e}")
            return stats
        finally:
            cursor.close()
            conn.close()

# Singleton instance
_embeddings_manager = None

def get_embeddings_manager():
    """Get or create embeddings manager instance"""
    global _embeddings_manager
    if _embeddings_manager is None:
        _embeddings_manager = EmbeddingsManager()
    return _embeddings_manager