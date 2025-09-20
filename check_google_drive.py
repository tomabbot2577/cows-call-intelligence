#!/usr/bin/env python3
"""
Check Google Drive folder and list uploaded files
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, '/var/www/call-recording-system')

from src.storage.google_drive import GoogleDriveManager

def check_google_drive():
    print("="*80)
    print("GOOGLE DRIVE CHECK")
    print("="*80)
    
    # Load configuration
    from dotenv import load_dotenv
    load_dotenv('/var/www/call-recording-system/.env')
    
    folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
    creds_path = os.getenv('GOOGLE_CREDENTIALS_PATH')
    impersonate = os.getenv('GOOGLE_IMPERSONATE_EMAIL')
    
    print(f"\n📁 Configuration:")
    print(f"  - Folder ID: {folder_id}")
    print(f"  - Credentials: {creds_path}")
    print(f"  - Impersonate: {impersonate}")
    
    # Initialize Google Drive Manager
    print(f"\n🔧 Initializing Google Drive...")
    drive = GoogleDriveManager(
        credentials_path=creds_path,
        folder_id=folder_id,
        impersonate_email=impersonate
    )
    
    # Get folder information
    print(f"\n📂 Checking folder access...")
    try:
        folder_info = drive.service.files().get(
            fileId=folder_id,
            fields='id,name,webViewLink,owners'
        ).execute()
        
        print(f"  ✓ Folder Name: {folder_info.get('name')}")
        print(f"  ✓ Folder Link: {folder_info.get('webViewLink')}")
        owners = folder_info.get('owners', [])
        if owners:
            print(f"  ✓ Owner: {owners[0].get('displayName', 'Unknown')} ({owners[0].get('emailAddress', 'Unknown')})")
    except Exception as e:
        print(f"  ✗ Error accessing folder: {e}")
        return
    
    # List recent files in the folder
    print(f"\n📄 Recent files in folder:")
    print(f"-" * 60)
    
    try:
        # Query for files in the folder
        query = f"'{folder_id}' in parents and trashed = false"
        
        response = drive.service.files().list(
            q=query,
            fields='files(id, name, mimeType, size, createdTime, modifiedTime, webViewLink)',
            orderBy='createdTime desc',
            pageSize=20
        ).execute()
        
        files = response.get('files', [])
        
        if not files:
            print("  No files found in the folder")
        else:
            print(f"  Found {len(files)} files (showing recent 20):")
            print()
            
            # Group by type
            audio_files = [f for f in files if 'audio' in f.get('mimeType', '') or f['name'].endswith('.mp3')]
            json_files = [f for f in files if f['name'].endswith('.json')]
            text_files = [f for f in files if f['name'].endswith('.txt')]
            other_files = [f for f in files if f not in audio_files + json_files + text_files]
            
            if audio_files:
                print(f"  🎵 Audio Files ({len(audio_files)}):")
                for f in audio_files[:5]:  # Show first 5
                    size_mb = int(f.get('size', 0)) / (1024*1024) if f.get('size') else 0
                    print(f"    - {f['name'][:50]}... ({size_mb:.2f} MB)")
                    print(f"      Created: {f.get('createdTime', 'Unknown')[:19]}")
                    print(f"      Link: {f.get('webViewLink', 'No link')}")
                    print()
                if len(audio_files) > 5:
                    print(f"    ... and {len(audio_files) - 5} more audio files")
                print()
            
            if json_files:
                print(f"  📋 Metadata Files ({len(json_files)}):")
                for f in json_files[:5]:
                    print(f"    - {f['name']}")
                    print(f"      Created: {f.get('createdTime', 'Unknown')[:19]}")
                if len(json_files) > 5:
                    print(f"    ... and {len(json_files) - 5} more metadata files")
                print()
            
            if text_files:
                print(f"  📝 Transcript Files ({len(text_files)}):")
                for f in text_files[:5]:
                    print(f"    - {f['name']}")
                    print(f"      Created: {f.get('createdTime', 'Unknown')[:19]}")
                    print(f"      Link: {f.get('webViewLink', 'No link')}")
                if len(text_files) > 5:
                    print(f"    ... and {len(text_files) - 5} more transcript files")
                print()
            
            if other_files:
                print(f"  📁 Other Files ({len(other_files)}):")
                for f in other_files[:3]:
                    print(f"    - {f['name']} ({f.get('mimeType', 'Unknown type')})")
                print()
        
        # Get folder statistics
        print(f"\n📊 Folder Statistics:")
        print(f"-" * 60)
        
        # Count all files
        all_query = f"'{folder_id}' in parents and trashed = false"
        all_files = []
        page_token = None
        
        while True:
            response = drive.service.files().list(
                q=all_query,
                fields='nextPageToken, files(id, name, size, mimeType)',
                pageSize=100,
                pageToken=page_token
            ).execute()
            
            all_files.extend(response.get('files', []))
            page_token = response.get('nextPageToken')
            
            if not page_token:
                break
        
        total_size = sum(int(f.get('size', 0)) for f in all_files if f.get('size'))
        audio_count = len([f for f in all_files if 'audio' in f.get('mimeType', '') or f['name'].endswith('.mp3')])
        json_count = len([f for f in all_files if f['name'].endswith('.json')])
        txt_count = len([f for f in all_files if f['name'].endswith('.txt')])
        
        print(f"  Total Files: {len(all_files)}")
        print(f"  - Audio Files: {audio_count}")
        print(f"  - Metadata Files (JSON): {json_count}")
        print(f"  - Transcript Files (TXT): {txt_count}")
        print(f"  - Other Files: {len(all_files) - audio_count - json_count - txt_count}")
        print(f"  Total Size: {total_size / (1024*1024):.2f} MB")
        
    except Exception as e:
        print(f"  ✗ Error listing files: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n" + "="*80)
    print(f"\n🔗 Direct folder link:")
    print(f"   {folder_info.get('webViewLink')}")
    print(f"\n💡 If you can't see the files:")
    print(f"   1. Make sure you're logged in as: {impersonate}")
    print(f"   2. Or check if the folder is shared with your account")
    print(f"   3. The folder ID is: {folder_id}")
    print(f"\n" + "="*80)

if __name__ == "__main__":
    check_google_drive()