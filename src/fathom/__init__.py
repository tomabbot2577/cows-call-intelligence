"""
Fathom AI Integration Module

Provides access to Fathom AI video meeting transcripts and summaries.
Supports Google Meet, Zoom, and Microsoft Teams via Fathom's recording notetaker.
"""

from .client import FathomClient
from .key_manager import FathomKeyManager

__all__ = ['FathomClient', 'FathomKeyManager']
