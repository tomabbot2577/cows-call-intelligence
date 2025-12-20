"""Vertex AI RAG Service - Structured queries with filtering."""

import os
from typing import Optional, Dict, Any, List
import logging

import vertexai
from vertexai.preview import rag
from vertexai.generative_models import GenerativeModel
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class VertexRAGService:
    """Manages Vertex AI RAG for structured queries with filtering."""

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: str = "us-central1",
        corpus_name: str = "mst_call_intelligence",
        credentials_path: Optional[str] = None
    ):
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "mst-pcrecruiter")
        self.location = location
        self.corpus_display_name = corpus_name
        self.corpus = None
        self.corpus_name = None

        # Initialize credentials
        credentials_path = credentials_path or os.getenv(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "/var/www/call-recording-system/config/google_service_account.json"
        )

        if credentials_path and os.path.exists(credentials_path):
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            vertexai.init(
                project=self.project_id,
                location=self.location,
                credentials=credentials
            )
        else:
            vertexai.init(project=self.project_id, location=self.location)

        self._system_instruction = """
You are a call intelligence analyst for MST/PCRecruiter.
Analyze calls based on structured filters and provide exact metrics.
Always acknowledge what filters were applied to your analysis.

When providing analysis:
1. Reference specific call IDs and dates
2. Include exact scores and metrics
3. Identify patterns across filtered calls
4. Provide actionable recommendations
5. Highlight anomalies or concerns
"""

    def initialize_corpus(self) -> Optional[str]:
        """Initialize or get existing RAG corpus."""
        try:
            # List existing corpora
            corpora = list(rag.list_corpora())

            for c in corpora:
                if c.display_name == self.corpus_display_name:
                    self.corpus = c
                    self.corpus_name = c.name
                    logger.info(f"Found existing corpus: {c.name}")
                    return c.name

            # Create new corpus if not found
            logger.info(f"Creating new corpus: {self.corpus_display_name}")
            self.corpus = rag.create_corpus(
                display_name=self.corpus_display_name,
                description="MST/PCRecruiter call transcripts with Layer 1-5 metadata"
            )
            self.corpus_name = self.corpus.name
            return self.corpus_name

        except Exception as e:
            logger.error(f"Error initializing corpus: {e}")
            return None

    def import_from_gcs(
        self,
        gcs_path: str,
        chunk_size: int = 1024,
        chunk_overlap: int = 200
    ) -> Dict[str, Any]:
        """
        Import documents from GCS into the RAG corpus.

        Args:
            gcs_path: GCS URI (gs://bucket/path)
            chunk_size: Size of text chunks
            chunk_overlap: Overlap between chunks

        Returns:
            Import result dict
        """
        if not self.corpus_name:
            self.initialize_corpus()

        if not self.corpus_name:
            return {"error": "Failed to initialize corpus"}

        try:
            result = rag.import_files(
                corpus_name=self.corpus_name,
                paths=[gcs_path],
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )

            logger.info(f"Imported files from {gcs_path}")
            return {
                "corpus": self.corpus_name,
                "gcs_path": gcs_path,
                "status": "success"
            }

        except Exception as e:
            logger.error(f"Import failed: {e}")
            return {"error": str(e)}

    def query(
        self,
        query: str,
        filters: Optional[Dict] = None,
        top_k: int = 10
    ) -> Dict[str, Any]:
        """
        Query the RAG corpus with optional filters.

        Args:
            query: The question to ask
            filters: Optional filter dict (e.g., {"agent_name": "John", "churn_risk_score": {"op": ">", "value": 7}})
            top_k: Number of relevant documents to retrieve

        Returns:
            Response dict with answer and metadata
        """
        if not self.corpus_name:
            self.initialize_corpus()

        try:
            # Build filter expression if provided
            filter_expr = self._build_filter_expression(filters) if filters else None

            # Create retrieval config
            rag_retrieval_config = rag.RagRetrievalConfig(
                top_k=top_k,
                filter=rag.Filter(vector_distance_threshold=0.5) if not filter_expr else None
            )

            # Generate with RAG
            model = GenerativeModel(
                "gemini-1.5-pro-001",
                system_instruction=self._system_instruction
            )

            # Build the query with filter context
            enhanced_query = query
            if filter_expr:
                enhanced_query = f"[Filters applied: {filter_expr}]\n\n{query}"

            # Use RAG retrieval
            rag_source = rag.Retrieval(
                source=rag.VertexRagStore(
                    rag_corpora=[self.corpus_name],
                    similarity_top_k=top_k
                )
            )

            response = model.generate_content(
                enhanced_query,
                tools=[rag_source]
            )

            return {
                "response": response.text,
                "filters_applied": filter_expr,
                "system": "vertex",
                "corpus": self.corpus_name,
                "model": "gemini-1.5-pro-001"
            }

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {
                "response": f"Error processing query: {str(e)}",
                "filters_applied": None,
                "system": "vertex",
                "error": str(e)
            }

    def _build_filter_expression(self, filters: Dict) -> str:
        """Build a filter expression string from filter dict."""
        expressions = []

        for field, condition in filters.items():
            if isinstance(condition, dict):
                op = condition.get("op", "=")
                value = condition.get("value")
                if isinstance(value, str):
                    expressions.append(f"{field} {op} '{value}'")
                else:
                    expressions.append(f"{field} {op} {value}")
            elif isinstance(condition, bool):
                expressions.append(f"{field} = {str(condition).lower()}")
            elif isinstance(condition, str):
                expressions.append(f"{field} = '{condition}'")
            else:
                expressions.append(f"{field} = {condition}")

        return " AND ".join(expressions)

    def get_corpus_stats(self) -> Dict[str, Any]:
        """Get corpus statistics."""
        if not self.corpus_name:
            self.initialize_corpus()

        try:
            if self.corpus:
                return {
                    "name": self.corpus.name,
                    "display_name": self.corpus.display_name,
                    "status": "active"
                }
            return {"status": "not_initialized"}

        except Exception as e:
            return {"error": str(e)}

    def list_files_in_corpus(self) -> List[Dict[str, Any]]:
        """List all files in the corpus."""
        if not self.corpus_name:
            self.initialize_corpus()

        try:
            files = list(rag.list_files(corpus_name=self.corpus_name))
            return [
                {
                    "name": f.name,
                    "display_name": f.display_name,
                    "size_bytes": f.size_bytes,
                }
                for f in files
            ]
        except Exception as e:
            logger.error(f"Failed to list files: {e}")
            return []

    def delete_corpus(self) -> bool:
        """Delete the corpus (use with caution!)."""
        if not self.corpus_name:
            return False

        try:
            rag.delete_corpus(name=self.corpus_name)
            logger.info(f"Deleted corpus: {self.corpus_name}")
            self.corpus = None
            self.corpus_name = None
            return True
        except Exception as e:
            logger.error(f"Failed to delete corpus: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get service status."""
        try:
            stats = self.get_corpus_stats()
            return {
                "status": "healthy",
                "project": self.project_id,
                "location": self.location,
                "corpus": stats
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    try:
        service = VertexRAGService()
        print(f"Vertex RAG Service initialized")
        print(f"  Project: {service.project_id}")
        print(f"  Location: {service.location}")

        status = service.get_status()
        print(f"\nStatus: {status}")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
