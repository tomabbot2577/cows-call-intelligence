"""
N8N Integration Module
Provides webhook endpoints and data formatting for N8N workflows
"""

import os
import json
import requests
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class N8NWebhookPayload:
    """Standard webhook payload for N8N workflows"""
    event_type: str
    timestamp: str
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    callback_url: Optional[str] = None
    workflow_id: Optional[str] = None
    priority: str = 'normal'


class N8NIntegration:
    """
    N8N workflow integration for transcript processing
    """

    def __init__(
        self,
        webhook_base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        queue_directory: str = "/var/www/call-recording-system/data/structured/n8n_workflows"
    ):
        """
        Initialize N8N integration

        Args:
            webhook_base_url: N8N webhook base URL
            api_key: Optional API key for webhook authentication
            queue_directory: Directory for queued items
        """
        self.webhook_base_url = webhook_base_url or os.getenv('N8N_WEBHOOK_BASE_URL')
        self.api_key = api_key or os.getenv('N8N_API_KEY')
        self.queue_dir = Path(queue_directory)

        # Webhook endpoints for different workflows
        self.webhook_endpoints = {
            'new_transcript': '/webhook/transcript/new',
            'sentiment_analysis': '/webhook/analysis/sentiment',
            'entity_extraction': '/webhook/analysis/entities',
            'summarization': '/webhook/analysis/summary',
            'customer_insights': '/webhook/insights/customer',
            'alert_trigger': '/webhook/alerts/trigger',
            'batch_process': '/webhook/batch/process'
        }

        # Ensure queue directories exist
        self._initialize_directories()

    def _initialize_directories(self):
        """Create necessary directories"""
        directories = [
            self.queue_dir / 'queue',
            self.queue_dir / 'processing',
            self.queue_dir / 'processed',
            self.queue_dir / 'failed',
            self.queue_dir / 'webhooks',
            self.queue_dir / 'templates'
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def process_transcript_for_n8n(
        self,
        transcript_data: Dict[str, Any],
        workflow_type: str = 'new_transcript'
    ) -> Dict[str, Any]:
        """
        Process transcript data for N8N workflows

        Args:
            transcript_data: Structured transcript data
            workflow_type: Type of workflow to trigger

        Returns:
            Processing result
        """
        try:
            # Prepare N8N-optimized payload
            n8n_payload = self._create_n8n_payload(transcript_data, workflow_type)

            # Queue for processing
            queue_result = self._queue_payload(n8n_payload)

            # Trigger webhook if configured
            webhook_result = None
            if self.webhook_base_url:
                webhook_result = self._trigger_webhook(n8n_payload, workflow_type)

            return {
                'success': True,
                'queued': queue_result['success'],
                'queue_id': queue_result.get('queue_id'),
                'webhook_triggered': webhook_result is not None,
                'webhook_response': webhook_result
            }

        except Exception as e:
            logger.error(f"Error processing transcript for N8N: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _create_n8n_payload(
        self,
        transcript_data: Dict[str, Any],
        workflow_type: str
    ) -> Dict[str, Any]:
        """
        Create N8N-optimized payload

        N8N Best Practices:
        1. Flat structure for easy field mapping
        2. Clear, descriptive field names
        3. Include workflow hints and metadata
        4. Webhook-friendly format
        """
        # Extract key information
        call_info = transcript_data.get('call_info', {})
        content = transcript_data.get('content', {})
        features = transcript_data.get('features', {})
        temporal = transcript_data.get('temporal', {})

        # Create flat, N8N-friendly structure
        payload = {
            # Identification
            'transcript_id': transcript_data.get('id'),
            'recording_id': call_info.get('recording_id'),

            # Timestamps
            'call_timestamp': call_info.get('start_time'),
            'processing_timestamp': datetime.utcnow().isoformat(),

            # Call details (flat structure)
            'from_number': call_info.get('participants', {}).get('from', {}).get('number'),
            'from_name': call_info.get('participants', {}).get('from', {}).get('name'),
            'to_number': call_info.get('participants', {}).get('to', {}).get('number'),
            'to_name': call_info.get('participants', {}).get('to', {}).get('name'),
            'call_direction': call_info.get('direction'),
            'duration_seconds': call_info.get('duration_seconds'),

            # Content
            'transcript_text': content.get('text'),
            'word_count': features.get('metrics', {}).get('word_count'),
            'confidence_score': transcript_data.get('language_info', {}).get('transcription_confidence'),
            'language': transcript_data.get('language_info', {}).get('language'),

            # Temporal features (useful for routing)
            'year': temporal.get('year'),
            'month': temporal.get('month'),
            'day': temporal.get('day'),
            'hour': temporal.get('hour'),
            'day_of_week': temporal.get('day_of_week'),
            'is_business_hours': temporal.get('is_business_hours'),

            # Extracted entities (for workflow routing)
            'has_phone_numbers': len(features.get('entities', {}).get('phone_numbers', [])) > 0,
            'has_emails': len(features.get('entities', {}).get('emails', [])) > 0,
            'has_amounts': len(features.get('entities', {}).get('amounts', [])) > 0,
            'phone_numbers_found': features.get('entities', {}).get('phone_numbers', []),
            'emails_found': features.get('entities', {}).get('emails', []),
            'amounts_found': features.get('entities', {}).get('amounts', []),

            # Keywords for routing
            'keywords': features.get('keywords', []),

            # Workflow metadata
            'workflow_type': workflow_type,
            'workflow_hints': transcript_data.get('n8n_hints', {}),
            'priority': transcript_data.get('n8n_hints', {}).get('priority', 'normal'),

            # Segments (for detailed analysis)
            'segments': content.get('segments', [])[:10],  # Limit to first 10 for webhook

            # Callback information
            'callback_url': f"/api/n8n/callback/{transcript_data.get('id')}",
            'webhook_source': 'call_recording_system'
        }

        return payload

    def _queue_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Queue payload for N8N processing

        Args:
            payload: N8N payload

        Returns:
            Queue result
        """
        try:
            queue_id = f"{payload['transcript_id']}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            queue_file = self.queue_dir / 'queue' / f"{queue_id}.json"

            # Add queue metadata
            queued_payload = {
                **payload,
                'queue_metadata': {
                    'queue_id': queue_id,
                    'queued_at': datetime.utcnow().isoformat(),
                    'status': 'queued',
                    'attempts': 0
                }
            }

            # Save to queue
            with open(queue_file, 'w') as f:
                json.dump(queued_payload, f, indent=2, default=str)

            logger.info(f"Payload queued for N8N: {queue_id}")

            return {
                'success': True,
                'queue_id': queue_id,
                'queue_file': str(queue_file)
            }

        except Exception as e:
            logger.error(f"Failed to queue payload: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _trigger_webhook(
        self,
        payload: Dict[str, Any],
        workflow_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Trigger N8N webhook

        Args:
            payload: Webhook payload
            workflow_type: Type of workflow

        Returns:
            Webhook response or None
        """
        if not self.webhook_base_url:
            return None

        try:
            # Get endpoint for workflow type
            endpoint = self.webhook_endpoints.get(workflow_type, '/webhook/default')
            webhook_url = f"{self.webhook_base_url}{endpoint}"

            # Prepare headers
            headers = {
                'Content-Type': 'application/json'
            }

            if self.api_key:
                headers['Authorization'] = f"Bearer {self.api_key}"

            # Send webhook
            response = requests.post(
                webhook_url,
                json=payload,
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                logger.info(f"Webhook triggered successfully: {workflow_type}")
                return {
                    'status': 'success',
                    'response': response.json() if response.text else None
                }
            else:
                logger.warning(f"Webhook returned status {response.status_code}")
                return {
                    'status': 'error',
                    'status_code': response.status_code,
                    'response': response.text
                }

        except requests.exceptions.RequestException as e:
            logger.error(f"Webhook request failed: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }

    def create_batch_workflow(
        self,
        transcript_ids: List[str],
        workflow_type: str = 'batch_analysis'
    ) -> Dict[str, Any]:
        """
        Create batch workflow for multiple transcripts

        Args:
            transcript_ids: List of transcript IDs
            workflow_type: Type of batch workflow

        Returns:
            Batch workflow result
        """
        batch_id = f"batch_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        batch_payload = {
            'batch_id': batch_id,
            'workflow_type': workflow_type,
            'transcript_ids': transcript_ids,
            'total_count': len(transcript_ids),
            'created_at': datetime.utcnow().isoformat(),
            'status': 'pending',
            'webhook_url': f"{self.webhook_base_url}/webhook/batch/status/{batch_id}"
        }

        # Save batch configuration
        batch_file = self.queue_dir / 'queue' / f"{batch_id}.json"
        with open(batch_file, 'w') as f:
            json.dump(batch_payload, f, indent=2)

        # Trigger batch webhook
        if self.webhook_base_url:
            self._trigger_webhook(batch_payload, 'batch_process')

        return {
            'success': True,
            'batch_id': batch_id,
            'transcript_count': len(transcript_ids)
        }

    def get_queue_status(self) -> Dict[str, Any]:
        """
        Get current queue status

        Returns:
            Queue status information
        """
        queue_path = self.queue_dir / 'queue'
        processing_path = self.queue_dir / 'processing'
        processed_path = self.queue_dir / 'processed'
        failed_path = self.queue_dir / 'failed'

        return {
            'queued': len(list(queue_path.glob('*.json'))),
            'processing': len(list(processing_path.glob('*.json'))),
            'processed': len(list(processed_path.glob('*.json'))),
            'failed': len(list(failed_path.glob('*.json'))),
            'timestamp': datetime.utcnow().isoformat()
        }

    def process_callback(
        self,
        transcript_id: str,
        workflow_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process callback from N8N workflow

        Args:
            transcript_id: Transcript ID
            workflow_result: Result from N8N workflow

        Returns:
            Processing result
        """
        try:
            # Move from processing to processed
            processing_file = self.queue_dir / 'processing' / f"{transcript_id}.json"
            processed_file = self.queue_dir / 'processed' / f"{transcript_id}.json"

            if processing_file.exists():
                # Load original data
                with open(processing_file, 'r') as f:
                    original_data = json.load(f)

                # Add workflow result
                processed_data = {
                    **original_data,
                    'workflow_result': workflow_result,
                    'processed_at': datetime.utcnow().isoformat(),
                    'status': 'completed'
                }

                # Save to processed
                with open(processed_file, 'w') as f:
                    json.dump(processed_data, f, indent=2)

                # Remove from processing
                processing_file.unlink()

                logger.info(f"Processed callback for {transcript_id}")

                return {
                    'success': True,
                    'transcript_id': transcript_id,
                    'status': 'completed'
                }

            else:
                logger.warning(f"Processing file not found for {transcript_id}")
                return {
                    'success': False,
                    'error': 'Processing file not found'
                }

        except Exception as e:
            logger.error(f"Error processing callback: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def retry_failed_items(self) -> Dict[str, Any]:
        """
        Retry failed queue items

        Returns:
            Retry result
        """
        failed_path = self.queue_dir / 'failed'
        queue_path = self.queue_dir / 'queue'

        failed_files = list(failed_path.glob('*.json'))
        retry_count = 0

        for failed_file in failed_files:
            try:
                # Move back to queue
                new_path = queue_path / failed_file.name
                failed_file.rename(new_path)
                retry_count += 1

            except Exception as e:
                logger.error(f"Failed to retry {failed_file}: {e}")

        return {
            'success': True,
            'retried_count': retry_count,
            'remaining_failed': len(list(failed_path.glob('*.json')))
        }