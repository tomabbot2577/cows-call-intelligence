#!/usr/bin/env python3
"""
Simple test of Salad API configuration
"""

import os
import sys
import time

sys.path.insert(0, '/var/www/call-recording-system')

from src.transcription.salad_transcriber_enhanced import SaladTranscriberEnhanced

def test_salad():
    print("Testing Salad API configuration...")
    print("="*60)
    
    # Test audio URL
    audio_url = "https://www.learningcontainer.com/wp-content/uploads/2020/02/Kalimba.mp3"
    
    try:
        # Initialize
        print("Initializing Salad Transcriber...")
        transcriber = SaladTranscriberEnhanced(
            api_key='salad_cloud_user_eG0tAkgYi0w0IPPUHpikdfhZG2Auw9MIin9Ld8PdLDQ0HGYCn',
            organization_name='mst'
        )
        print("✓ Initialized successfully")
        
        # Test transcription
        print(f"\nTesting transcription of: {audio_url}")
        result = transcriber.transcribe_file(audio_url)
        
        if result:
            print("\n✓ Transcription successful!")
            print(f"  - Text length: {len(result.text)} chars")
            print(f"  - First 100 chars: {result.text[:100]}...")
            print(f"  - Confidence: {result.confidence}")
            print(f"  - Word count: {result.word_count}")
        else:
            print("✗ Transcription failed")
            
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_salad()