"""
RingCentral Video Transcription Handler

Handles transcription of RingCentral Video recordings using Salad Cloud.
RingCentral Video only provides keywords, not full transcripts, so we need
to download the recording and submit it to Salad Cloud for transcription.

Flow:
1. Download recording from RingCentral Video API
2. Upload to temporary storage (Google Drive) to get accessible URL
3. Submit to Salad Cloud for transcription
4. Store transcript in video_meetings table
"""

import os
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class VideoTranscriptionHandler:
    """
    Handles transcription of RingCentral Video recordings.

    Uses the existing Salad Cloud transcription infrastructure.
    """

    def __init__(self, db_session: Session = None):
        """
        Initialize the video transcription handler.

        Args:
            db_session: SQLAlchemy session for database operations
        """
        self.db = db_session

        # Initialize transcriber lazily
        self._transcriber = None
        self._video_client = None
        self._drive_manager = None

        # Storage paths
        self.temp_audio_dir = Path('/var/www/call-recording-system/data/video_audio_temp')
        self.temp_audio_dir.mkdir(parents=True, exist_ok=True)

        # Audio server URL (for locally hosted files)
        self.audio_server_url = os.getenv('AUDIO_SERVER_URL', 'http://31.97.102.13:8080/audio')

        logger.info("VideoTranscriptionHandler initialized")

    @property
    def transcriber(self):
        """Lazy load Salad transcriber."""
        if self._transcriber is None:
            from src.transcription.salad_transcriber_enhanced import SaladTranscriberEnhanced
            self._transcriber = SaladTranscriberEnhanced(
                api_key=os.getenv('SALAD_API_KEY'),
                organization_name=os.getenv('SALAD_ORG_NAME', 'mst'),
                enable_diarization=True,
                enable_summarization=True
            )
        return self._transcriber

    @property
    def video_client(self):
        """Lazy load RingCentral Video client."""
        if self._video_client is None:
            from src.ringcentral.video_client import RCVideoClient
            self._video_client = RCVideoClient()
        return self._video_client

    @property
    def drive_manager(self):
        """Lazy load Google Drive manager."""
        if self._drive_manager is None:
            from src.storage.google_drive import GoogleDriveManager
            self._drive_manager = GoogleDriveManager()
        return self._drive_manager

    def transcribe_video_meeting(
        self,
        meeting_id: int,
        recording_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Transcribe a video meeting recording.

        Args:
            meeting_id: Database ID of the video_meetings record
            recording_id: RingCentral recording ID

        Returns:
            Transcription result dict or None on failure
        """
        logger.info(f"Starting transcription for meeting {meeting_id}, recording {recording_id}")

        try:
            # Get media_link and media_url from database (stored in raw_ringcentral_data)
            media_link = None
            media_url = None
            if self.db:
                result = self.db.execute(
                    text("""
                        SELECT raw_ringcentral_data->>'mediaLink' as media_link,
                               raw_ringcentral_data->>'url' as media_url
                        FROM video_meetings
                        WHERE id = :meeting_id
                    """),
                    {'meeting_id': meeting_id}
                )
                row = result.fetchone()
                if row:
                    media_link = row[0]
                    media_url = row[1]
                    if media_url:
                        logger.info(f"Using stored media URL for download")
                    elif media_link:
                        logger.info(f"Using stored mediaLink for download")

            # Step 1: Download recording from RingCentral
            temp_file = self.temp_audio_dir / f"rc_video_{recording_id}.mp4"

            download_path = self.video_client.download_recording(
                recording_id=recording_id,
                output_path=str(temp_file),
                media_link=media_link,
                media_url=media_url
            )

            if not download_path:
                logger.error(f"Failed to download recording {recording_id}")
                return None

            logger.info(f"Downloaded recording to {download_path}")

            # Step 2: Convert to audio if needed (mp4 -> mp3)
            audio_path = self._extract_audio(Path(download_path))
            if not audio_path:
                logger.error(f"Failed to extract audio from {download_path}")
                return None

            # Step 3: Get accessible URL for Salad Cloud
            audio_url = self._get_audio_url(audio_path)
            if not audio_url:
                logger.error("Failed to create accessible URL for audio")
                return None

            logger.info(f"Audio accessible at: {audio_url}")

            # Step 4: Submit to Salad Cloud for transcription
            result = self.transcriber.transcribe_file(
                audio_url=audio_url,
                custom_metadata={
                    'source': 'ringcentral_video',
                    'meeting_id': meeting_id,
                    'recording_id': recording_id
                }
            )

            # Step 5: Update database with transcript
            if result and result.text:
                self._update_meeting_transcript(meeting_id, result)
                logger.info(f"Transcription complete: {result.word_count} words")

            # Step 6: Cleanup temp files
            self._cleanup_temp_files(temp_file, audio_path)

            return result.to_dict() if result else None

        except Exception as e:
            logger.error(f"Transcription failed for meeting {meeting_id}: {e}")
            return None

    def _extract_audio(self, video_path: Path) -> Optional[Path]:
        """
        Extract audio from video file using ffmpeg.

        Args:
            video_path: Path to video file

        Returns:
            Path to audio file or None
        """
        import subprocess

        audio_path = video_path.with_suffix('.mp3')

        try:
            # Use ffmpeg to extract audio
            cmd = [
                'ffmpeg', '-i', str(video_path),
                '-vn',  # No video
                '-acodec', 'libmp3lame',
                '-ar', '16000',  # 16kHz sample rate
                '-ac', '1',  # Mono
                '-ab', '64k',  # 64kbps bitrate
                '-y',  # Overwrite
                str(audio_path)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode == 0 and audio_path.exists():
                logger.info(f"Extracted audio to {audio_path}")
                return audio_path
            else:
                logger.error(f"ffmpeg failed: {result.stderr}")
                return None

        except subprocess.TimeoutExpired:
            logger.error("ffmpeg timed out")
            return None
        except FileNotFoundError:
            logger.error("ffmpeg not found - install with: sudo apt install ffmpeg")
            return None
        except Exception as e:
            logger.error(f"Audio extraction failed: {e}")
            return None

    def _get_audio_url(self, audio_path: Path) -> Optional[str]:
        """
        Get an accessible URL for the audio file.

        Uses Google Drive with public sharing for Salad Cloud access.

        Args:
            audio_path: Path to audio file

        Returns:
            Accessible URL or None
        """
        # Upload to Google Drive and make public for Salad Cloud access
        try:
            file_id, public_url = self.drive_manager.upload_and_share(
                str(audio_path),
                file_name=f"video_temp_{audio_path.stem}.mp3"
            )

            if public_url:
                logger.info(f"Audio uploaded to Google Drive: {public_url}")
                return public_url
        except Exception as e:
            logger.error(f"Failed to upload to Google Drive: {e}")

        return None

    def _update_meeting_transcript(
        self,
        meeting_id: int,
        result: Any
    ):
        """
        Update the video_meetings table with transcription result.

        Args:
            meeting_id: Database ID
            result: TranscriptionResult object
        """
        if not self.db:
            logger.warning("No database session - skipping transcript update")
            return

        try:
            self.db.execute(
                text("""
                    UPDATE video_meetings
                    SET transcript_text = :transcript,
                        transcription_status = 'completed',
                        transcription_word_count = :word_count,
                        transcription_duration_seconds = :duration,
                        transcription_confidence = :confidence,
                        transcription_completed_at = :completed_at,
                        updated_at = NOW()
                    WHERE id = :meeting_id
                """),
                {
                    'transcript': result.text,
                    'word_count': result.word_count,
                    'duration': result.duration_seconds,
                    'confidence': result.confidence,
                    'completed_at': datetime.now(timezone.utc),
                    'meeting_id': meeting_id
                }
            )
            self.db.commit()
            logger.info(f"Updated transcript for meeting {meeting_id}")

        except Exception as e:
            logger.error(f"Failed to update transcript: {e}")
            self.db.rollback()

    def _cleanup_temp_files(self, *paths):
        """Remove temporary files."""
        for path in paths:
            if path and Path(path).exists():
                try:
                    Path(path).unlink()
                except Exception as e:
                    logger.warning(f"Could not remove temp file {path}: {e}")

    def process_pending_transcriptions(self, limit: int = 10) -> Dict[str, int]:
        """
        Process video meetings that need transcription.

        Args:
            limit: Maximum number to process

        Returns:
            Stats dict with processed/failed counts
        """
        if not self.db:
            logger.error("Database session required for batch processing")
            return {'processed': 0, 'failed': 0, 'skipped': 0}

        stats = {'processed': 0, 'failed': 0, 'skipped': 0}

        try:
            # Get meetings from RingCentral source that need transcription
            result = self.db.execute(
                text("""
                    SELECT id, recording_id
                    FROM video_meetings
                    WHERE source = 'ringcentral'
                      AND transcript_text IS NULL
                      AND transcription_status != 'failed'
                      AND recording_id IS NOT NULL
                    ORDER BY meeting_date DESC
                    LIMIT :limit
                """),
                {'limit': limit}
            )

            meetings = result.fetchall()

            if not meetings:
                logger.info("No pending video transcriptions")
                return stats

            logger.info(f"Found {len(meetings)} meetings needing transcription")

            for meeting_id, recording_id in meetings:
                try:
                    result = self.transcribe_video_meeting(meeting_id, recording_id)
                    if result:
                        stats['processed'] += 1
                    else:
                        stats['failed'] += 1
                        # Mark as failed to avoid retry loops
                        self.db.execute(
                            text("""
                                UPDATE video_meetings
                                SET transcription_status = 'failed',
                                    updated_at = NOW()
                                WHERE id = :meeting_id
                            """),
                            {'meeting_id': meeting_id}
                        )
                        self.db.commit()

                except Exception as e:
                    logger.error(f"Error processing meeting {meeting_id}: {e}")
                    stats['failed'] += 1

            return stats

        except Exception as e:
            logger.error(f"Batch processing failed: {e}")
            return stats


def transcribe_recording(recording_id: str, output_path: str = None) -> Optional[Dict]:
    """
    Convenience function to transcribe a single RingCentral Video recording.

    Args:
        recording_id: RingCentral recording ID
        output_path: Optional path to save transcript

    Returns:
        Transcription result dict or None
    """
    handler = VideoTranscriptionHandler()

    try:
        # Download recording
        temp_file = handler.temp_audio_dir / f"rc_video_{recording_id}.mp4"
        download_path = handler.video_client.download_recording(
            recording_id=recording_id,
            output_path=str(temp_file)
        )

        if not download_path:
            logger.error(f"Failed to download recording {recording_id}")
            return None

        # Extract audio
        audio_path = handler._extract_audio(Path(download_path))
        if not audio_path:
            return None

        # Get URL
        audio_url = handler._get_audio_url(audio_path)
        if not audio_url:
            return None

        # Transcribe
        result = handler.transcriber.transcribe_file(
            audio_url=audio_url,
            output_path=output_path,
            custom_metadata={
                'source': 'ringcentral_video',
                'recording_id': recording_id
            }
        )

        # Cleanup
        handler._cleanup_temp_files(temp_file, audio_path)

        return result.to_dict() if result else None

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return None
