"""
Google Vertex AI RAG Integration Module

This module provides integration with Google Vertex AI RAG Engine for:
- Semantic search across call transcripts
- Document indexing with metadata
- Corpus management
"""

from .config import VertexAIConfig
from .corpus_manager import VertexAICorpusManager
from .search_client import VertexSearchClient
from .rag_indexer import VertexRAGIndexer

__all__ = [
    'VertexAIConfig',
    'VertexAICorpusManager',
    'VertexSearchClient',
    'VertexRAGIndexer'
]
