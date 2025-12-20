"""
Vertex AI RAG Indexer

Indexes call transcripts with metadata into Vertex AI RAG Engine.
Used for both batch migration and real-time indexing of new transcripts.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path
import uuid

try:
    import vertexai
    from vertexai import rag
    from google.cloud import storage
    VERTEX_AI_AVAILABLE = True
except ImportError:
    VERTEX_AI_AVAILABLE = False

from .config import VertexAIConfig, default_config
from .corpus_manager import VertexAICorpusManager

logger = logging.getLogger(__name__)


class VertexRAGIndexer:
    """
    Indexes call transcripts into Vertex AI RAG Engine.

    Each transcript is stored as a document with:
    - Full transcript text in 'content' field
    - All metadata in 'structData' field (call info, AI insights, etc.)
    """

    def __init__(self, config: Optional[VertexAIConfig] = None):
        """
        Initialize the RAG indexer

        Args:
            config: Optional configuration
        """
        self.config = config or default_config
        self._corpus_manager = None
        self._corpus_name = None
        self._storage_client = None
        self._initialized = False

        if not VERTEX_AI_AVAILABLE:
            logger.warning("Vertex AI SDK not installed. Run: pip install google-cloud-aiplatform google-cloud-storage")
            return

        self._initialize()

    def _initialize(self):
        """Initialize Vertex AI and storage clients"""
        try:
            # Set credentials
            if self.config.credentials_path and Path(self.config.credentials_path).exists():
                import os
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = self.config.credentials_path

            # Initialize Vertex AI
            vertexai.init(
                project=self.config.project_id,
                location=self.config.location
            )

            # Initialize corpus manager
            self._corpus_manager = VertexAICorpusManager(self.config)

            # Get or create corpus
            self._corpus_name = self._corpus_manager.get_or_create_corpus()

            # Initialize storage client
            self._storage_client = storage.Client()

            self._initialized = True
            logger.info(f"RAG Indexer initialized with corpus: {self._corpus_name}")

        except Exception as e:
            logger.error(f"Failed to initialize RAG Indexer: {e}")
            raise

    def index_transcript(
        self,
        recording_id: str,
        transcript_text: str,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Index a single transcript with metadata into Vertex AI RAG

        Args:
            recording_id: Unique recording identifier
            transcript_text: Full transcript text
            metadata: Dictionary containing all metadata (call info, AI insights, etc.)

        Returns:
            Result dict with status and details
        """
        if not self._initialized:
            raise RuntimeError("RAG Indexer not initialized")

        try:
            # Build document
            document = self._build_document(recording_id, transcript_text, metadata)

            # Upload to GCS
            gcs_uri = self._upload_document(recording_id, document)

            # Import into corpus
            self._import_document(gcs_uri)

            logger.info(f"Indexed transcript {recording_id} into Vertex AI RAG")

            return {
                'status': 'success',
                'recording_id': recording_id,
                'gcs_uri': gcs_uri,
                'corpus': self._corpus_name
            }

        except Exception as e:
            logger.error(f"Failed to index transcript {recording_id}: {e}")
            return {
                'status': 'error',
                'recording_id': recording_id,
                'error': str(e)
            }

    def _build_document(
        self,
        recording_id: str,
        transcript_text: str,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build a Vertex AI compatible document

        Args:
            recording_id: Recording ID
            transcript_text: Full transcript
            metadata: All metadata

        Returns:
            Document dict
        """
        # Clean and validate metadata
        clean_metadata = self._clean_metadata(metadata)
        clean_metadata['recording_id'] = recording_id
        clean_metadata['indexed_at'] = datetime.utcnow().isoformat()

        return {
            'id': recording_id,
            'structData': clean_metadata,
            'content': transcript_text
        }

    def _clean_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean metadata for Vertex AI compatibility

        - Convert None to empty strings
        - Convert complex objects to strings
        - Ensure all values are JSON serializable
        """
        clean = {}

        for key, value in metadata.items():
            if value is None:
                clean[key] = ''
            elif isinstance(value, (list, dict)):
                # Keep lists and dicts as-is (they're JSON serializable)
                clean[key] = value
            elif isinstance(value, (int, float, bool, str)):
                clean[key] = value
            elif isinstance(value, datetime):
                clean[key] = value.isoformat()
            else:
                # Convert other types to string
                clean[key] = str(value)

        return clean

    def _upload_document(self, recording_id: str, document: Dict[str, Any]) -> str:
        """
        Upload document to GCS as JSONL

        Args:
            recording_id: Recording ID for filename
            document: Document to upload

        Returns:
            GCS URI of uploaded file
        """
        bucket = self._storage_client.bucket(self.config.gcs_bucket)
        blob_name = f"{self.config.gcs_transcripts_prefix}{recording_id}.json"
        blob = bucket.blob(blob_name)

        # Convert to JSON
        content = json.dumps(document, ensure_ascii=False, indent=2)

        # Upload
        blob.upload_from_string(content, content_type='application/json')

        gcs_uri = f"gs://{self.config.gcs_bucket}/{blob_name}"
        logger.debug(f"Uploaded document to {gcs_uri}")

        return gcs_uri

    def _import_document(self, gcs_uri: str):
        """
        Import a document from GCS into the RAG corpus

        Args:
            gcs_uri: GCS URI of the document
        """
        try:
            # Configure chunking
            transformation_config = rag.TransformationConfig(
                chunking_config=rag.ChunkingConfig(
                    chunk_size=self.config.chunk_size,
                    chunk_overlap=self.config.chunk_overlap,
                ),
            )

            # Import file
            rag.import_files(
                self._corpus_name,
                [gcs_uri],
                transformation_config=transformation_config,
                max_embedding_requests_per_min=self.config.max_embedding_requests_per_min,
            )

            logger.debug(f"Imported {gcs_uri} into corpus")

        except Exception as e:
            logger.error(f"Failed to import document: {e}")
            raise

    def index_batch(
        self,
        transcripts: List[Dict[str, Any]],
        batch_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Index multiple transcripts as a batch

        Args:
            transcripts: List of dicts with 'recording_id', 'transcript_text', 'metadata'
            batch_id: Optional batch identifier

        Returns:
            Batch result summary
        """
        if not self._initialized:
            raise RuntimeError("RAG Indexer not initialized")

        batch_id = batch_id or f"batch_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        results = {
            'batch_id': batch_id,
            'total': len(transcripts),
            'success': 0,
            'failed': 0,
            'errors': []
        }

        # Upload all documents to GCS first
        gcs_uris = []
        for transcript in transcripts:
            try:
                document = self._build_document(
                    transcript['recording_id'],
                    transcript['transcript_text'],
                    transcript.get('metadata', {})
                )
                gcs_uri = self._upload_document(transcript['recording_id'], document)
                gcs_uris.append(gcs_uri)
                results['success'] += 1
            except Exception as e:
                results['failed'] += 1
                results['errors'].append({
                    'recording_id': transcript.get('recording_id'),
                    'error': str(e)
                })

        # Batch import all uploaded files
        if gcs_uris:
            try:
                transformation_config = rag.TransformationConfig(
                    chunking_config=rag.ChunkingConfig(
                        chunk_size=self.config.chunk_size,
                        chunk_overlap=self.config.chunk_overlap,
                    ),
                )

                rag.import_files(
                    self._corpus_name,
                    gcs_uris,
                    transformation_config=transformation_config,
                    max_embedding_requests_per_min=self.config.max_embedding_requests_per_min,
                )

                logger.info(f"Batch {batch_id}: Imported {len(gcs_uris)} documents")

            except Exception as e:
                logger.error(f"Batch import failed: {e}")
                results['errors'].append({'batch_import': str(e)})

        return results

    def delete_transcript(self, recording_id: str) -> bool:
        """
        Delete a transcript from the RAG corpus

        Args:
            recording_id: Recording ID to delete

        Returns:
            True if deleted successfully
        """
        if not self._initialized:
            raise RuntimeError("RAG Indexer not initialized")

        try:
            # Delete from GCS
            bucket = self._storage_client.bucket(self.config.gcs_bucket)
            blob_name = f"{self.config.gcs_transcripts_prefix}{recording_id}.json"
            blob = bucket.blob(blob_name)

            if blob.exists():
                blob.delete()
                logger.info(f"Deleted {recording_id} from GCS")

            # Note: Deleting from RAG corpus requires finding the file ID
            # This is more complex and may require listing files first

            return True

        except Exception as e:
            logger.error(f"Failed to delete transcript {recording_id}: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """
        Get indexer statistics

        Returns:
            Stats dict
        """
        stats = {
            'initialized': self._initialized,
            'corpus_name': self._corpus_name,
            'gcs_bucket': self.config.gcs_bucket,
        }

        if self._initialized:
            try:
                # Count documents in GCS
                bucket = self._storage_client.bucket(self.config.gcs_bucket)
                blobs = list(bucket.list_blobs(prefix=self.config.gcs_transcripts_prefix))
                stats['gcs_document_count'] = len(blobs)

                # Get corpus stats
                if self._corpus_manager:
                    corpus_stats = self._corpus_manager.get_corpus_stats(self._corpus_name)
                    stats['corpus_stats'] = corpus_stats

            except Exception as e:
                stats['error'] = str(e)

        return stats
