#!/usr/bin/env python3
"""
Freshdesk KB to Vertex AI RAG Import

Exports Freshdesk KB data to JSONL format and imports to Vertex AI RAG corpus.
Handles file size limits by splitting large files into parts.

Key Constraints:
- JSONL files must be < 10MB for Vertex AI RAG
- SDK version: google-cloud-aiplatform >= 1.132.0
- Chunk size: 512 tokens, overlap: 100 tokens

Usage:
    python -m rag_integration.jobs.freshdesk_vertex_import
    python -m rag_integration.jobs.freshdesk_vertex_import --export-only
    python -m rag_integration.jobs.freshdesk_vertex_import --import-only
"""

import os
import sys
import json
import glob
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, '/var/www/call-recording-system')

import vertexai
from vertexai import rag
from google.cloud import storage
from google.oauth2 import service_account
import psycopg2

from dotenv import load_dotenv
load_dotenv('/var/www/call-recording-system/.env')

# Configuration
PROJECT_ID = os.getenv('GOOGLE_CLOUD_PROJECT', 'call-recording-481713')
LOCATION = 'us-west1'
CORPUS_NAME = 'mst_call_intelligence'
GCS_BUCKET = 'call-recording-rag-data'
GCS_PREFIX = 'freshdesk'
CREDENTIALS_PATH = '/var/www/call-recording-system/config/google_service_account.json'
DATABASE_URL = os.getenv('RAG_DATABASE_URL',
    os.getenv('DATABASE_URL', ''))
EXPORT_DIR = '/var/www/call-recording-system/data/rag_exports'

# Vertex AI RAG limits
MAX_JSONL_SIZE_MB = 10
MAX_JSONL_SIZE_BYTES = MAX_JSONL_SIZE_MB * 1024 * 1024
LINES_PER_PART = 2000  # ~6-7MB per part

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FreshdeskVertexImporter:
    """Exports Freshdesk KB to JSONL and imports to Vertex AI RAG."""

    def __init__(self):
        self.credentials = service_account.Credentials.from_service_account_file(
            CREDENTIALS_PATH,
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        self.storage_client = storage.Client(credentials=self.credentials)
        self.bucket = self.storage_client.bucket(GCS_BUCKET)

        # Initialize Vertex AI
        vertexai.init(
            project=PROJECT_ID,
            location=LOCATION,
            credentials=self.credentials
        )

        self.corpus_name = None

    def get_freshdesk_data(self) -> List[Dict[str, Any]]:
        """Fetch enriched Freshdesk Q&A data from database."""
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        cur.execute("""
            SELECT
                qa_id, ticket_id, question, answer,
                category, priority, tags,
                requester_email, agent_name,
                created_at, resolved_at,
                ai_topics, ai_problem_type, ai_product_area,
                ai_sentiment, ai_complexity, ai_resolution_quality,
                ai_resolution_complete, ai_follow_up_needed,
                enriched_at
            FROM kb_freshdesk_qa
            WHERE enriched_at IS NOT NULL
            ORDER BY ticket_id
        """)

        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()

        cur.close()
        conn.close()

        return [dict(zip(columns, row)) for row in rows]

    def format_for_vertex_rag(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format a single Q&A pair for Vertex AI RAG."""
        # Build rich text content
        content_parts = [
            "[SOURCE: FRESHDESK SUPPORT TICKET]",
            f"Ticket ID: {data.get('ticket_id')}",
            f"Category: {data.get('category', 'N/A')}",
            f"Priority: {data.get('priority', 'N/A')}",
            f"Agent: {data.get('agent_name', 'N/A')}",
            "",
            "QUESTION:",
            str(data.get('question', '')),
            "",
            "ANSWER:",
            str(data.get('answer', '')),
        ]

        # Add AI analysis if available
        if data.get('ai_topics'):
            topics = data['ai_topics']
            if isinstance(topics, list):
                content_parts.extend(["", f"Topics: {', '.join(topics)}"])

        if data.get('ai_problem_type'):
            content_parts.append(f"Problem Type: {data['ai_problem_type']}")

        if data.get('ai_sentiment'):
            content_parts.append(f"Sentiment: {data['ai_sentiment']}")

        text_content = "\n".join(content_parts)

        # Build struct_data for filtering
        ai_topics = data.get('ai_topics', [])
        if isinstance(ai_topics, str):
            try:
                ai_topics = json.loads(ai_topics)
            except:
                ai_topics = [ai_topics] if ai_topics else []

        return {
            "id": f"fd_{data.get('qa_id', data.get('ticket_id'))}",
            "content": {
                "mime_type": "text/plain",
                "text": text_content
            },
            "struct_data": {
                "qa_id": f"fd_{data.get('qa_id')}",
                "ticket_id": data.get('ticket_id'),
                "source_type": "freshdesk",
                "category": data.get('category'),
                "priority": data.get('priority'),
                "agent_name": data.get('agent_name'),
                "ai_topics": ai_topics,
                "ai_problem_type": data.get('ai_problem_type'),
                "ai_product_area": data.get('ai_product_area'),
                "ai_sentiment": data.get('ai_sentiment'),
                "ai_complexity": data.get('ai_complexity'),
                "ai_resolution_quality": data.get('ai_resolution_quality'),
                "is_enriched": data.get('enriched_at') is not None
            }
        }

    def export_to_jsonl(self) -> List[str]:
        """Export Freshdesk data to split JSONL files."""
        logger.info("Fetching Freshdesk data...")
        data = self.get_freshdesk_data()
        logger.info(f"Found {len(data)} enriched Q&A pairs")

        if not data:
            return []

        # Create export directory
        os.makedirs(EXPORT_DIR, exist_ok=True)

        # Generate timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Split into parts
        parts = []
        for i in range(0, len(data), LINES_PER_PART):
            part_data = data[i:i + LINES_PER_PART]
            part_num = i // LINES_PER_PART

            part_file = f"{EXPORT_DIR}/freshdesk_vertex_part_{part_num:02d}_{timestamp}.jsonl"

            with open(part_file, 'w') as f:
                for record in part_data:
                    formatted = self.format_for_vertex_rag(record)
                    f.write(json.dumps(formatted) + '\n')

            size_mb = os.path.getsize(part_file) / 1024 / 1024
            logger.info(f"Created: {part_file} ({len(part_data)} records, {size_mb:.2f} MB)")
            parts.append(part_file)

        return parts

    def upload_to_gcs(self, local_files: List[str]) -> List[str]:
        """Upload JSONL files to GCS."""
        gcs_uris = []

        for local_file in local_files:
            blob_name = f"{GCS_PREFIX}/{os.path.basename(local_file)}"
            blob = self.bucket.blob(blob_name)
            blob.upload_from_filename(local_file)

            gcs_uri = f"gs://{GCS_BUCKET}/{blob_name}"
            logger.info(f"Uploaded: {gcs_uri}")
            gcs_uris.append(gcs_uri)

        return gcs_uris

    def get_or_create_corpus(self) -> str:
        """Get existing or create new RAG corpus."""
        corpora = list(rag.list_corpora())

        for c in corpora:
            if c.display_name == CORPUS_NAME:
                self.corpus_name = c.name
                logger.info(f"Found existing corpus: {c.name}")
                return c.name

        logger.info(f"Creating new corpus: {CORPUS_NAME}")
        corpus = rag.create_corpus(
            display_name=CORPUS_NAME,
            description="MST/PCRecruiter Knowledge Base - Call Recordings and Freshdesk Support"
        )
        self.corpus_name = corpus.name
        return corpus.name

    def import_to_rag(self, gcs_uris: List[str]) -> Dict[str, Any]:
        """Import JSONL files to Vertex AI RAG corpus."""
        corpus_name = self.get_or_create_corpus()

        results = {
            "corpus": corpus_name,
            "files_imported": 0,
            "files_failed": 0,
            "details": []
        }

        for gcs_uri in gcs_uris:
            logger.info(f"Importing: {gcs_uri}")
            try:
                result = rag.import_files(
                    corpus_name=corpus_name,
                    paths=[gcs_uri],
                    transformation_config=rag.TransformationConfig(
                        chunking_config=rag.ChunkingConfig(
                            chunk_size=512,
                            chunk_overlap=100,
                        ),
                    ),
                    max_embedding_requests_per_min=1000,
                )

                results["files_imported"] += 1
                results["details"].append({
                    "uri": gcs_uri,
                    "status": "success",
                    "result": str(result)
                })
                logger.info(f"  Success: {result}")

            except Exception as e:
                results["files_failed"] += 1
                results["details"].append({
                    "uri": gcs_uri,
                    "status": "failed",
                    "error": str(e)
                })
                logger.error(f"  Failed: {e}")

        return results

    def update_tracking(self, records_count: int, gcs_uris: List[str],
                       corpus_name: str, status: str) -> None:
        """Update tracking table in database."""
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO kb_rag_exports (
                export_type, records_count, gcs_uri,
                vertex_imported, vertex_corpus,
                created_at, exported_at, imported_at, status
            ) VALUES (
                'freshdesk', %s, %s,
                %s, %s,
                NOW(), NOW(), NOW(), %s
            )
        """, (
            records_count,
            ','.join(gcs_uris),
            status == 'imported',
            corpus_name,
            status
        ))

        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"Tracking updated: {status}")

    def run(self, export_only: bool = False, import_only: bool = False) -> Dict[str, Any]:
        """Run full export and import pipeline."""
        result = {
            "timestamp": datetime.now().isoformat(),
            "export": None,
            "import": None
        }

        if not import_only:
            # Export to JSONL
            logger.info("=" * 50)
            logger.info("EXPORTING TO JSONL")
            logger.info("=" * 50)

            local_files = self.export_to_jsonl()

            if not local_files:
                logger.warning("No data to export")
                return result

            # Upload to GCS
            logger.info("\nUploading to GCS...")
            gcs_uris = self.upload_to_gcs(local_files)

            result["export"] = {
                "files": len(local_files),
                "gcs_uris": gcs_uris
            }

        if not export_only:
            # Get GCS URIs if import-only
            if import_only:
                # Find latest files in GCS
                blobs = list(self.bucket.list_blobs(prefix=f"{GCS_PREFIX}/freshdesk_vertex_part_"))
                gcs_uris = [f"gs://{GCS_BUCKET}/{b.name}" for b in blobs]
                gcs_uris = sorted(gcs_uris)[-3:]  # Latest 3 parts

            # Import to Vertex AI RAG
            logger.info("\n" + "=" * 50)
            logger.info("IMPORTING TO VERTEX AI RAG")
            logger.info("=" * 50)

            import_result = self.import_to_rag(gcs_uris)
            result["import"] = import_result

            # Update tracking
            records_count = len(self.get_freshdesk_data()) if not import_only else 0
            status = "imported" if import_result["files_failed"] == 0 else "partial"
            self.update_tracking(
                records_count,
                gcs_uris,
                import_result["corpus"],
                status
            )

        logger.info("\n" + "=" * 50)
        logger.info("COMPLETE")
        logger.info("=" * 50)

        return result


def main():
    parser = argparse.ArgumentParser(description='Freshdesk to Vertex AI RAG Import')
    parser.add_argument('--export-only', action='store_true',
                       help='Only export to JSONL, do not import')
    parser.add_argument('--import-only', action='store_true',
                       help='Only import existing files from GCS')

    args = parser.parse_args()

    importer = FreshdeskVertexImporter()
    result = importer.run(
        export_only=args.export_only,
        import_only=args.import_only
    )

    print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    main()
