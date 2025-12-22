"""
Layer 6: Learning Intelligence (UTL-based)

Implements the Unified Theory of Learning for meeting analysis.
Formula: L = f(ΔS × ΔC × wₑ × cos(φ))

Where:
- ΔS = Entropy/novelty introduced (new information)
- ΔC = Coherence/understanding achieved (how well absorbed)
- wₑ = Emotional engagement factor
- φ = Phase alignment (challenge-support synchronization)

Learning States:
- aha_zone: High learning, perfect balance
- overwhelmed: Too much novelty, low coherence
- bored: Low novelty, high existing coherence
- disengaged: Low emotional engagement
- building: Moderate learning, steady progress
- struggling: Low coherence despite engagement
"""

import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class LearningAnalyzer:
    """Layer 6: UTL-based learning intelligence analysis."""

    PROMPT = """Analyze this meeting for learning effectiveness using UTL framework:

TRANSCRIPT:
{transcript}

MEETING TYPE: {meeting_type}
QUALITY SCORE: {quality_score}/10
OBJECTIVES MET: {objectives_score}%

Analyze the learning dynamics and return JSON:
{{
    "learning_score": 0.0-1.0,
    "learning_rationale": "explanation of learning score",

    "entropy_delta": {{
        "score": 0.0-1.0,
        "novel_concepts": ["new concepts introduced"],
        "complexity_level": "low|medium|high",
        "information_density": "sparse|moderate|dense"
    }},

    "coherence_delta": {{
        "score": 0.0-1.0,
        "understanding_indicators": ["signs of comprehension"],
        "confusion_indicators": ["signs of confusion"],
        "retention_signals": ["signs information will be retained"]
    }},

    "emotional_engagement": {{
        "score": 0.0-1.0,
        "engagement_type": "intellectual|emotional|practical|mixed",
        "high_points": ["moments of high engagement"],
        "low_points": ["moments of low engagement"]
    }},

    "phase_alignment": {{
        "score": -1.0 to 1.0,
        "challenge_level": "too_easy|appropriate|too_hard",
        "support_provided": "insufficient|adequate|excellent",
        "pacing": "too_slow|appropriate|too_fast"
    }},

    "learning_state": "aha_zone|overwhelmed|bored|disengaged|building|struggling",
    "state_explanation": "why this learning state",

    "knowledge_transfer_rate": 0.0-1.0,
    "knowledge_gaps_identified": ["gaps in understanding observed"],

    "host_teaching_effectiveness": {{
        "score": 0-100,
        "strengths": ["teaching strengths observed"],
        "improvements": ["areas for improvement"]
    }},

    "participant_learning_indicators": [
        {{
            "participant": "name or role",
            "learning_state": "aha_zone|building|struggling|etc",
            "engagement_level": 0.0-1.0,
            "key_takeaways": ["what they seemed to learn"]
        }}
    ],

    "lambda_adjustments": {{
        "recommended_pacing": "slower|maintain|faster",
        "recommended_depth": "less_detail|maintain|more_detail",
        "recommended_examples": "fewer|maintain|more",
        "recommended_interaction": "less|maintain|more"
    }},

    "coaching_recommendations": [
        {{
            "for": "host|participant|all",
            "recommendation": "specific coaching suggestion",
            "rationale": "based on UTL analysis",
            "expected_improvement": "what would improve"
        }}
    ],

    "meeting_learning_summary": {{
        "total_concepts_introduced": number,
        "concepts_understood": number,
        "concepts_requiring_followup": ["list"],
        "recommended_next_session_focus": "what to focus on next"
    }}
}}

Return ONLY valid JSON, no additional text."""

    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def analyze(self, meeting: Dict, all_layers: Dict) -> Dict:
        """Analyze learning dynamics using UTL framework."""
        transcript = meeting.get('transcript_text', '')[:15000]

        layer1 = all_layers.get('layer1', {})
        layer2 = all_layers.get('layer2', {})
        layer3 = all_layers.get('layer3', {})

        prompt = self.PROMPT.format(
            transcript=transcript,
            meeting_type=layer1.get('meeting_type', 'unknown'),
            quality_score=layer2.get('meeting_quality_score', 5),
            objectives_score=layer3.get('objectives_met_score', 50)
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=3000,
                temperature=0.4
            )

            content = response.choices[0].message.content
            result = self._parse_response(content)

            # Calculate composite learning score if not provided
            if 'learning_score' not in result or result['learning_score'] is None:
                result['learning_score'] = self._calculate_learning_score(result)

            return result

        except Exception as e:
            logger.error(f"Layer 6 analysis failed: {e}")
            return self._default_response()

    def _calculate_learning_score(self, result: Dict) -> float:
        """
        Calculate L = f(ΔS × ΔC × wₑ × cos(φ))

        This is a simplified implementation of the UTL formula.
        """
        try:
            # Extract component scores
            entropy = result.get('entropy_delta', {}).get('score', 0.5)
            coherence = result.get('coherence_delta', {}).get('score', 0.5)
            engagement = result.get('emotional_engagement', {}).get('score', 0.5)
            phase = result.get('phase_alignment', {}).get('score', 0)

            # Calculate cos(φ) - phase alignment factor
            import math
            # Convert phase score (-1 to 1) to cosine
            # Perfect alignment (0) = cos(0) = 1
            # Misalignment (-1 or 1) = lower value
            phase_factor = math.cos(abs(phase) * math.pi / 2)

            # Calculate learning score
            # L = ΔS × ΔC × wₑ × cos(φ)
            learning = entropy * coherence * engagement * phase_factor

            # Normalize to 0-1 range
            return max(0.0, min(1.0, learning))

        except Exception as e:
            logger.warning(f"Learning score calculation failed: {e}")
            return 0.5

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
            "learning_score": 0.5,
            "entropy_delta": {"score": 0.5},
            "coherence_delta": {"score": 0.5},
            "emotional_engagement": {"score": 0.5},
            "phase_alignment": {"score": 0},
            "learning_state": "building",
            "knowledge_transfer_rate": 0.5,
            "host_teaching_effectiveness": {"score": 50},
            "lambda_adjustments": {},
            "coaching_recommendations": []
        }
