"""Gemini File Search Service - Semantic queries using Gemini."""

import os
from typing import Optional, Dict, Any, List
import logging

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class GeminiFileSearchService:
    """Manages Gemini File Search for semantic queries over call transcripts."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        store_name: str = "mst_call_intelligence"
    ):
        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required")

        genai.configure(api_key=api_key)
        self.store_name = store_name
        self.store = None
        self.model = None

        self._system_instruction = """
You are a call intelligence analyst for MST/PCRecruiter, a recruiting software company.
Your job is to analyze customer support and sales calls to provide actionable insights.

When answering questions:
1. Always cite specific calls by their Call ID when possible
2. Include relevant metrics (quality scores, sentiment, etc.)
3. Be specific with agent names, dates, and customer companies
4. Provide actionable recommendations when appropriate
5. Highlight patterns and trends across multiple calls

Focus areas:
- Customer satisfaction and sentiment trends
- Agent performance and coaching opportunities
- Churn risk identification
- Process improvement recommendations
- Upsell/cross-sell opportunities
"""

    def initialize_store(self) -> str:
        """Initialize or get existing Gemini File Search store."""
        try:
            # Try to find existing store
            stores = list(genai.list_files())
            logger.info(f"Found {len(stores)} existing files in Gemini")

            # For now, we'll use the file-based approach
            # Gemini File Search stores are managed differently
            return self.store_name

        except Exception as e:
            logger.warning(f"Error initializing store: {e}")
            return self.store_name

    def upload_file(self, file_path: str, display_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Upload a JSONL file to Gemini for processing.

        Args:
            file_path: Path to the JSONL file
            display_name: Optional display name

        Returns:
            File metadata dict
        """
        try:
            display_name = display_name or os.path.basename(file_path)

            uploaded_file = genai.upload_file(
                path=file_path,
                display_name=display_name
            )

            logger.info(f"Uploaded file: {uploaded_file.name}")

            return {
                "name": uploaded_file.name,
                "display_name": uploaded_file.display_name,
                "uri": uploaded_file.uri,
                "state": str(uploaded_file.state),
            }

        except Exception as e:
            logger.error(f"Failed to upload file: {e}")
            raise

    def list_files(self) -> List[Dict[str, Any]]:
        """List all uploaded files."""
        try:
            files = list(genai.list_files())
            return [
                {
                    "name": f.name,
                    "display_name": f.display_name,
                    "uri": f.uri,
                    "state": str(f.state),
                }
                for f in files
            ]
        except Exception as e:
            logger.error(f"Failed to list files: {e}")
            return []

    def delete_file(self, file_name: str) -> bool:
        """Delete a file from Gemini."""
        try:
            genai.delete_file(file_name)
            logger.info(f"Deleted file: {file_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file: {e}")
            return False

    def query(self, query: str, context_files: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Query Gemini with semantic understanding.

        Args:
            query: The question to ask
            context_files: Optional list of file names to include as context

        Returns:
            Response dict with answer and citations
        """
        try:
            # Get the model
            model = genai.GenerativeModel(
                model_name='gemini-2.0-flash',
                system_instruction=self._system_instruction
            )

            # Build the prompt with context if files provided
            if context_files:
                # Get file references
                file_refs = []
                for file_name in context_files:
                    try:
                        file_ref = genai.get_file(file_name)
                        file_refs.append(file_ref)
                    except Exception as e:
                        logger.warning(f"Could not get file {file_name}: {e}")

                if file_refs:
                    # Generate with file context
                    response = model.generate_content([*file_refs, query])
                else:
                    response = model.generate_content(query)
            else:
                response = model.generate_content(query)

            # Extract citations if available
            citations = []
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                    gm = candidate.grounding_metadata
                    if hasattr(gm, 'grounding_chunks'):
                        for chunk in gm.grounding_chunks:
                            if hasattr(chunk, 'retrieved_context'):
                                citations.append({
                                    "source": getattr(chunk.retrieved_context, 'uri', 'unknown'),
                                    "text": getattr(chunk.retrieved_context, 'text', '')[:200]
                                })

            return {
                "response": response.text,
                "citations": citations,
                "system": "gemini",
                "model": "gemini-2.0-flash"
            }

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {
                "response": f"Error processing query: {str(e)}",
                "citations": [],
                "system": "gemini",
                "error": str(e)
            }

    def query_with_transcript(self, query: str, transcript_text: str) -> Dict[str, Any]:
        """
        Query Gemini with a specific transcript as context.

        Args:
            query: The question to ask
            transcript_text: The transcript text to analyze

        Returns:
            Response dict
        """
        try:
            model = genai.GenerativeModel(
                model_name='gemini-2.0-flash',  # Use flash for speed
                system_instruction=self._system_instruction
            )

            prompt = f"""
Analyze the following call transcript and answer the question.

TRANSCRIPT:
{transcript_text}

QUESTION: {query}
"""

            response = model.generate_content(prompt)

            return {
                "response": response.text,
                "citations": [],
                "system": "gemini",
                "model": "gemini-2.0-flash"
            }

        except Exception as e:
            logger.error(f"Query with transcript failed: {e}")
            return {
                "response": f"Error: {str(e)}",
                "citations": [],
                "system": "gemini",
                "error": str(e)
            }

    def analyze_calls_batch(self, query: str, call_summaries: List[Dict]) -> Dict[str, Any]:
        """
        Analyze multiple calls with a single query.

        Args:
            query: The analysis question
            call_summaries: List of call summary dicts with metadata

        Returns:
            Response dict with analysis
        """
        try:
            model = genai.GenerativeModel(
                model_name='gemini-2.0-flash',
                system_instruction=self._system_instruction
            )

            # Format call summaries
            calls_text = "\n\n".join([
                f"--- Call {c.get('call_id', 'Unknown')} ---\n"
                f"Date: {c.get('call_date', 'N/A')}\n"
                f"Agent: {c.get('employee_name', 'N/A')}\n"
                f"Customer: {c.get('customer_name', 'N/A')} ({c.get('customer_company', 'N/A')})\n"
                f"Sentiment: {c.get('customer_sentiment', 'N/A')}\n"
                f"Quality Score: {c.get('call_quality_score', 'N/A')}/10\n"
                f"Summary: {c.get('summary', 'N/A')}"
                for c in call_summaries
            ])

            prompt = f"""
Analyze the following {len(call_summaries)} calls and answer the question.

CALLS:
{calls_text}

QUESTION: {query}

Provide a comprehensive analysis with specific examples from the calls.
"""

            response = model.generate_content(prompt)

            return {
                "response": response.text,
                "calls_analyzed": len(call_summaries),
                "citations": [{"call_id": c.get('call_id')} for c in call_summaries],
                "system": "gemini",
                "model": "gemini-2.0-flash"
            }

        except Exception as e:
            logger.error(f"Batch analysis failed: {e}")
            return {
                "response": f"Error: {str(e)}",
                "calls_analyzed": 0,
                "citations": [],
                "system": "gemini",
                "error": str(e)
            }

    def get_status(self) -> Dict[str, Any]:
        """Get service status and statistics."""
        try:
            files = self.list_files()
            return {
                "status": "healthy",
                "store_name": self.store_name,
                "files_count": len(files),
                "files": files[:5],  # First 5 files
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
        service = GeminiFileSearchService()
        print("Gemini File Search Service initialized")

        status = service.get_status()
        print(f"\nStatus: {status}")

        # Test a simple query
        result = service.query("What are common issues in customer support calls?")
        print(f"\nTest query result:")
        print(f"  Response: {result['response'][:200]}...")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
