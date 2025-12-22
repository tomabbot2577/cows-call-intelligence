"""
Layer 4: Recommendations

Generates coaching points, sales recommendations, and process improvements.
"""

import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class RecommendationEngine:
    """Layer 4: Generate actionable recommendations."""

    PROMPT = """Based on the meeting analysis, generate recommendations:

TRANSCRIPT EXCERPT:
{transcript}

MEETING TYPE: {meeting_type}
MEETING QUALITY: {quality_score}/10
CHURN RISK: {churn_risk}
NPS PREDICTION: {nps_score}
OBJECTIVES MET: {objectives_score}%

UNRESOLVED ISSUES:
{unresolved_issues}

Generate recommendations and return JSON:
{{
    "host_coaching": [
        {{
            "area": "communication|preparation|follow-up|technical|rapport",
            "observation": "what was observed",
            "recommendation": "specific improvement suggestion",
            "example": "concrete example from transcript if available",
            "priority": "high|medium|low"
        }}
    ],

    "sales_recommendations": [
        {{
            "opportunity": "description of opportunity",
            "action": "recommended action",
            "timing": "when to take action",
            "expected_impact": "potential revenue/outcome"
        }}
    ],

    "customer_success_actions": [
        {{
            "action": "what to do",
            "reason": "why it's needed",
            "urgency": "immediate|this_week|this_month",
            "owner_role": "CSM|Support|Sales|Executive"
        }}
    ],

    "process_improvements": [
        {{
            "process": "which process needs improvement",
            "current_issue": "what's wrong currently",
            "suggestion": "how to improve",
            "benefit": "expected benefit"
        }}
    ],

    "knowledge_gaps": [
        {{
            "topic": "knowledge area",
            "gap_type": "training|documentation|tooling",
            "recommendation": "how to address"
        }}
    ],

    "follow_up_priority": "urgent|high|medium|low",
    "follow_up_deadline": "YYYY-MM-DD or null",
    "follow_up_owner": "suggested owner",
    "follow_up_message": "suggested follow-up message template",

    "risk_mitigation": [
        {{
            "risk": "identified risk",
            "mitigation": "how to mitigate",
            "timeline": "when to act"
        }}
    ]
}}

Return ONLY valid JSON, no additional text."""

    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def analyze(self, meeting: Dict, all_layers: Dict) -> Dict:
        """Generate recommendations based on all previous layers."""
        transcript = meeting.get('transcript_text', '')[:10000]

        layer1 = all_layers.get('layer1', {})
        layer2 = all_layers.get('layer2', {})
        layer3 = all_layers.get('layer3', {})

        unresolved = layer3.get('unresolved_issues', [])
        if isinstance(unresolved, list):
            unresolved_text = '\n'.join([
                f"- {i.get('issue', i)}: {i.get('blocker', 'N/A')}"
                for i in unresolved
            ])
        else:
            unresolved_text = str(unresolved)

        prompt = self.PROMPT.format(
            transcript=transcript,
            meeting_type=layer1.get('meeting_type', 'unknown'),
            quality_score=layer2.get('meeting_quality_score', 5),
            churn_risk=layer2.get('churn_risk_level', 'low'),
            nps_score=layer2.get('nps_score', 5),
            objectives_score=layer3.get('objectives_met_score', 50),
            unresolved_issues=unresolved_text or "None identified"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2500,
                temperature=0.4
            )

            content = response.choices[0].message.content
            return self._parse_response(content)

        except Exception as e:
            logger.error(f"Layer 4 analysis failed: {e}")
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
            "host_coaching": [],
            "sales_recommendations": [],
            "customer_success_actions": [],
            "process_improvements": [],
            "follow_up_priority": "medium"
        }
