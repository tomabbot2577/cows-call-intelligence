"""
Fathom AI API Client

Provides access to Fathom AI video meeting transcripts and summaries.
Implements rate limiting (60 calls/min) and proper error handling.

API Documentation: https://fathom.video/api
"""

import time
import logging
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FathomMeeting:
    """Represents a Fathom meeting record."""
    recording_id: int
    title: str
    created_at: datetime
    duration_seconds: int
    platform: str
    call_type: str
    participants: List[Dict]
    calendar_invitees: List[Dict]
    crm_matches: Dict
    action_items: List[Dict]
    raw_data: Dict


class FathomAPIError(Exception):
    """Exception for Fathom API errors."""

    def __init__(self, message: str, status_code: int = None, response: dict = None):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(self.message)


class FathomRateLimitError(FathomAPIError):
    """Exception for rate limit errors."""
    pass


class FathomClient:
    """
    Client for Fathom AI API.

    Rate limit: 60 calls/minute (enforced with 1.0s delay between calls)

    Usage:
        client = FathomClient(api_key="your-api-key")
        meetings = client.list_meetings(created_after=datetime(2024, 1, 1))
        transcript = client.get_transcript(recording_id=12345)
    """

    BASE_URL = "https://api.fathom.ai/external/v1"
    RATE_LIMIT_DELAY = 1.0  # seconds between requests (60/min = 1/sec)

    def __init__(self, api_key: str, rate_limit_delay: float = None):
        """
        Initialize Fathom client.

        Args:
            api_key: Fathom API key (format: xxx.yyy)
            rate_limit_delay: Optional override for rate limit delay
        """
        if not api_key:
            raise ValueError("Fathom API key is required")

        self.api_key = api_key
        self.rate_limit_delay = rate_limit_delay or self.RATE_LIMIT_DELAY
        self._last_request_time = 0

        self.session = requests.Session()
        self.session.headers.update({
            'X-Api-Key': self.api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })

        logger.info("FathomClient initialized")

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
        self._last_request_time = time.time()

    def _request(self, method: str, endpoint: str, params: dict = None,
                 json_data: dict = None, retry_count: int = 3) -> Dict:
        """
        Make an API request with rate limiting and retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., /calls)
            params: Query parameters
            json_data: JSON body data
            retry_count: Number of retries on failure

        Returns:
            JSON response as dict
        """
        self._rate_limit()

        url = f"{self.BASE_URL}{endpoint}"

        for attempt in range(retry_count):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data,
                    timeout=30
                )

                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 60))
                    logger.warning(f"Rate limited. Waiting {retry_after}s")
                    time.sleep(retry_after)
                    continue

                # Handle other errors
                if response.status_code >= 400:
                    error_data = response.json() if response.text else {}
                    raise FathomAPIError(
                        message=error_data.get('message', f'HTTP {response.status_code}'),
                        status_code=response.status_code,
                        response=error_data
                    )

                return response.json()

            except requests.RequestException as e:
                logger.error(f"Request error (attempt {attempt + 1}): {e}")
                if attempt == retry_count - 1:
                    raise FathomAPIError(f"Request failed after {retry_count} attempts: {e}")
                time.sleep(2 ** attempt)  # Exponential backoff

        raise FathomAPIError("Max retries exceeded")

    def list_meetings(self, created_after: datetime = None,
                      limit: int = 100) -> List[FathomMeeting]:
        """
        List meetings with optional date filter.

        Args:
            created_after: Only return meetings created after this time
            limit: Maximum number of meetings to return

        Returns:
            List of FathomMeeting objects
        """
        meetings = []
        cursor = None
        page_size = min(limit, 50)  # API max per page is typically 50

        while len(meetings) < limit:
            params = {'limit': page_size}

            if created_after:
                # Format as ISO 8601
                if created_after.tzinfo is None:
                    created_after = created_after.replace(tzinfo=timezone.utc)
                params['created_after'] = created_after.isoformat()

            if cursor:
                params['cursor'] = cursor

            logger.debug(f"Fetching meetings page (cursor={cursor})")

            data = self._request('GET', '/meetings', params=params)

            # Parse response - Fathom API structure
            records = data.get('meetings', data.get('calls', data.get('data', [])))
            if not records:
                break

            for record in records:
                meeting = self._parse_meeting(record)
                if meeting:
                    meetings.append(meeting)

            # Check for next page
            cursor = data.get('next_cursor')
            if not cursor:
                break

            # Stop if we've hit the limit
            if len(meetings) >= limit:
                break

        logger.info(f"Retrieved {len(meetings)} meetings from Fathom")
        return meetings[:limit]

    def _parse_meeting(self, data: Dict) -> Optional[FathomMeeting]:
        """Parse raw API data into a FathomMeeting object."""
        try:
            # Parse created_at timestamp
            created_at_str = data.get('created_at') or data.get('createdAt')
            if created_at_str:
                if isinstance(created_at_str, str):
                    # Handle various ISO formats
                    created_at_str = created_at_str.replace('Z', '+00:00')
                    created_at = datetime.fromisoformat(created_at_str)
                else:
                    created_at = datetime.fromtimestamp(created_at_str, tz=timezone.utc)
            else:
                created_at = datetime.now(timezone.utc)

            return FathomMeeting(
                recording_id=data.get('id') or data.get('recording_id'),
                title=data.get('title') or data.get('name', 'Untitled Meeting'),
                created_at=created_at,
                duration_seconds=data.get('duration') or data.get('duration_seconds', 0),
                platform=data.get('platform', 'unknown'),
                call_type=data.get('call_type') or data.get('type', 'meeting'),
                participants=data.get('participants', []),
                calendar_invitees=data.get('calendar_invitees', []),
                crm_matches=data.get('crm_matches', {}),
                action_items=data.get('action_items', []),
                raw_data=data
            )
        except Exception as e:
            logger.error(f"Error parsing meeting: {e}")
            return None

    def get_meeting(self, recording_id: int) -> Optional[FathomMeeting]:
        """
        Get details for a specific meeting.

        Args:
            recording_id: The Fathom recording ID

        Returns:
            FathomMeeting object or None if not found
        """
        try:
            data = self._request('GET', f'/meetings/{recording_id}')
            return self._parse_meeting(data)
        except FathomAPIError as e:
            if e.status_code == 404:
                logger.warning(f"Meeting {recording_id} not found")
                return None
            raise

    def get_transcript(self, recording_id: int) -> Optional[Dict]:
        """
        Get the full transcript for a meeting.

        Args:
            recording_id: The Fathom recording ID

        Returns:
            Transcript data dict with 'text' and 'segments' keys
        """
        try:
            # Try recordings endpoint first, fall back to meetings
            try:
                data = self._request('GET', f'/recordings/{recording_id}/transcript')
            except FathomAPIError:
                data = self._request('GET', f'/meetings/{recording_id}/transcript')

            return {
                'text': data.get('text') or data.get('transcript', ''),
                'segments': data.get('segments', []),
                'raw': data
            }
        except FathomAPIError as e:
            if e.status_code == 404:
                logger.warning(f"Transcript for {recording_id} not found")
                return None
            raise

    def get_summary(self, recording_id: int) -> Optional[Dict]:
        """
        Get the AI-generated summary for a meeting.

        Args:
            recording_id: The Fathom recording ID

        Returns:
            Summary data dict
        """
        try:
            data = self._request('GET', f'/meetings/{recording_id}/summary')
            return {
                'summary': data.get('summary') or data.get('text', ''),
                'key_points': data.get('key_points', []),
                'action_items': data.get('action_items', []),
                'raw': data
            }
        except FathomAPIError as e:
            if e.status_code == 404:
                logger.warning(f"Summary for {recording_id} not found")
                return None
            raise

    def get_action_items(self, recording_id: int) -> List[Dict]:
        """
        Get action items for a meeting.

        Args:
            recording_id: The Fathom recording ID

        Returns:
            List of action item dicts
        """
        try:
            data = self._request('GET', f'/meetings/{recording_id}/action-items')
            return data.get('action_items', data.get('data', []))
        except FathomAPIError as e:
            if e.status_code == 404:
                return []
            raise

    def verify_api_key(self) -> bool:
        """
        Verify that the API key is valid by making a test request.

        Returns:
            True if API key is valid, False otherwise
        """
        try:
            # Try to list meetings with limit=1
            self._request('GET', '/meetings', params={'limit': 1})
            logger.info("Fathom API key verified successfully")
            return True
        except FathomAPIError as e:
            if e.status_code in (401, 403):
                logger.error("Fathom API key is invalid or expired")
                return False
            raise

    def get_user_info(self) -> Optional[Dict]:
        """
        Get information about the authenticated user.

        Returns:
            User info dict or None
        """
        try:
            data = self._request('GET', '/user')
            return data
        except FathomAPIError:
            return None
