"""
RingCentral Video Sync Job

Syncs video meetings from RingCentral Video API to the database.
Requires Video permission to be enabled on the RingCentral app.
"""

import os
import sys
import json
import hashlib
import logging
import psycopg2
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from pathlib import Path

from .video_client import RCVideoClient, VideoMeeting

logger = logging.getLogger(__name__)


class RCVideoSyncJob:
    """
    Syncs RingCentral Video meetings to the database.

    Features:
    - Syncs meetings from specified time range
    - Enriches participants with phone numbers
    - Deduplicates by meeting_id
    - Queues recordings for transcription
    """

    def __init__(self, database_url: str = None, hours_back: int = 12):
        """
        Initialize the sync job.

        Args:
            database_url: PostgreSQL connection URL
            hours_back: Hours to look back for meetings
        """
        self.database_url = database_url or os.getenv('RAG_DATABASE_URL')
        if not self.database_url:
            raise ValueError("Database URL is required")

        self.hours_back = hours_back
        self.client = None

        logger.info(f"RCVideoSyncJob initialized (hours_back={hours_back})")

    def _get_connection(self):
        """Get database connection."""
        return psycopg2.connect(self.database_url)

    def _generate_content_hash(self, meeting: VideoMeeting) -> str:
        """Generate content hash for deduplication."""
        content = f"{meeting.meeting_id}:{meeting.name}:{meeting.duration_seconds}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _is_duplicate(self, meeting_id: str) -> bool:
        """Check if meeting already exists in database."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id FROM video_meetings
                    WHERE source = 'ringcentral' AND recording_id = %s
                """, (int(meeting_id),))
                return cur.fetchone() is not None
        finally:
            conn.close()

    def _classify_meeting_type(self, meeting: VideoMeeting) -> str:
        """Classify the meeting type."""
        name_lower = meeting.name.lower() if meeting.name else ''

        if any(word in name_lower for word in ['demo', 'sales', 'prospect']):
            return 'sales'
        elif any(word in name_lower for word in ['interview', 'candidate']):
            return 'interview'
        elif any(word in name_lower for word in ['training', 'onboard']):
            return 'training'
        elif any(word in name_lower for word in ['standup', 'team', 'sync']):
            return 'internal'
        else:
            return 'meeting'

    def _save_meeting(self, meeting: VideoMeeting) -> Optional[int]:
        """
        Save a meeting to the database with ALL metadata.

        Args:
            meeting: VideoMeeting object

        Returns:
            Meeting ID if saved, None if duplicate
        """
        if self._is_duplicate(meeting.meeting_id):
            logger.debug(f"Skipping duplicate meeting {meeting.meeting_id}")
            return None

        content_hash = self._generate_content_hash(meeting)

        # Enrich participants with ALL contact info (phone, name, company, etc.)
        enriched_participants = self.client.enrich_participants_with_phone(
            meeting.participants
        )

        # Enrich host with phone numbers if we have extension ID
        host_phone_business = meeting.host_phone_business
        host_phone_mobile = meeting.host_phone_mobile
        host_extension_number = meeting.host_extension_number

        if meeting.host_extension_id and not host_phone_business:
            host_ext = self.client.get_extension(meeting.host_extension_id)
            if host_ext:
                host_phone_business = host_ext.get('phone_business')
                host_phone_mobile = host_ext.get('phone_mobile')
                host_extension_number = host_ext.get('extension_number')

        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                # Insert main meeting record with ALL fields
                cur.execute("""
                    INSERT INTO video_meetings (
                        recording_id, source, title, meeting_type, platform,
                        host_name, host_email, host_phone, host_extension_id,
                        start_time, end_time, duration_seconds,
                        participant_count, has_recording,
                        participants_json, recordings_json, ringcentral_keywords,
                        content_hash, raw_ringcentral_data,
                        meeting_status, chat_id, account_id
                    ) VALUES (
                        %s, 'ringcentral', %s, %s, 'ringcentral_video',
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s
                    )
                    RETURNING id
                """, (
                    meeting.meeting_id,
                    meeting.name,
                    self._classify_meeting_type(meeting),
                    meeting.host_name,
                    meeting.host_email,
                    host_phone_business,
                    meeting.host_extension_id,
                    meeting.start_time,
                    meeting.end_time,
                    meeting.duration_seconds,
                    meeting.participant_count,
                    meeting.has_recording,
                    json.dumps(enriched_participants) if enriched_participants else None,
                    json.dumps(meeting.recordings) if meeting.recordings else None,
                    None,  # ringcentral_keywords - populated later if available
                    content_hash,
                    json.dumps(meeting.raw_data),
                    meeting.status,
                    meeting.chat_id,
                    meeting.account_id
                ))

                meeting_id = cur.fetchone()[0]

                # Insert participants with ALL contact info
                for p in enriched_participants:
                    cur.execute("""
                        INSERT INTO video_meeting_participants (
                            meeting_id, participant_name, participant_email,
                            participant_email_domain, is_external,
                            phone_business, phone_mobile, phone_home,
                            ringcentral_extension_id, extension_number,
                            first_name, last_name,
                            company, department, job_title,
                            role, is_host, device_type,
                            join_time, leave_time, duration_seconds
                        ) VALUES (
                            %s, %s, %s,
                            %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s
                        )
                    """, (
                        meeting_id,
                        p.get('name', 'Unknown'),
                        p.get('email'),
                        p.get('email_domain'),
                        p.get('is_external', True),
                        p.get('phone_business'),
                        p.get('phone_mobile'),
                        p.get('phone_home'),
                        p.get('extension_id'),
                        p.get('extension_number'),
                        p.get('first_name'),
                        p.get('last_name'),
                        p.get('company'),
                        p.get('department'),
                        p.get('job_title'),
                        p.get('role'),
                        p.get('is_host', False),
                        p.get('device_type'),
                        p.get('join_time'),
                        p.get('leave_time'),
                        p.get('duration_seconds')
                    ))

                conn.commit()

                logger.info(f"Saved RC Video meeting {meeting.meeting_id} -> video_meetings.id={meeting_id} "
                           f"({meeting.participant_count} participants)")
                return meeting_id

        except Exception as e:
            conn.rollback()
            logger.error(f"Error saving meeting {meeting.meeting_id}: {e}")
            raise
        finally:
            conn.close()

    def check_permission(self) -> Dict:
        """
        Check if Video API permission is available.

        Returns:
            Permission status dict
        """
        try:
            self.client = RCVideoClient()
            return self.client.check_video_permission()
        except Exception as e:
            return {
                'has_permission': False,
                'message': f'Initialization error: {e}'
            }

    def sync(self, hours_back: int = None) -> Dict:
        """
        Sync video meetings from RingCentral.

        Args:
            hours_back: Hours to look back (overrides instance default)

        Returns:
            Sync statistics
        """
        hours = hours_back or self.hours_back

        stats = {
            'sync_time': datetime.now(timezone.utc).isoformat(),
            'hours_back': hours,
            'meetings_found': 0,
            'meetings_saved': 0,
            'duplicates_skipped': 0,
            'errors': []
        }

        try:
            # Initialize client
            self.client = RCVideoClient()

            # Check permission first
            perm = self.client.check_video_permission()
            if not perm['has_permission']:
                stats['errors'].append(perm['message'])
                logger.warning(f"Video API not available: {perm['message']}")
                return stats

            # Pre-cache all extensions for efficient phone enrichment
            logger.info("Pre-caching extensions for phone enrichment...")
            self.client.get_all_extensions()

            # Calculate time range
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=hours)

            logger.info(f"Syncing meetings from {start_time} to {end_time}")

            # Fetch and save meetings
            for meeting in self.client.get_meeting_history(start_time, end_time):
                stats['meetings_found'] += 1

                try:
                    meeting_id = self._save_meeting(meeting)
                    if meeting_id:
                        stats['meetings_saved'] += 1
                    else:
                        stats['duplicates_skipped'] += 1

                except Exception as e:
                    stats['errors'].append(f"Meeting {meeting.meeting_id}: {str(e)}")
                    logger.error(f"Error saving meeting {meeting.meeting_id}: {e}")

        except Exception as e:
            stats['errors'].append(str(e))
            logger.error(f"Sync failed: {e}")

        logger.info(f"RC Video sync complete: {stats['meetings_saved']} new, "
                    f"{stats['duplicates_skipped']} duplicates")

        return stats

    def sync_recordings(self, limit: int = 100) -> Dict:
        """
        Sync recordings directly from account recordings API.

        This is useful when meeting history is empty but recordings exist.
        Captures host info with full contact details.

        Args:
            limit: Maximum number of recordings to sync

        Returns:
            Sync statistics
        """
        stats = {
            'sync_time': datetime.now(timezone.utc).isoformat(),
            'recordings_found': 0,
            'recordings_saved': 0,
            'duplicates_skipped': 0,
            'errors': []
        }

        try:
            # Initialize client
            self.client = RCVideoClient()

            # Pre-cache all extensions for efficient phone enrichment
            logger.info("Pre-caching extensions for phone enrichment...")
            extensions = self.client.get_all_extensions()
            logger.info(f"Cached {len(extensions)} extensions")

            # Build extension lookup by ID
            ext_lookup = {str(e['id']): e for e in extensions}

            logger.info(f"Syncing up to {limit} recordings...")

            conn = self._get_connection()
            count = 0

            try:
                for recording in self.client.list_account_recordings(per_page=100):
                    if count >= limit:
                        break

                    stats['recordings_found'] += 1
                    count += 1

                    try:
                        # Check for duplicate
                        recording_id = recording.get('id')
                        with conn.cursor() as cur:
                            cur.execute("""
                                SELECT id FROM video_meetings
                                WHERE source = 'ringcentral'
                                AND (source_unique_id = %s OR ringcentral_short_id = %s)
                            """, (recording_id, recording.get('short_id')))

                            if cur.fetchone():
                                stats['duplicates_skipped'] += 1
                                continue

                        # Get host info from raw_data
                        raw_data = recording.get('raw_data', {})
                        host_info = raw_data.get('hostInfo', {})
                        if hasattr(host_info, '__dict__'):
                            host_info = {k: getattr(host_info, k) for k in dir(host_info)
                                        if not k.startswith('_') and not callable(getattr(host_info, k))}

                        host_ext_id = str(host_info.get('extensionId', ''))
                        host_ext = ext_lookup.get(host_ext_id, {})

                        # Parse start time
                        start_time_str = recording.get('start_time')
                        if start_time_str:
                            if isinstance(start_time_str, str):
                                start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                            else:
                                start_time = datetime.now(timezone.utc)
                        else:
                            start_time = datetime.now(timezone.utc)

                        # Get title from display_name (the API field name)
                        title = recording.get('display_name') or recording.get('name', 'RingCentral Recording')
                        meeting_type = self._classify_recording_type(title)

                        with conn.cursor() as cur:
                            cur.execute("""
                                INSERT INTO video_meetings (
                                    source, source_unique_id, ringcentral_short_id,
                                    title, meeting_type, platform,
                                    host_name, host_email, host_phone, host_extension_id,
                                    recording_start_time, start_time, duration_seconds,
                                    has_recording, recording_url, recording_media_url,
                                    recording_status,
                                    raw_ringcentral_data,
                                    created_at, updated_at
                                ) VALUES (
                                    'ringcentral', %s, %s,
                                    %s, %s, 'ringcentral_video',
                                    %s, %s, %s, %s,
                                    %s, %s, %s,
                                    TRUE, %s, %s,
                                    %s,
                                    %s,
                                    NOW(), NOW()
                                )
                                RETURNING id
                            """, (
                                recording_id,
                                recording.get('short_id'),
                                title,
                                meeting_type,
                                host_ext.get('name') or host_info.get('displayName'),
                                host_ext.get('email'),
                                host_ext.get('phone_business'),
                                host_ext_id,
                                start_time,
                                start_time,
                                recording.get('duration', 0),
                                recording.get('url'),
                                recording.get('media_link'),
                                recording.get('status'),
                                json.dumps(raw_data)
                            ))

                            meeting_id = cur.fetchone()[0]

                            # Insert host as participant with full details
                            if host_ext:
                                cur.execute("""
                                    INSERT INTO video_meeting_participants (
                                        meeting_id, source,
                                        participant_name, participant_email,
                                        participant_email_domain, is_external,
                                        phone_business, phone_mobile, phone_home,
                                        ringcentral_extension_id, extension_number,
                                        first_name, last_name,
                                        company, department, job_title,
                                        role, is_host,
                                        created_at
                                    ) VALUES (
                                        %s, 'ringcentral',
                                        %s, %s,
                                        %s, FALSE,
                                        %s, %s, %s,
                                        %s, %s,
                                        %s, %s,
                                        %s, %s, %s,
                                        'host', TRUE,
                                        NOW()
                                    )
                                """, (
                                    meeting_id,
                                    host_ext.get('name'),
                                    host_ext.get('email'),
                                    host_ext.get('email', '').split('@')[-1] if host_ext.get('email') else None,
                                    host_ext.get('phone_business'),
                                    host_ext.get('phone_mobile'),
                                    host_ext.get('phone_home'),
                                    host_ext_id,
                                    host_ext.get('extension_number'),
                                    host_ext.get('first_name'),
                                    host_ext.get('last_name'),
                                    host_ext.get('company'),
                                    host_ext.get('department'),
                                    host_ext.get('job_title')
                                ))

                            conn.commit()
                            stats['recordings_saved'] += 1
                            logger.info(f"Saved recording {recording_id}: {recording.get('name')}")

                    except Exception as e:
                        conn.rollback()
                        stats['errors'].append(f"Recording {recording.get('id')}: {str(e)}")
                        logger.error(f"Error saving recording: {e}")

            finally:
                conn.close()

        except Exception as e:
            stats['errors'].append(str(e))
            logger.error(f"Recording sync failed: {e}")

        logger.info(f"Recording sync complete: {stats['recordings_saved']} new, "
                    f"{stats['duplicates_skipped']} duplicates")

        return stats

    def _classify_recording_type(self, name: str) -> str:
        """Classify recording based on name."""
        name_lower = name.lower() if name else ''

        if any(word in name_lower for word in ['training', 'onboard']):
            return 'training'
        elif any(word in name_lower for word in ['demo', 'sales', 'prospect']):
            return 'sales'
        elif any(word in name_lower for word in ['ticket']):
            return 'support'
        elif any(word in name_lower for word in ['interview', 'candidate']):
            return 'interview'
        else:
            return 'meeting'


def main():
    """Command-line interface for RingCentral Video sync."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Load environment
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))
    from dotenv import load_dotenv
    load_dotenv(project_root / '.env')

    parser = argparse.ArgumentParser(description='RingCentral Video Sync')
    parser.add_argument('--hours-back', type=int, default=12,
                        help='Hours to look back (default: 12)')
    parser.add_argument('--check-only', action='store_true',
                        help='Only check if Video API is accessible')

    args = parser.parse_args()

    sync_job = RCVideoSyncJob(hours_back=args.hours_back)

    if args.check_only:
        perm = sync_job.check_permission()
        print(f"\nVideo API Permission Check:")
        print(f"  Has Permission: {perm['has_permission']}")
        print(f"  Message: {perm['message']}")

        if not perm['has_permission']:
            print("\nTo enable Video API access:")
            print("  1. Go to RingCentral Developer Portal")
            print("  2. Select your app")
            print("  3. Add 'Video' permission")
            print("  4. Regenerate and update JWT token")

        return 0 if perm['has_permission'] else 1

    else:
        results = sync_job.sync()

        print(f"\nRingCentral Video Sync Complete:")
        print(f"  Meetings found: {results['meetings_found']}")
        print(f"  Meetings saved: {results['meetings_saved']}")
        print(f"  Duplicates skipped: {results['duplicates_skipped']}")

        if results['errors']:
            print(f"\n  Errors ({len(results['errors'])}):")
            for err in results['errors'][:5]:
                print(f"    - {err}")

        return 0


if __name__ == '__main__':
    sys.exit(main())
