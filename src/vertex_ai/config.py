"""
Vertex AI RAG Configuration

Configuration settings for Google Vertex AI RAG Engine integration.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class VertexAIConfig:
    """Configuration for Vertex AI RAG Engine"""

    # GCP Project Settings
    project_id: str = os.getenv('VERTEX_AI_PROJECT_ID', 'call-insights-rag-prod')
    location: str = os.getenv('VERTEX_AI_LOCATION', 'us-west1')

    # RAG Corpus Settings
    corpus_display_name: str = 'call-recordings-corpus'
    corpus_description: str = 'Call recording transcripts with AI-generated insights'

    # Cloud Storage Settings
    gcs_bucket: str = os.getenv('VERTEX_AI_GCS_BUCKET', 'call-insights-rag-data-west')
    gcs_transcripts_prefix: str = 'transcripts/'
    gcs_exports_prefix: str = 'exports/'

    # Embedding Settings
    embedding_model: str = 'text-embedding-005'

    # Chunking Settings
    chunk_size: int = 1024  # characters per chunk
    chunk_overlap: int = 200  # overlap between chunks

    # Rate Limiting
    max_embedding_requests_per_min: int = 1000
    batch_size: int = 500  # documents per batch import

    # Credentials
    credentials_path: Optional[str] = os.getenv(
        'VERTEX_AI_CREDENTIALS_PATH',
        '/var/www/call-recording-system/config/vertex_ai_service_account.json'
    )

    @property
    def gcs_transcripts_uri(self) -> str:
        """Full GCS URI for transcripts"""
        return f"gs://{self.gcs_bucket}/{self.gcs_transcripts_prefix}"

    @property
    def gcs_exports_uri(self) -> str:
        """Full GCS URI for exports"""
        return f"gs://{self.gcs_bucket}/{self.gcs_exports_prefix}"

    def validate(self) -> bool:
        """Validate configuration"""
        errors = []

        if not self.project_id:
            errors.append("VERTEX_AI_PROJECT_ID not set")

        if not self.gcs_bucket:
            errors.append("VERTEX_AI_GCS_BUCKET not set")

        if self.credentials_path and not os.path.exists(self.credentials_path):
            errors.append(f"Credentials file not found: {self.credentials_path}")

        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")

        return True


# Default configuration instance
default_config = VertexAIConfig()
