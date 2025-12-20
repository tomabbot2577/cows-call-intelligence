#!/usr/bin/env python3
"""
Setup Optimized Google Drive Folder Structure for N8N/LLM Processing
Creates a well-organized hierarchy matching our data structure
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, '/var/www/call-recording-system')

from src.storage.google_drive import GoogleDriveManager
from dotenv import load_dotenv

def create_folder_structure():
    """
    Create optimized folder structure in Google Drive
    """
    print("\n" + "="*80)
    print("GOOGLE DRIVE FOLDER STRUCTURE SETUP")
    print("Optimized for N8N Workflows & AI/LLM Processing")
    print("="*80)
    
    # Load environment
    load_dotenv('/var/www/call-recording-system/.env')
    
    # Initialize Google Drive
    print("\n🔧 Initializing Google Drive...")
    drive = GoogleDriveManager(
        credentials_path=os.getenv('GOOGLE_CREDENTIALS_PATH'),
        folder_id=os.getenv('GOOGLE_DRIVE_FOLDER_ID'),
        impersonate_email=os.getenv('GOOGLE_IMPERSONATE_EMAIL')
    )
    
    root_folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
    
    # Define optimized folder structure
    folder_structure = {
        '📦 AI_Processed_Calls': {  # Main organized folder
            '🗓️ By_Date': {  # Chronological organization
                '2025': {
                    '01-January': {},
                    '09-September': {
                        'Transcripts': {},
                        'Enriched': {},
                        'Audio_Archive': {}  # If we decide to keep any audio
                    },
                    '10-October': {},
                    '11-November': {},
                    '12-December': {}
                }
            },
            '📞 By_Phone': {  # Phone-based organization
                'Inbound': {},
                'Outbound': {},
                'VIP_Numbers': {}
            },
            '👥 By_Customer': {  # Customer organization
                'Active_Customers': {},
                'Archived_Customers': {}
            },
            '🤖 N8N_Workflows': {  # N8N integration
                'Queue': {},        # New items for processing
                'Processing': {},   # Currently being processed
                'Processed': {},    # Completed items
                'Failed': {},       # Failed processing
                'Webhooks': {}      # Webhook data
            },
            '🧠 LLM_Analysis': {  # AI/LLM outputs
                'Summaries': {},
                'Sentiment': {},
                'Topics': {},
                'Action_Items': {},
                'Entities': {},
                'Insights': {}
            },
            '📊 Analytics': {  # Aggregated data
                'Daily_Reports': {},
                'Weekly_Summaries': {},
                'Monthly_Analysis': {},
                'Customer_Insights': {},
                'Trends': {}
            },
            '🔍 Search_Indexes': {  # Search metadata
                'Master_Index': {},
                'By_Keywords': {},
                'By_Entities': {}
            },
            '📄 Exports': {  # Export formats
                'CSV': {},
                'JSON': {},
                'Reports': {}
            },
            '⚠️ Alerts': {  # Alert-triggered items
                'High_Priority': {},
                'Negative_Sentiment': {},
                'Compliance_Issues': {}
            }
        },
        '🔒 Audio_Deletion_Logs': {},  # Security compliance logs
        '📊 System_Metrics': {}  # System performance data
    }
    
    created_folders = {}
    
    def create_folders_recursive(structure, parent_id, path=""):
        """
        Recursively create folder structure
        """
        for folder_name, subfolders in structure.items():
            current_path = f"{path}/{folder_name}" if path else folder_name
            
            # Check if folder exists
            query = f"name='{folder_name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            existing = drive.service.files().list(
                q=query,
                fields='files(id, name)'
            ).execute()
            
            if existing.get('files'):
                folder_id = existing['files'][0]['id']
                print(f"  ✓ Exists: {current_path}")
            else:
                # Create folder
                folder_metadata = {
                    'name': folder_name,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [parent_id]
                }
                
                folder = drive.service.files().create(
                    body=folder_metadata,
                    fields='id, name, webViewLink'
                ).execute()
                
                folder_id = folder['id']
                print(f"  ✅ Created: {current_path}")
                print(f"     Link: {folder.get('webViewLink')}")
            
            created_folders[current_path] = folder_id
            
            # Create subfolders
            if subfolders:
                create_folders_recursive(subfolders, folder_id, current_path)
    
    print("\n📁 Creating folder structure...")
    print("-" * 60)
    
    try:
        create_folders_recursive(folder_structure, root_folder_id)
        
        print("\n" + "="*80)
        print("✅ FOLDER STRUCTURE CREATED SUCCESSFULLY")
        print("="*80)
        
        # Get main folders for easy access
        print("\n📑 KEY FOLDER LOCATIONS:")
        print("-" * 60)
        
        key_folders = [
            '📦 AI_Processed_Calls',
            '📦 AI_Processed_Calls/🤖 N8N_Workflows/Queue',
            '📦 AI_Processed_Calls/🧠 LLM_Analysis',
            '📦 AI_Processed_Calls/🗓️ By_Date/2025/09-September/Transcripts'
        ]
        
        for folder_path in key_folders:
            if folder_path in created_folders:
                folder_id = created_folders[folder_path]
                # Get folder details
                folder_info = drive.service.files().get(
                    fileId=folder_id,
                    fields='webViewLink'
                ).execute()
                
                print(f"\n📁 {folder_path.split('/')[-1]}")
                print(f"   ID: {folder_id}")
                print(f"   Link: {folder_info.get('webViewLink')}")
        
        # Save folder IDs for configuration
        import json
        config_file = '/var/www/call-recording-system/google_drive_folders.json'
        with open(config_file, 'w') as f:
            json.dump({
                'created_at': datetime.now().isoformat(),
                'root_folder_id': root_folder_id,
                'folders': created_folders,
                'key_folders': {
                    'ai_processed': created_folders.get('📦 AI_Processed_Calls'),
                    'n8n_queue': created_folders.get('📦 AI_Processed_Calls/🤖 N8N_Workflows/Queue'),
                    'transcripts': created_folders.get('📦 AI_Processed_Calls/🗓️ By_Date/2025/09-September/Transcripts'),
                    'llm_analysis': created_folders.get('📦 AI_Processed_Calls/🧠 LLM_Analysis'),
                    'analytics': created_folders.get('📦 AI_Processed_Calls/📊 Analytics')
                }
            }, f, indent=2)
        
        print(f"\n💾 Folder configuration saved to: {config_file}")
        
        print("\n" + "="*80)
        print("🎉 SETUP COMPLETE!")
        print("="*80)
        print("\nYour Google Drive is now organized with:")
        print("✅ Chronological organization (By_Date)")
        print("✅ Phone-based grouping (By_Phone)")
        print("✅ Customer segmentation (By_Customer)")
        print("✅ N8N workflow queues")
        print("✅ LLM analysis folders")
        print("✅ Analytics and reporting structure")
        print("✅ Security compliance logging")
        
        print("\n💡 Next Steps:")
        print("1. Update .env with specific folder IDs if needed")
        print("2. Configure storage handlers to use new structure")
        print("3. Run test to verify uploads go to correct folders")
        
    except Exception as e:
        print(f"\n❌ Error creating folders: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    create_folder_structure()