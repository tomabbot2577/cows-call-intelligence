"""RAG Integration Configuration"""

import os
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass
class RAGConfig:
    """Configuration for RAG integration layer."""

    # Google Cloud
    gcp_project: str
    gcs_bucket: str
    vertex_location: str
    google_credentials_path: str

    # Gemini
    gemini_api_key: str
    gemini_file_search_store: str

    # Vertex AI RAG
    vertex_corpus_name: str

    # Database
    database_url: str

    # Paths
    export_dir: Path

    # Email (for reports)
    smtp_host: Optional[str]
    smtp_port: int
    smtp_user: Optional[str]
    smtp_password: Optional[str]
    alert_email_to: Optional[str]

    # API
    api_port: int
    api_password: str

    @classmethod
    def from_env(cls) -> "RAGConfig":
        """Load configuration from environment variables."""
        return cls(
            # Google Cloud
            gcp_project=os.getenv("GOOGLE_CLOUD_PROJECT", "call-recording-481713"),
            gcs_bucket=os.getenv("GCS_RAG_BUCKET", "call-recording-rag-data"),
            vertex_location=os.getenv("VERTEX_AI_LOCATION", "us-west1"),
            google_credentials_path=os.getenv(
                "GOOGLE_APPLICATION_CREDENTIALS",
                "/var/www/call-recording-system/config/google_service_account.json"
            ),

            # Gemini
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_file_search_store=os.getenv("GEMINI_FILE_SEARCH_STORE", "mst_call_intelligence"),

            # Vertex AI RAG
            vertex_corpus_name=os.getenv("VERTEX_CORPUS_NAME", "mst_call_intelligence"),

            # Database
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights"
            ),

            # Paths
            export_dir=Path(os.getenv(
                "RAG_EXPORT_DIR",
                "/var/www/call-recording-system/rag_integration/exports"
            )),

            # Email
            smtp_host=os.getenv("SMTP_HOST"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_user=os.getenv("SMTP_USER"),
            smtp_password=os.getenv("SMTP_PASSWORD"),
            alert_email_to=os.getenv("ALERT_EMAIL_TO"),

            # API
            api_port=int(os.getenv("RAG_API_PORT", "8081")),
            api_password=os.getenv("RAG_API_PASSWORD", "!pcr123"),
        )

    def validate(self) -> list:
        """Validate configuration and return list of errors."""
        errors = []

        if not self.gemini_api_key:
            errors.append("GEMINI_API_KEY is not set")

        if not Path(self.google_credentials_path).exists():
            errors.append(f"Google credentials not found: {self.google_credentials_path}")

        return errors


# Singleton config instance
_config: Optional[RAGConfig] = None


def get_config() -> RAGConfig:
    """Get or create the configuration singleton."""
    global _config
    if _config is None:
        _config = RAGConfig.from_env()
    return _config
