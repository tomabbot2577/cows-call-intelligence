"""
Salad Cloud Transcription Service
Transcription implementation using Salad Cloud API
"""

import os
import time
import logging
import json
import tempfile
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime

from salad_cloud_transcription_sdk import SaladCloudTranscriptionSdk
from salad_cloud_transcription_sdk.models.transcription_request import TranscriptionRequest
from salad_cloud_transcription_sdk.models.transcription_job_input import TranscriptionJobInput
from salad_cloud_transcription_sdk.models.transcription_engine import TranscriptionEngine
from salad_cloud_sdk.models.inference_endpoint_job import InferenceEndpointJob

logger = logging.getLogger(__name__)


class TranscriptionResult:
    """
    Container for transcription results (compatible with existing interface)
    """

    def __init__(
        self,
        text: str,
        language: str,
        language_probability: float,
        segments: List[Dict],
        word_count: int,
        confidence: float,
        duration_seconds: float,
        processing_time_seconds: float
    ):
        self.text = text
        self.language = language
        self.language_probability = language_probability
        self.segments = segments
        self.word_count = word_count
        self.confidence = confidence
        self.duration_seconds = duration_seconds
        self.processing_time_seconds = processing_time_seconds

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'text': self.text,
            'language': self.language,
            'language_probability': self.language_probability,
            'segments': self.segments,
            'word_count': self.word_count,
            'confidence': self.confidence,
            'duration_seconds': self.duration_seconds,
            'processing_time_seconds': self.processing_time_seconds
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


class SaladTranscriber:
    """
    Transcription pipeline using Salad Cloud API
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        organization_name: Optional[str] = None,
        engine: str = 'full',
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        webhook_url: Optional[str] = None,
        polling_interval: int = 5,
        max_wait_time: int = 3600
    ):
        """
        Initialize Salad Cloud transcriber

        Args:
            api_key: Salad Cloud API key
            organization_name: Organization name for billing
            engine: Transcription engine ('full' or 'fast')
            language: Target language code (optional)
            initial_prompt: Initial prompt for better context
            webhook_url: Optional webhook for completion notification
            polling_interval: Seconds between status checks
            max_wait_time: Maximum time to wait for completion (seconds)
        """
        # Get API key from environment or parameter
        self.api_key = api_key or os.environ.get('SALAD_API_KEY')
        if not self.api_key:
            raise ValueError("Salad Cloud API key is required")

        # Get organization name
        self.organization_name = organization_name or os.environ.get('SALAD_ORG_NAME', 'default')

        # Initialize SDK
        self.sdk = SaladCloudTranscriptionSdk(api_key=self.api_key)

        # Transcription settings
        self.engine = TranscriptionEngine.Full if engine == 'full' else TranscriptionEngine.Fast
        self.language = language
        self.initial_prompt = initial_prompt
        self.webhook_url = webhook_url

        # Polling settings
        self.polling_interval = polling_interval
        self.max_wait_time = max_wait_time

        # Statistics
        self.total_transcriptions = 0
        self.total_audio_duration = 0
        self.total_processing_time = 0

        logger.info(f"SaladTranscriber initialized with engine: {engine}")

    def transcribe_file(
        self,
        audio_path: str,
        output_path: Optional[str] = None,
        save_segments: bool = True
    ) -> TranscriptionResult:
        """
        Transcribe audio file using Salad Cloud API

        Args:
            audio_path: Path to audio file
            output_path: Optional path to save transcript
            save_segments: Whether to include segment data

        Returns:
            TranscriptionResult object

        Raises:
            ValueError: If audio file doesn't exist
            RuntimeError: If transcription fails
        """
        start_time = time.time()

        # Validate file exists
        if not Path(audio_path).exists():
            raise ValueError(f"Audio file not found: {audio_path}")

        logger.info(f"Starting transcription of {audio_path}")

        try:
            # Create transcription request with required parameters
            job_input = TranscriptionJobInput(
                return_as_file=False,  # We want JSON response, not file
                language_code=self.language or 'en',  # Default to English
                word_level_timestamps=save_segments,
                custom_prompt=self.initial_prompt or ''
            )

            request = TranscriptionRequest(
                options=job_input,
                webhook=self.webhook_url,
                metadata={
                    'file_name': Path(audio_path).name,
                    'timestamp': datetime.utcnow().isoformat()
                }
            )

            # Submit transcription job
            logger.info("Submitting transcription job to Salad Cloud")
            job = self.sdk.transcribe(
                source=audio_path,
                organization_name=self.organization_name,
                request=request,
                engine=self.engine,
                auto_poll=False  # We'll poll manually for better control
            )

            job_id = job.id
            logger.info(f"Transcription job created: {job_id}")

            # Poll for completion
            result_data = self._wait_for_completion(job_id)

            # Process the result
            transcription_result = self._process_result(result_data, start_time)

            # Save if output path provided
            if output_path:
                self._save_transcript(transcription_result, output_path)

            # Update statistics
            self.total_transcriptions += 1
            self.total_processing_time += transcription_result.processing_time_seconds

            logger.info(
                f"Transcription completed: {transcription_result.word_count} words, "
                f"{transcription_result.processing_time_seconds:.1f}s processing"
            )

            return transcription_result

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise RuntimeError(f"Transcription failed: {e}")

    def _wait_for_completion(self, job_id: str) -> Dict[str, Any]:
        """
        Poll for job completion

        Args:
            job_id: Transcription job ID

        Returns:
            Transcription result data

        Raises:
            RuntimeError: If job fails or times out
        """
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > self.max_wait_time:
                raise RuntimeError(f"Transcription timed out after {self.max_wait_time}s")

            # Get job status
            job = self.sdk.get_transcription_job(
                organization_name=self.organization_name,
                job_id=job_id
            )

            status = job.status
            logger.debug(f"Job {job_id} status: {status}")

            if status == 'succeeded':
                # Job completed successfully
                if hasattr(job, 'output') and job.output:
                    return json.loads(job.output) if isinstance(job.output, str) else job.output
                else:
                    raise RuntimeError("Job succeeded but no output available")

            elif status == 'failed':
                error_msg = getattr(job, 'error', 'Unknown error')
                raise RuntimeError(f"Transcription job failed: {error_msg}")

            elif status == 'cancelled':
                raise RuntimeError("Transcription job was cancelled")

            # Still pending/running, wait and retry
            time.sleep(self.polling_interval)

    def _process_result(
        self,
        result_data: Dict[str, Any],
        start_time: float
    ) -> TranscriptionResult:
        """
        Process Salad Cloud result into TranscriptionResult

        Args:
            result_data: Raw result from Salad Cloud
            start_time: Processing start timestamp

        Returns:
            TranscriptionResult object
        """
        processing_time = time.time() - start_time

        # Extract transcription data
        text = result_data.get('text', '')
        language = result_data.get('language', 'unknown')
        segments = result_data.get('segments', [])

        # Calculate metrics
        word_count = len(text.split())

        # Calculate confidence from segments if available
        confidence = self._calculate_confidence(segments)

        # Estimate duration from segments
        duration = 0
        if segments:
            last_segment = segments[-1]
            duration = last_segment.get('end', 0)

        # Language probability (Salad may not provide this)
        language_probability = result_data.get('language_probability', 1.0)

        return TranscriptionResult(
            text=text,
            language=language,
            language_probability=language_probability,
            segments=segments,
            word_count=word_count,
            confidence=confidence,
            duration_seconds=duration,
            processing_time_seconds=processing_time
        )

    def _calculate_confidence(self, segments: List[Dict]) -> float:
        """
        Calculate overall confidence from segments

        Args:
            segments: List of segment dictionaries

        Returns:
            Confidence score (0.0 to 1.0)
        """
        if not segments:
            return 0.0

        total_confidence = 0
        count = 0

        for segment in segments:
            # Salad might provide confidence/probability per segment
            seg_confidence = segment.get('confidence', segment.get('probability', 0.95))
            total_confidence += seg_confidence
            count += 1

        return total_confidence / count if count > 0 else 0.0

    def _save_transcript(
        self,
        result: TranscriptionResult,
        output_path: str
    ):
        """
        Save transcript to file

        Args:
            result: Transcription result
            output_path: Output file path
        """
        ext = Path(output_path).suffix.lower()

        if ext == '.json':
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(result.to_json())

        elif ext == '.txt':
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(result.text)

        elif ext == '.srt':
            self._save_as_srt(result, output_path)

        else:
            # Default to text
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(result.text)

        logger.info(f"Transcript saved to {output_path}")

    def _save_as_srt(self, result: TranscriptionResult, output_path: str):
        """
        Save transcript as SRT subtitle file

        Args:
            result: Transcription result
            output_path: Output file path
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, segment in enumerate(result.segments, 1):
                # Write subtitle number
                f.write(f"{i}\n")

                # Write timestamp
                start_time = self._seconds_to_srt_time(segment.get('start', 0))
                end_time = self._seconds_to_srt_time(segment.get('end', 0))
                f.write(f"{start_time} --> {end_time}\n")

                # Write text
                text = segment.get('text', '').strip()
                f.write(f"{text}\n\n")

    def _seconds_to_srt_time(self, seconds: float) -> str:
        """
        Convert seconds to SRT timestamp format

        Args:
            seconds: Time in seconds

        Returns:
            SRT timestamp string
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)

        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get transcription statistics

        Returns:
            Dictionary with statistics
        """
        avg_speed = 0
        if self.total_audio_duration > 0:
            avg_speed = self.total_processing_time / self.total_audio_duration

        return {
            'total_transcriptions': self.total_transcriptions,
            'total_audio_duration_seconds': self.total_audio_duration,
            'total_processing_time_seconds': self.total_processing_time,
            'average_speed_ratio': avg_speed,
            'engine': self.engine.value,
            'organization': self.organization_name
        }

    def cancel_job(self, job_id: str) -> None:
        """
        Cancel a running transcription job

        Args:
            job_id: Job ID to cancel
        """
        try:
            self.sdk.delete_transcription_job(
                organization_name=self.organization_name,
                job_id=job_id
            )
            logger.info(f"Cancelled job: {job_id}")
        except Exception as e:
            logger.error(f"Failed to cancel job {job_id}: {e}")

    def list_jobs(self, page: int = 1, page_size: int = 10) -> List[Dict]:
        """
        List recent transcription jobs

        Args:
            page: Page number
            page_size: Items per page

        Returns:
            List of job dictionaries
        """
        try:
            collection = self.sdk.list_transcription_jobs(
                organization_name=self.organization_name,
                page=page,
                page_size=page_size
            )

            jobs = []
            for job in collection.items:
                jobs.append({
                    'id': job.id,
                    'status': job.status,
                    'created': job.created_at,
                    'metadata': getattr(job, 'metadata', {})
                })

            return jobs

        except Exception as e:
            logger.error(f"Failed to list jobs: {e}")
            return []