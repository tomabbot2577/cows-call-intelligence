"""
RingCentral Video API Client

Provides access to RingCentral Video meeting history and recordings.
Requires the "Video" permission to be added to the RingCentral app.

NOTE: As of Dec 2025, the RingCentral app needs the Video permission
added via the Developer Portal before this client can be used.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Generator
from dataclasses import dataclass

from ringcentral import SDK

logger = logging.getLogger(__name__)


@dataclass
class VideoMeeting:
    """Represents a RingCentral Video meeting with full metadata."""
    meeting_id: str
    name: str
    start_time: datetime
    end_time: Optional[datetime]
    duration_seconds: int
    host_id: str
    host_name: Optional[str]
    host_email: Optional[str]
    host_extension_id: Optional[str]
    host_extension_number: Optional[str]
    host_phone_business: Optional[str]
    host_phone_mobile: Optional[str]
    meeting_type: str
    status: str
    chat_id: Optional[str]
    account_id: Optional[str]
    participants: List[Dict]
    participant_count: int
    has_recording: bool
    recording_id: Optional[str]
    recordings: List[Dict]
    raw_data: Dict


class RCVideoClient:
    """
    Client for RingCentral Video API.

    Provides access to:
    - Video meeting history
    - Meeting details and participants
    - Recording access
    - Extension lookup for phone enrichment
    """

    def __init__(self, jwt_token: str = None):
        """
        Initialize the RingCentral Video client.

        Args:
            jwt_token: RingCentral JWT token (or from env)
        """
        self.client_id = os.getenv('RC_CLIENT_ID') or os.getenv('RINGCENTRAL_CLIENT_ID')
        self.client_secret = os.getenv('RC_CLIENT_SECRET') or os.getenv('RINGCENTRAL_CLIENT_SECRET')
        self.jwt_token = jwt_token or os.getenv('RC_JWT_TOKEN') or os.getenv('RINGCENTRAL_JWT_TOKEN')
        self.server_url = os.getenv('RC_SERVER_URL') or os.getenv('RINGCENTRAL_SERVER_URL', 'https://platform.ringcentral.com')

        if not all([self.client_id, self.client_secret, self.jwt_token]):
            raise ValueError("Missing RingCentral credentials")

        self.sdk = SDK(self.client_id, self.client_secret, self.server_url)
        self.platform = self.sdk.platform()
        self.platform.login(jwt=self.jwt_token)

        # Cache for extension data
        self._extension_cache = {}

        logger.info("RCVideoClient initialized")

    def _safe_get(self, obj, attr, default=None):
        """Safely get attribute from JsonObject or dict."""
        if obj is None:
            return default
        if hasattr(obj, attr):
            val = getattr(obj, attr, default)
            return val if val is not None else default
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return default

    def check_video_permission(self) -> Dict:
        """
        Check if the Video permission is available.

        Returns:
            Dict with permission status and message
        """
        try:
            response = self.platform.get('/rcvideo/v1/history/meetings', {'limit': 1})
            return {
                'has_permission': True,
                'message': 'Video API accessible'
            }
        except Exception as e:
            error_str = str(e)
            if 'InsufficientPermissions' in error_str or 'CMN-401' in error_str:
                return {
                    'has_permission': False,
                    'message': 'Video permission required. Add "Video" permission in RingCentral Developer Portal.'
                }
            else:
                return {
                    'has_permission': False,
                    'message': f'Error: {error_str}'
                }

    def get_meeting_history(self, start_time: datetime = None,
                            end_time: datetime = None,
                            per_page: int = 25) -> Generator[VideoMeeting, None, None]:
        """
        Get video meeting history.

        Args:
            start_time: Start of time range
            end_time: End of time range
            per_page: Results per page

        Yields:
            VideoMeeting objects
        """
        if not start_time:
            start_time = datetime.now(timezone.utc) - timedelta(days=30)
        if not end_time:
            end_time = datetime.now(timezone.utc)

        page_token = None

        while True:
            # RingCentral Video API expects Unix timestamps in milliseconds
            params = {
                'startTime': int(start_time.timestamp() * 1000),
                'endTime': int(end_time.timestamp() * 1000),
                'perPage': per_page
            }

            if page_token:
                params['pageToken'] = page_token

            try:
                response = self.platform.get('/rcvideo/v1/history/meetings', params)
                data = response.json()

                records = self._safe_get(data, 'records', [])

                for record in records:
                    meeting = self._parse_meeting(record)
                    if meeting:
                        yield meeting

                # Check for next page
                paging = self._safe_get(data, 'paging', {})
                page_token = self._safe_get(paging, 'pageToken')

                if not page_token or not records:
                    break

            except Exception as e:
                logger.error(f"Error fetching meeting history: {e}")
                raise

    def _parse_meeting(self, data) -> Optional[VideoMeeting]:
        """Parse raw API data into a VideoMeeting object with full metadata."""
        try:
            # Parse start time
            start_time_str = self._safe_get(data, 'startTime')
            if start_time_str:
                if isinstance(start_time_str, str):
                    start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                elif isinstance(start_time_str, (int, float)):
                    # Handle Unix timestamp in milliseconds
                    start_time = datetime.fromtimestamp(start_time_str / 1000, tz=timezone.utc)
                else:
                    start_time = datetime.fromtimestamp(start_time_str, tz=timezone.utc)
            else:
                start_time = datetime.now(timezone.utc)

            # Parse end time
            end_time_str = self._safe_get(data, 'endTime')
            if end_time_str:
                if isinstance(end_time_str, str):
                    end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                elif isinstance(end_time_str, (int, float)):
                    end_time = datetime.fromtimestamp(end_time_str / 1000, tz=timezone.utc)
                else:
                    end_time = datetime.fromtimestamp(end_time_str, tz=timezone.utc)
            else:
                end_time = None

            # Get participants with ALL metadata
            participants = []
            raw_participants = self._safe_get(data, 'participants', [])
            for p in raw_participants:
                participant = {
                    'id': self._safe_get(p, 'id'),
                    'name': self._safe_get(p, 'name'),
                    'email': self._safe_get(p, 'email'),
                    'extension_id': self._safe_get(p, 'extensionId'),
                    'role': self._safe_get(p, 'role'),  # host, participant, etc.
                    'is_host': self._safe_get(p, 'isHost', False),
                    'device_type': self._safe_get(p, 'deviceType'),
                    'join_time': self._safe_get(p, 'joinTime'),
                    'leave_time': self._safe_get(p, 'leaveTime'),
                    # Phone fields will be enriched later
                    'phone_business': None,
                    'phone_mobile': None,
                    'phone_home': None,
                    'extension_number': None,
                    'first_name': None,
                    'last_name': None,
                    'company': None,
                    'department': None,
                    'job_title': None
                }
                participants.append(participant)

            # Get recordings with full metadata
            raw_recordings = self._safe_get(data, 'recordings', [])
            recordings = []
            for r in raw_recordings:
                recordings.append({
                    'id': self._safe_get(r, 'id'),
                    'name': self._safe_get(r, 'name'),
                    'start_time': self._safe_get(r, 'startTime'),
                    'duration': self._safe_get(r, 'duration'),
                    'status': self._safe_get(r, 'status'),
                    'size': self._safe_get(r, 'size'),
                    'content_uri': self._safe_get(r, 'contentUri'),
                    'download_uri': self._safe_get(r, 'downloadUri')
                })

            has_recording = len(recordings) > 0
            recording_id = recordings[0]['id'] if recordings else None

            # Get host extension ID for phone enrichment
            host_id = self._safe_get(data, 'hostId')
            host_extension_id = self._safe_get(data, 'hostExtensionId') or host_id

            return VideoMeeting(
                meeting_id=str(self._safe_get(data, 'id')),
                name=self._safe_get(data, 'name', 'Untitled Meeting'),
                start_time=start_time,
                end_time=end_time,
                duration_seconds=self._safe_get(data, 'duration', 0),
                host_id=str(host_id) if host_id else '',
                host_name=self._safe_get(data, 'hostName'),
                host_email=self._safe_get(data, 'hostEmail'),
                host_extension_id=str(host_extension_id) if host_extension_id else None,
                host_extension_number=None,  # Will be enriched
                host_phone_business=None,    # Will be enriched
                host_phone_mobile=None,      # Will be enriched
                meeting_type=self._safe_get(data, 'type', 'meeting'),
                status=self._safe_get(data, 'status', 'unknown'),
                chat_id=self._safe_get(data, 'chatId'),
                account_id=self._safe_get(data, 'accountId'),
                participants=participants,
                participant_count=len(participants),
                has_recording=has_recording,
                recording_id=recording_id,
                recordings=recordings,
                raw_data=self._to_dict(data)
            )

        except Exception as e:
            logger.error(f"Error parsing meeting: {e}")
            return None

    def _to_dict(self, obj) -> Dict:
        """Convert JsonObject to dict recursively."""
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, list):
            return [self._to_dict(item) for item in obj]
        if isinstance(obj, dict):
            return {k: self._to_dict(v) for k, v in obj.items()}

        result = {}
        for attr in dir(obj):
            if not attr.startswith('_'):
                try:
                    val = getattr(obj, attr)
                    if not callable(val):
                        result[attr] = self._to_dict(val)
                except:
                    pass
        return result

    def get_meeting(self, meeting_id: str) -> Optional[VideoMeeting]:
        """
        Get details for a specific meeting.

        Args:
            meeting_id: The meeting ID

        Returns:
            VideoMeeting object or None
        """
        try:
            response = self.platform.get(f'/rcvideo/v1/history/meetings/{meeting_id}')
            data = response.json()
            return self._parse_meeting(data)
        except Exception as e:
            logger.error(f"Error fetching meeting {meeting_id}: {e}")
            return None

    def get_recording_url(self, recording_id: str) -> Optional[str]:
        """
        Get download URL for a recording.

        Args:
            recording_id: The recording ID

        Returns:
            URL to download recording or None
        """
        try:
            response = self.platform.get(f'/rcvideo/v1/recordings/{recording_id}')
            data = response.json()
            return self._safe_get(data, 'downloadUrl')
        except Exception as e:
            logger.error(f"Error getting recording URL: {e}")
            return None

    def get_extension(self, extension_id: str) -> Optional[Dict]:
        """
        Get extension details with ALL contact information.

        This method works even without Video permission.

        Args:
            extension_id: RingCentral extension ID

        Returns:
            Extension details with all contact fields
        """
        # Check cache first
        if extension_id in self._extension_cache:
            return self._extension_cache[extension_id]

        try:
            response = self.platform.get(f'/restapi/v1.0/account/~/extension/{extension_id}')
            data = response.json()

            # Get contact info
            contact = self._safe_get(data, 'contact', {})

            ext_info = {
                # Extension info
                'id': self._safe_get(data, 'id'),
                'name': self._safe_get(data, 'name'),
                'extension_number': self._safe_get(data, 'extensionNumber'),
                'type': self._safe_get(data, 'type'),
                'status': self._safe_get(data, 'status'),
                # Contact - Names
                'first_name': self._safe_get(contact, 'firstName'),
                'last_name': self._safe_get(contact, 'lastName'),
                'email': self._safe_get(contact, 'email'),
                # Contact - Phone numbers
                'phone_business': self._safe_get(contact, 'businessPhone'),
                'phone_mobile': self._safe_get(contact, 'mobilePhone'),
                'phone_home': self._safe_get(contact, 'homePhone'),
                # Contact - Company info
                'company': self._safe_get(contact, 'company'),
                'department': self._safe_get(contact, 'department'),
                'job_title': self._safe_get(contact, 'jobTitle'),
                # Contact - Address
                'business_address': self._safe_get(contact, 'businessAddress'),
                'home_address': self._safe_get(contact, 'homeAddress'),
            }

            # Cache the result
            self._extension_cache[extension_id] = ext_info
            return ext_info

        except Exception as e:
            logger.warning(f"Error fetching extension {extension_id}: {e}")
            return None

    def get_all_extensions(self, limit: int = 100) -> List[Dict]:
        """
        Get all extensions for the account with ALL contact info.

        This method works even without Video permission.

        Args:
            limit: Maximum number of extensions to fetch

        Returns:
            List of extension info dicts with full contact details
        """
        extensions = []

        try:
            response = self.platform.get('/restapi/v1.0/account/~/extension',
                                         {'perPage': min(limit, 100)})
            data = response.json()

            records = self._safe_get(data, 'records', [])

            for ext in records:
                contact = self._safe_get(ext, 'contact', {})

                ext_info = {
                    # Extension info
                    'id': self._safe_get(ext, 'id'),
                    'name': self._safe_get(ext, 'name'),
                    'extension_number': self._safe_get(ext, 'extensionNumber'),
                    'type': self._safe_get(ext, 'type'),
                    'status': self._safe_get(ext, 'status'),
                    # Contact - Names
                    'first_name': self._safe_get(contact, 'firstName'),
                    'last_name': self._safe_get(contact, 'lastName'),
                    'email': self._safe_get(contact, 'email'),
                    # Contact - Phone numbers
                    'phone_business': self._safe_get(contact, 'businessPhone'),
                    'phone_mobile': self._safe_get(contact, 'mobilePhone'),
                    'phone_home': self._safe_get(contact, 'homePhone'),
                    # Contact - Company info
                    'company': self._safe_get(contact, 'company'),
                    'department': self._safe_get(contact, 'department'),
                    'job_title': self._safe_get(contact, 'jobTitle'),
                }

                extensions.append(ext_info)

                # Cache for later use
                if ext_info['id']:
                    self._extension_cache[str(ext_info['id'])] = ext_info

            logger.info(f"Retrieved {len(extensions)} extensions")

        except Exception as e:
            logger.error(f"Error fetching extensions: {e}")

        return extensions

    def enrich_participants_with_phone(self, participants: List[Dict]) -> List[Dict]:
        """
        Enrich participant list with ALL contact info from extensions.

        Adds:
        - Phone numbers (business, mobile, home)
        - Names (first, last)
        - Company info (company, department, job title)
        - Extension number
        - Duration (calculated from join/leave times)

        Args:
            participants: List of participant dicts with optional extension_id

        Returns:
            Enriched participant list with all available data
        """
        for p in participants:
            # Calculate participant duration from join/leave times
            join_time = p.get('join_time')
            leave_time = p.get('leave_time')
            if join_time and leave_time:
                try:
                    # Parse timestamps and calculate duration
                    if isinstance(join_time, str):
                        join_dt = datetime.fromisoformat(join_time.replace('Z', '+00:00'))
                    elif isinstance(join_time, (int, float)):
                        join_dt = datetime.fromtimestamp(join_time / 1000, tz=timezone.utc)
                    else:
                        join_dt = None

                    if isinstance(leave_time, str):
                        leave_dt = datetime.fromisoformat(leave_time.replace('Z', '+00:00'))
                    elif isinstance(leave_time, (int, float)):
                        leave_dt = datetime.fromtimestamp(leave_time / 1000, tz=timezone.utc)
                    else:
                        leave_dt = None

                    if join_dt and leave_dt:
                        p['duration_seconds'] = int((leave_dt - join_dt).total_seconds())
                except Exception:
                    p['duration_seconds'] = None
            else:
                p['duration_seconds'] = None

            # Enrich with extension data
            ext_id = p.get('extension_id')
            if ext_id:
                ext_info = self.get_extension(str(ext_id))
                if ext_info:
                    # Phone numbers
                    p['phone_business'] = ext_info.get('phone_business')
                    p['phone_mobile'] = ext_info.get('phone_mobile')
                    p['phone_home'] = ext_info.get('phone_home')
                    # Extension
                    p['extension_number'] = ext_info.get('extension_number')
                    # Names
                    p['first_name'] = ext_info.get('first_name')
                    p['last_name'] = ext_info.get('last_name')
                    # Company info
                    p['company'] = ext_info.get('company')
                    p['department'] = ext_info.get('department')
                    p['job_title'] = ext_info.get('job_title')
                    # Fill in email if missing
                    if not p.get('email'):
                        p['email'] = ext_info.get('email')
                    # Fill in name if missing
                    if not p.get('name'):
                        p['name'] = ext_info.get('name')

            # Calculate email domain for external detection
            email = p.get('email')
            if email and '@' in email:
                p['email_domain'] = email.split('@')[-1].lower()
                # Mark as internal if mainsequence domain
                internal_domains = ['mainsequence.net', 'mainsequencetechnology.com']
                p['is_internal'] = p['email_domain'] in internal_domains
                p['is_external'] = not p['is_internal']
            else:
                p['email_domain'] = None
                p['is_internal'] = None
                p['is_external'] = None

        return participants

    def list_account_recordings(self, per_page: int = 25,
                                 page_token: str = None) -> Generator[Dict, None, None]:
        """
        List all recordings owned by users in the account.

        Endpoint: GET /rcvideo/v1/account/~/recordings
        Requires: Video permission

        Args:
            per_page: Number of items per page
            page_token: Token for pagination

        Yields:
            Recording dicts
        """
        current_token = page_token

        while True:
            params = {'perPage': per_page}
            if current_token:
                params['pageToken'] = current_token

            try:
                response = self.platform.get('/rcvideo/v1/account/~/recordings', params)
                data = response.json()

                recordings = self._safe_get(data, 'recordings', [])

                for recording in recordings:
                    yield self._parse_recording(recording)

                # Check for next page
                paging = self._safe_get(data, 'paging', {})
                current_token = self._safe_get(paging, 'pageToken')

                if not current_token or not recordings:
                    break

            except Exception as e:
                logger.error(f"Error listing account recordings: {e}")
                raise

    def list_user_recordings(self, extension_id: str = '~',
                             per_page: int = 25,
                             page_token: str = None) -> Generator[Dict, None, None]:
        """
        List recordings owned by a specific user/extension.

        Endpoint: GET /rcvideo/v1/account/~/extension/{extensionId}/recordings
        Requires: Video permission

        Args:
            extension_id: Extension ID (~ for current user)
            per_page: Number of items per page
            page_token: Token for pagination

        Yields:
            Recording dicts
        """
        current_token = page_token

        while True:
            params = {'perPage': per_page}
            if current_token:
                params['pageToken'] = current_token

            try:
                response = self.platform.get(
                    f'/rcvideo/v1/account/~/extension/{extension_id}/recordings',
                    params
                )
                data = response.json()

                recordings = self._safe_get(data, 'recordings', [])

                for recording in recordings:
                    yield self._parse_recording(recording)

                # Check for next page
                paging = self._safe_get(data, 'paging', {})
                current_token = self._safe_get(paging, 'pageToken')

                if not current_token or not recordings:
                    break

            except Exception as e:
                logger.error(f"Error listing user recordings: {e}")
                raise

    def _parse_recording(self, data) -> Dict:
        """Parse a recording object into a dict."""
        # API returns 'displayName' not 'name'
        display_name = self._safe_get(data, 'displayName')
        name = display_name or self._safe_get(data, 'name', 'Untitled Recording')

        return {
            'id': self._safe_get(data, 'id'),
            'short_id': self._safe_get(data, 'shortId'),
            'name': name,
            'display_name': display_name,
            'meeting_id': self._safe_get(data, 'meetingId'),
            'start_time': self._safe_get(data, 'startTime'),
            'duration': self._safe_get(data, 'duration', 0),
            'size': self._safe_get(data, 'size', 0),
            'status': self._safe_get(data, 'status'),
            'url': self._safe_get(data, 'url'),
            'media_link': self._safe_get(data, 'mediaLink'),
            'expires_in': self._safe_get(data, 'expiresIn'),
            'content_uri': self._safe_get(data, 'contentUri'),
            'download_uri': self._safe_get(data, 'downloadUri'),
            'owner_id': self._safe_get(data, 'ownerId'),
            'owner_extension_id': self._safe_get(data, 'ownerExtensionId'),
            'host_info': self._safe_get(data, 'hostInfo'),
            'raw_data': self._to_dict(data)
        }

    def get_recording(self, recording_id: str) -> Optional[Dict]:
        """
        Get details for a specific recording.

        Args:
            recording_id: The recording ID

        Returns:
            Recording dict or None
        """
        try:
            response = self.platform.get(f'/rcvideo/v1/recordings/{recording_id}')
            data = response.json()
            return self._parse_recording(data)
        except Exception as e:
            logger.error(f"Error fetching recording {recording_id}: {e}")
            return None

    def download_recording(self, recording_id: str, output_path: str,
                            media_link: str = None,
                            media_url: str = None) -> Optional[str]:
        """
        Download a recording to a file.

        Args:
            recording_id: The recording ID
            output_path: Path to save the file
            media_link: Optional relative media link (from stored raw data)
            media_url: Optional full media URL (from stored raw data->url)

        Returns:
            Path to downloaded file or None
        """
        import requests

        try:
            # Option 1: Use full media URL with authenticated request
            if media_url and media_url.startswith('https://media.ringcentral.com'):
                logger.info(f"Downloading from media URL: {media_url[:60]}...")

                # Get access token from SDK
                token = self.platform.auth().access_token()

                headers = {
                    'Authorization': f'Bearer {token}',
                    'User-Agent': 'RCVideoClient/1.0'
                }

                response = requests.get(media_url, headers=headers, stream=True, timeout=300)

                if response.status_code == 200:
                    with open(output_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)

                    file_size = os.path.getsize(output_path)
                    logger.info(f"Downloaded recording {recording_id} to {output_path} ({file_size} bytes)")
                    return output_path
                else:
                    logger.error(f"Media URL returned {response.status_code}: {response.text[:200]}")

            # Option 2: Use relative media link with SDK
            download_uri = media_link

            # If no media_link provided, try to look up from API
            if not download_uri:
                recording = self.get_recording(recording_id)
                if not recording:
                    logger.error(f"Recording {recording_id} not found")
                    return None

                download_uri = recording.get('download_uri') or recording.get('content_uri')

            if not download_uri:
                logger.error(f"No download URL for recording {recording_id}")
                return None

            logger.info(f"Downloading from SDK: {download_uri[:50]}...")

            # Download the content via SDK
            response = self.platform.get(download_uri)

            with open(output_path, 'wb') as f:
                f.write(response.body())

            file_size = os.path.getsize(output_path)
            logger.info(f"Downloaded recording {recording_id} to {output_path} ({file_size} bytes)")
            return output_path

        except Exception as e:
            logger.error(f"Error downloading recording {recording_id}: {e}")
            return None
