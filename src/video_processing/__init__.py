"""
Video Meeting AI Processing Pipeline

6-layer AI analysis for video meetings from Fathom and RingCentral Video.

Layers:
1. Entity Extraction - Participants, companies, deal signals
2. Sentiment & Customer Health - NPS prediction, churn risk
3. Resolution & Outcomes - Objectives met, action item quality
4. Recommendations - Coaching points, follow-up actions
5. Advanced Metrics - Speaking time, competitive intel
6. Learning Intelligence - UTL-based learning analysis
"""

from .base_processor import VideoMeetingProcessor
from .layer1_entities import EntityExtractor
from .layer2_sentiment import SentimentAnalyzer
from .layer3_resolution import ResolutionTracker
from .layer4_recommendations import RecommendationEngine
from .layer5_advanced import AdvancedMetrics
from .layer6_learning import LearningAnalyzer

__all__ = [
    'VideoMeetingProcessor',
    'EntityExtractor',
    'SentimentAnalyzer',
    'ResolutionTracker',
    'RecommendationEngine',
    'AdvancedMetrics',
    'LearningAnalyzer'
]
