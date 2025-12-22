"""
Layer 5: Advanced Metrics

Speaking time analysis, Hormozi Blueprint scoring, competitive intel, financials.
"""

import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class AdvancedMetrics:
    """Layer 5: Advanced analytics and metrics."""

    PROMPT = """Perform advanced analysis on this meeting:

TRANSCRIPT:
{transcript}

MEETING TYPE: {meeting_type}
PARTICIPANTS: {participants}

Analyze and return JSON with:
{{
    "speaking_time": {{
        "host_percentage": 0-100,
        "participant_distribution": [
            {{"name": "participant name", "percentage": 0-100}}
        ],
        "talk_listen_ratio": 0.0-5.0,
        "monologue_instances": number,
        "average_turn_duration_seconds": number
    }},

    "hormozi_score": 0-100,
    "hormozi_components": {{
        "value_articulation": {{
            "score": 0-100,
            "evidence": ["specific examples from transcript"]
        }},
        "objection_handling": {{
            "score": 0-100,
            "objections_raised": number,
            "objections_resolved": number
        }},
        "urgency_creation": {{
            "score": 0-100,
            "techniques_used": ["list of urgency techniques"]
        }},
        "trust_building": {{
            "score": 0-100,
            "rapport_indicators": ["list of rapport indicators"]
        }},
        "close_attempt": {{
            "score": 0-100,
            "close_type": "hard|soft|trial|none",
            "outcome": "success|pending|failed|not_applicable"
        }}
    }},

    "competitive_mentions": [
        {{
            "competitor": "competitor name",
            "context": "positive|negative|neutral",
            "feature_comparison": "what was compared",
            "quote": "relevant quote"
        }}
    ],

    "deal_value": number or null,
    "deal_currency": "USD|EUR|etc or null",
    "contract_length": number of months or null,

    "financial_indicators": {{
        "budget_mentioned": true/false,
        "budget_range": "low|medium|high|enterprise or null",
        "pricing_discussed": true/false,
        "discount_requested": true/false,
        "roi_discussed": true/false
    }},

    "technical_depth": {{
        "score": 0-100,
        "topics": ["technical topics discussed"],
        "integration_needs": ["integration requirements mentioned"]
    }},

    "decision_dynamics": {{
        "decision_maker_present": true/false,
        "decision_timeline": "immediate|this_week|this_month|this_quarter|unknown",
        "buying_committee_size": number or null,
        "champion_identified": true/false
    }}
}}

Return ONLY valid JSON, no additional text."""

    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def analyze(self, meeting: Dict, all_layers: Dict) -> Dict:
        """Generate advanced metrics."""
        transcript = meeting.get('transcript_text', '')[:15000]

        layer1 = all_layers.get('layer1', {})
        participants = layer1.get('participants', [])

        prompt = self.PROMPT.format(
            transcript=transcript,
            meeting_type=layer1.get('meeting_type', 'unknown'),
            participants=json.dumps(participants, indent=2)
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2500,
                temperature=0.3
            )

            content = response.choices[0].message.content
            return self._parse_response(content)

        except Exception as e:
            logger.error(f"Layer 5 analysis failed: {e}")
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
            "speaking_time": {"host_percentage": 50},
            "hormozi_score": 50,
            "hormozi_components": {},
            "competitive_mentions": [],
            "deal_value": None,
            "financial_indicators": {}
        }
