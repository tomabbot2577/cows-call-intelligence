"""
Layer 2: Sentiment & Customer Health

Analyzes NPS prediction, churn risk, customer health, and meeting quality.
"""

import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """Layer 2: Sentiment and customer health analysis."""

    PROMPT = """Analyze the sentiment and customer health indicators in this meeting:

TRANSCRIPT:
{transcript}

MEETING TYPE: {meeting_type}
PARTICIPANTS: {participants}

Analyze and return JSON with:
{{
    "nps_score": 0-10 prediction,
    "nps_confidence": 0.0-1.0,
    "nps_rationale": "why this NPS score",

    "churn_risk_level": "none|low|medium|high|critical",
    "churn_risk_score": 0.0-1.0,
    "churn_indicators": ["list of churn signals observed"],

    "customer_health_score": 0-100,
    "health_indicators": {{
        "engagement": 0-100,
        "satisfaction": 0-100,
        "product_fit": 0-100,
        "relationship": 0-100
    }},

    "expansion_signals": [
        {{
            "signal": "description",
            "type": "upsell|cross-sell|referral|renewal",
            "strength": "strong|moderate|weak"
        }}
    ],

    "sentiment_positive": 0.0-1.0,
    "sentiment_negative": 0.0-1.0,
    "sentiment_neutral": 0.0-1.0,

    "emotional_moments": [
        {{
            "moment": "description",
            "emotion": "frustration|excitement|confusion|satisfaction",
            "quote": "relevant quote"
        }}
    ],

    "meeting_quality_score": 1-10,
    "quality_factors": {{
        "clarity": 1-10,
        "productivity": 1-10,
        "engagement": 1-10,
        "outcomes": 1-10
    }},

    "topics": ["main topics discussed"],
    "key_concerns": ["customer concerns raised"]
}}

Return ONLY valid JSON, no additional text."""

    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def analyze(self, meeting: Dict, layer1_results: Dict) -> Dict:
        """Analyze sentiment and customer health."""
        transcript = meeting.get('transcript_text', '')[:15000]
        meeting_type = layer1_results.get('meeting_type', 'unknown')
        participants = layer1_results.get('participants', [])

        prompt = self.PROMPT.format(
            transcript=transcript,
            meeting_type=meeting_type,
            participants=json.dumps(participants, indent=2)
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                temperature=0.3
            )

            content = response.choices[0].message.content
            return self._parse_response(content)

        except Exception as e:
            logger.error(f"Layer 2 analysis failed: {e}")
            return self._default_response()

    def _parse_response(self, content: str) -> Dict:
        """Parse LLM response."""
        try:
            content = content.strip()
            if '```' in content:
                import re
                match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
                if match:
                    content = match.group(1)

            return json.loads(content)
        except:
            return self._default_response()

    def _default_response(self) -> Dict:
        """Return default response on failure."""
        return {
            "nps_score": 5,
            "nps_confidence": 0.5,
            "churn_risk_level": "low",
            "churn_risk_score": 0.2,
            "customer_health_score": 70,
            "sentiment_positive": 0.33,
            "sentiment_negative": 0.33,
            "sentiment_neutral": 0.34,
            "meeting_quality_score": 5,
            "topics": [],
            "expansion_signals": []
        }
