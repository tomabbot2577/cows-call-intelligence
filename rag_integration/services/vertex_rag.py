"""Vertex AI RAG Service - Hybrid approach using database + vertexai.rag + google.genai."""

import os
from typing import Optional, Dict, Any, List
import logging
import psycopg2
from psycopg2.extras import RealDictCursor

import vertexai
from vertexai import rag  # Stable import (not deprecated)
from google import genai
from google.genai import types
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class VertexRAGService:
    """
    Hybrid RAG service combining:
    - PostgreSQL database for structured filtering (primary for filtered queries)
    - vertexai.rag for semantic retrieval (fallback for open-ended queries)
    - google.genai for generation (future-proof, replaces vertexai.generative_models)
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: str = "us-west1",
        corpus_name: str = "mst_call_intelligence",
        credentials_path: Optional[str] = None,
        database_url: Optional[str] = None
    ):
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "call-recording-481713")
        self.location = location
        self.corpus_display_name = corpus_name
        self.corpus = None
        self.corpus_name = None

        # Database connection for structured queries
        self.database_url = database_url or os.getenv(
            "RAG_DATABASE_URL",
            "postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights"
        )

        # Initialize credentials
        credentials_path = credentials_path or os.getenv(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "/var/www/call-recording-system/config/google_service_account.json"
        )

        # Initialize Vertex AI for RAG operations
        if credentials_path and os.path.exists(credentials_path):
            self.credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            vertexai.init(
                project=self.project_id,
                location=self.location,
                credentials=self.credentials
            )
        else:
            self.credentials = None
            vertexai.init(project=self.project_id, location=self.location)

        # Initialize google.genai client for generation (future-proof)
        # Try Vertex AI mode first, fall back to API key
        try:
            if self.credentials:
                self.genai_client = genai.Client(
                    vertexai=True,
                    project=self.project_id,
                    location=self.location,
                    credentials=self.credentials
                )
                self._genai_mode = "vertex"
            else:
                api_key = os.getenv("GEMINI_API_KEY")
                if api_key:
                    self.genai_client = genai.Client(api_key=api_key)
                    self._genai_mode = "api_key"
                else:
                    self.genai_client = genai.Client(
                        vertexai=True,
                        project=self.project_id,
                        location=self.location
                    )
                    self._genai_mode = "vertex_default"
        except Exception as e:
            logger.warning(f"Failed to initialize genai client: {e}")
            self.genai_client = None
            self._genai_mode = "unavailable"

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
        chunk_size: int = 512,
        chunk_overlap: int = 100
    ) -> Dict[str, Any]:
        """
        Import documents from GCS into the RAG corpus.

        Args:
            gcs_path: GCS URI (gs://bucket/path)
            chunk_size: Size of text chunks in tokens
            chunk_overlap: Overlap between chunks in tokens

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
                transformation_config=rag.TransformationConfig(
                    chunking_config=rag.ChunkingConfig(
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap
                    )
                ),
                max_embedding_requests_per_min=1000
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

    def retrieve_contexts(
        self,
        query: str,
        top_k: int = 10,
        distance_threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Direct context retrieval WITHOUT generation.
        Uses vertexai.rag.retrieval_query() - NOT deprecated.

        Args:
            query: The search query
            top_k: Number of contexts to retrieve
            distance_threshold: Maximum vector distance (lower = more similar)

        Returns:
            List of context dicts with text, source, and score
        """
        if not self.corpus_name:
            self.initialize_corpus()

        if not self.corpus_name:
            logger.error("Could not initialize corpus for retrieval")
            return []

        try:
            response = rag.retrieval_query(
                rag_resources=[
                    rag.RagResource(rag_corpus=self.corpus_name)
                ],
                text=query,
                rag_retrieval_config=rag.RagRetrievalConfig(
                    top_k=top_k,
                    filter=rag.Filter(vector_distance_threshold=distance_threshold),
                ),
            )

            contexts = []
            for ctx in response.contexts.contexts:
                contexts.append({
                    "text": ctx.text,
                    "source_uri": getattr(ctx, 'source_uri', None),
                    "score": getattr(ctx, 'score', None)
                })

            logger.info(f"Retrieved {len(contexts)} contexts for query")
            return contexts

        except Exception as e:
            logger.error(f"Retrieval failed: {e}")
            return []

    def query(
        self,
        query: str,
        filters: Optional[Dict] = None,
        top_k: int = 10
    ) -> Dict[str, Any]:
        """
        Query with structured filters using database, or semantic search using RAG corpus.

        Uses hybrid approach:
        1. If filters provided: Query PostgreSQL database for matching calls
        2. If no filters: Use vertexai.rag for semantic retrieval
        3. Generate response using google.genai (future-proof)

        Args:
            query: The question to ask
            filters: Optional filter dict (triggers database query when present)
            top_k: Number of relevant documents to retrieve

        Returns:
            Response dict with answer and metadata
        """
        # Validate query
        if not query or not isinstance(query, str):
            return {
                "response": "Error: Query cannot be empty",
                "filters_applied": None,
                "system": "vertex",
                "error": "Empty or invalid query"
            }

        try:
            # Build filter expression for display
            filter_expr = self._build_filter_expression(filters) if filters else None

            # HYBRID APPROACH: Use database for structured queries, RAG for semantic
            if filters and len(filters) > 0:
                # Step 1a: Query database with structured filters
                logger.info(f"Using DATABASE for structured query with filters: {list(filters.keys())}")
                db_calls = self._query_database_with_filters(filters, limit=top_k)

                if db_calls:
                    # Format database results as context
                    context_text = self._format_calls_as_context(db_calls)
                    data_source = "database"
                    num_results = len(db_calls)

                    prompt = f"""You are analyzing {num_results} calls from our database that match the following filters: {filter_expr}

Here are the matching calls with their details:

{context_text}

---

USER QUESTION: {query}

Based on the actual call data above, provide a detailed analysis. Include:
1. Summary of what you found (with specific counts and metrics)
2. Key patterns or insights from these calls
3. Specific examples with call IDs and dates
4. Recommendations based on the data

Be specific and reference the actual data provided."""

                else:
                    # No database results - try RAG corpus as fallback
                    logger.info("No database results, falling back to RAG corpus")
                    if not self.corpus_name:
                        self.initialize_corpus()

                    contexts = self.retrieve_contexts(query, top_k=top_k) if self.corpus_name else []

                    if not contexts:
                        return {
                            "response": f"No calls found matching the filter criteria: {filter_expr}\n\nThis could mean:\n- No calls in the database match these specific conditions\n- The filter values may need adjustment\n- Try broadening your search criteria",
                            "filters_applied": filter_expr,
                            "system": "vertex_db",
                            "calls_found": 0
                        }

                    context_text = "\n\n".join([
                        f"[Context {i+1}]:\n{ctx['text'][:1500]}"
                        for i, ctx in enumerate(contexts)
                    ])
                    data_source = "rag_corpus"
                    num_results = len(contexts)

                    prompt = f"""Based on the following relevant excerpts from our knowledge base, answer the question.

{context_text}

---

QUESTION: {query}
[Filters requested but no exact matches found: {filter_expr}]

Provide the best answer you can based on the available context."""

            else:
                # Step 1b: No filters - use RAG corpus for semantic search
                if not self.corpus_name:
                    self.initialize_corpus()

                if not self.corpus_name:
                    return {
                        "response": "Error: Could not initialize corpus",
                        "filters_applied": None,
                        "system": "vertex",
                        "error": "Corpus initialization failed"
                    }

                logger.info(f"Using RAG CORPUS for semantic query: {query[:100]}...")
                contexts = self.retrieve_contexts(query, top_k=top_k)

                if not contexts:
                    return {
                        "response": "No relevant information found in the knowledge base for this query.",
                        "filters_applied": filter_expr,
                        "system": "vertex",
                        "corpus": self.corpus_name,
                        "contexts_retrieved": 0
                    }

                context_text = "\n\n".join([
                    f"[Context {i+1}]:\n{ctx['text'][:1500]}"
                    for i, ctx in enumerate(contexts)
                ])
                data_source = "rag_corpus"
                num_results = len(contexts)

                prompt = f"""Based on the following relevant excerpts from our call transcripts and knowledge base, answer the question.

{context_text}

---

QUESTION: {query}

Provide a comprehensive answer based on the contexts above. Reference specific details when available."""

            # Step 2: Generate response using google.genai
            if self.genai_client:
                response = self.genai_client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self._system_instruction,
                        temperature=0.7,
                        max_output_tokens=2048
                    )
                )
                response_text = response.text
            else:
                response_text = f"Retrieved {num_results} results but AI generation unavailable.\n\n{context_text[:2000]}"

            return {
                "response": response_text,
                "filters_applied": filter_expr,
                "system": f"vertex_{data_source}",
                "data_source": data_source,
                "model": "gemini-2.0-flash",
                "genai_mode": self._genai_mode,
                "results_count": num_results
            }

        except Exception as e:
            logger.error(f"Query failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                "response": f"Error processing query: {str(e)}",
                "filters_applied": None,
                "system": "vertex",
                "error": str(e)
            }

    def query_with_rag_tool(
        self,
        query: str,
        top_k: int = 10
    ) -> Dict[str, Any]:
        """
        Alternative: Use google.genai with RAG tool integration.
        This lets Gemini automatically retrieve and use context.

        Args:
            query: The question to ask
            top_k: Number of contexts for retrieval

        Returns:
            Response dict
        """
        if not self.genai_client:
            return {"error": "GenAI client not available", "system": "vertex"}

        if not self.corpus_name:
            self.initialize_corpus()

        if not self.corpus_name:
            return {"error": "Corpus not initialized", "system": "vertex"}

        try:
            # Create RAG retrieval tool for google.genai
            rag_tool = types.Tool(
                retrieval=types.Retrieval(
                    vertex_rag_store=types.VertexRagStore(
                        rag_corpora=[self.corpus_name],
                        similarity_top_k=top_k,
                        vector_distance_threshold=0.5,
                    )
                )
            )

            response = self.genai_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=query,
                config=types.GenerateContentConfig(
                    tools=[rag_tool],
                    system_instruction=self._system_instruction,
                    temperature=0.7,
                    max_output_tokens=2048
                ),
            )

            return {
                "response": response.text,
                "system": "vertex_rag_tool",
                "corpus": self.corpus_name,
                "model": "gemini-2.0-flash",
                "genai_mode": self._genai_mode
            }

        except Exception as e:
            logger.error(f"RAG tool query failed: {e}")
            # Fall back to two-step approach
            logger.info("Falling back to two-step retrieval approach")
            return self.query(query, top_k=top_k)

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

    def _query_database_with_filters(
        self,
        filters: Dict[str, Any],
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Query PostgreSQL database with structured filters.
        Returns actual call data matching the filter criteria.
        """
        if not filters:
            return []

        try:
            conn = psycopg2.connect(self.database_url)
            conn.set_session(readonly=True)
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Build WHERE clauses from filters
            where_clauses = ["t.call_date IS NOT NULL"]
            params = []

            # Map filter fields to actual database columns
            # i = insights, r = call_resolutions, rec = call_recommendations
            # NOTE: churn_risk is TEXT ('none','low','medium','high') in call_resolutions, not numeric
            field_mapping = {
                "employee_name": ("t.employee_name", "ILIKE"),
                "customer_sentiment": ("i.customer_sentiment", "="),
                "call_type": ("i.call_type", "ILIKE"),
                "call_quality_score": ("i.call_quality_score", None),
                "customer_satisfaction_score": ("i.customer_satisfaction_score", None),
                "churn_risk": ("r.churn_risk", "="),  # TEXT: none/low/medium/high in call_resolutions
                "churn_risk_score": ("r.churn_risk", "="),  # Alias for churn_risk
                "resolution_effectiveness": ("r.resolution_effectiveness", None),
                "empathy_score": ("r.empathy_score", None),
                "escalation_required": ("i.escalation_required", "="),  # In insights table
                "escalation_needed": ("i.escalation_required", "="),  # Alias
                "follow_up_needed": ("i.follow_up_needed", "="),  # In insights table
                "follow_up_required": ("i.follow_up_needed", "="),  # Alias
                "first_call_resolution": ("i.first_call_resolution", "="),  # In insights table
                "call_date": ("t.call_date", None),
            }

            for field, condition in filters.items():
                if field not in field_mapping:
                    continue

                db_field, default_op = field_mapping[field]

                # Special handling for churn_risk - support "medium or higher"
                if field in ("churn_risk", "churn_risk_score") and isinstance(condition, str):
                    if condition == "medium":
                        # "medium" means medium OR high (churn risk > 5)
                        where_clauses.append(f"{db_field} IN ('medium', 'high')")
                    elif condition == "high":
                        where_clauses.append(f"{db_field} = 'high'")
                    elif condition == "low":
                        where_clauses.append(f"{db_field} = 'low'")
                    else:
                        where_clauses.append(f"{db_field} = %s")
                        params.append(condition)
                    continue

                if isinstance(condition, dict):
                    op = condition.get("op", "=")
                    value = condition.get("value")

                    if op == "BETWEEN" and isinstance(value, list) and len(value) == 2:
                        where_clauses.append(f"{db_field} BETWEEN %s AND %s")
                        params.extend(value)
                    else:
                        where_clauses.append(f"{db_field} {op} %s")
                        params.append(value)
                elif isinstance(condition, bool):
                    where_clauses.append(f"{db_field} = %s")
                    params.append(condition)
                elif isinstance(condition, str):
                    op = default_op or "="
                    if op == "ILIKE":
                        where_clauses.append(f"{db_field} ILIKE %s")
                        params.append(f"%{condition}%")
                    else:
                        where_clauses.append(f"{db_field} = %s")
                        params.append(condition)
                else:
                    where_clauses.append(f"{db_field} = %s")
                    params.append(condition)

            where_sql = " AND ".join(where_clauses)

            query = f"""
                SELECT
                    t.recording_id,
                    t.call_date,
                    t.duration_seconds,
                    t.employee_name,
                    t.customer_name,
                    t.customer_company,
                    t.from_number,
                    SUBSTRING(t.transcript_text, 1, 500) as transcript_excerpt,
                    i.customer_sentiment,
                    i.call_quality_score,
                    i.call_type,
                    i.summary,
                    i.key_topics,
                    i.resolution_status,
                    i.follow_up_needed,
                    i.escalation_required,
                    r.churn_risk,
                    i.first_call_resolution,
                    r.resolution_effectiveness,
                    r.empathy_score,
                    r.first_contact_resolution as fcr_resolution,
                    rec.risk_level
                FROM transcripts t
                LEFT JOIN insights i ON t.recording_id = i.recording_id
                LEFT JOIN call_resolutions r ON t.recording_id = r.recording_id
                LEFT JOIN call_recommendations rec ON t.recording_id = rec.recording_id
                WHERE {where_sql}
                ORDER BY t.call_date DESC
                LIMIT %s
            """
            params.append(limit)

            logger.info(f"Executing structured query with {len(where_clauses)} filters")
            cur.execute(query, params)
            results = cur.fetchall()

            cur.close()
            conn.close()

            # Convert to list of dicts with string dates
            calls = []
            for row in results:
                call = dict(row)
                if call.get('call_date'):
                    call['call_date'] = str(call['call_date'])
                calls.append(call)

            logger.info(f"Found {len(calls)} calls matching filters")
            return calls

        except Exception as e:
            logger.error(f"Database query failed: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _format_calls_as_context(self, calls: List[Dict[str, Any]]) -> str:
        """Format database results as context for AI."""
        if not calls:
            return ""

        context_parts = []
        for i, call in enumerate(calls, 1):
            parts = [f"[Call {i}]"]
            parts.append(f"Recording ID: {call.get('recording_id', 'N/A')}")
            parts.append(f"Date: {call.get('call_date', 'N/A')}")
            if call.get('employee_name'):
                parts.append(f"Agent: {call['employee_name']}")
            if call.get('customer_name'):
                parts.append(f"Customer: {call['customer_name']}")
            if call.get('customer_company'):
                parts.append(f"Company: {call['customer_company']}")
            if call.get('customer_sentiment'):
                parts.append(f"Sentiment: {call['customer_sentiment']}")
            if call.get('call_quality_score'):
                parts.append(f"Quality Score: {call['call_quality_score']}/10")
            if call.get('churn_risk'):
                parts.append(f"Churn Risk: {call['churn_risk'].upper()}")
            if call.get('resolution_effectiveness'):
                parts.append(f"Resolution Effectiveness: {call['resolution_effectiveness']}/10")
            if call.get('escalation_required'):
                parts.append("Status: ESCALATION REQUIRED")
            if call.get('follow_up_needed'):
                parts.append("Follow-up: NEEDED")
            if call.get('resolution_status'):
                parts.append(f"Resolution: {call['resolution_status']}")
            if call.get('first_call_resolution'):
                parts.append("First Call Resolution: Yes")
            if call.get('risk_level'):
                parts.append(f"Risk Level: {call['risk_level']}")
            if call.get('summary'):
                parts.append(f"Summary: {call['summary']}")
            if call.get('transcript_excerpt'):
                parts.append(f"Transcript Excerpt: {call['transcript_excerpt']}...")

            context_parts.append("\n".join(parts))

        return "\n\n---\n\n".join(context_parts)

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
                "corpus": stats,
                "genai_mode": self._genai_mode,
                "genai_available": self.genai_client is not None
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
        print(f"  GenAI Mode: {service._genai_mode}")

        status = service.get_status()
        print(f"\nStatus: {status}")

        # Test retrieval
        print("\nTesting retrieval...")
        contexts = service.retrieve_contexts("What are common customer complaints?", top_k=3)
        print(f"Retrieved {len(contexts)} contexts")

        # Test full query
        print("\nTesting full query...")
        result = service.query("What are common customer complaints?", top_k=5)
        print(f"Contexts: {result.get('contexts_retrieved', 0)}")
        print(f"GenAI Mode: {result.get('genai_mode', 'N/A')}")
        print(f"Response: {result.get('response', 'No response')[:500]}...")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
