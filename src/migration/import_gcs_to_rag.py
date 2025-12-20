#!/usr/bin/env python3
"""
Import GCS Documents to Vertex AI RAG

Imports existing GCS text files into the Vertex AI RAG corpus.
Uses batch size of 25 (API limit).

Usage:
    python src/migration/import_gcs_to_rag.py
"""

import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List
import time

# Add project root to path
sys.path.insert(0, '/var/www/call-recording-system')

import vertexai
from vertexai import rag
from google.cloud import storage

from src.vertex_ai.config import default_config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def import_gcs_documents():
    """Import all GCS transcripts into RAG corpus"""
    config = default_config

    # Set credentials
    if config.credentials_path:
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = config.credentials_path

    # Initialize Vertex AI
    vertexai.init(
        project=config.project_id,
        location=config.location
    )
    logger.info(f"Initialized Vertex AI: project={config.project_id}, location={config.location}")

    # Get corpus
    corpora = list(rag.list_corpora())
    corpus_name = None

    for corpus in corpora:
        if corpus.display_name == config.corpus_display_name:
            corpus_name = corpus.name
            logger.info(f"Found corpus: {corpus_name}")
            break

    if not corpus_name:
        raise RuntimeError("Corpus not found!")

    # List all files in GCS
    client = storage.Client()
    bucket = client.bucket(config.gcs_bucket)
    blobs = list(bucket.list_blobs(prefix='transcripts/'))

    txt_files = [b for b in blobs if b.name.endswith('.txt')]
    logger.info(f"Found {len(txt_files)} text files in GCS")

    # Build GCS URIs
    gcs_uris = [f"gs://{config.gcs_bucket}/{blob.name}" for blob in txt_files]

    # Import in batches of 25 (API limit)
    batch_size = 25
    successful = 0
    failed = 0

    transformation_config = rag.TransformationConfig(
        chunking_config=rag.ChunkingConfig(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
        ),
    )

    for i in range(0, len(gcs_uris), batch_size):
        batch = gcs_uris[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(gcs_uris) + batch_size - 1) // batch_size

        try:
            result = rag.import_files(
                corpus_name,
                batch,
                transformation_config=transformation_config,
                max_embedding_requests_per_min=config.max_embedding_requests_per_min,
            )
            successful += len(batch)
            logger.info(f"Batch {batch_num}/{total_batches}: Imported {len(batch)} files ({successful}/{len(gcs_uris)} total)")

            # Small delay between batches
            time.sleep(1)

        except Exception as e:
            failed += len(batch)
            logger.error(f"Batch {batch_num}/{total_batches}: Failed - {e}")

    logger.info(f"\n{'='*50}")
    logger.info("IMPORT COMPLETE")
    logger.info(f"{'='*50}")
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Total: {len(gcs_uris)}")

    # Save stats
    stats = {
        'timestamp': datetime.utcnow().isoformat(),
        'total_files': len(gcs_uris),
        'successful': successful,
        'failed': failed,
        'corpus': corpus_name
    }

    stats_file = Path('/var/www/call-recording-system/data/import_gcs_stats.json')
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=2)
    logger.info(f"Stats saved to {stats_file}")


if __name__ == '__main__':
    import_gcs_documents()
