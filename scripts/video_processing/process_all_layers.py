#!/usr/bin/env python3
"""
Video Meeting AI Layer Processing

Processes video meetings through the 6-layer AI pipeline.

Usage:
    python scripts/video_processing/process_all_layers.py
    python scripts/video_processing/process_all_layers.py --limit 20
    python scripts/video_processing/process_all_layers.py --meeting-id 123

Cron:
    0 */2 * * * /var/www/call-recording-system/scripts/run_video_ai_layers.sh
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(project_root / '.env')

from src.video_processing.base_processor import VideoMeetingProcessor

# Configure logging
log_dir = project_root / 'logs'
log_dir.mkdir(exist_ok=True)

log_file = log_dir / f"video_ai_layers_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='Video Meeting AI Layer Processing')
    parser.add_argument('--limit', type=int, default=10,
                        help='Maximum meetings to process (default: 10)')
    parser.add_argument('--meeting-id', type=int,
                        help='Process specific meeting ID')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be processed without running')

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Video Meeting AI Processing Started")
    logger.info(f"Limit: {args.limit}")
    logger.info("=" * 60)

    try:
        processor = VideoMeetingProcessor()

        if args.meeting_id:
            # Process single meeting
            logger.info(f"Processing single meeting: {args.meeting_id}")

            # Get meeting from database
            import psycopg2
            from psycopg2.extras import RealDictCursor

            conn = psycopg2.connect(os.getenv('RAG_DATABASE_URL'))
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, recording_id, source, title, transcript_text,
                           fathom_summary, participants_json, action_items_json,
                           meeting_type, platform, host_name
                    FROM video_meetings
                    WHERE id = %s
                """, (args.meeting_id,))
                meeting = cur.fetchone()
            conn.close()

            if not meeting:
                logger.error(f"Meeting {args.meeting_id} not found")
                return 1

            if args.dry_run:
                print(f"Would process meeting: {meeting['title']}")
                print(f"  Transcript length: {len(meeting.get('transcript_text', ''))}")
                return 0

            results = processor.process_meeting(dict(meeting))

            logger.info("=" * 60)
            logger.info("Processing Complete")
            logger.info("=" * 60)

            if 'error' in results:
                logger.error(f"Processing failed: {results['error']}")
                return 1
            else:
                logger.info("All 6 layers processed successfully")
                for layer in ['layer1', 'layer2', 'layer3', 'layer4', 'layer5', 'layer6']:
                    if layer in results:
                        logger.info(f"  {layer}: Complete")
                return 0

        else:
            # Process batch
            if args.dry_run:
                meetings = processor.get_pending_meetings(layer=1, limit=args.limit)
                print(f"Would process {len(meetings)} meetings:")
                for m in meetings:
                    print(f"  - {m['id']}: {m['title'][:50]}")
                return 0

            results = processor.process_batch(limit=args.limit)

            logger.info("=" * 60)
            logger.info("Batch Processing Complete")
            logger.info("=" * 60)
            logger.info(f"Processed: {results['processed']}")
            logger.info(f"Successful: {results['successful']}")
            logger.info(f"Failed: {results['failed']}")

            if results['errors']:
                logger.warning(f"Errors: {len(results['errors'])}")
                for err in results['errors'][:10]:
                    logger.warning(f"  - {err}")

            # Save results for monitoring
            results_file = project_root / 'data' / 'scheduler' / 'video_ai_layers_last.json'
            results_file.parent.mkdir(parents=True, exist_ok=True)

            with open(results_file, 'w') as f:
                json.dump({
                    **results,
                    'timestamp': datetime.now().isoformat()
                }, f, indent=2, default=str)

            logger.info(f"Results saved to {results_file}")

            return 0 if results['failed'] == 0 else 1

    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
