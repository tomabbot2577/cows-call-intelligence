"""
Fathom Meeting Downloader

Downloads meetings from Fathom AI for all configured employees.
Stores unified meeting data in video_meetings table.
"""

import os
import sys
import json
import hashlib
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from .client import FathomClient, FathomMeeting, FathomAPIError
from .key_manager import FathomKeyManager, FathomEmployee

logger = logging.getLogger(__name__)


class FathomDownloader:
    """
    Downloads and stores Fathom meetings for all employees.

    Features:
    - Syncs meetings from all active employees
    - Deduplicates by recording_id and content hash
    - Extracts participants, action items, and CRM matches
    - Tracks sync progress per employee
    """

    def __init__(self, database_url: str = None, hours_back: int = 2):
        """
        Initialize the downloader.

        Args:
            database_url: PostgreSQL connection URL
            hours_back: Hours to look back for new meetings (default 2)
        """
        self.database_url = database_url or os.getenv('RAG_DATABASE_URL')
        if not self.database_url:
            raise ValueError("Database URL is required")

        self.hours_back = hours_back
        self.key_manager = FathomKeyManager(database_url=self.database_url)

        logger.info(f"FathomDownloader initialized (hours_back={hours_back})")

    def _get_connection(self):
        """Get a database connection."""
        return psycopg2.connect(self.database_url)

    def _generate_content_hash(self, meeting: FathomMeeting, transcript: str = None) -> str:
        """Generate a hash to detect duplicate content."""
        content = f"{meeting.recording_id}:{meeting.title}:{meeting.duration_seconds}"
        if transcript:
            content += f":{transcript[:500]}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _is_duplicate(self, recording_id: int, content_hash: str = None) -> bool:
        """Check if meeting already exists in database."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                if content_hash:
                    cur.execute("""
                        SELECT id FROM video_meetings
                        WHERE source = 'fathom' AND (recording_id = %s OR content_hash = %s)
                    """, (recording_id, content_hash))
                else:
                    cur.execute("""
                        SELECT id FROM video_meetings
                        WHERE source = 'fathom' AND recording_id = %s
                    """, (recording_id,))

                return cur.fetchone() is not None
        finally:
            conn.close()

    def _extract_platform(self, meeting: FathomMeeting) -> str:
        """Extract meeting platform from Fathom data."""
        platform = meeting.platform or ''
        platform_lower = platform.lower()

        if 'zoom' in platform_lower:
            return 'zoom'
        elif 'meet' in platform_lower or 'google' in platform_lower:
            return 'google_meet'
        elif 'teams' in platform_lower or 'microsoft' in platform_lower:
            return 'teams'
        else:
            return platform or 'unknown'

    def _classify_meeting_type(self, meeting: FathomMeeting) -> str:
        """Classify meeting type based on participants and title."""
        title_lower = meeting.title.lower() if meeting.title else ''
        participants = meeting.participants or []

        # Check for sales indicators
        if any(word in title_lower for word in ['demo', 'sales', 'prospect', 'pitch']):
            return 'sales'

        # Check for interview indicators
        if any(word in title_lower for word in ['interview', 'candidate']):
            return 'interview'

        # Check for external participants
        has_external = any(
            p.get('is_external', False) or
            p.get('email', '').split('@')[-1] not in ['mainsequence.net', 'mainsequencetechnology.com']
            for p in participants if p.get('email')
        )

        if has_external:
            return 'external'
        else:
            return 'internal'

    def _save_meeting(self, meeting: FathomMeeting, employee: FathomEmployee,
                      transcript: str = None, summary_data: Dict = None) -> Optional[int]:
        """
        Save a meeting to the database.

        Args:
            meeting: FathomMeeting object
            employee: Employee who owns this meeting
            transcript: Full transcript text
            summary_data: AI summary data

        Returns:
            Meeting ID if saved, None if duplicate
        """
        content_hash = self._generate_content_hash(meeting, transcript)

        # Check for duplicates
        if self._is_duplicate(meeting.recording_id, content_hash):
            logger.debug(f"Skipping duplicate meeting {meeting.recording_id}")
            return None

        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                # Insert main meeting record
                cur.execute("""
                    INSERT INTO video_meetings (
                        recording_id, source, title, meeting_type, platform,
                        host_name, host_email, host_team,
                        start_time, duration_seconds,
                        transcript_text, fathom_summary,
                        participants_json, action_items_json, crm_matches_json,
                        content_hash, raw_fathom_data
                    ) VALUES (
                        %s, 'fathom', %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s
                    )
                    RETURNING id
                """, (
                    meeting.recording_id,
                    meeting.title,
                    self._classify_meeting_type(meeting),
                    self._extract_platform(meeting),
                    employee.employee_name,
                    employee.employee_email,
                    employee.team,
                    meeting.created_at,
                    meeting.duration_seconds,
                    transcript,
                    json.dumps(summary_data) if summary_data else None,
                    json.dumps(meeting.participants) if meeting.participants else None,
                    json.dumps(meeting.action_items) if meeting.action_items else None,
                    json.dumps(meeting.crm_matches) if meeting.crm_matches else None,
                    content_hash,
                    json.dumps(meeting.raw_data)
                ))

                meeting_id = cur.fetchone()[0]

                # Insert participants
                self._save_participants(cur, meeting_id, meeting)

                # Insert action items
                self._save_action_items(cur, meeting_id, meeting)

                # Insert CRM deal associations
                self._save_crm_deals(cur, meeting_id, meeting)

                conn.commit()

                logger.info(f"Saved Fathom meeting {meeting.recording_id} -> video_meetings.id={meeting_id}")
                return meeting_id

        except Exception as e:
            conn.rollback()
            logger.error(f"Error saving meeting {meeting.recording_id}: {e}")
            raise
        finally:
            conn.close()

    def _save_participants(self, cur, meeting_id: int, meeting: FathomMeeting):
        """Save participants for a meeting."""
        # Combine participants and calendar invitees
        all_participants = []

        for p in (meeting.participants or []):
            all_participants.append({
                'name': p.get('name', 'Unknown'),
                'email': p.get('email'),
                'is_invitee': False
            })

        for p in (meeting.calendar_invitees or []):
            # Skip if already in participants
            email = p.get('email')
            if email and not any(ap.get('email') == email for ap in all_participants):
                all_participants.append({
                    'name': p.get('name', 'Unknown'),
                    'email': email,
                    'is_invitee': True
                })

        # Get CRM contact info
        crm_contacts = {}
        for contact in meeting.crm_matches.get('contacts', []):
            email = contact.get('email')
            if email:
                crm_contacts[email] = {
                    'name': contact.get('name'),
                    'company': contact.get('company')
                }

        for p in all_participants:
            email = p.get('email', '')
            email_domain = email.split('@')[-1] if email and '@' in email else None

            # Determine if external
            is_external = (
                email_domain and
                email_domain not in ['mainsequence.net', 'mainsequencetechnology.com']
            )

            # Get CRM match if exists
            crm_info = crm_contacts.get(email, {})

            cur.execute("""
                INSERT INTO video_meeting_participants (
                    meeting_id, participant_name, participant_email,
                    participant_email_domain, is_external,
                    crm_contact_name, crm_company_name
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                meeting_id,
                p.get('name', 'Unknown'),
                email if email else None,
                email_domain,
                is_external,
                crm_info.get('name'),
                crm_info.get('company')
            ))

    def _save_action_items(self, cur, meeting_id: int, meeting: FathomMeeting):
        """Save action items for a meeting."""
        for item in (meeting.action_items or []):
            assignee = item.get('assignee', {})

            cur.execute("""
                INSERT INTO video_meeting_action_items (
                    meeting_id, action_text, assignee_name, assignee_email,
                    due_date, priority, is_completed
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                meeting_id,
                item.get('text') or item.get('description', ''),
                assignee.get('name'),
                assignee.get('email'),
                item.get('due_date'),
                item.get('priority', 'medium'),
                item.get('is_completed', False)
            ))

    def _save_crm_deals(self, cur, meeting_id: int, meeting: FathomMeeting):
        """Save CRM deal associations for a meeting."""
        for deal in meeting.crm_matches.get('deals', []):
            cur.execute("""
                INSERT INTO video_meeting_crm_deals (
                    meeting_id, deal_name, deal_stage, deal_value,
                    company_name, close_date, is_primary
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                meeting_id,
                deal.get('name'),
                deal.get('stage'),
                deal.get('value'),
                deal.get('company'),
                deal.get('close_date'),
                deal.get('is_primary', False)
            ))

    def sync_employee(self, employee: FathomEmployee, hours_back: int = None) -> Dict:
        """
        Sync meetings for a single employee.

        Args:
            employee: Employee to sync
            hours_back: Hours to look back (overrides instance default)

        Returns:
            Sync statistics dict
        """
        hours = hours_back or self.hours_back
        stats = {
            'employee': employee.employee_name,
            'meetings_found': 0,
            'meetings_saved': 0,
            'duplicates_skipped': 0,
            'errors': []
        }

        # Get API key
        api_key = self.key_manager.get_api_key(employee.employee_email)
        if not api_key:
            stats['errors'].append("No API key found")
            return stats

        try:
            client = FathomClient(api_key)

            # Calculate start time
            created_after = datetime.now(timezone.utc) - timedelta(hours=hours)

            # List meetings
            meetings = client.list_meetings(created_after=created_after, limit=100)
            stats['meetings_found'] = len(meetings)

            last_recording_id = None

            for meeting in meetings:
                try:
                    # Get transcript
                    transcript_data = client.get_transcript(meeting.recording_id)
                    transcript = transcript_data.get('text') if transcript_data else None

                    # Get summary
                    summary_data = client.get_summary(meeting.recording_id)

                    # Save meeting
                    meeting_id = self._save_meeting(
                        meeting=meeting,
                        employee=employee,
                        transcript=transcript,
                        summary_data=summary_data
                    )

                    if meeting_id:
                        stats['meetings_saved'] += 1
                        last_recording_id = meeting.recording_id
                    else:
                        stats['duplicates_skipped'] += 1

                except Exception as e:
                    stats['errors'].append(f"Meeting {meeting.recording_id}: {str(e)}")
                    logger.error(f"Error processing meeting {meeting.recording_id}: {e}")

            # Update sync status
            if last_recording_id:
                self.key_manager.update_sync_status(
                    employee.employee_email,
                    last_recording_id=last_recording_id
                )

        except FathomAPIError as e:
            stats['errors'].append(f"API error: {e.message}")
            logger.error(f"Fathom API error for {employee.employee_email}: {e}")

        except Exception as e:
            stats['errors'].append(str(e))
            logger.error(f"Error syncing {employee.employee_email}: {e}")

        return stats

    def sync_all_employees(self, hours_back: int = None) -> Dict:
        """
        Sync meetings for all active employees.

        Args:
            hours_back: Hours to look back (overrides instance default)

        Returns:
            Combined sync statistics
        """
        employees = self.key_manager.get_active_employees()

        logger.info(f"Starting Fathom sync for {len(employees)} employees")

        results = {
            'sync_time': datetime.now(timezone.utc).isoformat(),
            'employees_synced': 0,
            'total_meetings_found': 0,
            'total_meetings_saved': 0,
            'total_duplicates_skipped': 0,
            'employee_results': [],
            'errors': []
        }

        for employee in employees:
            logger.info(f"Syncing {employee.employee_name}...")

            stats = self.sync_employee(employee, hours_back=hours_back)
            results['employee_results'].append(stats)

            results['employees_synced'] += 1
            results['total_meetings_found'] += stats['meetings_found']
            results['total_meetings_saved'] += stats['meetings_saved']
            results['total_duplicates_skipped'] += stats['duplicates_skipped']

            if stats['errors']:
                results['errors'].extend(stats['errors'])

        logger.info(f"Fathom sync complete: {results['total_meetings_saved']} new meetings saved")

        return results


def main():
    """Command-line interface for Fathom downloader."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='Fathom Meeting Downloader')
    parser.add_argument('--hours-back', type=int, default=2,
                        help='Hours to look back for meetings (default: 2)')
    parser.add_argument('--employee', type=str,
                        help='Sync specific employee by email')
    parser.add_argument('--all', action='store_true',
                        help='Sync all active employees')

    args = parser.parse_args()

    downloader = FathomDownloader(hours_back=args.hours_back)

    if args.employee:
        employee = downloader.key_manager.get_employee(args.employee)
        if not employee:
            print(f"Employee not found: {args.employee}")
            sys.exit(1)

        results = downloader.sync_employee(employee)
        print(f"\nSync results for {employee.employee_name}:")
        print(f"  Meetings found: {results['meetings_found']}")
        print(f"  Meetings saved: {results['meetings_saved']}")
        print(f"  Duplicates skipped: {results['duplicates_skipped']}")
        if results['errors']:
            print(f"  Errors: {len(results['errors'])}")

    else:
        results = downloader.sync_all_employees()
        print(f"\nFathom Sync Complete:")
        print(f"  Employees synced: {results['employees_synced']}")
        print(f"  Total meetings found: {results['total_meetings_found']}")
        print(f"  Total meetings saved: {results['total_meetings_saved']}")
        print(f"  Duplicates skipped: {results['total_duplicates_skipped']}")

        if results['errors']:
            print(f"\n  Errors ({len(results['errors'])}):")
            for err in results['errors'][:5]:
                print(f"    - {err}")


if __name__ == '__main__':
    main()
