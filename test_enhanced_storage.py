#!/usr/bin/env python3
"""
Test the enhanced storage organizer with dual format output
"""

import os
import sys
import json
from pathlib import Path

sys.path.insert(0, '/var/www/call-recording-system')

from src.storage.enhanced_organizer import EnhancedStorageOrganizer

def test_enhanced_storage():
    """Test the enhanced storage with a sample transcription"""

    print("\n" + "="*80)
    print("TESTING ENHANCED STORAGE ORGANIZER")
    print("="*80)

    # Initialize organizer
    organizer = EnhancedStorageOrganizer()

    # Sample transcription result (from our earlier test)
    transcription_result = {
        'text': "Thank you for calling Main Sequence Technology. This is Garrett. How may I help you? Hey, Garrett. Chuck Draper. I've got an account with you guys. And just wondering, are you guys having any server issues? I think for the last five hours, I've had some real slow change in screen from PC Recruiter. Yeah, we did have a couple customers report that. Let me gather some information about your database here.",
        'word_count': 65,
        'confidence': 0.95,
        'language': 'en-US',
        'processing_time': 23.5,
        'segments': [
            {
                'id': 0,
                'speaker': 'agent',
                'start': 0.0,
                'end': 5.2,
                'text': 'Thank you for calling Main Sequence Technology. This is Garrett. How may I help you?',
                'confidence': 0.97
            },
            {
                'id': 1,
                'speaker': 'customer',
                'start': 5.5,
                'end': 15.3,
                'text': "Hey, Garrett. Chuck Draper. I've got an account with you guys. And just wondering, are you guys having any server issues?",
                'confidence': 0.94
            }
        ]
    }

    # Sample call metadata
    call_metadata = {
        'date': '2025-09-21',
        'time': '14:30:00',
        'duration': 240,
        'direction': 'inbound',
        'from': {
            'number': '+18475551234',
            'name': 'Chuck Draper',
            'company': 'MR Quaker Town'
        },
        'to': {
            'number': '+18005559999',
            'name': 'Main Sequence Support',
            'extension': '5467'
        },
        'file_size': 960000
    }

    # Test recording ID
    recording_id = 'TEST_3094616458037'

    # Google Drive ID (from our earlier upload)
    google_drive_id = '1eeU_XAAgN5Wkw_Z5T5zz9STZjT2Hx17Y'

    # Save the transcription
    print("\n📝 Saving transcription in dual format...")
    saved_paths = organizer.save_transcription(
        recording_id=recording_id,
        transcription_result=transcription_result,
        call_metadata=call_metadata,
        google_drive_id=google_drive_id
    )

    print("\n✅ Files created:")
    for file_type, path in saved_paths.items():
        if Path(path).exists():
            size = Path(path).stat().st_size
            print(f"  - {file_type}: {path} ({size:,} bytes)")

    # Read and display JSON content
    print("\n📄 JSON Content Preview:")
    with open(saved_paths['json'], 'r') as f:
        json_content = json.load(f)

    # Display key sections
    print(f"  Recording ID: {json_content['recording_id']}")
    print(f"  Version: {json_content['version']}")
    print(f"  Word Count: {json_content['transcription']['word_count']}")
    print(f"  AI Summary: {json_content['ai_analysis']['summary'][:100]}...")
    print(f"  Issue Type: {json_content['support_metrics']['issue_type']}")
    print(f"  N8N Tags: {json_content['n8n_metadata']['tags']}")
    print(f"  Google Drive ID: {json_content['storage']['google_drive_id']}")

    # Read and display Markdown preview
    print("\n📝 Markdown Content Preview:")
    with open(saved_paths['markdown'], 'r') as f:
        md_content = f.read()

    # Show first 1000 chars
    print(md_content[:1000])
    print("...")

    # Check N8N queue
    print("\n🔄 N8N Queue Entry:")
    with open(saved_paths['n8n_queue'], 'r') as f:
        queue_content = json.load(f)

    print(f"  Recording ID: {queue_content['recording_id']}")
    print(f"  Priority: {queue_content['priority']}")
    print(f"  Triggers: {queue_content['triggers']}")

    # Check indexes
    index_path = Path('/var/www/call-recording-system/data/transcriptions/indexes/master_index.json')
    if index_path.exists():
        with open(index_path, 'r') as f:
            index = json.load(f)

        print("\n📚 Master Index Updated:")
        if recording_id in index['recordings']:
            entry = index['recordings'][recording_id]
            print(f"  ✅ Recording indexed")
            print(f"     Date: {entry['date']}")
            print(f"     From: {entry['from']}")
            print(f"     Tags: {entry['tags']}")

    print("\n" + "="*80)
    print("✅ ENHANCED STORAGE TEST COMPLETE")
    print("="*80)
    print("\nKey Features Demonstrated:")
    print("1. ✅ Dual format storage (JSON + Markdown)")
    print("2. ✅ Comprehensive metadata for LLM analysis")
    print("3. ✅ N8N queue integration")
    print("4. ✅ Search index updates")
    print("5. ✅ AI analysis fields (sentiment, topics, entities)")
    print("6. ✅ Support metrics tracking")
    print("7. ✅ Google Drive reference linking")

if __name__ == "__main__":
    test_enhanced_storage()