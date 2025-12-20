#!/usr/bin/env python3
"""
Process recordings with proper RingCentral metadata integration.
"""

import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict
from dotenv import load_dotenv

load_dotenv("/var/www/call-recording-system/.env")
sys.path.insert(0, "/var/www/call-recording-system")

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DB_CONFIG = {
    "dbname": "call_insights",
    "user": "call_insights_user", 
    "password": "call_insights_pass",
    "host": "localhost",
    "port": 5432
}

class MetadataProcessor:
    def __init__(self):
        self.metadata_cache = self._load_metadata()
        logger.info(f"Loaded {len(self.metadata_cache)} metadata records")

    def _load_metadata(self) -> Dict[str, Dict]:
        metadata = {}
        downloads_file = Path("/var/www/call-recording-system/data/recordings_to_download.json")
        if downloads_file.exists():
            with open(downloads_file) as f:
                for rec in json.load(f):
                    rec_id = str(rec.get("id", ""))
                    if rec_id:
                        metadata[rec_id] = {
                            "duration": rec.get("duration", 0),
                            "start_time": rec.get("start_time", ""),
                            "from_name": rec.get("from", "Unknown"),
                            "to_name": rec.get("to", "Unknown"),
                            "direction": rec.get("direction", "Unknown")
                        }
        return metadata

    def parse_start_time(self, start_time: str):
        if not start_time:
            return None, None
        try:
            dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            return dt.date(), dt.time()
        except:
            return None, None

    def update_transcript_metadata(self, recording_id: str) -> bool:
        metadata = self.metadata_cache.get(recording_id, {})
        if not metadata:
            return False
        call_date, call_time = self.parse_start_time(metadata.get("start_time", ""))
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            cur.execute("""
                UPDATE transcripts SET
                    call_date = %s, call_time = %s, duration_seconds = %s, direction = %s, updated_at = NOW()
                WHERE recording_id = %s
            """, (call_date, call_time, metadata.get("duration", 0), metadata.get("direction"), recording_id))
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB error for {recording_id}: {e}")
            return False

    def update_all_missing_metadata(self):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            cur.execute("""
                SELECT recording_id FROM transcripts
                WHERE (call_date IS NULL OR direction IS NULL OR direction = %s)
                AND transcript_text IS NOT NULL
            """, ("Unknown",))
            missing = cur.fetchall()
            cur.close()
            conn.close()
            logger.info(f"Found {len(missing)} transcripts with missing metadata")
            updated = 0
            for (recording_id,) in missing:
                if self.update_transcript_metadata(recording_id):
                    updated += 1
            logger.info(f"Updated {updated}/{len(missing)} transcripts")
            return updated
        except Exception as e:
            logger.error(f"Error: {e}")
            return 0

    def verify_metadata_coverage(self):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) as total,
                    COUNT(call_date) as with_date,
                    COUNT(CASE WHEN direction IS NOT NULL AND direction NOT IN (%s, %s) THEN 1 END) as with_direction
                FROM transcripts WHERE transcript_text IS NOT NULL
            """, ("unknown", "Unknown"))
            result = cur.fetchone()
            cur.close()
            conn.close()
            print(f"\nMETADATA COVERAGE:")
            print(f"  Total transcripts: {result[0]}")
            print(f"  With call_date:    {result[1]} ({100*result[1]/result[0]:.1f}%)" if result[0] else "N/A")
            print(f"  With direction:    {result[2]} ({100*result[2]/result[0]:.1f}%)" if result[0] else "N/A")
        except Exception as e:
            logger.error(f"Error: {e}")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--update-all", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    
    processor = MetadataProcessor()
    if args.update_all:
        processor.update_all_missing_metadata()
        processor.verify_metadata_coverage()
    else:
        processor.verify_metadata_coverage()

if __name__ == "__main__":
    main()
