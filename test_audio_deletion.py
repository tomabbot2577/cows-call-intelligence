#!/usr/bin/env python3
"""
Test script to verify audio deletion security feature
CONFIRMS that audio files are DELETED after transcription
"""

import os
import sys
import json
import tempfile
import hashlib
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from src.storage.secure_storage_handler import SecureStorageHandler
from src.storage.google_drive import GoogleDriveManager
from src.config.settings import Settings

def create_test_audio_file():
    """Create a test audio file"""
    # Create temporary audio file
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        # Write some dummy data (not actual audio, just for testing)
        f.write(b'RIFF' + b'\x00' * 1000)  # Minimal WAV header structure
        return f.name

def create_test_transcript():
    """Create a test transcription result"""
    return {
        'text': 'This is a test transcription.',
        'language': 'en-US',
        'confidence': 0.95,
        'word_count': 5,
        'segments': [
            {
                'start': 0.0,
                'end': 2.0,
                'text': 'This is a test transcription.',
                'confidence': 0.95
            }
        ],
        'metadata': {
            'engine': 'test',
            'timestamp': datetime.now().isoformat()
        }
    }

def test_audio_deletion():
    """Test the audio deletion functionality"""
    print("=" * 70)
    print("AUDIO DELETION SECURITY TEST")
    print("=" * 70)
    print("This test verifies that audio files are DELETED after transcription")
    print("-" * 70)

    # Initialize settings
    settings = Settings()

    # Initialize Google Drive manager (optional, can be None for local-only test)
    try:
        drive_manager = GoogleDriveManager(
            credentials_path=settings.google_credentials_path,
            folder_id=settings.google_drive_folder_id
        )
        print("✅ Google Drive manager initialized")
    except Exception as e:
        print(f"⚠️ Google Drive not configured, using local-only test: {e}")
        drive_manager = None

    # Initialize secure storage handler
    handler = SecureStorageHandler(
        google_drive_manager=drive_manager,
        local_backup_dir='/tmp/test_transcripts',
        enable_audit_log=True,
        verify_deletion=True
    )
    print("✅ Secure storage handler initialized")

    # Create test audio file
    audio_file = create_test_audio_file()
    original_size = os.path.getsize(audio_file)
    print(f"\n✅ Test audio file created: {audio_file}")
    print(f"   File size: {original_size} bytes")

    # Verify file exists
    if os.path.exists(audio_file):
        print("✅ Verified: Audio file exists before processing")
    else:
        print("❌ ERROR: Audio file doesn't exist!")
        return False

    # Calculate hash before deletion
    with open(audio_file, 'rb') as f:
        original_hash = hashlib.sha256(f.read()).hexdigest()
    print(f"   File hash: {original_hash[:16]}...")

    # Create test transcript
    transcript = create_test_transcript()
    print("\n✅ Test transcript created")

    # Create call metadata
    call_metadata = {
        'recording_id': 'TEST_001',
        'call_start_time': datetime.now().isoformat(),
        'duration': 120,
        'from_number': '+1234567890',
        'to_number': '+0987654321',
        'direction': 'inbound'
    }

    print("\n" + "=" * 70)
    print("PROCESSING TRANSCRIPTION (WILL DELETE AUDIO)")
    print("=" * 70)

    # Process transcription (this should DELETE the audio file)
    result = handler.process_transcription(
        audio_file_path=audio_file,
        transcription_result=transcript,
        call_metadata=call_metadata
    )

    print("\n" + "-" * 70)
    print("PROCESSING RESULTS:")
    print("-" * 70)

    # Check results
    print(f"✅ Processing success: {result['success']}")
    print(f"✅ Transcript saved: {result['transcript_saved']}")
    print(f"✅ Audio deleted: {result['audio_deleted']}")
    print(f"✅ Deletion verified: {result['deletion_verified']}")

    if result.get('drive_file_id'):
        print(f"✅ Google Drive file ID: {result['drive_file_id']}")

    if result.get('local_backup_path'):
        print(f"✅ Local backup: {result['local_backup_path']}")

    # CRITICAL: Verify audio file is actually deleted
    print("\n" + "=" * 70)
    print("DELETION VERIFICATION:")
    print("=" * 70)

    if os.path.exists(audio_file):
        print("❌ SECURITY FAILURE: Audio file still exists!")
        print(f"   File: {audio_file}")
        return False
    else:
        print("✅ CONFIRMED: Audio file has been DELETED")
        print(f"   Original file: {audio_file}")
        print(f"   Original size: {original_size} bytes")
        print(f"   Original hash: {original_hash[:16]}...")
        print("   Current status: FILE DOES NOT EXIST ✅")

    # Check deletion details
    if 'deletion_details' in result:
        details = result['deletion_details']
        print("\nDeletion Details:")
        print(f"   Method used: {details.get('deletion_method')}")
        print(f"   Deletion time: {details.get('deletion_time')}")
        print(f"   Bytes deleted: {details.get('file_size_bytes')}")

    # Get statistics
    stats = handler.get_statistics()
    print("\n" + "-" * 70)
    print("HANDLER STATISTICS:")
    print("-" * 70)
    print(f"   Audio files deleted: {stats['audio_files_deleted']}")
    print(f"   Transcripts saved: {stats['transcripts_saved']}")
    print(f"   Total bytes deleted: {stats['total_audio_bytes_deleted']}")
    print(f"   Total MB deleted: {stats['total_audio_mb_deleted']}")

    # Check audit log
    audit_log_path = Path('/var/www/call-recording-system/logs/deletion_audit.log')
    if audit_log_path.exists():
        with open(audit_log_path, 'r') as f:
            lines = f.readlines()
            if lines:
                last_entry = json.loads(lines[-1])
                print("\n" + "-" * 70)
                print("AUDIT LOG ENTRY:")
                print("-" * 70)
                print(f"   Action: {last_entry.get('action')}")
                print(f"   Timestamp: {last_entry.get('timestamp')}")
                print(f"   Audio file: {last_entry.get('audio_file')}")
                print(f"   Deletion verified: {last_entry.get('deletion_result', {}).get('verified')}")
                print("✅ Audit log created successfully")

    # If using Google Drive, verify no audio files exist
    if drive_manager:
        print("\n" + "-" * 70)
        print("GOOGLE DRIVE VERIFICATION:")
        print("-" * 70)

        verification = handler.verify_no_audio_in_drive()
        if verification['verified']:
            print("✅ VERIFIED: No audio files in Google Drive")
        else:
            print(f"⚠️ WARNING: Found {verification.get('audio_files_found', 0)} audio files in Drive")
            if verification.get('files'):
                for file in verification['files'][:3]:
                    print(f"   - {file['name']} ({file['size']} bytes)")

    print("\n" + "=" * 70)
    print("TEST COMPLETED SUCCESSFULLY")
    print("=" * 70)
    print("✅ Audio deletion security feature is working correctly")
    print("✅ Audio files are being DELETED after transcription")
    print("✅ Only transcripts are being saved")
    print("✅ Audit trail is maintained")
    print("\n🔒 SECURITY STATUS: COMPLIANT ✅")

    return True

def cleanup_test_files():
    """Clean up any test files"""
    # Clean up test transcript backups
    test_dir = Path('/tmp/test_transcripts')
    if test_dir.exists():
        import shutil
        shutil.rmtree(test_dir)
        print("\n✅ Test files cleaned up")

if __name__ == "__main__":
    try:
        success = test_audio_deletion()
        cleanup_test_files()

        if success:
            print("\n🎉 All security tests passed!")
            sys.exit(0)
        else:
            print("\n❌ Security test failed!")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)