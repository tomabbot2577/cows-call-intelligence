"""
Vertex AI RAG Search Client

Provides semantic search functionality for call transcripts using Vertex AI RAG Engine.
"""

import logging
from typing import List, Dict, Optional, Any
from pathlib import Path

try:
    import vertexai
    from vertexai import rag
    VERTEX_AI_AVAILABLE = True
except ImportError:
    VERTEX_AI_AVAILABLE = False

from .config import VertexAIConfig, default_config

logger = logging.getLogger(__name__)


class VertexSearchClient:
    """Semantic search client for call transcripts using Vertex AI RAG"""

    def __init__(self, config: Optional[VertexAIConfig] = None, corpus_name: Optional[str] = None):
        """
        Initialize the search client

        Args:
            config: Optional configuration
            corpus_name: Optional corpus resource name
        """
        self.config = config or default_config
        self._corpus_name = corpus_name
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

            # Find corpus if not specified
            if not self._corpus_name:
                self._corpus_name = self._find_corpus()

            self._initialized = True
            logger.info(f"Search client initialized with corpus: {self._corpus_name}")

        except Exception as e:
            logger.error(f"Failed to initialize search client: {e}")
            raise

    def _find_corpus(self) -> Optional[str]:
        """Find the call recordings corpus"""
        try:
            corpora = rag.list_corpora()
            for corpus in corpora:
                if corpus.display_name == self.config.corpus_display_name:
                    return corpus.name
            return None
        except Exception as e:
            logger.warning(f"Could not find corpus: {e}")
            return None

    def semantic_search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        similarity_threshold: float = 0.1
    ) -> List[Dict[str, Any]]:
        """
        Perform semantic search on call transcripts

        Args:
            query: Natural language search query
            filters: Optional metadata filters (employee, customer, sentiment, date_from, date_to)
            limit: Maximum number of results
            similarity_threshold: Minimum relevance score (0-1, default 0.1)

        Returns:
            List of matching transcripts with metadata and relevance scores
        """
        if not self._initialized:
            raise RuntimeError("Search client not initialized")

        if not self._corpus_name:
            raise ValueError("No corpus available for search")

        try:
            # Configure retrieval
            rag_retrieval_config = rag.RagRetrievalConfig(
                top_k=limit,
            )

            # Execute retrieval query using the correct API
            response = rag.retrieval_query(
                text=query,
                rag_resources=[
                    rag.RagResource(
                        rag_corpus=self._corpus_name,
                    )
                ],
                rag_retrieval_config=rag_retrieval_config,
            )

            # Format results
            results = self._format_results(response, filters, similarity_threshold)

            logger.info(f"Search query '{query[:50]}...' returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise

    def _format_results(
        self,
        response: Any,
        filters: Optional[Dict[str, Any]] = None,
        similarity_threshold: float = 0.1
    ) -> List[Dict[str, Any]]:
        """
        Format RAG response into dashboard-compatible results

        Args:
            response: Vertex AI RAG response
            filters: Optional post-retrieval filters
            similarity_threshold: Minimum similarity score (default 0.1)

        Returns:
            Formatted results list
        """
        results = []

        if not hasattr(response, 'contexts') or not response.contexts:
            return results

        for context in response.contexts.contexts:
            # Extract relevance score (Vertex AI uses 'score' field)
            score = getattr(context, 'score', 0.0)

            # Skip low-score results
            if score < similarity_threshold:
                continue

            # Extract source info
            source_uri = getattr(context, 'source_uri', '')
            source_name = getattr(context, 'source_display_name', '')
            text = getattr(context, 'text', '')

            # Extract recording_id from source name (e.g., "3045934816036.txt" -> "3045934816036")
            recording_id = source_name.replace('.txt', '') if source_name else self._extract_id_from_uri(source_uri)

            # Parse metadata from the document text (since all metadata is embedded)
            parsed_data = self._parse_document_text(text)

            result = {
                'recording_id': recording_id,
                'relevance_score': round(score * 100, 1),  # Convert to percentage
                'text_snippet': text[:500] if text else '',
                'source_uri': source_uri,

                # Metadata parsed from document
                'call_date': parsed_data.get('call_date', 'Unknown'),
                'duration_seconds': parsed_data.get('duration_seconds', 0),
                'customer_name': parsed_data.get('customer_name', ''),
                'employee_name': parsed_data.get('employee_name', ''),
                'customer_company': parsed_data.get('customer_company', ''),
                'customer_sentiment': parsed_data.get('customer_sentiment', ''),
                'call_quality_score': parsed_data.get('call_quality_score', 0),
                'call_type': parsed_data.get('call_type', ''),
                'summary': parsed_data.get('summary', ''),
                'resolution_status': parsed_data.get('resolution_status', ''),
                'key_topics': parsed_data.get('key_topics', []),
            }

            # Apply filters
            if filters and not self._matches_filters(result, filters):
                continue

            results.append(result)

        # Sort by relevance score descending
        results.sort(key=lambda x: x['relevance_score'], reverse=True)

        return results

    def _parse_document_text(self, text: str) -> Dict[str, Any]:
        """
        Parse metadata from document text (since metadata is embedded in content)

        Args:
            text: Document text with embedded metadata

        Returns:
            Parsed metadata dictionary
        """
        parsed = {}

        if not text:
            return parsed

        lines = text.split('\n')

        for line in lines:
            line = line.strip()

            # Parse key fields
            if line.startswith('Customer:'):
                parsed['customer_name'] = line.replace('Customer:', '').strip()
            elif line.startswith('Company:'):
                parsed['customer_company'] = line.replace('Company:', '').strip()
            elif line.startswith('Employee:'):
                parsed['employee_name'] = line.replace('Employee:', '').strip()
            elif line.startswith('Date:'):
                parsed['call_date'] = line.replace('Date:', '').strip()
            elif line.startswith('Duration:'):
                # Parse "5.0 minutes" to seconds
                duration_str = line.replace('Duration:', '').strip()
                try:
                    if 'minutes' in duration_str:
                        mins = float(duration_str.split()[0])
                        parsed['duration_seconds'] = mins * 60
                except:
                    pass
            elif line.startswith('Summary:'):
                parsed['summary'] = line.replace('Summary:', '').strip()
            elif line.startswith('Type:'):
                parsed['call_type'] = line.replace('Type:', '').strip()
            elif line.startswith('Topics:'):
                topics_str = line.replace('Topics:', '').strip()
                parsed['key_topics'] = [t.strip() for t in topics_str.split(',')]
            elif line.startswith('Sentiment:'):
                parsed['customer_sentiment'] = line.replace('Sentiment:', '').strip()
            elif line.startswith('Quality Score:'):
                try:
                    score_str = line.replace('Quality Score:', '').strip()
                    parsed['call_quality_score'] = float(score_str.split('/')[0])
                except:
                    pass
            elif line.startswith('Status:'):
                parsed['resolution_status'] = line.replace('Status:', '').strip()

        return parsed

    def _extract_struct_data(self, context: Any) -> Dict[str, Any]:
        """Extract structured data from context"""
        struct_data = {}

        # Try to get metadata from context attributes
        if hasattr(context, 'metadata'):
            metadata = context.metadata
            if isinstance(metadata, dict):
                struct_data = metadata
            elif hasattr(metadata, 'fields'):
                # Protobuf struct
                for key, value in metadata.fields.items():
                    struct_data[key] = self._extract_value(value)

        return struct_data

    def _extract_value(self, value: Any) -> Any:
        """Extract value from protobuf Value"""
        if hasattr(value, 'string_value'):
            return value.string_value
        elif hasattr(value, 'number_value'):
            return value.number_value
        elif hasattr(value, 'bool_value'):
            return value.bool_value
        elif hasattr(value, 'list_value'):
            return [self._extract_value(v) for v in value.list_value.values]
        return str(value)

    def _extract_id_from_uri(self, uri: str) -> str:
        """Extract recording ID from GCS URI"""
        if not uri:
            return ''
        # gs://bucket/transcripts/recording_id.json -> recording_id
        path = uri.split('/')[-1]
        return path.replace('.json', '').replace('.jsonl', '')

    def _matches_filters(self, result: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """Check if result matches all filters"""
        for key, value in filters.items():
            if not value:
                continue

            result_value = result.get(key)
            if result_value is None:
                continue

            if key in ('date_from', 'date_to'):
                # Date range filters
                call_date = result.get('call_date')
                if call_date:
                    if key == 'date_from' and call_date < value:
                        return False
                    if key == 'date_to' and call_date > value:
                        return False

            elif key == 'min_quality':
                # Quality score filter
                score = result.get('call_quality_score')
                if score is not None and score < value:
                    return False

            elif key in ('employee', 'customer'):
                # Name filters (case-insensitive partial match)
                field = f"{key}_name"
                name = result.get(field, '')
                if name and value.lower() not in name.lower():
                    return False

            elif key == 'sentiment':
                # Exact match for sentiment
                if result.get('customer_sentiment') != value:
                    return False

        return True

    def get_similar_calls(
        self,
        recording_id: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find calls similar to a given recording

        Args:
            recording_id: Source recording ID
            limit: Maximum number of similar calls

        Returns:
            List of similar calls
        """
        # This would require fetching the recording's text first
        # For now, return empty list
        logger.info(f"get_similar_calls not fully implemented for {recording_id}")
        return []

    def health_check(self) -> Dict[str, Any]:
        """
        Check search client health

        Returns:
            Health status dict
        """
        status = {
            'initialized': self._initialized,
            'corpus_name': self._corpus_name,
            'corpus_available': False,
            'sdk_available': VERTEX_AI_AVAILABLE,
        }

        if self._initialized and self._corpus_name:
            try:
                corpus = rag.get_corpus(self._corpus_name)
                status['corpus_available'] = True
                status['corpus_display_name'] = corpus.display_name
            except Exception as e:
                status['error'] = str(e)

        return status
