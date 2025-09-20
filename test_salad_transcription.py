#!/usr/bin/env python3
"""
Test script for Salad Cloud transcription integration
"""

import os
import sys
import logging
import json
from pathlib import Path
import tempfile
import requests
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from src.transcription.salad_transcriber import SaladTranscriber
from src.transcription.pipeline import TranscriptionPipeline
from src.config.settings import Settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_test_audio():
    """Create a test audio file for transcription"""
    # Download a sample audio file
    logger.info("Downloading test audio file...")

    # Using a public domain audio sample
    audio_url = "https://www.kozco.com/tech/LRMonoPhase4.wav"

    try:
        response = requests.get(audio_url, timeout=30)
        response.raise_for_status()

        # Save to temporary file
        temp_file = tempfile.NamedTemporaryFile(
            suffix='.wav',
            delete=False,
            dir='/tmp'
        )
        temp_file.write(response.content)
        temp_file.close()

        logger.info(f"Test audio saved to: {temp_file.name}")
        return temp_file.name

    except Exception as e:
        logger.error(f"Failed to download test audio: {e}")
        return None


def test_salad_transcriber():
    """Test direct Salad Cloud transcriber"""
    logger.info("=" * 50)
    logger.info("Testing Salad Cloud Transcriber")
    logger.info("=" * 50)

    # Load settings
    settings = Settings()

    # Initialize transcriber
    transcriber = SaladTranscriber(
        api_key=settings.salad_api_key,
        organization_name=settings.salad_org_name,
        engine=settings.salad_engine
    )

    # Get or create test audio
    audio_path = create_test_audio()
    if not audio_path:
        logger.error("No test audio available")
        return False

    try:
        # Transcribe
        logger.info(f"Starting transcription of: {audio_path}")
        result = transcriber.transcribe_file(
            audio_path=audio_path,
            save_segments=True
        )

        # Display results
        logger.info("Transcription completed successfully!")
        logger.info(f"Language: {result.language}")
        logger.info(f"Word count: {result.word_count}")
        logger.info(f"Confidence: {result.confidence:.2%}")
        logger.info(f"Processing time: {result.processing_time_seconds:.2f}s")
        logger.info(f"Audio duration: {result.duration_seconds:.2f}s")

        # Show transcript preview
        text_preview = result.text[:500] + "..." if len(result.text) > 500 else result.text
        logger.info(f"Transcript preview: {text_preview}")

        # Save full result
        output_file = f"/tmp/salad_test_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w') as f:
            f.write(result.to_json())
        logger.info(f"Full result saved to: {output_file}")

        # Test statistics
        stats = transcriber.get_statistics()
        logger.info(f"Transcriber statistics: {json.dumps(stats, indent=2)}")

        return True

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return False

    finally:
        # Clean up
        if os.path.exists(audio_path):
            os.unlink(audio_path)
            logger.info("Cleaned up test audio file")


def test_pipeline_integration():
    """Test the integrated pipeline with Salad Cloud"""
    logger.info("=" * 50)
    logger.info("Testing Pipeline Integration")
    logger.info("=" * 50)

    # Initialize pipeline (should use Salad by default based on config)
    pipeline = TranscriptionPipeline()

    # Verify service type
    service_info = pipeline.get_service_info()
    logger.info(f"Pipeline service info: {json.dumps(service_info, indent=2)}")

    if service_info['service'] != 'salad':
        logger.warning(f"Pipeline is using {service_info['service']} instead of Salad Cloud")

    # Get test audio
    audio_path = create_test_audio()
    if not audio_path:
        logger.error("No test audio available")
        return False

    try:
        # Process through pipeline
        logger.info(f"Processing audio through pipeline: {audio_path}")
        result = pipeline.process(audio_path)

        # Display results
        logger.info("Pipeline processing completed!")
        logger.info(f"Text length: {len(result.get('text', ''))}")
        logger.info(f"Language: {result.get('language', 'unknown')}")

        return True

    except Exception as e:
        logger.error(f"Pipeline processing failed: {e}")
        return False

    finally:
        # Clean up
        if os.path.exists(audio_path):
            os.unlink(audio_path)


def test_job_management():
    """Test job listing and management features"""
    logger.info("=" * 50)
    logger.info("Testing Job Management Features")
    logger.info("=" * 50)

    settings = Settings()
    transcriber = SaladTranscriber(
        api_key=settings.salad_api_key,
        organization_name=settings.salad_org_name
    )

    try:
        # List recent jobs
        jobs = transcriber.list_jobs(page=1, page_size=5)
        logger.info(f"Found {len(jobs)} recent jobs")

        for job in jobs:
            logger.info(f"  Job {job['id']}: {job['status']} (created: {job['created']})")

        return True

    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        return False


def main():
    """Main test runner"""
    logger.info("Starting Salad Cloud Transcription Tests")
    logger.info("=" * 70)

    # Check configuration
    settings = Settings()
    logger.info(f"Transcription service: {settings.transcription_service}")
    logger.info(f"Salad organization: {settings.salad_org_name}")
    logger.info(f"Salad engine: {settings.salad_engine}")
    logger.info(f"API key configured: {'Yes' if settings.salad_api_key else 'No'}")

    if not settings.salad_api_key:
        logger.error("Salad API key not configured!")
        return 1

    # Run tests
    tests_passed = 0
    tests_total = 0

    # Test 1: Direct Salad transcriber
    tests_total += 1
    if test_salad_transcriber():
        tests_passed += 1
        logger.info("✅ Salad transcriber test passed")
    else:
        logger.error("❌ Salad transcriber test failed")

    # Test 2: Pipeline integration
    tests_total += 1
    if test_pipeline_integration():
        tests_passed += 1
        logger.info("✅ Pipeline integration test passed")
    else:
        logger.error("❌ Pipeline integration test failed")

    # Test 3: Job management
    tests_total += 1
    if test_job_management():
        tests_passed += 1
        logger.info("✅ Job management test passed")
    else:
        logger.error("❌ Job management test failed")

    # Summary
    logger.info("=" * 70)
    logger.info(f"Test Summary: {tests_passed}/{tests_total} tests passed")

    if tests_passed == tests_total:
        logger.info("🎉 All tests passed! Salad Cloud integration is working.")
        return 0
    else:
        logger.error(f"⚠️  {tests_total - tests_passed} test(s) failed.")
        return 1


if __name__ == "__main__":
    exit(main())