#!/usr/bin/env python3
"""
Load transcript content from JSON files into PostgreSQL database
"""

import json
import os
import sys
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': 'REDACTED_DB_PASSWORD',
    'host': 'localhost',
    'port': 5432
}

def load_transcript_from_json(json_path):
    """Load transcript content from JSON file"""
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)

        # Extract transcript text from various possible formats
        transcript_text = ""

        if 'transcript_text' in data:
            transcript_text = data['transcript_text']
        elif 'transcription' in data and 'text' in data['transcription']:
            transcript_text = data['transcription']['text']
        elif 'salad_response' in data and 'transcript' in data['salad_response']:
            transcript_text = data['salad_response']['transcript']

        # Get word count
        word_count = len(transcript_text.split()) if transcript_text else 0

        # Extract other metadata
        customer_name = "Unknown"
        employee_name = "Unknown"
        duration_seconds = 0

        if 'call_metadata' in data:
            metadata = data['call_metadata']
            duration_seconds = metadata.get('duration_seconds', 0)

            if 'to' in metadata:
                customer_name = metadata['to'].get('name', 'Unknown')
            if 'from' in metadata:
                employee_name = metadata['from'].get('name', 'Unknown')

        return {
            'transcript_text': transcript_text,
            'word_count': word_count,
            'customer_name': customer_name,
            'employee_name': employee_name,
            'duration_seconds': duration_seconds
        }

    except Exception as e:
        logger.error(f"Error loading {json_path}: {e}")
        return None

def update_transcript_content(recording_id, content_data):
    """Update transcript content in database"""
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE transcripts
            SET
                transcript_text = %s,
                word_count = %s,
                customer_name = %s,
                employee_name = %s,
                duration_seconds = %s
            WHERE recording_id = %s
        """, (
            content_data['transcript_text'],
            content_data['word_count'],
            content_data['customer_name'],
            content_data['employee_name'],
            content_data['duration_seconds'],
            recording_id
        ))

        conn.commit()
        return cursor.rowcount > 0

    except Exception as e:
        logger.error(f"Database error for {recording_id}: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

def main():
    """Load all transcript content from JSON files"""

    transcript_dir = Path('/var/www/call-recording-system/data/transcriptions/json')

    if not transcript_dir.exists():
        print("❌ Transcript directory not found")
        return

    # Find all JSON transcript files
    json_files = list(transcript_dir.glob('**/*.json'))
    json_files = [f for f in json_files if not f.name.endswith('.enhanced.json')]

    print(f"📁 Found {len(json_files)} transcript files")

    updated_count = 0
    processed_count = 0

    for json_file in json_files:
        recording_id = json_file.stem

        # Load transcript content
        content_data = load_transcript_from_json(json_file)

        if content_data and content_data['transcript_text']:
            # Update database
            if update_transcript_content(recording_id, content_data):
                updated_count += 1
                if updated_count % 50 == 0:
                    print(f"  ✅ Updated {updated_count} transcripts...")

        processed_count += 1

        if processed_count % 100 == 0:
            print(f"  📊 Processed {processed_count}/{len(json_files)} files...")

    print(f"\n✅ Loading complete!")
    print(f"  📊 Processed: {processed_count} files")
    print(f"  ✅ Updated: {updated_count} transcripts")

    # Verify results
    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) as total,
               COUNT(CASE WHEN transcript_text IS NOT NULL AND LENGTH(transcript_text) > 100 THEN 1 END) as with_content
        FROM transcripts
    """)

    result = cursor.fetchone()
    print(f"\n📊 Database Status:")
    print(f"  Total transcripts: {result['total']}")
    print(f"  With content: {result['with_content']}")

    cursor.close()
    conn.close()

if __name__ == "__main__":
    main()