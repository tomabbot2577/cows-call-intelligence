"""
Layer 1: Entity Extraction

Extracts participants, companies, deal signals, and meeting classification.
"""

import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class EntityExtractor:
    """Layer 1: Extract entities and classify meetings."""

    PROMPT = """Analyze this video meeting transcript and extract entities:

TRANSCRIPT:
{transcript}

EXISTING PARTICIPANTS:
{participants}

FATHOM SUMMARY (if available):
{summary}

Extract and return JSON with:
{{
    "meeting_type": "sales|support|training|interview|internal|external",
    "meeting_purpose": "brief description of meeting purpose",
    "participants": [
        {{
            "name": "participant name",
            "role": "their role/title if mentioned",
            "company": "their company if mentioned",
            "is_host": true/false,
            "is_external": true/false
        }}
    ],
    "companies_mentioned": [
        {{
            "name": "company name",
            "context": "how they were mentioned",
            "is_customer": true/false,
            "is_competitor": true/false
        }}
    ],
    "deal_signals": [
        {{
            "signal_type": "budget|timeline|authority|need",
            "quote": "relevant quote",
            "strength": "strong|moderate|weak"
        }}
    ],
    "competitor_mentions": ["list of competitors mentioned"],
    "products_discussed": ["list of products/features discussed"],
    "key_dates": ["any dates or deadlines mentioned"],
    "crm_matches": {{
        "potential_contacts": ["emails or names to match"],
        "potential_companies": ["companies to match in CRM"]
    }}
}}

Return ONLY valid JSON, no additional text."""

    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def analyze(self, meeting: Dict) -> Dict:
        """Analyze meeting for entity extraction."""
        transcript = meeting.get('transcript_text', '')[:15000]
        participants = meeting.get('participants_json', '[]')
        summary = meeting.get('fathom_summary', '')

        if isinstance(participants, str):
            try:
                participants = json.loads(participants)
            except:
                participants = []

        prompt = self.PROMPT.format(
            transcript=transcript,
            participants=json.dumps(participants, indent=2),
            summary=summary[:2000] if summary else "Not available"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                temperature=0.2
            )

            content = response.choices[0].message.content
            return self._parse_response(content)

        except Exception as e:
            logger.error(f"Layer 1 analysis failed: {e}")
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
            "meeting_type": "unknown",
            "participants": [],
            "companies_mentioned": [],
            "deal_signals": [],
            "competitor_mentions": [],
            "products_discussed": [],
            "crm_matches": {}
        }
