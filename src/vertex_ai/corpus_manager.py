"""
Vertex AI RAG Corpus Manager

Manages the RAG corpus for call recording transcripts:
- Create/delete corpus
- Import documents from GCS
- Get corpus statistics
"""

import logging
from typing import List, Dict, Optional, Any
from pathlib import Path

try:
    import vertexai
    from vertexai import rag
    from google.cloud import storage
    VERTEX_AI_AVAILABLE = True
except ImportError:
    VERTEX_AI_AVAILABLE = False

from .config import VertexAIConfig, default_config

logger = logging.getLogger(__name__)


class VertexAICorpusManager:
    """Manages Vertex AI RAG corpus for call transcripts"""

    def __init__(self, config: Optional[VertexAIConfig] = None):
        """
        Initialize the corpus manager

        Args:
            config: Optional configuration, uses default if not provided
        """
        self.config = config or default_config
        self._corpus = None
        self._corpus_name = None
        self._initialized = False

        if not VERTEX_AI_AVAILABLE:
            logger.warning("Vertex AI SDK not installed. Run: pip install google-cloud-aiplatform")
            return

        self._initialize()

    def _initialize(self):
        """Initialize Vertex AI connection"""
        try:
            # Set credentials if path provided
            if self.config.credentials_path and Path(self.config.credentials_path).exists():
                import os
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = self.config.credentials_path

            # Initialize Vertex AI
            vertexai.init(
                project=self.config.project_id,
                location=self.config.location
            )

            self._initialized = True
            logger.info(f"Vertex AI initialized: project={self.config.project_id}, location={self.config.location}")

        except Exception as e:
            logger.error(f"Failed to initialize Vertex AI: {e}")
            raise

    def create_corpus(self, display_name: Optional[str] = None) -> str:
        """
        Create a new RAG corpus

        Args:
            display_name: Optional display name, uses config default if not provided

        Returns:
            Corpus resource name
        """
        if not self._initialized:
            raise RuntimeError("Vertex AI not initialized")

        display_name = display_name or self.config.corpus_display_name

        try:
            # Configure embedding model
            embedding_config = rag.RagEmbeddingModelConfig(
                vertex_prediction_endpoint=rag.VertexPredictionEndpoint(
                    publisher_model=f"publishers/google/models/{self.config.embedding_model}"
                )
            )

            # Create corpus with embedding config
            corpus = rag.create_corpus(
                display_name=display_name,
                description=self.config.corpus_description,
                backend_config=rag.RagVectorDbConfig(
                    rag_embedding_model_config=embedding_config
                ),
            )

            self._corpus = corpus
            self._corpus_name = corpus.name

            logger.info(f"Created corpus: {corpus.name}")
            return corpus.name

        except Exception as e:
            logger.error(f"Failed to create corpus: {e}")
            raise

    def get_corpus(self, corpus_name: Optional[str] = None) -> Any:
        """
        Get an existing corpus

        Args:
            corpus_name: Full corpus resource name or display name

        Returns:
            Corpus object
        """
        if not self._initialized:
            raise RuntimeError("Vertex AI not initialized")

        try:
            # List all corpora and find by name
            corpora = rag.list_corpora()

            search_name = corpus_name or self.config.corpus_display_name

            for corpus in corpora:
                if corpus.display_name == search_name or corpus.name == search_name:
                    self._corpus = corpus
                    self._corpus_name = corpus.name
                    logger.info(f"Found corpus: {corpus.name}")
                    return corpus

            logger.warning(f"Corpus not found: {search_name}")
            return None

        except Exception as e:
            logger.error(f"Failed to get corpus: {e}")
            raise

    def get_or_create_corpus(self, display_name: Optional[str] = None) -> str:
        """
        Get existing corpus or create new one

        Args:
            display_name: Corpus display name

        Returns:
            Corpus resource name
        """
        display_name = display_name or self.config.corpus_display_name

        # Try to get existing
        corpus = self.get_corpus(display_name)
        if corpus:
            return corpus.name

        # Create new
        return self.create_corpus(display_name)

    def import_documents(
        self,
        gcs_paths: List[str],
        corpus_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Import documents from GCS into the corpus

        Args:
            gcs_paths: List of GCS URIs (gs://bucket/path/*.jsonl)
            corpus_name: Optional corpus name, uses current if not provided

        Returns:
            Import operation result
        """
        if not self._initialized:
            raise RuntimeError("Vertex AI not initialized")

        corpus_name = corpus_name or self._corpus_name
        if not corpus_name:
            raise ValueError("No corpus specified. Create or get a corpus first.")

        try:
            # Configure chunking
            transformation_config = rag.TransformationConfig(
                chunking_config=rag.ChunkingConfig(
                    chunk_size=self.config.chunk_size,
                    chunk_overlap=self.config.chunk_overlap,
                ),
            )

            # Import files
            result = rag.import_files(
                corpus_name,
                gcs_paths,
                transformation_config=transformation_config,
                max_embedding_requests_per_min=self.config.max_embedding_requests_per_min,
            )

            logger.info(f"Imported documents from {len(gcs_paths)} paths")
            return {
                'status': 'success',
                'corpus': corpus_name,
                'paths': gcs_paths,
                'result': str(result)
            }

        except Exception as e:
            logger.error(f"Failed to import documents: {e}")
            raise

    def delete_corpus(self, corpus_name: Optional[str] = None) -> bool:
        """
        Delete a corpus

        Args:
            corpus_name: Corpus to delete, uses current if not provided

        Returns:
            True if deleted successfully
        """
        if not self._initialized:
            raise RuntimeError("Vertex AI not initialized")

        corpus_name = corpus_name or self._corpus_name
        if not corpus_name:
            raise ValueError("No corpus specified")

        try:
            rag.delete_corpus(corpus_name)
            logger.info(f"Deleted corpus: {corpus_name}")

            if corpus_name == self._corpus_name:
                self._corpus = None
                self._corpus_name = None

            return True

        except Exception as e:
            logger.error(f"Failed to delete corpus: {e}")
            raise

    def list_corpora(self) -> List[Dict[str, str]]:
        """
        List all corpora in the project

        Returns:
            List of corpus info dicts
        """
        if not self._initialized:
            raise RuntimeError("Vertex AI not initialized")

        try:
            corpora = rag.list_corpora()
            return [
                {
                    'name': corpus.name,
                    'display_name': corpus.display_name,
                    'description': getattr(corpus, 'description', ''),
                }
                for corpus in corpora
            ]

        except Exception as e:
            logger.error(f"Failed to list corpora: {e}")
            raise

    def get_corpus_stats(self, corpus_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get statistics for a corpus

        Args:
            corpus_name: Corpus to get stats for

        Returns:
            Statistics dict
        """
        if not self._initialized:
            raise RuntimeError("Vertex AI not initialized")

        corpus_name = corpus_name or self._corpus_name
        if not corpus_name:
            raise ValueError("No corpus specified")

        try:
            corpus = rag.get_corpus(corpus_name)

            # Get file list
            files = list(rag.list_files(corpus_name))

            return {
                'corpus_name': corpus.name,
                'display_name': corpus.display_name,
                'file_count': len(files),
                'files': [
                    {
                        'name': f.name,
                        'display_name': f.display_name,
                    }
                    for f in files[:100]  # Limit to first 100
                ]
            }

        except Exception as e:
            logger.error(f"Failed to get corpus stats: {e}")
            raise

    def upload_to_gcs(
        self,
        content: str,
        destination_blob_name: str,
        bucket_name: Optional[str] = None
    ) -> str:
        """
        Upload content to GCS

        Args:
            content: Content to upload
            destination_blob_name: Destination path in bucket
            bucket_name: Optional bucket name, uses config default

        Returns:
            GCS URI of uploaded file
        """
        bucket_name = bucket_name or self.config.gcs_bucket

        try:
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(destination_blob_name)

            blob.upload_from_string(content, content_type='application/json')

            gcs_uri = f"gs://{bucket_name}/{destination_blob_name}"
            logger.info(f"Uploaded to {gcs_uri}")
            return gcs_uri

        except Exception as e:
            logger.error(f"Failed to upload to GCS: {e}")
            raise
