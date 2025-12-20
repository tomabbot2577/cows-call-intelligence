#!/usr/bin/env python3
"""
Import JSONL Files to Vertex AI RAG

Imports exported JSONL files into the Vertex AI RAG corpus.

Usage:
    python src/migration/import_to_rag.py --source /path/to/exports/
    python src/migration/import_to_rag.py --source gs://bucket/exports/
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

# Add project root to path
sys.path.insert(0, '/var/www/call-recording-system')

from src.vertex_ai.config import default_config
from src.vertex_ai.corpus_manager import VertexAICorpusManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class VertexAIImporter:
    """Imports JSONL files into Vertex AI RAG corpus"""

    def __init__(self):
        """Initialize the importer"""
        # Set credentials
        if default_config.credentials_path:
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = default_config.credentials_path

        self.corpus_manager = VertexAICorpusManager()
        self.stats = {
            'files_processed': 0,
            'documents_imported': 0,
            'errors': []
        }

    def upload_local_to_gcs(self, local_path: str) -> List[str]:
        """
        Upload local JSONL files to GCS

        Args:
            local_path: Path to local directory with JSONL files

        Returns:
            List of GCS URIs
        """
        from google.cloud import storage

        local_dir = Path(local_path)
        jsonl_files = list(local_dir.glob('*.jsonl'))

        if not jsonl_files:
            logger.warning(f"No JSONL files found in {local_path}")
            return []

        client = storage.Client()
        bucket = client.bucket(default_config.gcs_bucket)
        gcs_uris = []

        for file_path in jsonl_files:
            blob_name = f"imports/{file_path.name}"
            blob = bucket.blob(blob_name)

            logger.info(f"Uploading {file_path.name} to GCS...")
            blob.upload_from_filename(str(file_path))

            gcs_uri = f"gs://{default_config.gcs_bucket}/{blob_name}"
            gcs_uris.append(gcs_uri)
            logger.info(f"Uploaded: {gcs_uri}")

        return gcs_uris

    def import_from_gcs(self, gcs_uris: List[str], corpus_name: str = None) -> Dict[str, Any]:
        """
        Import JSONL files from GCS into RAG corpus

        Args:
            gcs_uris: List of GCS URIs to import
            corpus_name: Optional corpus name (uses default if not provided)

        Returns:
            Import results
        """
        if not gcs_uris:
            logger.warning("No GCS URIs to import")
            return self.stats

        # Get or create corpus
        if not corpus_name:
            corpus_name = self.corpus_manager.get_or_create_corpus()

        logger.info(f"Importing {len(gcs_uris)} files into corpus: {corpus_name}")

        try:
            result = self.corpus_manager.import_documents(gcs_uris, corpus_name)
            self.stats['files_processed'] = len(gcs_uris)
            self.stats['import_result'] = result
            logger.info(f"Import complete: {result}")

        except Exception as e:
            logger.error(f"Import failed: {e}")
            self.stats['errors'].append(str(e))

        return self.stats

    def import_from_local(self, local_path: str, corpus_name: str = None) -> Dict[str, Any]:
        """
        Import local JSONL files (uploads to GCS first)

        Args:
            local_path: Path to local directory
            corpus_name: Optional corpus name

        Returns:
            Import results
        """
        # Upload to GCS
        gcs_uris = self.upload_local_to_gcs(local_path)

        if not gcs_uris:
            return self.stats

        # Import from GCS
        return self.import_from_gcs(gcs_uris, corpus_name)

    def count_documents_in_jsonl(self, path: str) -> int:
        """Count total documents in JSONL files"""
        total = 0

        if path.startswith('gs://'):
            # GCS path - count by listing blobs
            from google.cloud import storage
            client = storage.Client()

            # Parse bucket and prefix
            parts = path.replace('gs://', '').split('/', 1)
            bucket_name = parts[0]
            prefix = parts[1] if len(parts) > 1 else ''

            bucket = client.bucket(bucket_name)
            blobs = bucket.list_blobs(prefix=prefix)

            for blob in blobs:
                if blob.name.endswith('.jsonl'):
                    # Download and count lines
                    content = blob.download_as_text()
                    total += len(content.strip().split('\n'))

        else:
            # Local path
            local_dir = Path(path)
            for jsonl_file in local_dir.glob('*.jsonl'):
                with open(jsonl_file, 'r') as f:
                    total += sum(1 for _ in f)

        return total


def main():
    parser = argparse.ArgumentParser(description='Import JSONL files to Vertex AI RAG')
    parser.add_argument('--source', '-s', required=True,
                       help='Source path (local directory or gs:// URI)')
    parser.add_argument('--corpus', '-c',
                       help='Corpus name (uses default if not specified)')
    parser.add_argument('--count-only', action='store_true',
                       help='Only count documents, do not import')

    args = parser.parse_args()

    logger.info("Starting Vertex AI RAG Import")
    logger.info(f"Source: {args.source}")

    importer = VertexAIImporter()

    if args.count_only:
        count = importer.count_documents_in_jsonl(args.source)
        logger.info(f"Total documents: {count}")
        return

    # Determine if source is GCS or local
    if args.source.startswith('gs://'):
        # GCS source - list JSONL files
        from google.cloud import storage
        client = storage.Client()

        parts = args.source.replace('gs://', '').split('/', 1)
        bucket_name = parts[0]
        prefix = parts[1] if len(parts) > 1 else ''

        bucket = client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix=prefix))

        gcs_uris = [
            f"gs://{bucket_name}/{blob.name}"
            for blob in blobs
            if blob.name.endswith('.jsonl')
        ]

        stats = importer.import_from_gcs(gcs_uris, args.corpus)
    else:
        # Local source
        stats = importer.import_from_local(args.source, args.corpus)

    logger.info(f"\n{'='*50}")
    logger.info(f"Import Complete!")
    logger.info(f"Files processed: {stats.get('files_processed', 0)}")

    if stats.get('errors'):
        logger.warning(f"Errors: {len(stats['errors'])}")
        for error in stats['errors']:
            logger.warning(f"  - {error}")

    # Save stats
    stats_file = Path('/var/www/call-recording-system/data/import_stats.json')
    stats['timestamp'] = datetime.utcnow().isoformat()
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=2, default=str)
    logger.info(f"Stats saved to {stats_file}")


if __name__ == '__main__':
    main()
