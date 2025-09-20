#!/usr/bin/env python3
"""
Complete Pipeline Test - Salad Transcription + N8N/LLM Organization + Google Drive
Tests the full optimized workflow with proper data structure for AI/LLM processing
"""

import os
import sys
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import logging

# Add project to path
sys.path.insert(0, '/var/www/call-recording-system')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_complete_pipeline():
    """
    Test the complete optimized pipeline:
    1. Transcribe with Salad (diarization, summarization, timestamps)
    2. Enrich with LLM insights
    3. Organize for N8N/LLM (multi-dimensional structure)
    4. Upload to Google Drive
    5. Verify audio deletion (security compliance)
    """
    
    print("\n" + "="*80)
    print("COMPLETE PIPELINE TEST - OPTIMIZED FOR N8N & LLM")
    print("="*80)
    
    # Load environment
    from dotenv import load_dotenv
    load_dotenv('/var/www/call-recording-system/.env')
    
    # Import components
    from src.transcription.salad_transcriber_enhanced import SaladTranscriberEnhanced
    from src.storage.google_drive import GoogleDriveManager
    from src.storage.secure_storage_handler import SecureStorageHandler
    from src.storage.structured_data_organizer import StructuredDataOrganizer
    from src.enrichment.enrichment_pipeline import EnrichmentPipeline
    from src.integrations.n8n_integration import N8NIntegration
    from src.search.transcript_search_engine import TranscriptSearchEngine
    
    print("\n📋 CONFIGURATION:")
    print(f"  - Salad Org: mst")
    print(f"  - Google Drive: {os.getenv('GOOGLE_DRIVE_FOLDER_ID')}")
    print(f"  - Impersonate: {os.getenv('GOOGLE_IMPERSONATE_EMAIL')}")
    print(f"  - Data Structure: Optimized for N8N/LLM")
    
    # Initialize components
    print("\n🔧 INITIALIZING COMPONENTS:")
    
    # 1. Salad Transcriber with advanced features
    print("  1. Salad Transcriber (with diarization & summarization)...")
    transcriber = SaladTranscriberEnhanced(
        api_key=os.getenv('SALAD_API_KEY'),
        organization_name='mst',
        enable_diarization=True,
        enable_summarization=True,
        initial_prompt="Business call - identify speakers, key topics, and action items"
    )
    print("     ✓ Initialized")
    
    # 2. Google Drive Manager - using optimized folders
    print("  2. Google Drive Manager (optimized folders)...")
    google_drive = GoogleDriveManager(
        credentials_path=os.getenv('GOOGLE_CREDENTIALS_PATH'),
        folder_id=os.getenv('GOOGLE_DRIVE_TRANSCRIPTS_FOLDER'),  # Use transcripts folder
        impersonate_email=os.getenv('GOOGLE_IMPERSONATE_EMAIL')
    )
    print("     ✓ Initialized")
    
    # 3. Secure Storage Handler (handles audio deletion)
    print("  3. Secure Storage Handler (with audio deletion)...")
    storage_handler = SecureStorageHandler(
        google_drive_manager=google_drive,
        verify_deletion=True
    )
    print("     ✓ Initialized")
    
    # 4. Structured Data Organizer (N8N/LLM optimized)
    print("  4. Structured Data Organizer (multi-dimensional)...")
    data_dir = Path('/var/www/call-recording-system/data/structured')
    data_organizer = StructuredDataOrganizer(base_directory=str(data_dir))
    print("     ✓ Initialized")
    
    # 5. Enrichment Pipeline
    print("  5. Enrichment Pipeline (Salad + LLM)...")
    enrichment = EnrichmentPipeline(
        enable_salad_features=True,
        enable_llm_enrichment=bool(os.getenv('OPENAI_API_KEY')),
        openai_api_key=os.getenv('OPENAI_API_KEY')
    )
    print("     ✓ Initialized")
    
    # 6. N8N Integration
    print("  6. N8N Integration...")
    n8n = N8NIntegration(
        queue_directory=str(data_dir / 'n8n_workflows')
    )
    print("     ✓ Initialized")
    
    # 7. Search Engine
    print("  7. Search Engine (SQLite FTS5)...")
    search_engine = TranscriptSearchEngine(
        index_directory=str(data_dir / 'indexes')
    )
    print("     ✓ Initialized")
    
    # Test recordings
    test_recordings = [
        {
            'id': f'test_{datetime.now().strftime("%Y%m%d")}_{i:03d}',
            'audio_url': 'https://www.learningcontainer.com/wp-content/uploads/2020/02/Kalimba.mp3',
            'caller_name': f'Test Caller {i}',
            'phone_from': f'+1212555{1000+i:04d}',
            'phone_to': '+18005551234',
            'duration': 60 + (i * 10),
            'start_time': datetime.now(timezone.utc).isoformat(),
            'direction': 'inbound' if i % 2 == 0 else 'outbound'
        }
        for i in range(1, 4)  # Testing with 3 calls for now
    ]
    
    print(f"\n📞 TEST RECORDINGS: {len(test_recordings)} calls")
    
    results = []
    successful = 0
    failed = 0
    
    for i, recording in enumerate(test_recordings, 1):
        print(f"\n{'='*60}")
        print(f"PROCESSING CALL {i}/{len(test_recordings)}: {recording['id']}")
        print(f"{'='*60}")
        
        try:
            # Step 1: Transcribe with Salad
            print("\n📝 Step 1: Salad Transcription...")
            print(f"  URL: {recording['audio_url']}")
            
            transcription_result = transcriber.transcribe_file(
                audio_url=recording['audio_url']
            )
            
            if transcription_result:
                print(f"  ✓ Transcribed: {transcription_result.word_count} words")
                print(f"  ✓ Confidence: {transcription_result.confidence:.2%}")
                if transcription_result.metadata.get('speakers'):
                    print(f"  ✓ Speakers: {len(transcription_result.metadata.get('speakers', []))} identified")
                print(f"  ✓ Processing time: {transcription_result.processing_time:.2f}s")
            else:
                print("  ✗ Transcription failed")
                failed += 1
                continue
            
            # Step 2: Enrich transcript
            print("\n🧠 Step 2: Enrichment...")
            
            call_metadata = {
                'recording_id': recording['id'],
                'from_number': recording['phone_from'],
                'to_number': recording['phone_to'],
                'caller_name': recording['caller_name'],
                'duration': recording['duration'],
                'start_time': recording['start_time'],
                'direction': recording['direction']
            }
            
            enriched = enrichment.enrich_transcript(
                transcript_data=transcription_result.to_dict(),
                call_metadata=call_metadata,
                salad_result=transcription_result.to_dict()
            )
            
            print("  ✓ Enrichment complete")
            if 'salad_features' in enriched:
                print(f"  ✓ Salad features: diarization={enriched['salad_features'].get('has_diarization')}")
            if 'llm_enrichment' in enriched:
                print(f"  ✓ LLM insights: {len(enriched.get('llm_enrichment', {}))} categories")
            if 'alerts' in enriched:
                print(f"  ✓ Alerts: {len(enriched.get('alerts', []))} generated")
            
            # Step 3: Organize structured data
            print("\n📂 Step 3: Structured Data Organization (N8N/LLM)...")
            
            organized = data_organizer.process_transcription(
                transcription_data=enriched,
                call_metadata=call_metadata
            )
            
            if organized:
                print("  ✓ Data organized in multiple dimensions:")
                for path in organized.get('paths', [])[:5]:
                    print(f"    - {path}")
                print(f"  ✓ Indexes updated: {organized.get('indexes_updated', False)}")
            
            # Step 4: Queue for N8N
            print("\n🔄 Step 4: N8N Integration...")
            
            n8n_result = n8n.process_transcript_for_n8n(
                transcript_data=organized['document']
            )
            
            if n8n_result:
                print(f"  ✓ Queued for N8N: {n8n_result.get('queue_path')}")
                print(f"  ✓ Webhook payload ready: {n8n_result.get('webhook_ready', False)}")
            
            # Step 5: Index for search
            print("\n🔍 Step 5: Search Indexing...")
            
            search_engine.index_transcript(organized['document'])
            print("  ✓ Indexed for full-text search")
            
            # Step 6: Upload to Google Drive
            print("\n☁️ Step 6: Google Drive Upload...")

            upload_result = storage_handler.process_transcription(
                audio_file_path=recording['audio_url'],  # Using URL as path
                transcription_result=enriched,
                call_metadata=recording
            )
            
            if upload_result:
                print(f"  ✓ Transcript uploaded: {upload_result.get('transcript_file_id')}")
                print(f"  ✓ Audio deleted: {upload_result.get('audio_deleted', False)}")
                print(f"  ✓ Deletion verified: {upload_result.get('audio_deletion_verified', False)}")
            
            successful += 1
            results.append({
                'recording_id': recording['id'],
                'status': 'success',
                'transcript_words': transcription_result.word_count,
                'enriched': True,
                'organized': True,
                'indexed': True,
                'uploaded': True,
                'audio_deleted': upload_result.get('audio_deleted', False)
            })
            
            print(f"\n✅ Call {recording['id']} processed successfully!")
            
        except Exception as e:
            logger.error(f"Failed to process {recording['id']}: {e}")
            failed += 1
            results.append({
                'recording_id': recording['id'],
                'status': 'failed',
                'error': str(e)
            })
            print(f"\n❌ Call {recording['id']} failed: {e}")
        
        # Brief pause
        time.sleep(2)
    
    # Final summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    print(f"\n📊 RESULTS:")
    print(f"  Total calls: {len(test_recordings)}")
    print(f"  ✅ Successful: {successful}")
    print(f"  ❌ Failed: {failed}")
    
    # Check data organization
    print(f"\n📁 DATA ORGANIZATION:")
    if data_dir.exists():
        for subdir in ['by_date', 'by_phone', 'by_customer', 'n8n_workflows', 'ml_datasets', 'indexes']:
            path = data_dir / subdir
            if path.exists():
                file_count = sum(1 for _ in path.rglob('*.json'))
                print(f"  - {subdir}: {file_count} files")
    
    # Check Google Drive
    print(f"\n☁️ GOOGLE DRIVE:")
    try:
        # Get Transcripts folder
        query = f"name='Transcripts' and '{os.getenv('GOOGLE_DRIVE_FOLDER_ID')}' in parents"
        folders = google_drive.service.files().list(
            q=query,
            fields='files(id, name, webViewLink)'
        ).execute()
        
        if folders.get('files'):
            folder = folders['files'][0]
            print(f"  📁 Transcripts folder: {folder.get('webViewLink')}")
            
            # Count files
            files = google_drive.service.files().list(
                q=f"'{folder['id']}' in parents",
                fields='files(id)'
            ).execute()
            print(f"  📄 Files uploaded: {len(files.get('files', []))}")
    except Exception as e:
        print(f"  ❌ Error checking Drive: {e}")
    
    # Security compliance
    print(f"\n🔒 SECURITY COMPLIANCE:")
    audio_deleted = sum(1 for r in results if r.get('audio_deleted', False))
    print(f"  Audio files deleted: {audio_deleted}/{len(results)}")
    if audio_deleted == successful:
        print("  ✅ COMPLIANT: All audio files deleted after transcription")
    else:
        print("  ⚠️ WARNING: Some audio files may not have been deleted")
    
    # Analytics
    print(f"\n📈 ANALYTICS READY:")
    analytics = search_engine.get_analytics()
    print(f"  Total indexed documents: {analytics.get('total_documents', 0)}")
    print(f"  Search indexes: {len(analytics.get('indexes', []))}")
    print(f"  Entity extraction: {analytics.get('entity_stats', {})}")
    
    # Save results
    results_file = Path('/var/www/call-recording-system/test_complete_results.json')
    with open(results_file, 'w') as f:
        json.dump({
            'test_timestamp': datetime.now(timezone.utc).isoformat(),
            'total_processed': len(test_recordings),
            'successful': successful,
            'failed': failed,
            'data_structure': 'optimized_for_n8n_llm',
            'results': results
        }, f, indent=2)
    
    print(f"\n📋 Results saved to: {results_file}")
    print("\n" + "="*80)
    print("TEST COMPLETE!")
    print("="*80)

if __name__ == "__main__":
    test_complete_pipeline()