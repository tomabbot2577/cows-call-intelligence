"""
Layer 3: Resolution & Outcomes

Tracks objectives met, action item quality, decisions, and loop closure.
"""

import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ResolutionTracker:
    """Layer 3: Track resolutions and outcomes."""

    PROMPT = """Analyze the meeting outcomes and resolution effectiveness:

TRANSCRIPT:
{transcript}

MEETING TYPE: {meeting_type}
MEETING PURPOSE: {purpose}
SENTIMENT: {sentiment_summary}

Analyze and return JSON with:
{{
    "objectives_met_score": 0-100,
    "objectives_met_details": "explanation of objectives met/not met",
    "stated_objectives": ["objectives stated at start of meeting"],
    "achieved_objectives": ["objectives that were achieved"],
    "unmet_objectives": ["objectives not achieved"],

    "fcr_achieved": true/false,
    "fcr_details": "First Contact Resolution explanation",

    "escalation_required": true/false,
    "escalation_reason": "if escalation needed, why",
    "escalation_to": "who/what team for escalation",

    "loop_closure_score": 0-100,
    "open_loops": ["items left unresolved"],
    "closed_loops": ["items fully resolved"],

    "action_item_quality_score": 0-100,
    "action_items_analysis": [
        {{
            "item": "action item text",
            "owner": "assigned person",
            "deadline": "mentioned deadline or null",
            "clarity_score": 1-10,
            "measurable": true/false
        }}
    ],

    "decisions_made": [
        {{
            "decision": "what was decided",
            "context": "why it was decided",
            "impact": "expected impact",
            "stakeholders": ["who was involved"]
        }}
    ],

    "unresolved_issues": [
        {{
            "issue": "description",
            "blocker": "what's blocking resolution",
            "next_step": "suggested next step"
        }}
    ],

    "follow_up_required": true/false,
    "follow_up_items": ["list of follow-up items needed"],
    "recommended_next_meeting": "suggestion for next meeting topic/timing"
}}

Return ONLY valid JSON, no additional text."""

    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def analyze(self, meeting: Dict, layer1: Dict, layer2: Dict) -> Dict:
        """Analyze resolutions and outcomes."""
        transcript = meeting.get('transcript_text', '')[:15000]
        meeting_type = layer1.get('meeting_type', 'unknown')
        purpose = layer1.get('meeting_purpose', 'Not specified')

        sentiment_summary = f"""
        NPS: {layer2.get('nps_score', 'N/A')}
        Health Score: {layer2.get('customer_health_score', 'N/A')}
        Churn Risk: {layer2.get('churn_risk_level', 'N/A')}
        Quality Score: {layer2.get('meeting_quality_score', 'N/A')}
        """

        prompt = self.PROMPT.format(
            transcript=transcript,
            meeting_type=meeting_type,
            purpose=purpose,
            sentiment_summary=sentiment_summary
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
            logger.error(f"Layer 3 analysis failed: {e}")
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
            "objectives_met_score": 50,
            "fcr_achieved": False,
            "escalation_required": False,
            "loop_closure_score": 50,
            "action_item_quality_score": 50,
            "decisions_made": [],
            "unresolved_issues": [],
            "follow_up_required": True
        }
