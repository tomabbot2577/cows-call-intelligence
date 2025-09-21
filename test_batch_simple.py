#!/usr/bin/env python3
"""
Simplified Batch Test - 3 recordings with all features
Shows exactly what's working
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
from src.transcription.salad_transcriber import SaladTranscriber
from src.storage.google_drive import GoogleDriveManager
from src.database.session import SessionManager
from src.database.models import CallRecording

load_dotenv('/var/www/call-recording-system/.env')

def test_batch():
    """Test batch processing with 3 files"""

    print("\n" + "="*80)
    print("SIMPLIFIED BATCH TEST - 3 RECORDINGS")
    print("="*80)

    # Get 3 small test files
    audio_dir = Path('/var/www/call-recording-system/data/audio_queue')
    test_files = []

    for mp3 in sorted(audio_dir.glob('*.mp3')):
        if 50_000 < mp3.stat().st_size < 500_000:  # 50KB-500KB
            test_files.append(mp3)
            if len(test_files) >= 3:
                break

    print(f"\nSelected {len(test_files)} test files:")
    for f in test_files:
        print(f"  - {f.name} ({f.stat().st_size:,} bytes)")

    # Initialize components
    print("\n1. Initializing components...")

    transcriber = SaladTranscriber(
        api_key=os.getenv('SALAD_API_KEY'),
        organization_name=os.getenv('SALAD_ORG_NAME', 'mst'),
        engine='full',
        language='en'
    )

    drive = GoogleDriveManager(
        credentials_path=os.getenv('GOOGLE_CREDENTIALS_PATH'),
        impersonate_email=os.getenv('GOOGLE_IMPERSONATE_EMAIL')
    )

    session_mgr = SessionManager()

    print("✅ Components initialized")

    # Process each file
    results = []

    for i, audio_file in enumerate(test_files, 1):
        print(f"\n[{i}/3] Processing {audio_file.name}...")
        recording_id = audio_file.stem

        try:
            # 1. Transcribe
            print("  📝 Transcribing...")
            start = time.time()

            result = transcriber.transcribe_file(
                audio_path=str(audio_file),
                save_segments=True
            )

            elapsed = time.time() - start

            print(f"  ✅ Transcribed: {result.word_count} words in {elapsed:.1f}s")
            print(f"     Confidence: {result.confidence}")
            print(f"     Language: {result.language}")

            # 2. Upload to Google Drive
            print("  ☁️ Uploading to Google Drive...")

            upload_data = {
                'recording_id': recording_id,
                'transcription': {
                    'text': result.text,
                    'word_count': result.word_count,
                    'confidence': result.confidence,
                    'segments_count': len(result.segments) if result.segments else 0
                },
                'metadata': {
                    'file': audio_file.name,
                    'size': audio_file.stat().st_size,
                    'processed': datetime.utcnow().isoformat()
                }
            }

            try:
                file_id = drive.upload_json(
                    data=upload_data,
                    file_name=f"{recording_id}_test.json"
                )
                print(f"  ✅ Uploaded: {file_id}")
            except Exception as e:
                print(f"  ⚠️ Upload failed: {e}")
                file_id = None

            # 3. Update database
            print("  💾 Updating database...")

            try:
                with session_mgr.get_session() as session:
                    # Check if exists
                    record = session.query(CallRecording).filter_by(
                        recording_id=recording_id
                    ).first()

                    if not record:
                        # Create minimal record
                        record = CallRecording(
                            recording_id=recording_id,
                            call_id=recording_id,  # Use same ID
                            start_time=datetime.utcnow(),
                            duration=0
                        )
                        session.add(record)

                    # Update transcription fields
                    record.transcription_text = result.text[:1000]  # First 1000 chars
                    record.transcription_status = 'completed'
                    record.word_count = result.word_count
                    record.transcription_confidence = result.confidence
                    record.google_drive_file_id = file_id
                    record.transcription_completed_at = datetime.utcnow()
                    record.updated_at = datetime.utcnow()

                    session.commit()
                    print("  ✅ Database updated")

            except Exception as e:
                print(f"  ⚠️ Database error: {e}")

            # Store result
            results.append({
                'recording_id': recording_id,
                'status': 'success',
                'word_count': result.word_count,
                'confidence': result.confidence,
                'google_drive_id': file_id,
                'processing_time': elapsed
            })

        except Exception as e:
            print(f"  ❌ Failed: {e}")
            results.append({
                'recording_id': recording_id,
                'status': 'failed',
                'error': str(e)
            })

        # Brief pause
        if i < len(test_files):
            time.sleep(2)

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    successful = sum(1 for r in results if r.get('status') == 'success')
    print(f"✅ Successful: {successful}/3")

    if successful > 0:
        total_words = sum(r.get('word_count', 0) for r in results if r.get('status') == 'success')
        avg_confidence = sum(r.get('confidence', 0) for r in results if r.get('status') == 'success') / successful
        avg_time = sum(r.get('processing_time', 0) for r in results if r.get('status') == 'success') / successful

        print(f"📊 Total words: {total_words}")
        print(f"🎯 Avg confidence: {avg_confidence:.2%}")
        print(f"⏱️ Avg time: {avg_time:.1f}s")

    print("\nDetailed Results:")
    for r in results:
        if r['status'] == 'success':
            print(f"  ✅ {r['recording_id']}: {r['word_count']} words, {r['confidence']:.2%} conf, GDrive: {r.get('google_drive_id', 'N/A')}")
        else:
            print(f"  ❌ {r['recording_id']}: {r.get('error', 'Unknown error')}")

    # Save results
    with open('test_batch_results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n📁 Results saved to test_batch_results.json")

if __name__ == "__main__":
    test_batch()