"""
Base Video Meeting Processor

Orchestrates the 6-layer AI processing pipeline for video meetings.
"""

import os
import json
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from openai import OpenAI

logger = logging.getLogger(__name__)


class VideoMeetingProcessor:
    """
    Orchestrates 6-layer AI processing for video meetings.

    Layers:
    1. Entity Extraction
    2. Sentiment & Customer Health
    3. Resolution & Outcomes
    4. Recommendations
    5. Advanced Metrics
    6. Learning Intelligence
    """

    def __init__(self, database_url: str = None, api_key: str = None):
        """
        Initialize the processor.

        Args:
            database_url: PostgreSQL connection URL
            api_key: OpenRouter API key
        """
        self.database_url = database_url or os.getenv('RAG_DATABASE_URL')
        if not self.database_url:
            raise ValueError("Database URL is required")

        self.api_key = api_key or os.getenv('OPENROUTER_API_KEY')
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is required")

        # Initialize OpenRouter client
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key
        )

        # Default model for analysis
        self.model = "google/gemini-2.0-flash-001"

        logger.info("VideoMeetingProcessor initialized")

    def _get_connection(self):
        """Get database connection."""
        return psycopg2.connect(self.database_url)

    def _safe_json_parse(self, response_content: str, fallback: dict = None) -> dict:
        """Safely parse JSON from LLM response."""
        if fallback is None:
            fallback = {}

        try:
            content = response_content.strip()

            # Remove markdown code blocks
            if '```' in content:
                import re
                match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
                if match:
                    content = match.group(1)

            return json.loads(content)

        except json.JSONDecodeError:
            try:
                import re
                match = re.search(r'\{[\s\S]*\}', response_content)
                if match:
                    return json.loads(match.group())
            except:
                pass

            logger.warning(f"JSON parse failed: {response_content[:100]}...")
            return fallback

    def _call_llm(self, prompt: str, system_prompt: str = None,
                  max_tokens: int = 2000, temperature: float = 0.3) -> str:
        """
        Call the LLM with a prompt.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            max_tokens: Max tokens in response
            temperature: Sampling temperature

        Returns:
            Response text
        """
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

    def get_pending_meetings(self, layer: int = 1, limit: int = 10) -> List[Dict]:
        """
        Get meetings pending processing for a specific layer.

        Args:
            layer: Layer number (1-6)
            limit: Maximum meetings to return

        Returns:
            List of meeting dicts
        """
        layer_field = f"layer{layer}_complete"
        prev_layer_field = f"layer{layer-1}_complete" if layer > 1 else None

        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if layer == 1:
                    # Layer 1: needs transcript, not processed yet
                    cur.execute(f"""
                        SELECT id, recording_id, source, title, transcript_text,
                               fathom_summary, participants_json, action_items_json,
                               meeting_type, platform, host_name
                        FROM video_meetings
                        WHERE transcript_text IS NOT NULL
                          AND {layer_field} = FALSE
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (limit,))
                else:
                    # Layers 2-6: previous layer complete
                    cur.execute(f"""
                        SELECT id, recording_id, source, title, transcript_text,
                               fathom_summary, participants_json, action_items_json,
                               meeting_type, platform, host_name
                        FROM video_meetings
                        WHERE {prev_layer_field} = TRUE
                          AND {layer_field} = FALSE
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (limit,))

                return [dict(row) for row in cur.fetchall()]

        finally:
            conn.close()

    def update_layer_status(self, meeting_id: int, layer: int,
                            success: bool = True):
        """
        Update the layer completion status for a meeting.

        Args:
            meeting_id: Meeting ID
            layer: Layer number (1-6)
            success: Whether layer completed successfully
        """
        layer_field = f"layer{layer}_complete"

        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE video_meetings
                    SET {layer_field} = %s,
                        updated_at = NOW()
                    WHERE id = %s
                """, (success, meeting_id))
                conn.commit()

        finally:
            conn.close()

    def save_layer_results(self, meeting_id: int, layer: int, results: Dict):
        """
        Save layer results to appropriate table.

        Args:
            meeting_id: Meeting ID
            layer: Layer number
            results: Layer analysis results
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                if layer == 1:
                    # Entity extraction - update main meeting record
                    cur.execute("""
                        UPDATE video_meetings
                        SET meeting_type = COALESCE(%s, meeting_type),
                            crm_matches_json = %s
                        WHERE id = %s
                    """, (
                        results.get('meeting_type'),
                        json.dumps(results.get('crm_matches', {})),
                        meeting_id
                    ))

                elif layer == 2:
                    # Sentiment - save to insights table
                    cur.execute("""
                        INSERT INTO video_meeting_insights (
                            meeting_id, nps_score, nps_confidence,
                            churn_risk_level, churn_risk_score,
                            customer_health_score, expansion_signals,
                            sentiment_positive, sentiment_negative, sentiment_neutral,
                            meeting_quality_score, topic_json
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (meeting_id) DO UPDATE SET
                            nps_score = EXCLUDED.nps_score,
                            churn_risk_level = EXCLUDED.churn_risk_level,
                            customer_health_score = EXCLUDED.customer_health_score,
                            updated_at = NOW()
                    """, (
                        meeting_id,
                        results.get('nps_score'),
                        results.get('nps_confidence'),
                        results.get('churn_risk_level'),
                        results.get('churn_risk_score'),
                        results.get('customer_health_score'),
                        json.dumps(results.get('expansion_signals', [])),
                        results.get('sentiment_positive', 0),
                        results.get('sentiment_negative', 0),
                        results.get('sentiment_neutral', 0),
                        results.get('meeting_quality_score'),
                        json.dumps(results.get('topics', []))
                    ))

                elif layer == 3:
                    # Resolution - save to resolutions table
                    cur.execute("""
                        INSERT INTO video_meeting_resolutions (
                            meeting_id, objectives_met_score, objectives_met_details,
                            fcr_achieved, escalation_required, loop_closure_score,
                            action_item_quality_score, decisions_made_json,
                            unresolved_issues_json
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (meeting_id) DO UPDATE SET
                            objectives_met_score = EXCLUDED.objectives_met_score,
                            fcr_achieved = EXCLUDED.fcr_achieved,
                            updated_at = NOW()
                    """, (
                        meeting_id,
                        results.get('objectives_met_score'),
                        results.get('objectives_met_details'),
                        results.get('fcr_achieved'),
                        results.get('escalation_required'),
                        results.get('loop_closure_score'),
                        results.get('action_item_quality_score'),
                        json.dumps(results.get('decisions_made', [])),
                        json.dumps(results.get('unresolved_issues', []))
                    ))

                elif layer == 4:
                    # Recommendations - save to recommendations table
                    cur.execute("""
                        INSERT INTO video_meeting_recommendations (
                            meeting_id, host_coaching_json, sales_recommendations_json,
                            customer_success_actions_json, process_improvements_json,
                            follow_up_priority, follow_up_deadline
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (meeting_id) DO UPDATE SET
                            host_coaching_json = EXCLUDED.host_coaching_json,
                            sales_recommendations_json = EXCLUDED.sales_recommendations_json,
                            updated_at = NOW()
                    """, (
                        meeting_id,
                        json.dumps(results.get('host_coaching', [])),
                        json.dumps(results.get('sales_recommendations', [])),
                        json.dumps(results.get('customer_success_actions', [])),
                        json.dumps(results.get('process_improvements', [])),
                        results.get('follow_up_priority'),
                        results.get('follow_up_deadline')
                    ))

                elif layer == 5:
                    # Advanced metrics
                    cur.execute("""
                        INSERT INTO video_meeting_advanced_metrics (
                            meeting_id, speaking_time_distribution,
                            hormozi_blueprint_score, hormozi_components_json,
                            competitive_mentions_json, deal_value_mentioned,
                            contract_length_mentioned, financial_indicators_json
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (meeting_id) DO UPDATE SET
                            speaking_time_distribution = EXCLUDED.speaking_time_distribution,
                            hormozi_blueprint_score = EXCLUDED.hormozi_blueprint_score,
                            updated_at = NOW()
                    """, (
                        meeting_id,
                        json.dumps(results.get('speaking_time', {})),
                        results.get('hormozi_score'),
                        json.dumps(results.get('hormozi_components', {})),
                        json.dumps(results.get('competitive_mentions', [])),
                        results.get('deal_value'),
                        results.get('contract_length'),
                        json.dumps(results.get('financial_indicators', {}))
                    ))

                elif layer == 6:
                    # Learning intelligence (UTL)
                    cur.execute("""
                        INSERT INTO video_meeting_learning_analysis (
                            meeting_id, learning_score, entropy_delta,
                            coherence_delta, emotional_engagement,
                            phase_alignment, learning_state,
                            knowledge_transfer_rate, host_teaching_effectiveness,
                            lambda_adjustments_json, coaching_recommendations_json
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (meeting_id) DO UPDATE SET
                            learning_score = EXCLUDED.learning_score,
                            learning_state = EXCLUDED.learning_state,
                            updated_at = NOW()
                    """, (
                        meeting_id,
                        results.get('learning_score'),
                        results.get('entropy_delta'),
                        results.get('coherence_delta'),
                        results.get('emotional_engagement'),
                        results.get('phase_alignment'),
                        results.get('learning_state'),
                        results.get('knowledge_transfer_rate'),
                        results.get('host_teaching_effectiveness'),
                        json.dumps(results.get('lambda_adjustments', {})),
                        json.dumps(results.get('coaching_recommendations', []))
                    ))

                conn.commit()

        finally:
            conn.close()

    def process_meeting(self, meeting: Dict) -> Dict:
        """
        Process a single meeting through all 6 layers.

        Args:
            meeting: Meeting dict from database

        Returns:
            Combined results from all layers
        """
        from .layer1_entities import EntityExtractor
        from .layer2_sentiment import SentimentAnalyzer
        from .layer3_resolution import ResolutionTracker
        from .layer4_recommendations import RecommendationEngine
        from .layer5_advanced import AdvancedMetrics
        from .layer6_learning import LearningAnalyzer

        meeting_id = meeting['id']
        transcript = meeting.get('transcript_text', '')

        if not transcript:
            logger.warning(f"Meeting {meeting_id} has no transcript")
            return {}

        results = {'meeting_id': meeting_id}

        try:
            # Layer 1: Entity Extraction
            logger.info(f"Processing Layer 1 for meeting {meeting_id}")
            layer1 = EntityExtractor(self.client, self.model)
            results['layer1'] = layer1.analyze(meeting)
            self.save_layer_results(meeting_id, 1, results['layer1'])
            self.update_layer_status(meeting_id, 1, True)

            # Layer 2: Sentiment & Customer Health
            logger.info(f"Processing Layer 2 for meeting {meeting_id}")
            layer2 = SentimentAnalyzer(self.client, self.model)
            results['layer2'] = layer2.analyze(meeting, results['layer1'])
            self.save_layer_results(meeting_id, 2, results['layer2'])
            self.update_layer_status(meeting_id, 2, True)

            # Layer 3: Resolution & Outcomes
            logger.info(f"Processing Layer 3 for meeting {meeting_id}")
            layer3 = ResolutionTracker(self.client, self.model)
            results['layer3'] = layer3.analyze(meeting, results['layer1'], results['layer2'])
            self.save_layer_results(meeting_id, 3, results['layer3'])
            self.update_layer_status(meeting_id, 3, True)

            # Layer 4: Recommendations
            logger.info(f"Processing Layer 4 for meeting {meeting_id}")
            layer4 = RecommendationEngine(self.client, self.model)
            results['layer4'] = layer4.analyze(meeting, results)
            self.save_layer_results(meeting_id, 4, results['layer4'])
            self.update_layer_status(meeting_id, 4, True)

            # Layer 5: Advanced Metrics
            logger.info(f"Processing Layer 5 for meeting {meeting_id}")
            layer5 = AdvancedMetrics(self.client, self.model)
            results['layer5'] = layer5.analyze(meeting, results)
            self.save_layer_results(meeting_id, 5, results['layer5'])
            self.update_layer_status(meeting_id, 5, True)

            # Layer 6: Learning Intelligence
            logger.info(f"Processing Layer 6 for meeting {meeting_id}")
            layer6 = LearningAnalyzer(self.client, self.model)
            results['layer6'] = layer6.analyze(meeting, results)
            self.save_layer_results(meeting_id, 6, results['layer6'])
            self.update_layer_status(meeting_id, 6, True)

            logger.info(f"Completed all 6 layers for meeting {meeting_id}")

        except Exception as e:
            logger.error(f"Error processing meeting {meeting_id}: {e}")
            results['error'] = str(e)

        return results

    def process_batch(self, limit: int = 10) -> Dict:
        """
        Process a batch of pending meetings.

        Args:
            limit: Maximum meetings to process

        Returns:
            Batch processing statistics
        """
        stats = {
            'processed': 0,
            'successful': 0,
            'failed': 0,
            'errors': []
        }

        # Get meetings needing Layer 1
        meetings = self.get_pending_meetings(layer=1, limit=limit)
        logger.info(f"Found {len(meetings)} meetings pending processing")

        for meeting in meetings:
            try:
                results = self.process_meeting(meeting)
                stats['processed'] += 1

                if 'error' not in results:
                    stats['successful'] += 1
                else:
                    stats['failed'] += 1
                    stats['errors'].append(results['error'])

            except Exception as e:
                stats['processed'] += 1
                stats['failed'] += 1
                stats['errors'].append(str(e))
                logger.error(f"Batch processing error: {e}")

        return stats
