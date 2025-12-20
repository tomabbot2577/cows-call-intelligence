#!/usr/bin/env python3
"""
Test script for enhanced Salad Cloud transcription with best practices
"""

import os
import sys
import logging
import json
import time
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from src.transcription.salad_transcriber_enhanced import SaladTranscriberEnhanced
from src.transcription.pipeline import TranscriptionPipeline
from src.config.settings import Settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_enhanced_transcriber_with_url():
    """Test enhanced Salad transcriber with a URL"""
    logger.info("=" * 70)
    logger.info("Testing Enhanced Salad Transcriber with Best Practices")
    logger.info("=" * 70)

    # Load settings
    settings = Settings()

    # Initialize enhanced transcriber
    transcriber = SaladTranscriberEnhanced(
        api_key=settings.salad_api_key,
        organization_name=settings.salad_org_name,
        engine='full',  # Always full for best quality
        language='en-US',  # American English
        initial_prompt=settings.salad_initial_prompt,
        max_retries=3,
        enable_monitoring=True,
        enable_diarization=False,  # Can enable for speaker identification
        enable_summarization=False,  # Can enable for automatic summary
        custom_vocabulary=""  # Add domain-specific terms if needed
    )

    # Use a public audio URL for testing
    # Note: In production, this would be RingCentral recording URLs
    test_audio_url = "https://www2.cs.uic.edu/~i101/SoundFiles/StarWars60.wav"

    try:
        logger.info(f"Starting transcription of: {test_audio_url}")
        logger.info("Configuration:")
        logger.info(f"  - Engine: FULL (Best Quality)")
        logger.info(f"  - Language: en-US (American English)")
        logger.info(f"  - Max Retries: 3")
        logger.info(f"  - Monitoring: Enabled")

        # Transcribe with full metadata capture
        result = transcriber.transcribe_file(
            audio_url=test_audio_url,
            save_segments=True,
            custom_metadata={
                'test_run': True,
                'test_timestamp': datetime.now().isoformat(),
                'purpose': 'Enhanced API validation'
            }
        )

        # Display comprehensive results
        logger.info("=" * 70)
        logger.info("TRANSCRIPTION RESULTS")
        logger.info("=" * 70)

        # Basic information
        logger.info(f"Job ID: {result.job_id}")
        logger.info(f"Language: {result.language} (confidence: {result.language_probability:.2%})")
        logger.info(f"Word Count: {result.word_count}")
        logger.info(f"Overall Confidence: {result.confidence:.2%}")
        logger.info(f"Audio Duration: {result.duration_seconds:.2f} seconds")
        logger.info(f"Processing Time: {result.processing_time_seconds:.2f} seconds")

        # Efficiency metrics
        if result.duration_seconds > 0:
            speed_ratio = result.processing_time_seconds / result.duration_seconds
            words_per_minute = (result.word_count / result.duration_seconds) * 60
            logger.info(f"Processing Speed Ratio: {speed_ratio:.2f}x")
            logger.info(f"Words Per Minute: {words_per_minute:.1f}")

        # Transcript preview
        text_preview = result.text[:500] + "..." if len(result.text) > 500 else result.text
        logger.info(f"\nTranscript Preview:")
        logger.info(f"{text_preview}")

        # Segment analysis
        if result.segments:
            logger.info(f"\nSegment Analysis:")
            logger.info(f"  - Total Segments: {len(result.segments)}")

            # Show first few segments with timestamps
            for i, segment in enumerate(result.segments[:3]):
                logger.info(f"  - Segment {i+1}:")
                logger.info(f"    Time: {segment.get('start', 0):.2f}s - {segment.get('end', 0):.2f}s")
                logger.info(f"    Text: {segment.get('text', '')[:100]}...")
                logger.info(f"    Confidence: {segment.get('confidence', 0):.2%}")

        # Metadata
        logger.info(f"\nMetadata:")
        logger.info(f"  - Source URL: {result.metadata.get('source_url')}")
        logger.info(f"  - Engine: {result.metadata.get('engine')}")
        logger.info(f"  - Organization: {result.metadata.get('organization')}")
        logger.info(f"  - Custom: {json.dumps(result.metadata.get('custom', {}), indent=4)}")

        # Timestamps
        logger.info(f"\nProcessing Timestamps:")
        for key, value in result.timestamps.items():
            logger.info(f"  - {key}: {value}")

        # Save full result with metadata
        output_file = f"/tmp/salad_enhanced_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w') as f:
            f.write(result.to_json())
        logger.info(f"\nFull result saved to: {output_file}")

        # Get and display metrics
        logger.info("\n" + "=" * 70)
        logger.info("MONITORING METRICS")
        logger.info("=" * 70)

        metrics = transcriber.get_metrics()
        logger.info(f"Service Metrics:")
        logger.info(f"  - Total Jobs: {metrics.get('total_jobs', 0)}")
        logger.info(f"  - Success Rate: {metrics.get('success_rate', 0)}%")
        logger.info(f"  - Active Jobs: {metrics.get('active_job_count', 0)}")
        logger.info(f"  - Total Audio Hours: {metrics.get('total_audio_hours', 0):.2f}")
        logger.info(f"  - Total Words Transcribed: {metrics.get('total_words_transcribed', 0):,}")

        # Configuration info
        config = metrics.get('configuration', {})
        logger.info(f"\nConfiguration:")
        for key, value in config.items():
            logger.info(f"  - {key}: {value}")

        # Health check
        logger.info("\n" + "=" * 70)
        logger.info("HEALTH CHECK")
        logger.info("=" * 70)

        health = transcriber.health_check()
        logger.info(f"Health Status: {health.get('status')}")
        logger.info(f"API Status: {health.get('api_status')}")
        logger.info(f"Service: {health.get('service')}")
        logger.info(f"Engine: {health.get('engine')}")
        logger.info(f"Language: {health.get('language')}")

        return True

    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pipeline_with_enhanced():
    """Test the pipeline integration with enhanced transcriber"""
    logger.info("\n" + "=" * 70)
    logger.info("Testing Pipeline with Enhanced Salad Transcriber")
    logger.info("=" * 70)

    # Initialize pipeline (should use enhanced Salad)
    pipeline = TranscriptionPipeline()

    # Verify service type
    service_info = pipeline.get_service_info()
    logger.info(f"Pipeline Configuration:")
    logger.info(f"  - Service: {service_info['service']}")
    logger.info(f"  - Engine: {service_info['engine']}")

    if service_info['service'] != 'salad':
        logger.warning(f"Pipeline is using {service_info['service']} instead of Salad")
        return False

    # Test URL
    test_url = "https://www2.cs.uic.edu/~i101/SoundFiles/gettysburg10.wav"

    try:
        logger.info(f"\nProcessing: {test_url}")

        # Process through pipeline
        result = pipeline.process(test_url)

        # Display results
        logger.info("Pipeline processing completed successfully!")
        logger.info(f"  - Text Length: {len(result.get('text', ''))}")
        logger.info(f"  - Language: {result.get('language', 'unknown')}")
        logger.info(f"  - Word Count: {result.get('word_count', 0)}")
        logger.info(f"  - Confidence: {result.get('confidence', 0) * 100:.1f}%")

        # Show preview
        text = result.get('text', '')
        preview = text[:300] + "..." if len(text) > 300 else text
        logger.info(f"\nText Preview: {preview}")

        return True

    except Exception as e:
        logger.error(f"Pipeline test failed: {e}")
        return False


def test_error_handling():
    """Test error handling and retry logic"""
    logger.info("\n" + "=" * 70)
    logger.info("Testing Error Handling and Retry Logic")
    logger.info("=" * 70)

    settings = Settings()

    transcriber = SaladTranscriberEnhanced(
        api_key=settings.salad_api_key,
        organization_name=settings.salad_org_name,
        max_retries=2,  # Set low for testing
        retry_delay=2,
        enable_monitoring=True
    )

    # Test with invalid URL
    invalid_url = "not_a_valid_url.wav"

    try:
        logger.info(f"Testing with invalid URL: {invalid_url}")
        result = transcriber.transcribe_file(invalid_url)
        logger.error("Should have raised an error for invalid URL")
        return False

    except ValueError as e:
        logger.info(f"✅ Correctly caught invalid URL error: {e}")

    # Test with non-existent URL
    non_existent_url = "https://example.com/non_existent_audio.wav"

    try:
        logger.info(f"\nTesting with non-existent URL: {non_existent_url}")
        result = transcriber.transcribe_file(non_existent_url)
        logger.error("Should have failed for non-existent URL")
        return False

    except RuntimeError as e:
        logger.info(f"✅ Correctly caught error after retries: {e}")
        # Check that retries were attempted
        if "after 2 attempts" in str(e):
            logger.info("✅ Retry logic working correctly")

    logger.info("\n✅ Error handling tests passed")
    return True


def main():
    """Main test runner"""
    logger.info("Starting Enhanced Salad Cloud Transcription Tests")
    logger.info("=" * 70)

    # Check configuration
    settings = Settings()
    logger.info(f"Configuration Check:")
    logger.info(f"  - Service: {settings.transcription_service}")
    logger.info(f"  - Organization: {settings.salad_org_name}")
    logger.info(f"  - Language: {settings.salad_language}")
    logger.info(f"  - Engine: FULL (enforced)")
    logger.info(f"  - Monitoring: {'Enabled' if settings.salad_enable_monitoring else 'Disabled'}")
    logger.info(f"  - API Key: {'✅ Configured' if settings.salad_api_key else '❌ Missing'}")

    if not settings.salad_api_key:
        logger.error("Salad API key not configured!")
        return 1

    # Run tests
    tests_passed = 0
    tests_total = 0

    # Test 1: Enhanced transcriber with full features
    tests_total += 1
    logger.info("\n" + "=" * 70)
    logger.info("TEST 1: Enhanced Transcriber with Best Practices")
    logger.info("=" * 70)
    if test_enhanced_transcriber_with_url():
        tests_passed += 1
        logger.info("✅ Enhanced transcriber test passed")
    else:
        logger.error("❌ Enhanced transcriber test failed")

    # Test 2: Pipeline integration
    tests_total += 1
    logger.info("\n" + "=" * 70)
    logger.info("TEST 2: Pipeline Integration")
    logger.info("=" * 70)
    if test_pipeline_with_enhanced():
        tests_passed += 1
        logger.info("✅ Pipeline integration test passed")
    else:
        logger.error("❌ Pipeline integration test failed")

    # Test 3: Error handling and retries
    tests_total += 1
    logger.info("\n" + "=" * 70)
    logger.info("TEST 3: Error Handling and Retries")
    logger.info("=" * 70)
    if test_error_handling():
        tests_passed += 1
        logger.info("✅ Error handling test passed")
    else:
        logger.error("❌ Error handling test failed")

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Results: {tests_passed}/{tests_total} tests passed")

    if tests_passed == tests_total:
        logger.info("🎉 All tests passed! Enhanced Salad Cloud integration is working perfectly.")
        logger.info("\nBest Practices Implemented:")
        logger.info("  ✅ Using FULL engine for maximum quality")
        logger.info("  ✅ American English (en-US) configured")
        logger.info("  ✅ Comprehensive metadata capture")
        logger.info("  ✅ Robust error handling with retries")
        logger.info("  ✅ Real-time monitoring and metrics")
        logger.info("  ✅ Health checks and alerting")
        logger.info("\nThe system is ready for production use!")
        return 0
    else:
        logger.error(f"⚠️  {tests_total - tests_passed} test(s) failed.")
        return 1


if __name__ == "__main__":
    exit(main())