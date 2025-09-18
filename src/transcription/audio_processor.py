"""
Audio Processor for Whisper Transcription
Handles audio preprocessing, chunking, and format conversion
"""

import os
import logging
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any
import tempfile

import numpy as np
import librosa
import soundfile as sf

logger = logging.getLogger(__name__)


class AudioProcessor:
    """
    Audio preprocessing for optimal Whisper transcription
    """

    # Whisper expects 16kHz mono audio
    TARGET_SAMPLE_RATE = 16000

    # Maximum chunk duration in seconds (30 minutes)
    MAX_CHUNK_DURATION = 1800

    # Overlap between chunks in seconds
    CHUNK_OVERLAP = 2

    # Supported audio formats
    SUPPORTED_FORMATS = ['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac', '.wma', '.mp4']

    def __init__(
        self,
        target_sr: int = TARGET_SAMPLE_RATE,
        normalize: bool = True,
        remove_silence: bool = False,
        denoise: bool = False
    ):
        """
        Initialize audio processor

        Args:
            target_sr: Target sample rate
            normalize: Whether to normalize audio
            remove_silence: Whether to remove silence
            denoise: Whether to apply denoising
        """
        self.target_sr = target_sr
        self.normalize = normalize
        self.remove_silence = remove_silence
        self.denoise = denoise

        # Check for ffmpeg
        self.ffmpeg_available = self._check_ffmpeg()

        logger.info(f"AudioProcessor initialized (normalize={normalize}, remove_silence={remove_silence})")

    def _check_ffmpeg(self) -> bool:
        """
        Check if ffmpeg is available

        Returns:
            True if ffmpeg is available
        """
        try:
            subprocess.run(
                ['ffmpeg', '-version'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except FileNotFoundError:
            logger.warning("ffmpeg not found, some audio formats may not be supported")
            return False

    def load_audio(
        self,
        audio_path: str,
        offset: float = 0,
        duration: Optional[float] = None
    ) -> Tuple[np.ndarray, int]:
        """
        Load audio file and convert to proper format

        Args:
            audio_path: Path to audio file
            offset: Start offset in seconds
            duration: Duration to load in seconds

        Returns:
            Tuple of (audio array, sample rate)

        Raises:
            ValueError: If audio format not supported
        """
        file_ext = Path(audio_path).suffix.lower()

        if file_ext not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported audio format: {file_ext}")

        try:
            # Load audio using librosa
            audio, sr = librosa.load(
                audio_path,
                sr=self.target_sr,
                mono=True,
                offset=offset,
                duration=duration
            )

            logger.debug(f"Loaded audio: shape={audio.shape}, sr={sr}")

            # Apply preprocessing
            audio = self._preprocess_audio(audio, sr)

            return audio, sr

        except Exception as e:
            logger.error(f"Failed to load audio: {e}")

            # Try with ffmpeg if available
            if self.ffmpeg_available:
                return self._load_with_ffmpeg(audio_path, offset, duration)
            else:
                raise

    def _load_with_ffmpeg(
        self,
        audio_path: str,
        offset: float = 0,
        duration: Optional[float] = None
    ) -> Tuple[np.ndarray, int]:
        """
        Load audio using ffmpeg as fallback

        Args:
            audio_path: Path to audio file
            offset: Start offset in seconds
            duration: Duration to load in seconds

        Returns:
            Tuple of (audio array, sample rate)
        """
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
            tmp_path = tmp_file.name

        try:
            # Build ffmpeg command
            cmd = ['ffmpeg', '-i', audio_path]

            if offset > 0:
                cmd.extend(['-ss', str(offset)])

            if duration:
                cmd.extend(['-t', str(duration)])

            cmd.extend([
                '-ar', str(self.target_sr),
                '-ac', '1',  # Mono
                '-f', 'wav',
                '-y',  # Overwrite
                tmp_path
            ])

            # Run ffmpeg
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )

            # Load converted audio
            audio, sr = librosa.load(tmp_path, sr=self.target_sr, mono=True)

            return audio, sr

        finally:
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _preprocess_audio(
        self,
        audio: np.ndarray,
        sr: int
    ) -> np.ndarray:
        """
        Apply preprocessing to audio

        Args:
            audio: Audio array
            sr: Sample rate

        Returns:
            Preprocessed audio array
        """
        # Normalize audio
        if self.normalize:
            audio = self._normalize_audio(audio)

        # Remove silence
        if self.remove_silence:
            audio = self._remove_silence(audio, sr)

        # Apply denoising
        if self.denoise:
            audio = self._denoise_audio(audio, sr)

        return audio

    def _normalize_audio(self, audio: np.ndarray) -> np.ndarray:
        """
        Normalize audio to [-1, 1] range

        Args:
            audio: Audio array

        Returns:
            Normalized audio
        """
        max_val = np.abs(audio).max()

        if max_val > 0:
            audio = audio / max_val * 0.95  # Leave some headroom

        return audio

    def _remove_silence(
        self,
        audio: np.ndarray,
        sr: int,
        threshold: float = 0.01
    ) -> np.ndarray:
        """
        Remove silence from audio

        Args:
            audio: Audio array
            sr: Sample rate
            threshold: Silence threshold

        Returns:
            Audio with silence removed
        """
        # Find non-silent intervals
        intervals = librosa.effects.split(
            audio,
            top_db=20,  # dB below reference to consider as silence
            frame_length=2048,
            hop_length=512
        )

        if len(intervals) > 0:
            # Concatenate non-silent parts
            non_silent = []
            for start, end in intervals:
                non_silent.append(audio[start:end])

            if non_silent:
                audio = np.concatenate(non_silent)

        return audio

    def _denoise_audio(
        self,
        audio: np.ndarray,
        sr: int
    ) -> np.ndarray:
        """
        Apply basic denoising to audio

        Args:
            audio: Audio array
            sr: Sample rate

        Returns:
            Denoised audio
        """
        # Simple spectral subtraction denoising
        # This is a basic implementation - consider using
        # more sophisticated methods for production

        # Estimate noise from first 0.5 seconds
        noise_sample_len = int(0.5 * sr)
        if len(audio) > noise_sample_len:
            noise_sample = audio[:noise_sample_len]

            # Compute noise spectrum
            noise_fft = np.fft.rfft(noise_sample)
            noise_power = np.abs(noise_fft) ** 2

            # Apply to full audio
            audio_fft = np.fft.rfft(audio)
            audio_power = np.abs(audio_fft) ** 2

            # Spectral subtraction
            clean_power = audio_power - noise_power.mean()
            clean_power = np.maximum(clean_power, 0)

            # Reconstruct audio
            clean_fft = np.sqrt(clean_power) * np.exp(1j * np.angle(audio_fft))
            audio = np.fft.irfft(clean_fft)

        return audio

    def chunk_audio(
        self,
        audio: np.ndarray,
        sr: int,
        max_duration: float = MAX_CHUNK_DURATION,
        overlap: float = CHUNK_OVERLAP
    ) -> List[Tuple[np.ndarray, int, int]]:
        """
        Split audio into chunks for processing

        Args:
            audio: Audio array
            sr: Sample rate
            max_duration: Maximum chunk duration in seconds
            overlap: Overlap between chunks in seconds

        Returns:
            List of (chunk_audio, start_sample, end_sample)
        """
        chunks = []

        total_samples = len(audio)
        chunk_samples = int(max_duration * sr)
        overlap_samples = int(overlap * sr)

        start = 0

        while start < total_samples:
            end = min(start + chunk_samples, total_samples)

            chunk = audio[start:end]
            chunks.append((chunk, start, end))

            # Move start with overlap
            start = end - overlap_samples if end < total_samples else total_samples

        logger.info(f"Split audio into {len(chunks)} chunks")
        return chunks

    def save_audio(
        self,
        audio: np.ndarray,
        sr: int,
        output_path: str,
        format: str = 'WAV'
    ):
        """
        Save audio to file

        Args:
            audio: Audio array
            sr: Sample rate
            output_path: Output file path
            format: Output format
        """
        try:
            sf.write(output_path, audio, sr, format=format)
            logger.info(f"Saved audio to {output_path}")
        except Exception as e:
            logger.error(f"Failed to save audio: {e}")
            raise

    def get_audio_info(self, audio_path: str) -> Dict[str, Any]:
        """
        Get information about audio file

        Args:
            audio_path: Path to audio file

        Returns:
            Dictionary with audio information
        """
        try:
            info = sf.info(audio_path)

            return {
                'duration_seconds': info.duration,
                'sample_rate': info.samplerate,
                'channels': info.channels,
                'format': info.format,
                'subtype': info.subtype,
                'frames': info.frames,
                'file_size_bytes': os.path.getsize(audio_path)
            }

        except Exception as e:
            logger.error(f"Failed to get audio info: {e}")
            return {}

    def validate_audio(
        self,
        audio_path: str,
        min_duration: float = 1.0,
        max_duration: float = 7200.0
    ) -> Tuple[bool, str]:
        """
        Validate audio file for processing

        Args:
            audio_path: Path to audio file
            min_duration: Minimum duration in seconds
            max_duration: Maximum duration in seconds

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check file exists
        if not os.path.exists(audio_path):
            return False, "File does not exist"

        # Check file size
        file_size = os.path.getsize(audio_path)
        if file_size == 0:
            return False, "File is empty"

        if file_size > 500 * 1024 * 1024:  # 500MB
            return False, "File too large (>500MB)"

        # Check format
        file_ext = Path(audio_path).suffix.lower()
        if file_ext not in self.SUPPORTED_FORMATS:
            return False, f"Unsupported format: {file_ext}"

        # Check audio properties
        try:
            info = self.get_audio_info(audio_path)

            if info.get('duration_seconds', 0) < min_duration:
                return False, f"Audio too short (<{min_duration}s)"

            if info.get('duration_seconds', 0) > max_duration:
                return False, f"Audio too long (>{max_duration}s)"

            return True, "Valid"

        except Exception as e:
            return False, f"Failed to validate: {e}"

    def extract_audio_from_video(
        self,
        video_path: str,
        output_path: Optional[str] = None
    ) -> str:
        """
        Extract audio from video file

        Args:
            video_path: Path to video file
            output_path: Output audio file path

        Returns:
            Path to extracted audio file
        """
        if not self.ffmpeg_available:
            raise RuntimeError("ffmpeg is required for video extraction")

        if not output_path:
            output_path = Path(video_path).with_suffix('.wav')

        try:
            cmd = [
                'ffmpeg', '-i', video_path,
                '-vn',  # No video
                '-ar', str(self.target_sr),
                '-ac', '1',  # Mono
                '-f', 'wav',
                '-y',  # Overwrite
                str(output_path)
            ]

            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )

            logger.info(f"Extracted audio to {output_path}")
            return str(output_path)

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to extract audio: {e}")
            raise