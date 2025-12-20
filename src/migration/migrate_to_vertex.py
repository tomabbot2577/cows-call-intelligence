#!/usr/bin/env python3
"""
Direct Migration to Vertex AI RAG

Exports transcripts from PostgreSQL and uploads directly to Vertex AI RAG
using individual text files with embedded metadata.

Usage:
    python src/migration/migrate_to_vertex.py
    python src/migration/migrate_to_vertex.py --limit 100  # Test with 100 records
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
import tempfile

import psycopg2
from psycopg2.extras import RealDictCursor

# Add project root to path
sys.path.insert(0, '/var/www/call-recording-system')

try:
    import vertexai
    from vertexai import rag
    from google.cloud import storage
    VERTEX_AI_AVAILABLE = True
except ImportError:
    VERTEX_AI_AVAILABLE = False
    print("WARNING: Vertex AI not available. Install: pip install google-cloud-aiplatform google-cloud-storage")

from src.vertex_ai.config import default_config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': 'call_insights_pass',
    'host': 'localhost',
    'port': 5432
}


class DirectMigrator:
    """Direct migration from PostgreSQL to Vertex AI RAG"""

    def __init__(self):
        """Initialize migrator"""
        self.config = default_config

        # Set credentials
        if self.config.credentials_path:
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = self.config.credentials_path

        self.stats = {
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'errors': []
        }

    def connect_db(self):
        """Connect to PostgreSQL"""
        return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

    def get_transcript_count(self, conn) -> int:
        """Get total transcript count"""
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM transcripts
            WHERE transcript_text IS NOT NULL
            AND LENGTH(transcript_text) > 100
        """)
        result = cursor.fetchone()
        cursor.close()
        return result['count']

    def fetch_transcripts(self, conn, offset: int, limit: int) -> List[Dict]:
        """Fetch transcripts with all related data"""
        cursor = conn.cursor()

        query = """
            SELECT
                t.recording_id,
                t.transcript_text,
                t.call_date,
                t.call_time,
                t.duration_seconds,
                t.direction,
                t.from_number,
                t.to_number,
                t.customer_name,
                t.customer_phone,
                t.customer_company,
                t.employee_name,
                t.employee_extension,
                t.word_count,
                t.confidence_score,

                -- Insights
                i.customer_sentiment,
                i.call_quality_score,
                i.customer_satisfaction_score,
                i.call_type,
                i.issue_category,
                i.summary,
                i.key_topics,
                i.follow_up_needed,
                i.escalation_required,
                i.coaching_notes,

                -- Resolutions
                cr.resolution_status,
                cr.problem_statement,
                cr.resolution_details,
                cr.follow_up_type,
                cr.follow_up_details,
                cr.closure_score,
                cr.empathy_score,
                cr.active_listening_score,
                cr.employee_knowledge_level,
                cr.customer_satisfaction_likely,
                cr.call_back_risk,
                cr.churn_risk,

                -- Recommendations
                rec.process_improvements,
                rec.employee_strengths,
                rec.employee_improvements,
                rec.suggested_phrases,
                rec.follow_up_actions,
                rec.knowledge_base_updates,
                rec.risk_level,
                rec.efficiency_score,
                rec.training_priority

            FROM transcripts t
            LEFT JOIN insights i ON t.recording_id = i.recording_id
            LEFT JOIN call_resolutions cr ON t.recording_id = cr.recording_id
            LEFT JOIN call_recommendations rec ON t.recording_id = rec.recording_id
            WHERE t.transcript_text IS NOT NULL
            AND LENGTH(t.transcript_text) > 100
            ORDER BY t.call_date DESC, t.recording_id
            OFFSET %s LIMIT %s
        """

        cursor.execute(query, (offset, limit))
        records = cursor.fetchall()
        cursor.close()
        return [dict(r) for r in records]

    def build_document_content(self, record: Dict) -> str:
        """Build rich document content with all metadata embedded"""
        recording_id = record['recording_id']
        transcript_text = record['transcript_text'] or ''

        # Extract metadata
        call_date = str(record.get('call_date', '')) if record.get('call_date') else 'Unknown'
        call_time = str(record.get('call_time', '')) if record.get('call_time') else ''
        duration_seconds = record.get('duration_seconds') or 0
        duration_mins = round(duration_seconds / 60, 1) if duration_seconds else 0
        direction = record.get('direction') or 'Unknown'
        from_number = record.get('from_number') or ''
        to_number = record.get('to_number') or ''

        # Participants
        customer_name = record.get('customer_name') or 'Unknown Customer'
        customer_phone = record.get('customer_phone') or ''
        customer_company = record.get('customer_company') or ''
        employee_name = record.get('employee_name') or 'Unknown Employee'
        employee_extension = record.get('employee_extension') or ''

        # Analysis
        customer_sentiment = record.get('customer_sentiment') or ''
        call_quality_score = record.get('call_quality_score') or 0
        call_type = record.get('call_type') or ''
        summary = record.get('summary') or ''
        key_topics = record.get('key_topics') or []
        coaching_notes = record.get('coaching_notes') or ''

        # Resolution
        resolution_status = record.get('resolution_status') or ''
        problem_statement = record.get('problem_statement') or ''
        follow_up_needed = bool(record.get('follow_up_needed'))
        escalation_required = bool(record.get('escalation_required'))

        # Scores
        closure_score = record.get('closure_score') or 0
        empathy_score = record.get('empathy_score') or 0
        efficiency_score = record.get('efficiency_score') or 0

        # Risk
        churn_risk = record.get('churn_risk') or ''
        call_back_risk = record.get('call_back_risk') or ''
        risk_level = record.get('risk_level') or ''

        # Recommendations
        process_improvements = record.get('process_improvements') or []
        employee_strengths = record.get('employee_strengths') or []
        employee_improvements = record.get('employee_improvements') or []
        follow_up_actions = record.get('follow_up_actions') or []

        # Build content
        parts = []

        parts.append(f"CALL RECORDING {recording_id}")
        parts.append(f"Date: {call_date} {call_time}")
        parts.append(f"Duration: {duration_mins} minutes")
        parts.append(f"Direction: {direction}")
        if from_number:
            parts.append(f"From Number: {from_number}")
        if to_number:
            parts.append(f"To Number: {to_number}")
        parts.append("")

        parts.append("PARTICIPANTS")
        parts.append(f"Customer: {customer_name}")
        if customer_company:
            parts.append(f"Company: {customer_company}")
        if customer_phone:
            parts.append(f"Phone: {customer_phone}")
        parts.append(f"Employee: {employee_name}")
        if employee_extension:
            parts.append(f"Extension: {employee_extension}")
        parts.append("")

        parts.append("CALL ANALYSIS")
        if summary:
            parts.append(f"Summary: {summary}")
        parts.append(f"Type: {call_type}")
        if key_topics:
            topics = ', '.join(key_topics) if isinstance(key_topics, list) else str(key_topics)
            parts.append(f"Topics: {topics}")
        parts.append(f"Sentiment: {customer_sentiment}")
        parts.append(f"Quality Score: {call_quality_score}/10")
        parts.append("")

        parts.append("RESOLUTION")
        parts.append(f"Status: {resolution_status}")
        if problem_statement:
            parts.append(f"Problem: {problem_statement}")
        parts.append(f"Follow-up Needed: {'Yes' if follow_up_needed else 'No'}")
        parts.append(f"Escalation: {'Required' if escalation_required else 'Not Required'}")
        parts.append("")

        parts.append("PERFORMANCE")
        parts.append(f"Closure: {closure_score}/10")
        parts.append(f"Empathy: {empathy_score}/10")
        parts.append(f"Efficiency: {efficiency_score}/10")
        parts.append("")

        parts.append("RISK ASSESSMENT")
        parts.append(f"Churn Risk: {churn_risk}")
        parts.append(f"Callback Risk: {call_back_risk}")
        parts.append(f"Overall Risk: {risk_level}")
        parts.append("")

        if coaching_notes:
            parts.append("COACHING NOTES")
            parts.append(coaching_notes)
            parts.append("")

        if employee_strengths:
            parts.append("STRENGTHS")
            for s in employee_strengths:
                parts.append(f"- {s}")
            parts.append("")

        if employee_improvements:
            parts.append("AREAS FOR IMPROVEMENT")
            for i in employee_improvements:
                parts.append(f"- {i}")
            parts.append("")

        if process_improvements:
            parts.append("PROCESS IMPROVEMENTS")
            for p in process_improvements:
                parts.append(f"- {p}")
            parts.append("")

        if follow_up_actions:
            parts.append("FOLLOW-UP ACTIONS")
            for a in follow_up_actions:
                parts.append(f"- {a}")
            parts.append("")

        parts.append("TRANSCRIPT")
        parts.append(transcript_text)

        return '\n'.join(parts)

    def upload_to_gcs(self, content: str, recording_id: str) -> str:
        """Upload document to GCS"""
        client = storage.Client()
        bucket = client.bucket(self.config.gcs_bucket)

        blob_name = f"transcripts/{recording_id}.txt"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(content, content_type='text/plain')

        return f"gs://{self.config.gcs_bucket}/{blob_name}"

    def migrate(self, limit: int = None, batch_size: int = 100) -> Dict:
        """
        Run the migration

        Args:
            limit: Optional limit on records to migrate
            batch_size: Records per batch for GCS upload
        """
        if not VERTEX_AI_AVAILABLE:
            raise RuntimeError("Vertex AI SDK not available")

        # Initialize Vertex AI
        vertexai.init(
            project=self.config.project_id,
            location=self.config.location
        )
        logger.info(f"Initialized Vertex AI: project={self.config.project_id}, location={self.config.location}")

        conn = self.connect_db()
        logger.info("Connected to PostgreSQL")

        try:
            total = self.get_transcript_count(conn)
            to_process = min(total, limit) if limit else total
            logger.info(f"Total transcripts: {total}, processing: {to_process}")

            # Get or create corpus
            corpora = list(rag.list_corpora())
            corpus_name = None

            for corpus in corpora:
                if corpus.display_name == self.config.corpus_display_name:
                    corpus_name = corpus.name
                    logger.info(f"Found existing corpus: {corpus_name}")
                    break

            if not corpus_name:
                logger.info("Creating new corpus...")
                embedding_config = rag.RagEmbeddingModelConfig(
                    vertex_prediction_endpoint=rag.VertexPredictionEndpoint(
                        publisher_model=f"publishers/google/models/{self.config.embedding_model}"
                    )
                )
                corpus = rag.create_corpus(
                    display_name=self.config.corpus_display_name,
                    description=self.config.corpus_description,
                    backend_config=rag.RagVectorDbConfig(
                        rag_embedding_model_config=embedding_config
                    ),
                )
                corpus_name = corpus.name
                logger.info(f"Created corpus: {corpus_name}")

            # Process in batches
            offset = 0
            gcs_uris = []

            while offset < to_process:
                current_batch = min(batch_size, to_process - offset)
                records = self.fetch_transcripts(conn, offset, current_batch)

                if not records:
                    break

                logger.info(f"Processing batch {offset}-{offset + len(records)}")

                for record in records:
                    try:
                        recording_id = record['recording_id']
                        content = self.build_document_content(record)

                        # Upload to GCS
                        gcs_uri = self.upload_to_gcs(content, recording_id)
                        gcs_uris.append(gcs_uri)

                        self.stats['successful'] += 1
                        self.stats['total_processed'] += 1

                        if self.stats['successful'] % 50 == 0:
                            logger.info(f"  Uploaded {self.stats['successful']} documents to GCS")

                    except Exception as e:
                        self.stats['failed'] += 1
                        self.stats['total_processed'] += 1
                        self.stats['errors'].append({
                            'recording_id': record.get('recording_id'),
                            'error': str(e)
                        })
                        logger.error(f"  Error processing {record.get('recording_id')}: {e}")

                offset += len(records)

            logger.info(f"Uploaded {len(gcs_uris)} documents to GCS")

            # Import to corpus in batches of 50 paths
            if gcs_uris:
                logger.info("Importing documents into RAG corpus...")

                import_batch_size = 50
                for i in range(0, len(gcs_uris), import_batch_size):
                    batch_uris = gcs_uris[i:i + import_batch_size]
                    try:
                        transformation_config = rag.TransformationConfig(
                            chunking_config=rag.ChunkingConfig(
                                chunk_size=self.config.chunk_size,
                                chunk_overlap=self.config.chunk_overlap,
                            ),
                        )

                        result = rag.import_files(
                            corpus_name,
                            batch_uris,
                            transformation_config=transformation_config,
                            max_embedding_requests_per_min=self.config.max_embedding_requests_per_min,
                        )
                        logger.info(f"  Imported batch {i // import_batch_size + 1}: {len(batch_uris)} files")

                    except Exception as e:
                        logger.error(f"  Failed to import batch: {e}")
                        self.stats['errors'].append({'batch': i, 'error': str(e)})

            self.stats['corpus_name'] = corpus_name
            self.stats['gcs_documents'] = len(gcs_uris)

            return self.stats

        finally:
            conn.close()
            logger.info("Disconnected from PostgreSQL")


def main():
    parser = argparse.ArgumentParser(description='Migrate PostgreSQL data to Vertex AI RAG')
    parser.add_argument('--limit', '-l', type=int, help='Limit number of records to migrate')
    parser.add_argument('--batch-size', '-b', type=int, default=100, help='Batch size for processing')

    args = parser.parse_args()

    migrator = DirectMigrator()

    logger.info("Starting direct migration to Vertex AI RAG")
    stats = migrator.migrate(limit=args.limit, batch_size=args.batch_size)

    logger.info(f"\n{'='*50}")
    logger.info("MIGRATION COMPLETE")
    logger.info(f"{'='*50}")
    logger.info(f"Total processed: {stats['total_processed']}")
    logger.info(f"Successful: {stats['successful']}")
    logger.info(f"Failed: {stats['failed']}")
    logger.info(f"GCS documents: {stats.get('gcs_documents', 0)}")

    if stats.get('errors'):
        logger.warning(f"Errors: {len(stats['errors'])}")

    # Save stats
    stats_file = Path('/var/www/call-recording-system/data/migration_stats.json')
    stats['timestamp'] = datetime.utcnow().isoformat()
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=2, default=str)
    logger.info(f"Stats saved to {stats_file}")


if __name__ == '__main__':
    main()
