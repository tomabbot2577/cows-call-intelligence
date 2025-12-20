#!/usr/bin/env python3
"""
Register all audio files in the recordings database
"""

import json
from pathlib import Path
from datetime import datetime
import os

print("=" * 80)
print("REGISTERING ALL RECORDINGS IN DATABASE")
print("=" * 80)

# Load existing database
recordings_db_path = Path('/var/www/call-recording-system/data/recordings_database.json')
if recordings_db_path.exists():
    with open(recordings_db_path, 'r') as f:
        recordings = json.load(f)
    print(f"\nExisting records in database: {len(recordings)}")
else:
    recordings = {}
    print("\nCreating new recordings database")

# Find all audio files
audio_queue_dir = Path('/var/www/call-recording-system/data/audio_queue')
audio_files = list(audio_queue_dir.glob('*.mp3'))
print(f"Total audio files found: {len(audio_files)}")

# Register each file
new_registrations = 0
already_registered = 0

for audio_file in sorted(audio_files):
    recording_id = audio_file.stem

    if recording_id not in recordings:
        # Register new recording
        file_stats = audio_file.stat()
        recordings[recording_id] = {
            "recording_id": recording_id,
            "status": "downloaded",
            "audio_path": str(audio_file),
            "file_size": file_stats.st_size,
            "downloaded_at": datetime.fromtimestamp(file_stats.st_mtime).isoformat(),
            "processed_at": datetime.now().isoformat(),
            "transcribed": False,
            "insights_generated": False,
            "source": "ringcentral",
            "needs_processing": True
        }
        new_registrations += 1

        if new_registrations <= 5:
            print(f"  ✅ Registered: {recording_id}")
    else:
        already_registered += 1

# Save updated database
with open(recordings_db_path, 'w') as f:
    json.dump(recordings, f, indent=2)

print(f"\n📊 REGISTRATION SUMMARY:")
print(f"  New registrations: {new_registrations}")
print(f"  Already registered: {already_registered}")
print(f"  Total in database: {len(recordings)}")

# Create a queue file for Salad Cloud processing
queue_path = Path('/var/www/call-recording-system/data/salad_queue.json')
queue = []

for recording_id, data in recordings.items():
    if not data.get('transcribed', False) and data.get('status') == 'downloaded':
        queue.append({
            "recording_id": recording_id,
            "audio_path": data['audio_path'],
            "priority": "normal",
            "added_to_queue": datetime.now().isoformat()
        })

with open(queue_path, 'w') as f:
    json.dump(queue, f, indent=2)

print(f"\n🥗 SALAD CLOUD QUEUE:")
print(f"  Total recordings queued for transcription: {len(queue)}")
print(f"  Queue saved to: {queue_path}")

print("\n" + "=" * 80)
print("REGISTRATION COMPLETE!")
print("All recordings are now registered and ready for Salad Cloud processing")
print("=" * 80)