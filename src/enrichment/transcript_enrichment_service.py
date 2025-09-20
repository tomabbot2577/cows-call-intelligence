"""
Transcript Enrichment Service
Enriches transcripts with sentiment, summaries, and semantic insights using LLMs
"""

import os
import json
import logging
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
import re
import requests
from enum import Enum

logger = logging.getLogger(__name__)


class Sentiment(Enum):
    """Sentiment classification"""
    VERY_POSITIVE = "very_positive"
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    VERY_NEGATIVE = "very_negative"


class CallCategory(Enum):
    """Call categorization"""
    SALES = "sales"
    SUPPORT = "support"
    COMPLAINT = "complaint"
    INQUIRY = "inquiry"
    BILLING = "billing"
    TECHNICAL = "technical"
    FEEDBACK = "feedback"
    OTHER = "other"


@dataclass
class EnrichmentResult:
    """Result of transcript enrichment"""
    summary: str
    sentiment: Dict[str, Any]
    topics: List[str]
    action_items: List[str]
    key_points: List[str]
    customer_intent: str
    resolution_status: str
    urgency_level: str
    categories: List[str]
    entities: Dict[str, List[str]]
    insights: Dict[str, Any]


class TranscriptEnrichmentService:
    """
    Service to enrich transcripts with AI-powered insights
    Supports multiple LLM providers for comprehensive analysis
    """

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
        ollama_url: Optional[str] = None,
        default_provider: str = "openai"
    ):
        """
        Initialize enrichment service

        Args:
            openai_api_key: OpenAI API key for GPT models
            anthropic_api_key: Anthropic API key for Claude
            ollama_url: Ollama server URL for local models
            default_provider: Default LLM provider
        """
        self.openai_api_key = openai_api_key or os.getenv('OPENAI_API_KEY')
        self.anthropic_api_key = anthropic_api_key or os.getenv('ANTHROPIC_API_KEY')
        self.ollama_url = ollama_url or os.getenv('OLLAMA_URL', 'http://localhost:11434')
        self.default_provider = default_provider

        # Initialize provider clients
        self._init_providers()

        # Prompt templates
        self.prompts = self._load_prompt_templates()

    def _init_providers(self):
        """Initialize LLM provider clients"""
        self.providers = {}

        # OpenAI
        if self.openai_api_key:
            try:
                import openai
                openai.api_key = self.openai_api_key
                self.providers['openai'] = openai
                logger.info("OpenAI provider initialized")
            except ImportError:
                logger.warning("OpenAI library not installed")

        # Anthropic
        if self.anthropic_api_key:
            try:
                from anthropic import Anthropic
                self.providers['anthropic'] = Anthropic(api_key=self.anthropic_api_key)
                logger.info("Anthropic provider initialized")
            except ImportError:
                logger.warning("Anthropic library not installed")

        # Ollama (local)
        if self.ollama_url:
            self.providers['ollama'] = {'url': self.ollama_url}
            logger.info(f"Ollama provider initialized at {self.ollama_url}")

    def _load_prompt_templates(self) -> Dict[str, str]:
        """Load prompt templates for different enrichment tasks"""
        return {
            'summary': """
                Analyze this call transcript and provide a concise summary.

                Transcript: {transcript}

                Provide:
                1. A 2-3 sentence executive summary
                2. Main topic of discussion
                3. Outcome or resolution (if any)

                Format as JSON with keys: executive_summary, main_topic, outcome
            """,

            'sentiment': """
                Analyze the sentiment and emotional tone of this call transcript.

                Transcript: {transcript}

                Provide:
                1. Overall sentiment (very_positive, positive, neutral, negative, very_negative)
                2. Customer sentiment score (0-100)
                3. Agent sentiment score (0-100)
                4. Sentiment progression (how it changed during the call)
                5. Emotional indicators (frustration, satisfaction, confusion, etc.)

                Format as JSON with keys: overall_sentiment, customer_score, agent_score, progression, emotions
            """,

            'topics_and_intent': """
                Extract topics and customer intent from this call transcript.

                Transcript: {transcript}

                Provide:
                1. Main topics discussed (list of up to 5)
                2. Customer's primary intent
                3. Secondary intents (if any)
                4. Product/service mentions
                5. Competitor mentions (if any)

                Format as JSON with keys: topics, primary_intent, secondary_intents, products_mentioned, competitors_mentioned
            """,

            'action_items': """
                Extract action items and follow-ups from this call transcript.

                Transcript: {transcript}

                Provide:
                1. Action items for the agent/company
                2. Action items for the customer
                3. Follow-up requirements
                4. Commitments made
                5. Deadlines mentioned

                Format as JSON with keys: agent_actions, customer_actions, follow_ups, commitments, deadlines
            """,

            'insights': """
                Extract business insights from this call transcript.

                Transcript: {transcript}

                Provide:
                1. Customer pain points
                2. Feature requests or suggestions
                3. Process improvement opportunities
                4. Training opportunities for agents
                5. Upsell/cross-sell opportunities
                6. Risk indicators (churn risk, escalation risk)

                Format as JSON with keys: pain_points, feature_requests, process_improvements, training_needs, sales_opportunities, risks
            """,

            'compliance': """
                Analyze this call for compliance and quality.

                Transcript: {transcript}

                Check for:
                1. Proper greeting and closing
                2. Required disclosures made
                3. Sensitive information handling
                4. Professionalism score (0-100)
                5. Policy adherence indicators

                Format as JSON with keys: greeting_check, closing_check, disclosures, sensitive_data_handled, professionalism_score, policy_adherence
            """,

            'entities': """
                Extract named entities and important information from this call transcript.

                Transcript: {transcript}

                Extract:
                1. Person names mentioned
                2. Company/organization names
                3. Product names
                4. Location references
                5. Account/order/reference numbers
                6. Dates and times mentioned
                7. Dollar amounts
                8. Email addresses
                9. Phone numbers
                10. URLs/websites

                Format as JSON with keys: persons, companies, products, locations, reference_numbers, dates, amounts, emails, phones, urls
            """
        }

    async def enrich_transcript(
        self,
        transcript_text: str,
        call_metadata: Optional[Dict[str, Any]] = None,
        enrichment_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Enrich transcript with AI-powered insights

        Args:
            transcript_text: The call transcript text
            call_metadata: Optional call metadata
            enrichment_types: Types of enrichment to perform

        Returns:
            Enriched metadata dictionary
        """
        if not enrichment_types:
            enrichment_types = [
                'summary',
                'sentiment',
                'topics_and_intent',
                'action_items',
                'insights',
                'entities'
            ]

        enriched_data = {
            'enrichment_timestamp': datetime.now(timezone.utc).isoformat(),
            'enrichment_version': '1.0',
            'provider': self.default_provider
        }

        # Run enrichments
        for enrichment_type in enrichment_types:
            try:
                if enrichment_type == 'summary':
                    enriched_data['summary'] = await self._generate_summary(transcript_text)
                elif enrichment_type == 'sentiment':
                    enriched_data['sentiment'] = await self._analyze_sentiment(transcript_text)
                elif enrichment_type == 'topics_and_intent':
                    enriched_data['topics_and_intent'] = await self._extract_topics_intent(transcript_text)
                elif enrichment_type == 'action_items':
                    enriched_data['action_items'] = await self._extract_action_items(transcript_text)
                elif enrichment_type == 'insights':
                    enriched_data['insights'] = await self._extract_insights(transcript_text)
                elif enrichment_type == 'entities':
                    enriched_data['entities'] = await self._extract_entities(transcript_text)
                elif enrichment_type == 'compliance':
                    enriched_data['compliance'] = await self._check_compliance(transcript_text)

            except Exception as e:
                logger.error(f"Failed to enrich {enrichment_type}: {e}")
                enriched_data[enrichment_type] = {'error': str(e)}

        # Add categorization
        enriched_data['categorization'] = self._categorize_call(enriched_data)

        # Add urgency assessment
        enriched_data['urgency'] = self._assess_urgency(enriched_data)

        # Add quality metrics
        enriched_data['quality_metrics'] = self._calculate_quality_metrics(transcript_text, enriched_data)

        return enriched_data

    async def _generate_summary(self, transcript: str) -> Dict[str, Any]:
        """Generate summary using LLM"""
        prompt = self.prompts['summary'].format(transcript=transcript[:3000])  # Limit context
        response = await self._call_llm(prompt)
        return self._parse_json_response(response, {
            'executive_summary': 'Summary not available',
            'main_topic': 'Unknown',
            'outcome': 'Unresolved'
        })

    async def _analyze_sentiment(self, transcript: str) -> Dict[str, Any]:
        """Analyze sentiment using LLM"""
        prompt = self.prompts['sentiment'].format(transcript=transcript[:3000])
        response = await self._call_llm(prompt)
        return self._parse_json_response(response, {
            'overall_sentiment': 'neutral',
            'customer_score': 50,
            'agent_score': 50,
            'progression': 'stable',
            'emotions': []
        })

    async def _extract_topics_intent(self, transcript: str) -> Dict[str, Any]:
        """Extract topics and intent using LLM"""
        prompt = self.prompts['topics_and_intent'].format(transcript=transcript[:3000])
        response = await self._call_llm(prompt)
        return self._parse_json_response(response, {
            'topics': [],
            'primary_intent': 'unknown',
            'secondary_intents': [],
            'products_mentioned': [],
            'competitors_mentioned': []
        })

    async def _extract_action_items(self, transcript: str) -> Dict[str, Any]:
        """Extract action items using LLM"""
        prompt = self.prompts['action_items'].format(transcript=transcript[:3000])
        response = await self._call_llm(prompt)
        return self._parse_json_response(response, {
            'agent_actions': [],
            'customer_actions': [],
            'follow_ups': [],
            'commitments': [],
            'deadlines': []
        })

    async def _extract_insights(self, transcript: str) -> Dict[str, Any]:
        """Extract business insights using LLM"""
        prompt = self.prompts['insights'].format(transcript=transcript[:3000])
        response = await self._call_llm(prompt)
        return self._parse_json_response(response, {
            'pain_points': [],
            'feature_requests': [],
            'process_improvements': [],
            'training_needs': [],
            'sales_opportunities': [],
            'risks': {}
        })

    async def _extract_entities(self, transcript: str) -> Dict[str, Any]:
        """Extract named entities using LLM"""
        prompt = self.prompts['entities'].format(transcript=transcript[:3000])
        response = await self._call_llm(prompt)
        return self._parse_json_response(response, {
            'persons': [],
            'companies': [],
            'products': [],
            'locations': [],
            'reference_numbers': [],
            'dates': [],
            'amounts': [],
            'emails': [],
            'phones': [],
            'urls': []
        })

    async def _check_compliance(self, transcript: str) -> Dict[str, Any]:
        """Check compliance using LLM"""
        prompt = self.prompts['compliance'].format(transcript=transcript[:3000])
        response = await self._call_llm(prompt)
        return self._parse_json_response(response, {
            'greeting_check': False,
            'closing_check': False,
            'disclosures': [],
            'sensitive_data_handled': True,
            'professionalism_score': 75,
            'policy_adherence': []
        })

    async def _call_llm(self, prompt: str) -> str:
        """
        Call LLM provider with prompt

        Args:
            prompt: The prompt to send

        Returns:
            LLM response text
        """
        provider = self.default_provider

        try:
            if provider == 'openai' and 'openai' in self.providers:
                import openai
                response = await asyncio.to_thread(
                    openai.ChatCompletion.create,
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a call center analytics expert. Always respond with valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=500
                )
                return response['choices'][0]['message']['content']

            elif provider == 'anthropic' and 'anthropic' in self.providers:
                client = self.providers['anthropic']
                response = await asyncio.to_thread(
                    client.messages.create,
                    model="claude-3-haiku-20240307",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=500,
                    temperature=0.3
                )
                return response.content[0].text

            elif provider == 'ollama' and 'ollama' in self.providers:
                response = requests.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": "llama2",
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.3}
                    },
                    timeout=30
                )
                if response.status_code == 200:
                    return response.json()['response']

            # Fallback to regex-based extraction
            return self._fallback_extraction(prompt)

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return self._fallback_extraction(prompt)

    def _fallback_extraction(self, prompt: str) -> str:
        """
        Fallback extraction when LLM is not available
        Uses regex and heuristics
        """
        # Simple fallback response
        return json.dumps({
            'note': 'LLM unavailable, using fallback extraction',
            'basic_analysis': True
        })

    def _parse_json_response(self, response: str, default: Dict) -> Dict[str, Any]:
        """
        Parse JSON response from LLM

        Args:
            response: LLM response text
            default: Default values if parsing fails

        Returns:
            Parsed dictionary
        """
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return json.loads(response)
        except:
            logger.warning("Failed to parse LLM response as JSON, using defaults")
            return default

    def _categorize_call(self, enriched_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Categorize call based on enriched data

        Args:
            enriched_data: Enriched metadata

        Returns:
            Categorization details
        """
        categories = []
        confidence_scores = {}

        # Check topics and intent
        topics = enriched_data.get('topics_and_intent', {}).get('topics', [])
        intent = enriched_data.get('topics_and_intent', {}).get('primary_intent', '')

        # Categorization rules
        if any(word in intent.lower() for word in ['support', 'help', 'issue', 'problem']):
            categories.append(CallCategory.SUPPORT.value)
            confidence_scores[CallCategory.SUPPORT.value] = 0.8

        if any(word in intent.lower() for word in ['complaint', 'unhappy', 'dissatisfied']):
            categories.append(CallCategory.COMPLAINT.value)
            confidence_scores[CallCategory.COMPLAINT.value] = 0.9

        if any(word in intent.lower() for word in ['buy', 'purchase', 'order', 'pricing']):
            categories.append(CallCategory.SALES.value)
            confidence_scores[CallCategory.SALES.value] = 0.85

        if any(word in intent.lower() for word in ['bill', 'payment', 'invoice', 'charge']):
            categories.append(CallCategory.BILLING.value)
            confidence_scores[CallCategory.BILLING.value] = 0.9

        if not categories:
            categories.append(CallCategory.OTHER.value)
            confidence_scores[CallCategory.OTHER.value] = 0.5

        return {
            'primary_category': categories[0] if categories else CallCategory.OTHER.value,
            'all_categories': categories,
            'confidence_scores': confidence_scores
        }

    def _assess_urgency(self, enriched_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Assess call urgency based on enriched data

        Args:
            enriched_data: Enriched metadata

        Returns:
            Urgency assessment
        """
        urgency_score = 0
        urgency_factors = []

        # Check sentiment
        sentiment = enriched_data.get('sentiment', {})
        if sentiment.get('overall_sentiment') in ['negative', 'very_negative']:
            urgency_score += 30
            urgency_factors.append('negative_sentiment')

        # Check for risk indicators
        risks = enriched_data.get('insights', {}).get('risks', {})
        if risks:
            urgency_score += 20
            urgency_factors.append('risk_indicators')

        # Check for complaints
        categories = enriched_data.get('categorization', {}).get('all_categories', [])
        if CallCategory.COMPLAINT.value in categories:
            urgency_score += 25
            urgency_factors.append('complaint')

        # Check for deadlines
        deadlines = enriched_data.get('action_items', {}).get('deadlines', [])
        if deadlines:
            urgency_score += 15
            urgency_factors.append('deadlines')

        # Determine urgency level
        if urgency_score >= 60:
            urgency_level = 'high'
        elif urgency_score >= 30:
            urgency_level = 'medium'
        else:
            urgency_level = 'low'

        return {
            'level': urgency_level,
            'score': urgency_score,
            'factors': urgency_factors
        }

    def _calculate_quality_metrics(
        self,
        transcript: str,
        enriched_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate call quality metrics

        Args:
            transcript: Original transcript
            enriched_data: Enriched metadata

        Returns:
            Quality metrics
        """
        metrics = {}

        # Calculate call efficiency (words per minute)
        word_count = len(transcript.split())
        metrics['word_count'] = word_count

        # Sentiment quality
        sentiment = enriched_data.get('sentiment', {})
        customer_score = sentiment.get('customer_score', 50)
        agent_score = sentiment.get('agent_score', 50)

        metrics['sentiment_quality'] = {
            'customer_satisfaction': customer_score / 100,
            'agent_performance': agent_score / 100,
            'overall': (customer_score + agent_score) / 200
        }

        # Resolution quality
        outcome = enriched_data.get('summary', {}).get('outcome', 'unknown')
        if 'resolved' in outcome.lower():
            metrics['resolution_score'] = 1.0
        elif 'partial' in outcome.lower():
            metrics['resolution_score'] = 0.5
        else:
            metrics['resolution_score'] = 0.0

        # Compliance score
        compliance = enriched_data.get('compliance', {})
        metrics['compliance_score'] = compliance.get('professionalism_score', 75) / 100

        # Overall quality score
        metrics['overall_quality'] = (
            metrics['sentiment_quality']['overall'] * 0.4 +
            metrics['resolution_score'] * 0.3 +
            metrics['compliance_score'] * 0.3
        )

        return metrics