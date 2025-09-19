"""
Whisper Transcription Pipeline
Main transcription logic with chunking, confidence scoring, and language detection
"""

import os
import time
import logging
import json
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime
import tempfile

import numpy as np
import whisper

from .model_manager import ModelManager
from .audio_processor import AudioProcessor

logger = logging.getLogger(__name__)


class TranscriptionResult:
    """
    Container for transcription results
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


class WhisperTranscriber:
    """
    Main transcription pipeline using Whisper
    """

    def __init__(
        self,
        model_name: str = 'base',
        device: Optional[str] = None,
        language: Optional[str] = None,
        task: str = 'transcribe',
        temperature: float = 0.0,
        compression_ratio_threshold: float = 2.4,
        logprob_threshold: float = -1.0,
        no_speech_threshold: float = 0.6,
        initial_prompt: Optional[str] = None
    ):
        """
        Initialize transcriber

        Args:
            model_name: Whisper model size
            device: Device to use (cuda/cpu/auto)
            language: Language code (None for auto-detect)
            task: Task type ('transcribe' or 'translate')
            temperature: Sampling temperature
            compression_ratio_threshold: Threshold for filtering
            logprob_threshold: Average log probability threshold
            no_speech_threshold: Threshold for detecting silence
            initial_prompt: Initial prompt for better context
        """
        # Initialize components
        self.model_manager = ModelManager(model_name=model_name, device=device)
        self.audio_processor = AudioProcessor()

        # Transcription parameters
        self.language = language
        self.task = task
        self.temperature = temperature
        self.compression_ratio_threshold = compression_ratio_threshold
        self.logprob_threshold = logprob_threshold
        self.no_speech_threshold = no_speech_threshold
        self.initial_prompt = initial_prompt

        # Statistics
        self.total_transcriptions = 0
        self.total_audio_duration = 0
        self.total_processing_time = 0

        logger.info(f"WhisperTranscriber initialized with model: {model_name}")

    def transcribe_file(
        self,
        audio_path: str,
        output_path: Optional[str] = None,
        save_segments: bool = True
    ) -> TranscriptionResult:
        """
        Transcribe audio file

        Args:
            audio_path: Path to audio file
            output_path: Optional path to save transcript
            save_segments: Whether to include segment data

        Returns:
            TranscriptionResult object

        Raises:
            ValueError: If audio validation fails
            RuntimeError: If transcription fails
        """
        start_time = time.time()

        # Validate audio
        is_valid, error_msg = self.audio_processor.validate_audio(audio_path)
        if not is_valid:
            raise ValueError(f"Audio validation failed: {error_msg}")

        logger.info(f"Starting transcription of {audio_path}")

        # Get audio info
        audio_info = self.audio_processor.get_audio_info(audio_path)
        duration_seconds = audio_info.get('duration_seconds', 0)

        # Load model
        model = self.model_manager.load_model()

        # Load and preprocess audio
        audio, sr = self.audio_processor.load_audio(audio_path)

        # Check if chunking is needed
        if duration_seconds > self.audio_processor.MAX_CHUNK_DURATION:
            result = self._transcribe_with_chunks(audio, sr, model)
        else:
            result = self._transcribe_audio(audio, model)

        # Calculate processing metrics
        processing_time = time.time() - start_time

        # Calculate confidence score
        confidence = self._calculate_confidence(result)

        # Count words
        word_count = len(result['text'].split())

        # Create result object
        transcription_result = TranscriptionResult(
            text=result['text'],
            language=result.get('language', 'unknown'),
            language_probability=result.get('language_probability', 0.0),
            segments=result.get('segments', []) if save_segments else [],
            word_count=word_count,
            confidence=confidence,
            duration_seconds=duration_seconds,
            processing_time_seconds=processing_time
        )

        # Save if output path provided
        if output_path:
            self._save_transcript(transcription_result, output_path)

        # Update statistics
        self.total_transcriptions += 1
        self.total_audio_duration += duration_seconds
        self.total_processing_time += processing_time
        self.model_manager.transcriptions_count += 1

        logger.info(
            f"Transcription completed: {word_count} words, "
            f"{duration_seconds:.1f}s audio, {processing_time:.1f}s processing, "
            f"confidence: {confidence:.2%}"
        )

        return transcription_result

    def _transcribe_audio(
        self,
        audio: np.ndarray,
        model: whisper.Whisper
    ) -> Dict[str, Any]:
        """
        Transcribe audio array

        Args:
            audio: Audio array
            model: Whisper model

        Returns:
            Transcription result dictionary
        """
        try:
            # Prepare options
            options = {
                'language': self.language,
                'task': self.task,
                'temperature': self.temperature,
                'compression_ratio_threshold': self.compression_ratio_threshold,
                'logprob_threshold': self.logprob_threshold,
                'no_speech_threshold': self.no_speech_threshold,
                'condition_on_previous_text': True,
                'initial_prompt': self.initial_prompt,
                'word_timestamps': True,  # Enable word-level timestamps
                'prepend_punctuations': '"\'([{-',
                'append_punctuations': '"\'.?!:)]}',
                'verbose': False
            }

            # Transcribe
            result = model.transcribe(audio, **options)

            # Post-process result
            result = self._post_process_result(result)

            return result

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise RuntimeError(f"Transcription failed: {e}")

    def _transcribe_with_chunks(
        self,
        audio: np.ndarray,
        sr: int,
        model: whisper.Whisper
    ) -> Dict[str, Any]:
        """
        Transcribe long audio with chunking

        Args:
            audio: Audio array
            sr: Sample rate
            model: Whisper model

        Returns:
            Combined transcription result
        """
        logger.info("Using chunked transcription for long audio")

        # Split audio into chunks
        chunks = self.audio_processor.chunk_audio(audio, sr)

        all_segments = []
        all_text = []
        detected_languages = {}

        for i, (chunk_audio, start_sample, end_sample) in enumerate(chunks, 1):
            logger.info(f"Processing chunk {i}/{len(chunks)}")

            # Transcribe chunk
            chunk_result = self._transcribe_audio(chunk_audio, model)

            # Adjust segment timestamps
            time_offset = start_sample / sr
            for segment in chunk_result.get('segments', []):
                segment['start'] += time_offset
                segment['end'] += time_offset
                all_segments.append(segment)

            # Collect text
            all_text.append(chunk_result['text'])

            # Track language detection
            lang = chunk_result.get('language', 'unknown')
            lang_prob = chunk_result.get('language_probability', 0.0)
            if lang in detected_languages:
                detected_languages[lang] += lang_prob
            else:
                detected_languages[lang] = lang_prob

        # Combine results
        combined_text = ' '.join(all_text)

        # Determine most likely language
        if detected_languages:
            best_language = max(detected_languages, key=detected_languages.get)
            language_probability = detected_languages[best_language] / len(chunks)
        else:
            best_language = 'unknown'
            language_probability = 0.0

        return {
            'text': combined_text,
            'segments': all_segments,
            'language': best_language,
            'language_probability': language_probability
        }

    def _calculate_confidence(self, result: Dict[str, Any]) -> float:
        """
        Calculate confidence score from transcription result

        Args:
            result: Transcription result

        Returns:
            Confidence score (0.0 to 1.0)
        """
        segments = result.get('segments', [])

        if not segments:
            return 0.0

        # Calculate average probability from segments
        total_prob = 0
        total_tokens = 0

        for segment in segments:
            # Get average logprob for segment
            avg_logprob = segment.get('avg_logprob', 0)

            # Convert logprob to probability
            prob = np.exp(avg_logprob)

            # Weight by number of tokens
            tokens = segment.get('tokens', [])
            if tokens:
                total_prob += prob * len(tokens)
                total_tokens += len(tokens)

        if total_tokens > 0:
            avg_confidence = total_prob / total_tokens
        else:
            avg_confidence = 0.0

        # Apply penalties for problematic segments
        penalty = 0

        for segment in segments:
            # High compression ratio indicates hallucination
            compression = segment.get('compression_ratio', 0)
            if compression > self.compression_ratio_threshold:
                penalty += 0.05

            # Low probability indicates uncertainty
            if segment.get('avg_logprob', 0) < self.logprob_threshold:
                penalty += 0.03

            # High no-speech probability
            if segment.get('no_speech_prob', 0) > self.no_speech_threshold:
                penalty += 0.02

        # Apply penalty and clamp to [0, 1]
        confidence = max(0.0, min(1.0, avg_confidence - penalty))

        return confidence

    def _post_process_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Post-process transcription result

        Args:
            result: Raw transcription result

        Returns:
            Processed result
        """
        # Clean up text
        text = result.get('text', '').strip()

        # Remove repetitions (common Whisper issue)
        text = self._remove_repetitions(text)

        # Fix common transcription errors
        text = self._fix_common_errors(text)

        result['text'] = text

        return result

    def _remove_repetitions(self, text: str, threshold: int = 3) -> str:
        """
        Remove repeated phrases from text

        Args:
            text: Input text
            threshold: Minimum repetitions to consider

        Returns:
            Text with repetitions removed
        """
        words = text.split()
        cleaned = []

        i = 0
        while i < len(words):
            # Look for repeated sequences
            repeated = False

            for seq_len in range(1, min(10, len(words) - i)):
                sequence = words[i:i + seq_len]
                count = 1

                j = i + seq_len
                while j + seq_len <= len(words):
                    if words[j:j + seq_len] == sequence:
                        count += 1
                        j += seq_len
                    else:
                        break

                if count >= threshold:
                    # Found repetition, keep only one instance
                    cleaned.extend(sequence)
                    i = j
                    repeated = True
                    break

            if not repeated:
                cleaned.append(words[i])
                i += 1

        return ' '.join(cleaned)

    def _fix_common_errors(self, text: str) -> str:
        """
        Fix common transcription errors

        Args:
            text: Input text

        Returns:
            Fixed text
        """
        # Common replacements
        replacements = {
            ' gonna ': ' going to ',
            ' wanna ': ' want to ',
            ' gotta ': ' got to ',
            '  ': ' ',  # Double spaces
        }

        for old, new in replacements.items():
            text = text.replace(old, new)

        return text

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
        # Determine format from extension
        ext = Path(output_path).suffix.lower()

        if ext == '.json':
            # Save as JSON with all metadata
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(result.to_json())

        elif ext == '.txt':
            # Save as plain text
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(result.text)

        elif ext == '.srt':
            # Save as SRT subtitles
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
                start_time = self._seconds_to_srt_time(segment['start'])
                end_time = self._seconds_to_srt_time(segment['end'])
                f.write(f"{start_time} --> {end_time}\n")

                # Write text
                f.write(f"{segment['text'].strip()}\n\n")

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
            'model_info': self.model_manager.get_model_info()
        }