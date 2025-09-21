"""
OpenAI Enhancement Module for Transcriptions
Uses GPT-3.5-turbo for cost-effective post-processing
"""

import os
import logging
from typing import Optional, Dict, Any
import openai
from openai import OpenAI

logger = logging.getLogger(__name__)


class OpenAIEnhancer:
    """
    Enhances transcriptions using OpenAI's GPT-3.5-turbo model
    Focuses on cost-effectiveness and quality improvements
    """

    def __init__(self):
        """Initialize OpenAI client with API key from environment"""
        self.api_key = os.environ.get('OPENAI_API_KEY')
        self.model = os.environ.get('OPENAI_MODEL', 'gpt-3.5-turbo')
        self.max_tokens = int(os.environ.get('OPENAI_MAX_TOKENS', 500))
        self.temperature = float(os.environ.get('OPENAI_TEMPERATURE', 0.3))

        if self.api_key:
            self.client = OpenAI(api_key=self.api_key)
            logger.info(f"OpenAI enhancer initialized with model: {self.model}")
        else:
            self.client = None
            logger.warning("OpenAI API key not found - enhancement features disabled")

    def enhance_transcription(self,
                             transcription_text: str,
                             request_type: str = "cleanup") -> Optional[str]:
        """
        Enhance transcription using OpenAI

        Args:
            transcription_text: Raw transcription text
            request_type: Type of enhancement (cleanup, summarize, extract_action_items)

        Returns:
            Enhanced text or None if API not available
        """
        if not self.client:
            return None

        try:
            # Define prompts based on request type
            prompts = {
                "cleanup": """Clean up this call transcription by:
1. Fixing grammar and punctuation errors
2. Removing filler words (um, uh, etc.)
3. Organizing into clear paragraphs
4. Maintaining the original meaning and speaker intent

Transcription:
""",
                "summarize": """Create a concise business summary of this call:
1. Key topics discussed
2. Decisions made
3. Action items
4. Important dates/deadlines

Transcription:
""",
                "extract_action_items": """Extract all action items from this call:
1. Task description
2. Assigned to (if mentioned)
3. Due date (if mentioned)
4. Priority (if mentioned)

Format as a bulleted list.

Transcription:
"""
            }

            prompt = prompts.get(request_type, prompts["cleanup"])

            # Make API call with cost-optimized settings
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a professional transcription assistant. Be concise and accurate."},
                    {"role": "user", "content": prompt + transcription_text[:4000]}  # Limit input to control costs
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                top_p=0.9,
                frequency_penalty=0.0,
                presence_penalty=0.0
            )

            enhanced_text = response.choices[0].message.content

            # Log token usage for cost tracking
            if hasattr(response, 'usage'):
                logger.info(f"OpenAI tokens used - Prompt: {response.usage.prompt_tokens}, "
                          f"Completion: {response.usage.completion_tokens}, "
                          f"Total: {response.usage.total_tokens}")

                # Estimate cost (GPT-3.5-turbo pricing as of 2024)
                # Input: $0.0005 per 1K tokens, Output: $0.0015 per 1K tokens
                input_cost = (response.usage.prompt_tokens / 1000) * 0.0005
                output_cost = (response.usage.completion_tokens / 1000) * 0.0015
                total_cost = input_cost + output_cost
                logger.info(f"Estimated cost: ${total_cost:.4f}")

            return enhanced_text

        except Exception as e:
            logger.error(f"OpenAI enhancement failed: {e}")
            return None

    def generate_smart_summary(self, transcription_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Generate a smart summary with multiple components

        Args:
            transcription_data: Full transcription data including text and metadata

        Returns:
            Dictionary with summary components or None
        """
        if not self.client or not transcription_data.get('text'):
            return None

        try:
            text = transcription_data['text'][:4000]  # Limit for cost control

            # Single efficient prompt to get multiple outputs
            prompt = """Analyze this business call and provide:

1. SUMMARY (2-3 sentences)
2. KEY POINTS (3-5 bullet points)
3. ACTION ITEMS (list any mentioned tasks)
4. SENTIMENT (positive/neutral/negative)
5. CALL TYPE (sales/support/internal/other)

Format your response as JSON.

Call transcription:
""" + text

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a business analyst. Respond only with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=0.3,
                response_format={"type": "json_object"}  # Force JSON response
            )

            import json
            result = json.loads(response.choices[0].message.content)

            # Add metadata
            result['processed_with'] = self.model
            result['enhancement_type'] = 'smart_summary'

            return result

        except Exception as e:
            logger.error(f"Smart summary generation failed: {e}")
            return None

    def estimate_processing_cost(self, text_length: int) -> float:
        """
        Estimate the cost of processing a text

        Args:
            text_length: Length of text in characters

        Returns:
            Estimated cost in USD
        """
        # Rough estimate: 1 token ≈ 4 characters
        estimated_tokens = text_length / 4

        # Add system prompt and response tokens
        prompt_tokens = estimated_tokens + 100  # System prompt overhead
        completion_tokens = self.max_tokens

        # GPT-3.5-turbo pricing
        input_cost = (prompt_tokens / 1000) * 0.0005
        output_cost = (completion_tokens / 1000) * 0.0015

        return input_cost + output_cost

    def is_available(self) -> bool:
        """Check if OpenAI enhancement is available"""
        return self.client is not None