#!/usr/bin/env python3
"""
Simple test of Salad transcription with local MP3 files
"""

import os
import sys
import json
import logging
from pathlib import Path

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv

# Load environment
load_dotenv('/var/www/call-recording-system/.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_with_local_file():
    """Test Salad with a local MP3 file from the queue"""
    logger.info("=" * 80)
    logger.info("TESTING SALAD WITH LOCAL MP3 FILE")
    logger.info("=" * 80)

    # Find a small test file
    audio_dir = Path('/var/www/call-recording-system/data/audio_queue')
    test_files = []

    for mp3_file in audio_dir.glob('*.mp3'):
        size = mp3_file.stat().st_size
        if 100_000 < size < 500_000:  # 100KB to 500KB for quick test
            test_files.append(mp3_file)

    if not test_files:
        logger.error("No suitable test files found")
        return False

    test_file = test_files[0]
    logger.info(f"\nTest file: {test_file.name}")
    logger.info(f"Size: {test_file.stat().st_size:,} bytes")

    # First test with the basic transcriber that accepts local files
    logger.info("\n1. Testing with basic SaladTranscriber (local file support)...")

    try:
        from src.transcription.salad_transcriber import SaladTranscriber

        transcriber = SaladTranscriber(
            api_key=os.getenv('SALAD_API_KEY'),
            organization_name=os.getenv('SALAD_ORG_NAME', 'mst'),  # Use correct env var
            engine='full',
            language='en'
        )

        result = transcriber.transcribe_file(
            audio_path=str(test_file),
            save_segments=True
        )

        logger.info("✅ Basic transcription successful!")
        logger.info(f"   Word count: {result.word_count}")
        logger.info(f"   Duration: {result.duration_seconds:.1f}s")
        logger.info(f"   Processing: {result.processing_time_seconds:.1f}s")
        logger.info(f"   Text preview: {result.text[:200]}...")

        # Save result
        output_dir = Path('/var/www/call-recording-system/test_output')
        output_dir.mkdir(exist_ok=True)

        with open(output_dir / f"{test_file.stem}_basic.json", 'w') as f:
            json.dump(result.to_dict(), f, indent=2)

        return True

    except Exception as e:
        logger.error(f"❌ Basic transcription failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def test_with_url():
    """Test with a public URL"""
    logger.info("\n" + "=" * 80)
    logger.info("TESTING SALAD WITH PUBLIC URL")
    logger.info("=" * 80)

    # Use a small public audio file
    test_url = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"

    logger.info(f"\nTest URL: {test_url}")

    try:
        from src.transcription.salad_transcriber_enhanced import SaladTranscriberEnhanced

        transcriber = SaladTranscriberEnhanced(
            api_key=os.getenv('SALAD_API_KEY'),
            organization_name=os.getenv('SALAD_ORG_NAME', 'mst'),  # Use correct env var
            engine='full',
            language='en-US',
            enable_diarization=True,
            enable_summarization=True
        )

        # The enhanced transcriber uses transcribe_file method (but with URL)
        result = transcriber.transcribe_file(
            audio_url=test_url,
            custom_metadata={'test': True, 'source': 'public_url'}
        )

        logger.info("✅ URL transcription successful!")
        logger.info(f"   Word count: {result.word_count}")
        logger.info(f"   Language: {result.language}")
        logger.info(f"   Confidence: {result.confidence:.2%}")

        return True

    except Exception as e:
        logger.error(f"❌ URL transcription failed: {e}")
        return False


def main():
    """Run tests"""

    # Test 1: Local file with basic transcriber
    local_success = test_with_local_file()

    # Test 2: Public URL with enhanced transcriber
    url_success = test_with_url()

    logger.info("\n" + "=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Local file test: {'✅ PASSED' if local_success else '❌ FAILED'}")
    logger.info(f"URL test: {'✅ PASSED' if url_success else '❌ FAILED'}")

    return local_success or url_success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)