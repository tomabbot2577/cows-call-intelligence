"""Query Router - Auto-routes queries to optimal RAG system."""

import re
from enum import Enum
from typing import Tuple, Optional, Dict, Any, List
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class RAGSystem(Enum):
    """Available RAG systems."""
    GEMINI = "gemini"
    VERTEX = "vertex"


class QueryRouter:
    """Routes queries to the optimal RAG system based on query patterns."""

    # Patterns that indicate structured queries (-> Vertex AI)
    VERTEX_PATTERNS = [
        # Score comparisons
        r'score\s*[><=!]+\s*\d',
        r'quality\s*[><=]\s*\d',
        r'churn.*[><=]\s*\d',
        r'satisfaction\s*[><=]\s*\d',

        # Agent/employee specific
        r"agent\s+\w+'?s?\s+(calls?|performance|metrics)",
        r"employee\s+\w+'?s?\s+(calls?|performance)",
        r"\w+'s\s+calls?",

        # Date filters
        r'this\s+(week|month|year)',
        r'last\s+(week|month|year|\d+\s+days?)',
        r'yesterday|today',
        r'\d{4}-\d{2}-\d{2}',
        r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}',

        # Explicit filters
        r'where\s+\w+\s*[=<>]',
        r'filter\s+(by|for)',
        r'all\s+calls\s+(with|where|from|to)',
        r'calls\s+from\s+\w+',

        # Boolean filters
        r'competitor.*mentioned',
        r'escalat(ed|ion)\s+calls?',
        r'follow[\s-]?up\s+needed',
        r'high\s+(risk|churn|priority)',
        r'low\s+quality',

        # Counting/aggregation
        r'how\s+many\s+calls?',
        r'count\s+(of\s+)?calls?',
        r'total\s+calls?',
        r'average\s+\w+\s+score',
    ]

    # Patterns that indicate semantic queries (-> Gemini)
    GEMINI_PATTERNS = [
        r'what\s+are\s+customers?\s+',
        r'why\s+(do|are|did)\s+',
        r'summarize\s+',
        r'explain\s+',
        r'find\s+patterns?',
        r'common\s+(issues?|problems?|complaints?)',
        r'trending\s+',
        r'insights?\s+(about|on|for)',
        r'recommendations?\s+for',
    ]

    def route(self, query: str) -> Tuple[RAGSystem, Optional[Dict]]:
        """
        Determine the best RAG system for a query.

        Args:
            query: The user's query

        Returns:
            Tuple of (RAGSystem, optional filters dict)
        """
        query_lower = query.lower()

        # First check for explicit Vertex patterns
        for pattern in self.VERTEX_PATTERNS:
            if re.search(pattern, query_lower):
                filters = self._extract_filters(query)
                logger.info(f"Routed to VERTEX (pattern match): {pattern[:30]}...")
                return (RAGSystem.VERTEX, filters)

        # Check for Gemini patterns
        for pattern in self.GEMINI_PATTERNS:
            if re.search(pattern, query_lower):
                logger.info(f"Routed to GEMINI (pattern match): {pattern[:30]}...")
                return (RAGSystem.GEMINI, None)

        # Default to Gemini for open-ended questions
        logger.info("Routed to GEMINI (default)")
        return (RAGSystem.GEMINI, None)

    def _extract_filters(self, query: str) -> Dict[str, Any]:
        """Extract structured filters from query text."""
        filters = {}
        query_lower = query.lower()

        # Score patterns
        score_patterns = [
            (r'churn\s*(?:risk\s*)?score\s*([><=!]+)\s*(\d+)', 'churn_risk_score'),
            (r'quality\s*score\s*([><=!]+)\s*(\d+)', 'call_quality_score'),
            (r'empathy\s*score\s*([><=!]+)\s*(\d+)', 'empathy_score'),
            (r'satisfaction\s*score?\s*([><=!]+)\s*(\d+)', 'customer_satisfaction_score'),
            (r'resolution.*score\s*([><=!]+)\s*(\d+)', 'resolution_effectiveness'),
        ]

        for pattern, field in score_patterns:
            match = re.search(pattern, query_lower)
            if match:
                op = match.group(1).replace('==', '=')
                filters[field] = {"op": op, "value": int(match.group(2))}

        # Agent/Employee name
        agent_patterns = [
            r"agent\s+(\w+)'?s?",
            r"employee\s+(\w+)'?s?",
            r"(\w+)'s\s+calls?",
        ]
        for pattern in agent_patterns:
            match = re.search(pattern, query_lower)
            if match:
                name = match.group(1).capitalize()
                # Avoid common words
                if name.lower() not in ['the', 'all', 'any', 'some', 'this', 'last']:
                    filters["employee_name"] = name
                    break

        # Call type
        call_types = ['support', 'sales', 'onboarding', 'retention', 'billing', 'complaint', 'inquiry']
        for ct in call_types:
            if ct in query_lower:
                filters["call_type"] = ct.capitalize()
                break

        # Sentiment
        if 'positive' in query_lower:
            filters["customer_sentiment"] = "positive"
        elif 'negative' in query_lower:
            filters["customer_sentiment"] = "negative"
        elif 'neutral' in query_lower:
            filters["customer_sentiment"] = "neutral"

        # Boolean filters
        if re.search(r'competitor.*mention', query_lower):
            filters["competitor_mentioned"] = True
        if re.search(r'escalat', query_lower):
            filters["escalation_required"] = True
        if re.search(r'follow[\s-]?up\s+needed', query_lower):
            filters["follow_up_needed"] = True
        if re.search(r'first\s+call\s+resolution', query_lower):
            filters["first_call_resolution"] = True

        # Date filters
        today = datetime.now()

        if 'today' in query_lower:
            filters["call_date"] = today.strftime('%Y-%m-%d')
        elif 'yesterday' in query_lower:
            filters["call_date"] = (today - timedelta(days=1)).strftime('%Y-%m-%d')
        elif 'this week' in query_lower:
            start = today - timedelta(days=today.weekday())
            filters["call_date"] = {"op": ">=", "value": start.strftime('%Y-%m-%d')}
        elif 'last week' in query_lower:
            start = today - timedelta(days=today.weekday() + 7)
            end = today - timedelta(days=today.weekday() + 1)
            filters["call_date"] = {"op": "BETWEEN", "value": [start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')]}
        elif 'this month' in query_lower:
            filters["call_date"] = {"op": ">=", "value": f"{today.year}-{today.month:02d}-01"}
        elif 'last month' in query_lower:
            if today.month == 1:
                last_month = datetime(today.year - 1, 12, 1)
            else:
                last_month = datetime(today.year, today.month - 1, 1)
            filters["call_date"] = {"op": ">=", "value": last_month.strftime('%Y-%m-%d')}

        # Explicit date
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', query)
        if date_match:
            filters["call_date"] = date_match.group(1)

        # Last N days
        days_match = re.search(r'last\s+(\d+)\s+days?', query_lower)
        if days_match:
            days = int(days_match.group(1))
            start = today - timedelta(days=days)
            filters["call_date"] = {"op": ">=", "value": start.strftime('%Y-%m-%d')}

        return filters


class UnifiedQueryService:
    """Unified interface to hybrid RAG system."""

    def __init__(self, gemini_service, vertex_service):
        """
        Initialize with both RAG services.

        Args:
            gemini_service: GeminiFileSearchService instance
            vertex_service: VertexRAGService instance
        """
        self.gemini = gemini_service
        self.vertex = vertex_service
        self.router = QueryRouter()

    def query(
        self,
        query: str,
        force_system: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a query, routing to the optimal system.

        Args:
            query: The user's question
            force_system: Optional system override ("gemini" or "vertex")

        Returns:
            Response dict with answer, citations, and metadata
        """
        import time
        start_time = time.time()

        # Determine which system to use
        if force_system:
            try:
                system = RAGSystem(force_system.lower())
            except ValueError:
                system = RAGSystem.GEMINI
            filters = self.router._extract_filters(query) if system == RAGSystem.VERTEX else None
        else:
            system, filters = self.router.route(query)

        # Execute query on appropriate system
        if system == RAGSystem.GEMINI:
            result = self.gemini.query(query)
        else:
            result = self.vertex.query(query, filters)

        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            "query": query,
            "system": result.get("system", system.value),
            "response": result["response"],
            "citations": result.get("citations", []),
            "filters": result.get("filters_applied") or filters,
            "query_time_ms": elapsed_ms,
            "error": result.get("error")
        }

    def get_routing_explanation(self, query: str) -> Dict[str, Any]:
        """Explain why a query would be routed to a particular system."""
        query_lower = query.lower()

        matched_vertex = []
        matched_gemini = []

        for pattern in self.router.VERTEX_PATTERNS:
            if re.search(pattern, query_lower):
                matched_vertex.append(pattern)

        for pattern in self.router.GEMINI_PATTERNS:
            if re.search(pattern, query_lower):
                matched_gemini.append(pattern)

        system, filters = self.router.route(query)

        return {
            "query": query,
            "routed_to": system.value,
            "filters_extracted": filters,
            "matched_vertex_patterns": matched_vertex,
            "matched_gemini_patterns": matched_gemini,
            "explanation": f"Query routed to {system.value} based on pattern matching"
        }


if __name__ == "__main__":
    # Test the router
    router = QueryRouter()

    test_queries = [
        "What are customers complaining about?",
        "Show me calls with churn risk > 7",
        "Agent John's calls this week",
        "Summarize competitor mentions",
        "All escalated calls from last month",
        "How many support calls did we get today?",
        "Find patterns in negative sentiment calls",
        "Calls where quality score < 5",
    ]

    print("Query Routing Test:\n")
    for query in test_queries:
        system, filters = router.route(query)
        print(f"Query: {query}")
        print(f"  -> System: {system.value}")
        if filters:
            print(f"  -> Filters: {filters}")
        print()
