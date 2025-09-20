"""
Enrichment Pipeline
Orchestrates transcript enrichment with Salad API features and LLM insights
"""

import os
import json
import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from pathlib import Path

from .transcript_enrichment_service import TranscriptEnrichmentService

logger = logging.getLogger(__name__)


class EnrichmentPipeline:
    """
    Pipeline to enrich transcripts with advanced metadata
    Combines Salad API features with LLM-powered insights
    """

    def __init__(
        self,
        enable_salad_features: bool = True,
        enable_llm_enrichment: bool = True,
        openai_api_key: Optional[str] = None,
        save_enriched_metadata: bool = True,
        enrichment_dir: str = "/var/www/call-recording-system/data/enriched"
    ):
        """
        Initialize enrichment pipeline

        Args:
            enable_salad_features: Use Salad API advanced features
            enable_llm_enrichment: Use LLM for additional insights
            openai_api_key: OpenAI API key for enrichment
            save_enriched_metadata: Save enriched data separately
            enrichment_dir: Directory for enriched metadata
        """
        self.enable_salad_features = enable_salad_features
        self.enable_llm_enrichment = enable_llm_enrichment
        self.save_enriched_metadata = save_enriched_metadata
        self.enrichment_dir = Path(enrichment_dir)

        # Initialize enrichment service if LLM is enabled
        if self.enable_llm_enrichment:
            self.enrichment_service = TranscriptEnrichmentService(
                openai_api_key=openai_api_key
            )

        # Create directories
        if self.save_enriched_metadata:
            self.enrichment_dir.mkdir(parents=True, exist_ok=True)
            (self.enrichment_dir / 'summaries').mkdir(exist_ok=True)
            (self.enrichment_dir / 'sentiment').mkdir(exist_ok=True)
            (self.enrichment_dir / 'insights').mkdir(exist_ok=True)
            (self.enrichment_dir / 'complete').mkdir(exist_ok=True)

        logger.info(f"EnrichmentPipeline initialized - Salad: {enable_salad_features}, LLM: {enable_llm_enrichment}")

    def configure_salad_job_input(self) -> Dict[str, Any]:
        """
        Configure Salad API job input with all available features

        Returns:
            Configuration for TranscriptionJobInput
        """
        config = {
            # Basic settings
            'return_as_file': False,
            'language_code': 'en-US',

            # Advanced features
            'word_level_timestamps': True,
            'sentence_level_timestamps': True,

            # Diarization (speaker identification)
            'diarization': True,
            'sentence_diarization': True,

            # Formats
            'srt': True,

            # Summarization (if supported)
            'summarize': 10,  # 10 sentence summary

            # Additional processing hints
            'custom_prompt': """
                This is a business call recording. Please:
                1. Identify different speakers clearly
                2. Note any customer sentiment changes
                3. Highlight key action items or commitments
                4. Mark any mentions of competitors or products
                5. Flag any compliance or policy issues
            """
        }

        logger.info("Salad job configured with advanced features: diarization, summarization, timestamps")
        return config

    def enrich_transcript_sync(
        self,
        transcript_data: Dict[str, Any],
        call_metadata: Dict[str, Any],
        salad_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Synchronous wrapper for enrich_transcript_async
        """
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self.enrich_transcript_async(transcript_data, call_metadata, salad_result)
            )
        finally:
            loop.close()

    def enrich_transcript(
        self,
        transcript_data: Dict[str, Any],
        call_metadata: Dict[str, Any],
        salad_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Synchronous version of enrich_transcript for backward compatibility
        """
        return self.enrich_transcript_sync(transcript_data, call_metadata, salad_result)

    async def enrich_transcript_async(
        self,
        transcript_data: Dict[str, Any],
        call_metadata: Dict[str, Any],
        salad_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Enrich transcript with all available insights

        Args:
            transcript_data: Basic transcript data
            call_metadata: Call metadata
            salad_result: Raw result from Salad API

        Returns:
            Fully enriched transcript data
        """
        enriched = {
            'original_transcript': transcript_data,
            'call_metadata': call_metadata,
            'enrichment_timestamp': datetime.now(timezone.utc).isoformat(),
            'enrichment_pipeline_version': '2.0'
        }

        # 1. Extract Salad API features
        if self.enable_salad_features and salad_result:
            enriched['salad_features'] = self._extract_salad_features(salad_result)

        # 2. Apply LLM enrichment
        if self.enable_llm_enrichment:
            transcript_text = transcript_data.get('text', '')

            try:
                llm_enrichment = await self.enrichment_service.enrich_transcript(
                    transcript_text=transcript_text,
                    call_metadata=call_metadata,
                    enrichment_types=[
                        'summary',
                        'sentiment',
                        'topics_and_intent',
                        'action_items',
                        'insights',
                        'entities',
                        'compliance'
                    ]
                )

                enriched['llm_enrichment'] = llm_enrichment
                logger.info(f"LLM enrichment completed for transcript {call_metadata.get('recording_id')}")

            except Exception as e:
                logger.error(f"LLM enrichment failed: {e}")
                enriched['llm_enrichment'] = {'error': str(e)}

        # 3. Combine insights
        enriched['combined_insights'] = self._combine_insights(enriched)

        # 4. Generate quality scores
        enriched['quality_scores'] = self._calculate_quality_scores(enriched)

        # 5. Generate alerts if needed
        enriched['alerts'] = self._generate_alerts(enriched)

        # 6. Save enriched metadata
        if self.save_enriched_metadata:
            self._save_enriched_data(enriched, call_metadata.get('recording_id', 'unknown'))

        return enriched

    def _extract_salad_features(self, salad_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract advanced features from Salad API result

        Args:
            salad_result: Raw Salad API response

        Returns:
            Extracted features
        """
        features = {
            'has_diarization': False,
            'speakers': [],
            'summary': None,
            'word_timestamps': [],
            'sentence_timestamps': [],
            'confidence_scores': [],
            'language_detection': {}
        }

        # Extract diarization (speaker identification)
        if 'speakers' in salad_result:
            features['has_diarization'] = True
            features['speakers'] = salad_result['speakers']
            logger.info(f"Found {len(features['speakers'])} speakers in diarization")

        # Extract segments with speaker labels
        segments = salad_result.get('segments', [])
        for segment in segments:
            if 'speaker' in segment:
                # Track speaker segments
                if 'speaker_segments' not in features:
                    features['speaker_segments'] = []

                features['speaker_segments'].append({
                    'speaker': segment['speaker'],
                    'start': segment.get('start'),
                    'end': segment.get('end'),
                    'text': segment.get('text'),
                    'confidence': segment.get('confidence', 0)
                })

            # Extract word-level timestamps
            if 'words' in segment:
                features['word_timestamps'].extend(segment['words'])

            # Track confidence scores
            if 'confidence' in segment:
                features['confidence_scores'].append(segment['confidence'])

        # Extract summary if available
        if 'summary' in salad_result:
            features['summary'] = salad_result['summary']
            logger.info("Summary extracted from Salad API")

        # Language detection confidence
        features['language_detection'] = {
            'language': salad_result.get('language', 'en-US'),
            'confidence': salad_result.get('language_probability', 0)
        }

        # Calculate average confidence
        if features['confidence_scores']:
            features['average_confidence'] = sum(features['confidence_scores']) / len(features['confidence_scores'])

        return features

    def _combine_insights(self, enriched: Dict[str, Any]) -> Dict[str, Any]:
        """
        Combine insights from multiple sources

        Args:
            enriched: Enriched data from all sources

        Returns:
            Combined insights
        """
        combined = {
            'summary': {},
            'sentiment': {},
            'topics': [],
            'action_items': [],
            'entities': {},
            'compliance': {},
            'speakers': {}
        }

        # Combine summaries
        if 'salad_features' in enriched and enriched['salad_features'].get('summary'):
            combined['summary']['salad'] = enriched['salad_features']['summary']

        if 'llm_enrichment' in enriched and 'summary' in enriched['llm_enrichment']:
            combined['summary']['llm'] = enriched['llm_enrichment']['summary']

        # Combine sentiment
        if 'llm_enrichment' in enriched and 'sentiment' in enriched['llm_enrichment']:
            combined['sentiment'] = enriched['llm_enrichment']['sentiment']

        # Combine topics
        if 'llm_enrichment' in enriched and 'topics_and_intent' in enriched['llm_enrichment']:
            combined['topics'] = enriched['llm_enrichment']['topics_and_intent'].get('topics', [])

        # Combine action items
        if 'llm_enrichment' in enriched and 'action_items' in enriched['llm_enrichment']:
            action_items = enriched['llm_enrichment']['action_items']
            combined['action_items'] = (
                action_items.get('agent_actions', []) +
                action_items.get('customer_actions', [])
            )

        # Combine entities
        if 'llm_enrichment' in enriched and 'entities' in enriched['llm_enrichment']:
            combined['entities'] = enriched['llm_enrichment']['entities']

        # Add speaker information
        if 'salad_features' in enriched:
            combined['speakers'] = {
                'count': len(enriched['salad_features'].get('speakers', [])),
                'has_diarization': enriched['salad_features'].get('has_diarization', False),
                'speakers': enriched['salad_features'].get('speakers', [])
            }

        return combined

    def _calculate_quality_scores(self, enriched: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate quality scores from enriched data

        Args:
            enriched: Enriched transcript data

        Returns:
            Quality scores
        """
        scores = {
            'transcription_quality': 0,
            'sentiment_quality': 0,
            'compliance_score': 0,
            'resolution_score': 0,
            'overall_quality': 0
        }

        # Transcription quality from Salad
        if 'salad_features' in enriched:
            avg_confidence = enriched['salad_features'].get('average_confidence', 0)
            scores['transcription_quality'] = avg_confidence

        # Sentiment quality
        if 'llm_enrichment' in enriched and 'sentiment' in enriched['llm_enrichment']:
            sentiment = enriched['llm_enrichment']['sentiment']
            customer_score = sentiment.get('customer_score', 50) / 100
            agent_score = sentiment.get('agent_score', 50) / 100
            scores['sentiment_quality'] = (customer_score + agent_score) / 2

        # Compliance score
        if 'llm_enrichment' in enriched and 'compliance' in enriched['llm_enrichment']:
            compliance = enriched['llm_enrichment']['compliance']
            scores['compliance_score'] = compliance.get('professionalism_score', 75) / 100

        # Resolution score
        if 'llm_enrichment' in enriched and 'summary' in enriched['llm_enrichment']:
            outcome = enriched['llm_enrichment']['summary'].get('outcome', '')
            if 'resolved' in outcome.lower():
                scores['resolution_score'] = 1.0
            elif 'partial' in outcome.lower():
                scores['resolution_score'] = 0.5
            else:
                scores['resolution_score'] = 0.0

        # Overall quality
        scores['overall_quality'] = (
            scores['transcription_quality'] * 0.3 +
            scores['sentiment_quality'] * 0.3 +
            scores['compliance_score'] * 0.2 +
            scores['resolution_score'] * 0.2
        )

        return scores

    def _generate_alerts(self, enriched: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Generate alerts based on enriched data

        Args:
            enriched: Enriched transcript data

        Returns:
            List of alerts
        """
        alerts = []

        # Check sentiment
        if 'llm_enrichment' in enriched and 'sentiment' in enriched['llm_enrichment']:
            sentiment = enriched['llm_enrichment']['sentiment']
            if sentiment.get('overall_sentiment') in ['very_negative', 'negative']:
                alerts.append({
                    'type': 'negative_sentiment',
                    'severity': 'high',
                    'message': f"Negative sentiment detected: {sentiment.get('overall_sentiment')}",
                    'details': sentiment
                })

        # Check urgency
        if 'llm_enrichment' in enriched and 'urgency' in enriched['llm_enrichment']:
            urgency = enriched['llm_enrichment']['urgency']
            if urgency.get('level') == 'high':
                alerts.append({
                    'type': 'high_urgency',
                    'severity': 'high',
                    'message': f"High urgency call: {', '.join(urgency.get('factors', []))}",
                    'details': urgency
                })

        # Check compliance
        if 'llm_enrichment' in enriched and 'compliance' in enriched['llm_enrichment']:
            compliance = enriched['llm_enrichment']['compliance']
            if compliance.get('professionalism_score', 100) < 60:
                alerts.append({
                    'type': 'compliance_issue',
                    'severity': 'medium',
                    'message': f"Low professionalism score: {compliance.get('professionalism_score')}",
                    'details': compliance
                })

        # Check for risks
        if 'llm_enrichment' in enriched and 'insights' in enriched['llm_enrichment']:
            risks = enriched['llm_enrichment']['insights'].get('risks', {})
            if risks:
                alerts.append({
                    'type': 'risk_detected',
                    'severity': 'high',
                    'message': 'Risk indicators detected',
                    'details': risks
                })

        return alerts

    def _save_enriched_data(self, enriched: Dict[str, Any], recording_id: str):
        """
        Save enriched metadata to files

        Args:
            enriched: Enriched data
            recording_id: Recording ID for filename
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Save complete enriched data
        complete_path = self.enrichment_dir / 'complete' / f"{recording_id}_{timestamp}_enriched.json"
        with open(complete_path, 'w') as f:
            json.dump(enriched, f, indent=2, default=str)

        # Save summary separately
        if 'combined_insights' in enriched and 'summary' in enriched['combined_insights']:
            summary_path = self.enrichment_dir / 'summaries' / f"{recording_id}_summary.json"
            with open(summary_path, 'w') as f:
                json.dump(enriched['combined_insights']['summary'], f, indent=2)

        # Save sentiment separately
        if 'combined_insights' in enriched and 'sentiment' in enriched['combined_insights']:
            sentiment_path = self.enrichment_dir / 'sentiment' / f"{recording_id}_sentiment.json"
            with open(sentiment_path, 'w') as f:
                json.dump(enriched['combined_insights']['sentiment'], f, indent=2)

        # Save insights separately
        if 'llm_enrichment' in enriched and 'insights' in enriched['llm_enrichment']:
            insights_path = self.enrichment_dir / 'insights' / f"{recording_id}_insights.json"
            with open(insights_path, 'w') as f:
                json.dump(enriched['llm_enrichment']['insights'], f, indent=2)

        logger.info(f"Enriched data saved for recording {recording_id}")