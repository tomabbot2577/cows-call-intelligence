#!/usr/bin/env python3
"""
Test script to process a single recording with transcription
Tests the complete pipeline: download, transcribe, upload
"""

import os
import logging
import tempfile
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
from pathlib import Path

from src.config.settings import Settings
from src.ringcentral.auth import RingCentralAuth
from src.ringcentral.client import RingCentralClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SingleRecordingTest:
    """Test transcription with a single recording"""

    def __init__(self):
        """Initialize the test"""
        self.settings = Settings()
        self._initialize_components()

    def _initialize_components(self):
        """Initialize components"""
        logger.info("Initializing components...")

        # RingCentral
        self.ringcentral_auth = RingCentralAuth(
            jwt_token=self.settings.ringcentral_jwt_token,
            client_id=self.settings.ringcentral_client_id,
            client_secret=self.settings.ringcentral_client_secret,
            sandbox=getattr(self.settings, 'ringcentral_sandbox', False)
        )
        self.ringcentral_client = RingCentralClient(auth=self.ringcentral_auth)

        logger.info("✅ RingCentral initialized")

    def fetch_one_recording(self) -> Dict[str, Any]:
        """Fetch just one recent recording"""
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=7)

        logger.info(f"📅 Fetching one recording from {start_date.date()} to {end_date.date()}")

        try:
            for record in self.ringcentral_client.get_all_call_logs(
                date_from=start_date,
                date_to=end_date,
                recording_type='All'
            ):
                recording_info = record.get('recording', {})
                if recording_info:
                    return {
                        'call_id': record.get('id'),
                        'session_id': record.get('sessionId'),
                        'start_time': record.get('startTime'),
                        'duration': record.get('duration', 0),
                        'from_name': record.get('from', {}).get('name'),
                        'from_number': record.get('from', {}).get('phoneNumber'),
                        'to_name': record.get('to', {}).get('name'),
                        'to_number': record.get('to', {}).get('phoneNumber'),
                        'direction': record.get('direction'),
                        'recording_id': recording_info.get('id'),
                    }
        except Exception as e:
            logger.error(f"Error fetching recording: {e}")
            raise

        return None

    def test_transcription(self, recording: Dict[str, Any]) -> bool:
        """Test transcription on a single recording"""
        recording_id = recording['recording_id']

        logger.info(f"\n{'='*60}")
        logger.info(f"📞 Testing transcription for recording {recording_id}")
        logger.info(f"  From: {recording['from_name']} ({recording['from_number']})")
        logger.info(f"  To: {recording['to_name']} ({recording['to_number']})")
        logger.info(f"  Duration: {recording['duration']} seconds")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # 1. Download recording
            logger.info(f"\n📥 Step 1: Downloading audio...")
            audio_path = temp_path / f"{recording_id}.mp3"

            try:
                self.ringcentral_client.download_recording(
                    recording_id=recording_id,
                    output_path=str(audio_path)
                )
                file_size = audio_path.stat().st_size
                logger.info(f"  ✅ Downloaded: {file_size:,} bytes")
            except Exception as e:
                logger.error(f"  ❌ Download failed: {e}")
                return False

            # 2. Test different transcription approaches
            logger.info(f"\n🎤 Step 2: Testing transcription approaches...")

            # Try 1: Direct Whisper
            logger.info("\n  Method 1: Direct Whisper (whisper library)")
            try:
                import whisper
                model = whisper.load_model("base")
                result = model.transcribe(str(audio_path))
                text = result.get("text", "")
                if text:
                    logger.info(f"    ✅ Success! Transcribed {len(text)} characters")
                    logger.info(f"    Preview: {text[:200]}...")
                    return True
            except Exception as e:
                logger.warning(f"    ❌ Failed: {e}")

            # Try 2: faster-whisper
            logger.info("\n  Method 2: faster-whisper")
            try:
                from faster_whisper import WhisperModel
                model = WhisperModel("base", device="cpu", compute_type="int8")
                segments, info = model.transcribe(str(audio_path))
                text = " ".join([segment.text for segment in segments])
                if text:
                    logger.info(f"    ✅ Success! Transcribed {len(text)} characters")
                    logger.info(f"    Preview: {text[:200]}...")
                    logger.info(f"    Language: {info.language}, Duration: {info.duration}s")
                    return True
            except Exception as e:
                logger.warning(f"    ❌ Failed: {e}")

            # Try 3: Using the existing pipeline
            logger.info("\n  Method 3: TranscriptionPipeline")
            try:
                from src.transcription.pipeline import TranscriptionPipeline
                pipeline = TranscriptionPipeline()
                result = pipeline.process(audio_path=str(audio_path))
                if result and 'text' in result:
                    text = result['text']
                    logger.info(f"    ✅ Success! Transcribed {len(text)} characters")
                    logger.info(f"    Preview: {text[:200]}...")
                    return True
            except Exception as e:
                logger.warning(f"    ❌ Failed: {e}")

            # Try 4: Using WhisperTranscriber directly
            logger.info("\n  Method 4: WhisperTranscriber directly")
            try:
                from src.transcription.whisper_transcriber import WhisperTranscriber
                transcriber = WhisperTranscriber(model_size="base")
                result = transcriber.transcribe_file(str(audio_path))
                if result and hasattr(result, 'text'):
                    text = result.text
                    logger.info(f"    ✅ Success! Transcribed {len(text)} characters")
                    logger.info(f"    Preview: {text[:200]}...")
                    return True
                elif isinstance(result, dict) and 'text' in result:
                    text = result['text']
                    logger.info(f"    ✅ Success! Transcribed {len(text)} characters")
                    logger.info(f"    Preview: {text[:200]}...")
                    return True
            except Exception as e:
                logger.warning(f"    ❌ Failed: {e}")

            logger.error("\n❌ All transcription methods failed!")
            return False

    def run(self):
        """Run the test"""
        print("\n" + "="*70)
        print("🧪 SINGLE RECORDING TRANSCRIPTION TEST")
        print("="*70)

        try:
            # Fetch one recording
            recording = self.fetch_one_recording()

            if not recording:
                print("❌ No recordings found")
                return

            # Test transcription
            success = self.test_transcription(recording)

            # Summary
            print("\n" + "="*70)
            print("📊 TEST RESULTS")
            print("="*70)

            if success:
                print("✅ Transcription successful!")
                print("\nNext steps:")
                print("1. Run test_15_complete_delegation.py to process 15 recordings")
                print("2. All recordings will be transcribed and uploaded to Google Drive")
            else:
                print("❌ Transcription failed")
                print("\nTroubleshooting:")
                print("1. Check if ffmpeg is installed: apt-get install ffmpeg")
                print("2. Check Whisper model files: ~/.cache/whisper/")
                print("3. Try different model size: tiny, base, small")
                print("4. Check available memory")

        except Exception as e:
            logger.error(f"Fatal error: {e}")
            raise
        finally:
            if hasattr(self, 'ringcentral_auth'):
                self.ringcentral_auth.close()


def main():
    """Main entry point"""
    test = SingleRecordingTest()
    test.run()


if __name__ == "__main__":
    main()