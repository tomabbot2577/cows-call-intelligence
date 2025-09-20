"""
Salad Cloud Transcription Service - Production Enhanced Version
Best practices implementation with full metadata capture, monitoring, and error handling
"""

import os
import time
import logging
import json
import tempfile
import traceback
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime, timezone
from enum import Enum
import threading
from collections import deque

from salad_cloud_transcription_sdk import SaladCloudTranscriptionSdk
from salad_cloud_transcription_sdk.models.transcription_request import TranscriptionRequest
from salad_cloud_transcription_sdk.models.transcription_job_input import TranscriptionJobInput
from salad_cloud_transcription_sdk.models.transcription_engine import TranscriptionEngine
from salad_cloud_sdk.models.inference_endpoint_job import InferenceEndpointJob

logger = logging.getLogger(__name__)


class TranscriptionStatus(Enum):
    """Transcription job status enum"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TranscriptionMetrics:
    """Metrics collector for monitoring"""

    def __init__(self):
        self.total_jobs = 0
        self.successful_jobs = 0
        self.failed_jobs = 0
        self.timeout_jobs = 0
        self.total_audio_seconds = 0.0
        self.total_processing_seconds = 0.0
        self.total_words_transcribed = 0
        self.api_errors = {}
        self.job_history = deque(maxlen=1000)  # Keep last 1000 jobs
        self.start_time = datetime.now(timezone.utc)
        self._lock = threading.Lock()

    def record_job(self, job_data: Dict[str, Any]):
        """Record job metrics"""
        with self._lock:
            self.total_jobs += 1

            status = job_data.get('status')
            if status == TranscriptionStatus.SUCCEEDED.value:
                self.successful_jobs += 1
                self.total_audio_seconds += job_data.get('audio_duration', 0)
                self.total_words_transcribed += job_data.get('word_count', 0)
            elif status == TranscriptionStatus.FAILED.value:
                self.failed_jobs += 1
                error = job_data.get('error', 'Unknown')
                self.api_errors[error] = self.api_errors.get(error, 0) + 1
            elif status == TranscriptionStatus.TIMEOUT.value:
                self.timeout_jobs += 1

            self.total_processing_seconds += job_data.get('processing_time', 0)
            self.job_history.append(job_data)

    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics"""
        with self._lock:
            uptime = (datetime.now(timezone.utc) - self.start_time).total_seconds()
            success_rate = (self.successful_jobs / self.total_jobs * 100) if self.total_jobs > 0 else 0
            avg_processing_time = (self.total_processing_seconds / self.total_jobs) if self.total_jobs > 0 else 0

            return {
                'uptime_seconds': uptime,
                'total_jobs': self.total_jobs,
                'successful_jobs': self.successful_jobs,
                'failed_jobs': self.failed_jobs,
                'timeout_jobs': self.timeout_jobs,
                'success_rate': round(success_rate, 2),
                'total_audio_hours': round(self.total_audio_seconds / 3600, 2),
                'total_processing_hours': round(self.total_processing_seconds / 3600, 2),
                'total_words_transcribed': self.total_words_transcribed,
                'average_processing_seconds': round(avg_processing_time, 2),
                'api_errors': dict(self.api_errors),
                'recent_jobs': list(self.job_history)[-10:]  # Last 10 jobs
            }


class TranscriptionResult:
    """
    Enhanced container for transcription results with full metadata
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
        processing_time_seconds: float,
        job_id: str,
        metadata: Dict[str, Any],
        timestamps: Dict[str, str],
        error: Optional[str] = None
    ):
        self.text = text
        self.language = language
        self.language_probability = language_probability
        self.segments = segments
        self.word_count = word_count
        self.confidence = confidence
        self.duration_seconds = duration_seconds
        self.processing_time_seconds = processing_time_seconds
        self.job_id = job_id
        self.metadata = metadata
        self.timestamps = timestamps
        self.error = error

    @property
    def processing_time(self) -> float:
        """Alias for processing_time_seconds for backward compatibility"""
        return self.processing_time_seconds

    @property
    def duration(self) -> float:
        """Alias for duration_seconds for backward compatibility"""
        return self.duration_seconds

    def to_dict(self) -> Dict[str, Any]:
        """Convert to comprehensive dictionary with all metadata"""
        return {
            'job_id': self.job_id,
            'text': self.text,
            'language': self.language,
            'language_probability': self.language_probability,
            'segments': self.segments,
            'word_count': self.word_count,
            'confidence': self.confidence,
            'duration_seconds': self.duration_seconds,
            'processing_time_seconds': self.processing_time_seconds,
            'metadata': self.metadata,
            'timestamps': self.timestamps,
            'error': self.error,
            'metrics': {
                'words_per_minute': round((self.word_count / self.duration_seconds * 60) if self.duration_seconds > 0 else 0, 2),
                'processing_speed_ratio': round((self.processing_time_seconds / self.duration_seconds) if self.duration_seconds > 0 else 0, 3)
            }
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string with proper formatting"""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str)


class SaladTranscriberEnhanced:
    """
    Production-ready Salad Cloud transcription with best practices
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        organization_name: Optional[str] = None,
        engine: str = 'full',  # Always use 'full' for best quality
        language: str = 'en-US',  # American English
        initial_prompt: Optional[str] = None,
        webhook_url: Optional[str] = None,
        polling_interval: int = 3,
        max_wait_time: int = 3600,
        max_retries: int = 3,
        retry_delay: int = 5,
        enable_monitoring: bool = True,
        enable_diarization: bool = False,
        enable_summarization: bool = False,
        custom_vocabulary: Optional[str] = None
    ):
        """
        Initialize enhanced Salad Cloud transcriber with best practices

        Args:
            api_key: Salad Cloud API key
            organization_name: Organization name for billing
            engine: Always 'full' for production quality
            language: Language code (en-US for American English)
            initial_prompt: Initial prompt for better context
            webhook_url: Optional webhook for completion notification
            polling_interval: Seconds between status checks
            max_wait_time: Maximum time to wait for completion (seconds)
            max_retries: Number of retry attempts for failed jobs
            retry_delay: Delay between retries (seconds)
            enable_monitoring: Enable metrics collection
            enable_diarization: Enable speaker diarization
            enable_summarization: Enable automatic summarization
            custom_vocabulary: Custom vocabulary for domain-specific terms
        """
        # Get API key from environment or parameter
        self.api_key = api_key or os.environ.get('SALAD_API_KEY')
        if not self.api_key:
            raise ValueError("Salad Cloud API key is required")

        # Get organization name - updated to 'mst'
        self.organization_name = organization_name or os.environ.get('SALAD_ORG_NAME', 'mst')

        # Initialize SDK with timeout and retry settings
        self.sdk = SaladCloudTranscriptionSdk(
            api_key=self.api_key,
            timeout=60000  # 60 second timeout for API calls
        )

        # Transcription settings - enforcing best practices
        self.engine = TranscriptionEngine.Full  # Always use Full for quality
        self.language = language  # en-US for American English
        self.initial_prompt = initial_prompt or "Professional business call transcription. Focus on accuracy and proper punctuation."
        self.webhook_url = webhook_url
        self.custom_vocabulary = custom_vocabulary

        # Enhanced features
        self.enable_diarization = enable_diarization
        self.enable_summarization = enable_summarization

        # Polling and retry settings
        self.polling_interval = polling_interval
        self.max_wait_time = max_wait_time
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Monitoring
        self.enable_monitoring = enable_monitoring
        self.metrics = TranscriptionMetrics() if enable_monitoring else None

        # Job tracking
        self.active_jobs = {}
        self._job_lock = threading.Lock()

        logger.info(
            f"SaladTranscriberEnhanced initialized: "
            f"engine=full, language={language}, "
            f"monitoring={'enabled' if enable_monitoring else 'disabled'}, "
            f"diarization={'enabled' if enable_diarization else 'disabled'}"
        )

    def transcribe_file(
        self,
        audio_url: str,
        output_path: Optional[str] = None,
        save_segments: bool = True,
        custom_metadata: Optional[Dict[str, Any]] = None
    ) -> TranscriptionResult:
        """
        Transcribe audio file with enhanced error handling and monitoring

        Args:
            audio_url: URL to audio file (must be accessible via HTTP/HTTPS)
            output_path: Optional path to save transcript
            save_segments: Whether to include segment data
            custom_metadata: Additional metadata to include

        Returns:
            TranscriptionResult object with full metadata

        Raises:
            ValueError: If URL is invalid
            RuntimeError: If transcription fails after retries
        """
        start_time = time.time()
        timestamps = {
            'started': datetime.now(timezone.utc).isoformat(),
            'submitted': None,
            'completed': None
        }

        # Validate URL
        if not audio_url.startswith(('http://', 'https://')):
            raise ValueError(f"Audio must be accessible via HTTP/HTTPS URL, got: {audio_url}")

        logger.info(f"Starting transcription of {audio_url}")

        # Prepare metadata
        metadata = {
            'source_url': audio_url,
            'engine': 'full',
            'language': self.language,
            'organization': self.organization_name,
            'custom': custom_metadata or {}
        }

        # Retry logic
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"Transcription attempt {attempt}/{self.max_retries}")

                # Create transcription request with best practices
                job_input = TranscriptionJobInput(
                    return_as_file=False,  # Get JSON response for metadata
                    language_code=self.language,  # en-US for American English
                    word_level_timestamps=True,  # Always capture word timestamps
                    sentence_level_timestamps=True,  # Capture sentence timestamps
                    diarization=self.enable_diarization,  # Speaker identification if needed
                    sentence_diarization=self.enable_diarization,
                    srt=True,  # Generate SRT format as well
                    summarize=10 if self.enable_summarization else 0,  # 10 sentence summary
                    custom_vocabulary=self.custom_vocabulary or '',
                    custom_prompt=self.initial_prompt
                )

                request = TranscriptionRequest(
                    options=job_input,
                    webhook=self.webhook_url,
                    metadata={
                        'file_url': audio_url,
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'attempt': attempt,
                        **metadata
                    }
                )

                # Submit transcription job
                logger.info("Submitting transcription job to Salad Cloud")
                timestamps['submitted'] = datetime.now(timezone.utc).isoformat()

                # Use the SDK's transcribe method properly
                from salad_cloud_transcription_sdk.models.transcription_engine import TranscriptionEngine

                # Submit transcription job via SDK wrapper
                job = self.sdk.transcribe(
                    source=audio_url,
                    organization_name=self.organization_name,
                    request=request,
                    engine=TranscriptionEngine.Full,  # Always use 'full' engine
                    auto_poll=False  # Manual polling for better control
                )

                job_id = job.id_  # Note: underscore in attribute name
                logger.info(f"Transcription job created: {job_id}")

                # Track active job
                with self._job_lock:
                    self.active_jobs[job_id] = {
                        'status': TranscriptionStatus.PENDING.value,
                        'started': datetime.now(timezone.utc).isoformat(),
                        'url': audio_url
                    }

                # Poll for completion with monitoring
                result_data = self._wait_for_completion_with_monitoring(job_id)

                timestamps['completed'] = datetime.now(timezone.utc).isoformat()

                # Process the result with enhanced metadata
                transcription_result = self._process_enhanced_result(
                    result_data,
                    start_time,
                    job_id,
                    metadata,
                    timestamps
                )

                # Save if output path provided
                if output_path:
                    self._save_enhanced_transcript(transcription_result, output_path)

                # Record metrics
                if self.enable_monitoring:
                    self.metrics.record_job({
                        'job_id': job_id,
                        'status': TranscriptionStatus.SUCCEEDED.value,
                        'audio_duration': transcription_result.duration_seconds,
                        'processing_time': transcription_result.processing_time_seconds,
                        'word_count': transcription_result.word_count,
                        'confidence': transcription_result.confidence,
                        'language': transcription_result.language,
                        'timestamp': timestamps['completed']
                    })

                # Clean up tracking
                with self._job_lock:
                    if job_id in self.active_jobs:
                        del self.active_jobs[job_id]

                logger.info(
                    f"Transcription completed successfully: "
                    f"{transcription_result.word_count} words, "
                    f"{transcription_result.duration_seconds:.1f}s audio, "
                    f"{transcription_result.processing_time_seconds:.1f}s processing, "
                    f"confidence: {transcription_result.confidence:.2%}"
                )

                return transcription_result

            except Exception as e:
                last_error = str(e)
                logger.error(f"Transcription attempt {attempt} failed: {e}")

                if self.enable_monitoring:
                    self.metrics.record_job({
                        'status': TranscriptionStatus.FAILED.value,
                        'error': last_error,
                        'attempt': attempt,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })

                if attempt < self.max_retries:
                    logger.info(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                    continue

                # All retries exhausted
                error_result = TranscriptionResult(
                    text='',
                    language='unknown',
                    language_probability=0.0,
                    segments=[],
                    word_count=0,
                    confidence=0.0,
                    duration_seconds=0.0,
                    processing_time_seconds=time.time() - start_time,
                    job_id='',
                    metadata=metadata,
                    timestamps=timestamps,
                    error=f"Transcription failed after {self.max_retries} attempts: {last_error}"
                )

                if output_path:
                    self._save_enhanced_transcript(error_result, output_path)

                raise RuntimeError(f"Transcription failed after {self.max_retries} attempts: {last_error}")

    def _wait_for_completion_with_monitoring(self, job_id: str) -> Dict[str, Any]:
        """
        Enhanced polling with monitoring and progress tracking

        Args:
            job_id: Transcription job ID

        Returns:
            Transcription result data

        Raises:
            RuntimeError: If job fails or times out
        """
        start_time = time.time()
        last_status = None
        status_changes = []

        while True:
            elapsed = time.time() - start_time

            # Check timeout
            if elapsed > self.max_wait_time:
                with self._job_lock:
                    if job_id in self.active_jobs:
                        self.active_jobs[job_id]['status'] = TranscriptionStatus.TIMEOUT.value

                if self.enable_monitoring:
                    self.metrics.record_job({
                        'job_id': job_id,
                        'status': TranscriptionStatus.TIMEOUT.value,
                        'elapsed_time': elapsed,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })

                raise RuntimeError(f"Transcription timed out after {self.max_wait_time}s")

            try:
                # Get job status
                job = self.sdk.get_transcription_job(
                    organization_name=self.organization_name,
                    job_id=job_id
                )

                status = job.status

                # Track status changes
                if status != last_status:
                    status_change = {
                        'status': status,
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'elapsed_seconds': round(elapsed, 2)
                    }
                    status_changes.append(status_change)
                    logger.info(f"Job {job_id} status: {status} (elapsed: {elapsed:.1f}s)")

                    with self._job_lock:
                        if job_id in self.active_jobs:
                            self.active_jobs[job_id]['status'] = status
                            self.active_jobs[job_id]['status_changes'] = status_changes

                    last_status = status

                # Check completion status
                if status == 'succeeded':
                    if hasattr(job, 'output') and job.output:
                        # Convert TranscriptionJobOutput to dict
                        if hasattr(job.output, 'to_dict'):
                            result = job.output.to_dict()
                        elif isinstance(job.output, str):
                            result = json.loads(job.output)
                        else:
                            # Fallback: extract attributes manually
                            result = {
                                'text': getattr(job.output, 'text', ''),
                                'duration': getattr(job.output, 'duration', 0),
                                'duration_in_seconds': getattr(job.output, 'duration_in_seconds', 0),
                                'summary': getattr(job.output, 'summary', ''),
                                'srt_content': getattr(job.output, 'srt_content', ''),
                                'word_segments': getattr(job.output, 'word_segments', []),
                                'sentence_level_timestamps': getattr(job.output, 'sentence_level_timestamps', []),
                                'processing_time': getattr(job.output, 'processing_time', 0),
                                'overall_processing_time': getattr(job.output, 'overall_processing_time', 0)
                            }
                        result['status_history'] = status_changes
                        return result
                    else:
                        raise RuntimeError("Job succeeded but no output available")

                elif status == 'failed':
                    error_msg = getattr(job, 'error', 'Unknown error')
                    raise RuntimeError(f"Transcription job failed: {error_msg}")

                elif status == 'cancelled':
                    raise RuntimeError("Transcription job was cancelled")

            except Exception as e:
                if 'timed out' in str(e) or 'failed' in str(e) or 'cancelled' in str(e):
                    raise
                logger.warning(f"Error checking job status: {e}")

            # Wait before next poll
            time.sleep(self.polling_interval)

    def _process_enhanced_result(
        self,
        result_data: Dict[str, Any],
        start_time: float,
        job_id: str,
        metadata: Dict[str, Any],
        timestamps: Dict[str, str]
    ) -> TranscriptionResult:
        """
        Process result with enhanced metadata extraction

        Args:
            result_data: Raw result from Salad Cloud
            start_time: Processing start timestamp
            job_id: Job ID
            metadata: Job metadata
            timestamps: Timing information

        Returns:
            Enhanced TranscriptionResult object
        """
        processing_time = time.time() - start_time

        # Extract transcription data with defaults
        text = result_data.get('text', '').strip()
        language = result_data.get('language', self.language)

        # Use sentence_level_timestamps as segments if available, otherwise word_segments
        segments = result_data.get('sentence_level_timestamps', [])
        if not segments:
            segments = result_data.get('segments', [])

        word_segments = result_data.get('word_segments', [])

        # Enhanced segment processing
        processed_segments = []
        total_confidence = 0
        segment_count = 0

        # Process sentence-level timestamps if available
        if isinstance(segments, list) and segments:
            for segment in segments:
                if isinstance(segment, dict):
                    processed_segment = {
                        'id': segment.get('id', segment_count),
                        'start': segment.get('start', segment.get('start_time', 0)),
                        'end': segment.get('end', segment.get('end_time', 0)),
                        'text': segment.get('text', segment.get('sentence', '')).strip(),
                        'confidence': segment.get('confidence', 0.95),
                        'words': []
                    }

                    # Add speaker info if diarization is enabled
                    if self.enable_diarization and 'speaker' in segment:
                        processed_segment['speaker'] = segment['speaker']

                    processed_segments.append(processed_segment)
                    total_confidence += processed_segment['confidence']
                    segment_count += 1

        # Add word-level data if available
        if word_segments:
            metadata['word_segments'] = word_segments

        # Calculate metrics
        word_count = len(text.split()) if text else 0
        confidence = (total_confidence / segment_count) if segment_count > 0 else 0.95

        # Calculate duration from result or segments
        duration = result_data.get('duration_in_seconds', 0)
        if not duration and result_data.get('duration'):
            duration = result_data['duration']
        if not duration and processed_segments:
            last_segment = processed_segments[-1]
            duration = last_segment.get('end', 0)

        # Language probability
        language_probability = result_data.get('language_probability', 0.99)

        # Add Salad-specific features to metadata
        if 'summary' in result_data:
            metadata['summary'] = result_data['summary']

        if 'srt_content' in result_data:
            metadata['srt_content'] = result_data['srt_content']

        if 'processing_time' in result_data:
            metadata['salad_processing_time'] = result_data['processing_time']

        if 'overall_processing_time' in result_data:
            metadata['overall_processing_time'] = result_data['overall_processing_time']

        # Add status history
        metadata['status_history'] = result_data.get('status_history', [])

        return TranscriptionResult(
            text=text,
            language=language,
            language_probability=language_probability,
            segments=processed_segments,
            word_count=word_count,
            confidence=confidence,
            duration_seconds=duration,
            processing_time_seconds=processing_time,
            job_id=job_id,
            metadata=metadata,
            timestamps=timestamps,
            error=None
        )

    def _save_enhanced_transcript(
        self,
        result: TranscriptionResult,
        output_path: str
    ):
        """
        Save transcript with full metadata

        Args:
            result: Transcription result
            output_path: Output file path
        """
        ext = Path(output_path).suffix.lower()

        if ext == '.json':
            # Save complete JSON with all metadata
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(result.to_json())
            logger.info(f"Full transcript with metadata saved to {output_path}")

        elif ext == '.txt':
            # Save plain text with header metadata
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(f"# Transcription Metadata\n")
                f.write(f"# Job ID: {result.job_id}\n")
                f.write(f"# Language: {result.language} (confidence: {result.language_probability:.2%})\n")
                f.write(f"# Duration: {result.duration_seconds:.1f}s\n")
                f.write(f"# Words: {result.word_count}\n")
                f.write(f"# Confidence: {result.confidence:.2%}\n")
                f.write(f"# Processing Time: {result.processing_time_seconds:.1f}s\n")
                f.write(f"# Timestamp: {result.timestamps.get('completed', 'N/A')}\n")
                f.write("#" * 50 + "\n\n")
                f.write(result.text)

        elif ext == '.srt':
            # Save as SRT with metadata comments
            self._save_as_srt_enhanced(result, output_path)

        else:
            # Default to JSON for complete data
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(result.to_json())

    def _save_as_srt_enhanced(self, result: TranscriptionResult, output_path: str):
        """
        Save enhanced SRT with speaker labels if available

        Args:
            result: Transcription result
            output_path: Output file path
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            # Add metadata as SRT comments
            f.write(f"# Job ID: {result.job_id}\n")
            f.write(f"# Language: {result.language}\n")
            f.write(f"# Confidence: {result.confidence:.2%}\n\n")

            for i, segment in enumerate(result.segments, 1):
                # Write subtitle number
                f.write(f"{i}\n")

                # Write timestamp
                start_time = self._seconds_to_srt_time(segment.get('start', 0))
                end_time = self._seconds_to_srt_time(segment.get('end', 0))
                f.write(f"{start_time} --> {end_time}\n")

                # Write text with speaker label if available
                text = segment.get('text', '').strip()
                if 'speaker' in segment:
                    text = f"[Speaker {segment['speaker']}]: {text}"
                f.write(f"{text}\n\n")

    def _seconds_to_srt_time(self, seconds: float) -> str:
        """Convert seconds to SRT timestamp format"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get comprehensive metrics and monitoring data

        Returns:
            Dictionary with metrics
        """
        if not self.enable_monitoring:
            return {'monitoring': 'disabled'}

        metrics = self.metrics.get_metrics()

        # Add current active jobs
        with self._job_lock:
            metrics['active_jobs'] = list(self.active_jobs.values())
            metrics['active_job_count'] = len(self.active_jobs)

        # Add configuration info
        metrics['configuration'] = {
            'engine': 'full',
            'language': self.language,
            'organization': self.organization_name,
            'max_retries': self.max_retries,
            'max_wait_time': self.max_wait_time,
            'diarization': self.enable_diarization,
            'summarization': self.enable_summarization
        }

        return metrics

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """
        Get detailed status of a specific job

        Args:
            job_id: Job ID to check

        Returns:
            Job status information
        """
        try:
            job = self.sdk.get_transcription_job(
                organization_name=self.organization_name,
                job_id=job_id
            )

            return {
                'id': job.id,
                'status': job.status,
                'created': getattr(job, 'created_at', None),
                'completed': getattr(job, 'completed_at', None),
                'error': getattr(job, 'error', None),
                'metadata': getattr(job, 'metadata', {})
            }

        except Exception as e:
            logger.error(f"Failed to get job status for {job_id}: {e}")
            return {'error': str(e)}

    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a running transcription job

        Args:
            job_id: Job ID to cancel

        Returns:
            True if cancelled successfully
        """
        try:
            self.sdk.delete_transcription_job(
                organization_name=self.organization_name,
                job_id=job_id
            )

            with self._job_lock:
                if job_id in self.active_jobs:
                    self.active_jobs[job_id]['status'] = TranscriptionStatus.CANCELLED.value

            logger.info(f"Cancelled job: {job_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel job {job_id}: {e}")
            return False

    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on the transcription service

        Returns:
            Health status information
        """
        health = {
            'status': 'healthy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'service': 'salad-cloud-transcription',
            'engine': 'full',
            'language': self.language
        }

        try:
            # Try to list recent jobs as a health check
            self.sdk.list_transcription_jobs(
                organization_name=self.organization_name,
                page=1,
                page_size=1
            )
            health['api_status'] = 'connected'

        except Exception as e:
            health['status'] = 'degraded'
            health['api_status'] = 'error'
            health['error'] = str(e)

        # Add metrics if monitoring is enabled
        if self.enable_monitoring:
            metrics = self.metrics.get_metrics()
            health['metrics'] = {
                'success_rate': metrics['success_rate'],
                'total_jobs': metrics['total_jobs'],
                'active_jobs': metrics.get('active_job_count', 0)
            }

        return health