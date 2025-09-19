#!/usr/bin/env python3
"""
Quick test of faster-whisper transcription
"""

import os
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config.settings import Settings
from src.ringcentral.auth import RingCentralAuth
from src.ringcentral.client import RingCentralClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


def test_faster_whisper():
    """Test faster-whisper transcription"""
    print("\n🧪 TESTING FASTER-WHISPER TRANSCRIPTION")
    print("="*50)

    settings = Settings()

    # Initialize RingCentral
    auth = RingCentralAuth(
        jwt_token=settings.ringcentral_jwt_token,
        client_id=settings.ringcentral_client_id,
        client_secret=settings.ringcentral_client_secret
    )
    client = RingCentralClient(auth=auth)

    try:
        # Get one recording
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=7)

        print(f"📅 Fetching a recording...")

        recording = None
        for record in client.get_all_call_logs(
            date_from=start_date,
            date_to=end_date,
            recording_type='All'
        ):
            if record.get('recording'):
                recording = record
                break

        if not recording:
            print("❌ No recordings found")
            return

        recording_id = recording['recording']['id']
        duration = recording.get('duration', 0)

        print(f"✅ Found recording {recording_id} ({duration} seconds)")

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / f"{recording_id}.mp3"

            # Download
            print(f"⬇️  Downloading audio...")
            client.download_recording(recording_id, str(audio_path))
            file_size = audio_path.stat().st_size
            print(f"✅ Downloaded: {file_size:,} bytes")

            # Transcribe with faster-whisper
            print(f"🎤 Transcribing with faster-whisper (tiny model for speed)...")

            try:
                from faster_whisper import WhisperModel

                # Use tiny model for speed
                model = WhisperModel("tiny", device="cpu", compute_type="int8")

                # Transcribe
                segments, info = model.transcribe(
                    str(audio_path),
                    beam_size=1,  # Faster with beam_size=1
                    language="en",  # Specify language for speed
                    vad_filter=True,  # Voice activity detection
                    vad_parameters=dict(
                        min_silence_duration_ms=500
                    )
                )

                # Collect text
                text_parts = []
                segment_count = 0
                for segment in segments:
                    text_parts.append(segment.text.strip())
                    segment_count += 1
                    if segment_count <= 3:
                        print(f"  Segment {segment_count}: {segment.text.strip()[:100]}...")

                full_text = " ".join(text_parts)

                print(f"\n✅ TRANSCRIPTION SUCCESSFUL!")
                print(f"  - Language: {info.language}")
                print(f"  - Duration: {info.duration:.1f}s")
                print(f"  - Segments: {segment_count}")
                print(f"  - Total text: {len(full_text)} characters")
                print(f"\n📝 First 500 characters:")
                print(f"  {full_text[:500]}...")

                return True

            except Exception as e:
                print(f"❌ Transcription failed: {e}")
                import traceback
                traceback.print_exc()
                return False

    finally:
        auth.close()


if __name__ == "__main__":
    success = test_faster_whisper()

    print("\n" + "="*50)
    if success:
        print("✅ Transcription works! Ready to process 15 recordings.")
    else:
        print("❌ Transcription failed. Check the errors above.")