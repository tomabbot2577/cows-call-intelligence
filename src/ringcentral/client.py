"""
RingCentral API Client
Main client for interacting with RingCentral REST API
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Generator
from urllib.parse import urljoin, urlencode, urlparse, parse_qs

import requests
from requests.adapters import HTTPAdapter
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

from .auth import RingCentralAuth
from .rate_limiter import AdaptiveRateLimiter
from .exceptions import (
    RingCentralAPIError,
    RateLimitError,
    RecordingNotFoundError,
    TokenExpiredError
)

logger = logging.getLogger(__name__)


class RingCentralClient:
    """
    Main client for RingCentral API operations
    """

    # API Version
    API_VERSION = "v1.0"

    # Endpoints
    ENDPOINTS = {
        'company_call_log': '/restapi/v1.0/account/~/call-log',
        'extension_call_log': '/restapi/v1.0/account/~/extension/~/call-log',
        'recording_metadata': '/restapi/v1.0/account/{accountId}/recording/{recordingId}',
        'recording_content': '/restapi/v1.0/account/{accountId}/recording/{recordingId}/content',
    }

    def __init__(
        self,
        auth: Optional[RingCentralAuth] = None,
        jwt_token: Optional[str] = None,
        sandbox: bool = False,
        timeout: int = 30,
        max_retries: int = 3
    ):
        """
        Initialize RingCentral API client

        Args:
            auth: Pre-configured RingCentralAuth instance
            jwt_token: JWT token for authentication
            sandbox: Whether to use sandbox environment
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
        """
        # Initialize authentication
        if auth:
            self.auth = auth
        else:
            self.auth = RingCentralAuth(
                jwt_token=jwt_token,
                sandbox=sandbox,
                timeout=timeout,
                max_retries=max_retries
            )

        self.timeout = timeout
        self.rate_limiter = AdaptiveRateLimiter()

        # Setup session
        self.session = requests.Session()
        adapter = HTTPAdapter(max_retries=max_retries)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        logger.info("RingCentralClient initialized")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((requests.RequestException, TokenExpiredError)),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        stream: bool = False
    ) -> requests.Response:
        """
        Make HTTP request to RingCentral API with retry logic

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint
            params: Query parameters
            data: Request body data
            stream: Whether to stream response

        Returns:
            Response object

        Raises:
            RingCentralAPIError: On API errors
            RateLimitError: On rate limit exceeded
        """
        # Check rate limit reset period
        reset_wait = self.rate_limiter.check_rate_limit_reset(endpoint)
        if reset_wait:
            import time
            time.sleep(reset_wait)

        # Apply rate limiting
        self.rate_limiter.wait_if_needed(endpoint)

        # Build URL
        url = urljoin(self.auth.base_url, endpoint)

        # Get headers
        headers = self.auth.get_auth_headers()
        if data and not stream:
            headers['Content-Type'] = 'application/json'

        try:
            logger.debug(f"{method} {url}")

            response = self.session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                data=json.dumps(data) if data else None,
                timeout=self.timeout,
                stream=stream
            )

            # Handle rate limiting
            if response.status_code == 429:
                retry_after = self.rate_limiter.handle_rate_limit_response(
                    endpoint,
                    response.status_code,
                    response.headers
                )
                self.rate_limiter.update_adaptive_limit(endpoint, False)

                raise RateLimitError(
                    "Rate limit exceeded",
                    retry_after=retry_after,
                    status_code=429,
                    response_data={'headers': dict(response.headers)}
                )

            # Handle token expiration
            if response.status_code == 401:
                logger.warning("Token expired, attempting refresh")
                self.auth.access_token = None  # Clear token to force refresh
                raise TokenExpiredError(
                    "Access token expired",
                    status_code=401
                )

            # Handle not found
            if response.status_code == 404:
                raise RecordingNotFoundError(
                    f"Resource not found: {endpoint}",
                    status_code=404
                )

            # Handle other errors
            if response.status_code >= 400:
                error_data = {}
                try:
                    error_data = response.json()
                except:
                    pass

                raise RingCentralAPIError(
                    f"API error: {response.status_code}",
                    status_code=response.status_code,
                    response_data=error_data
                )

            # Update adaptive rate limiting on success
            self.rate_limiter.update_adaptive_limit(endpoint, True)

            return response

        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise RingCentralAPIError(f"Request failed: {e}")

    def get_call_log(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        per_page: int = 100,
        page: Optional[int] = None,
        recording_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get call log records

        Args:
            date_from: Start date for call records
            date_to: End date for call records
            per_page: Number of records per page (max 100)
            page: Page number
            recording_type: Filter by recording type ('Automatic', 'OnDemand', 'All')

        Returns:
            Call log response with records
        """
        endpoint = self.ENDPOINTS['company_call_log']

        params = {
            'perPage': min(per_page, 100),
            'view': 'Detailed',
            'recordingType': recording_type or 'All'
        }

        if date_from:
            params['dateFrom'] = date_from.strftime('%Y-%m-%dT%H:%M:%S.000Z')

        if date_to:
            params['dateTo'] = date_to.strftime('%Y-%m-%dT%H:%M:%S.000Z')

        if page:
            params['page'] = page

        response = self._make_request('GET', endpoint, params=params)
        return response.json()

    def get_all_call_logs(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        recording_type: Optional[str] = None
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Get all call logs with pagination

        Args:
            date_from: Start date for call records
            date_to: End date for call records
            recording_type: Filter by recording type

        Yields:
            Individual call log records
        """
        page = 1
        has_more = True

        while has_more:
            logger.info(f"Fetching call log page {page}")

            result = self.get_call_log(
                date_from=date_from,
                date_to=date_to,
                page=page,
                recording_type=recording_type
            )

            records = result.get('records', [])

            for record in records:
                # Only yield records with recordings
                if record.get('recording'):
                    yield record

            # Check for more pages
            navigation = result.get('navigation', {})
            has_more = 'nextPage' in navigation

            page += 1

            # Safety check to prevent infinite loops
            if page > 1000:
                logger.warning("Reached maximum page limit")
                break

    def get_recording_metadata(
        self,
        recording_id: str,
        account_id: str = '~'
    ) -> Dict[str, Any]:
        """
        Get recording metadata

        Args:
            recording_id: Recording ID
            account_id: Account ID (default: current account)

        Returns:
            Recording metadata
        """
        endpoint = self.ENDPOINTS['recording_metadata'].format(
            accountId=account_id,
            recordingId=recording_id
        )

        response = self._make_request('GET', endpoint)
        return response.json()

    def download_recording(
        self,
        recording_id: str,
        account_id: str = '~',
        output_path: Optional[str] = None
    ) -> str:
        """
        Download a call recording

        Args:
            recording_id: Recording ID
            account_id: Account ID (default: current account)
            output_path: Path to save recording (optional)

        Returns:
            Path to downloaded file

        Raises:
            RecordingNotFoundError: If recording not found
            RingCentralAPIError: On download errors
        """
        endpoint = self.ENDPOINTS['recording_content'].format(
            accountId=account_id,
            recordingId=recording_id
        )

        # Stream the download
        response = self._make_request('GET', endpoint, stream=True)

        # Determine filename
        if not output_path:
            # Try to get filename from Content-Disposition header
            content_disposition = response.headers.get('Content-Disposition', '')
            if 'filename=' in content_disposition:
                filename = content_disposition.split('filename=')[1].strip('"')
            else:
                filename = f"{recording_id}.mp3"

            output_path = os.path.join(os.getcwd(), filename)

        # Download file
        try:
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            file_size = os.path.getsize(output_path)
            logger.info(f"Downloaded recording {recording_id} to {output_path} ({file_size} bytes)")

            return output_path

        except Exception as e:
            logger.error(f"Failed to save recording: {e}")
            if os.path.exists(output_path):
                os.remove(output_path)
            raise RingCentralAPIError(f"Failed to save recording: {e}")

    def get_recordings_for_period(
        self,
        start_date: datetime,
        end_date: Optional[datetime] = None,
        download_dir: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all recordings for a time period

        Args:
            start_date: Start date
            end_date: End date (default: now)
            download_dir: Directory to download recordings (optional)

        Returns:
            List of recording information
        """
        if not end_date:
            end_date = datetime.utcnow()

        recordings = []

        for call_record in self.get_all_call_logs(
            date_from=start_date,
            date_to=end_date
        ):
            recording_info = call_record.get('recording', {})

            if recording_info:
                record = {
                    'call_id': call_record.get('id'),
                    'session_id': call_record.get('sessionId'),
                    'telephony_session_id': call_record.get('telephonySessionId'),
                    'recording_id': recording_info.get('id'),
                    'start_time': call_record.get('startTime'),
                    'duration': call_record.get('duration'),
                    'direction': call_record.get('direction'),
                    'from': call_record.get('from', {}),
                    'to': call_record.get('to', {}),
                    'recording_type': recording_info.get('type'),
                    'content_uri': recording_info.get('contentUri')
                }

                # Download if directory specified
                if download_dir and recording_info.get('id'):
                    try:
                        os.makedirs(download_dir, exist_ok=True)
                        output_path = os.path.join(
                            download_dir,
                            f"{recording_info['id']}.mp3"
                        )

                        if not os.path.exists(output_path):
                            downloaded_path = self.download_recording(
                                recording_info['id'],
                                output_path=output_path
                            )
                            record['local_file'] = downloaded_path

                    except Exception as e:
                        logger.error(f"Failed to download recording {recording_info['id']}: {e}")
                        record['download_error'] = str(e)

                recordings.append(record)

        return recordings

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get client statistics

        Returns:
            Dictionary with statistics
        """
        return {
            'rate_limiter': self.rate_limiter.get_statistics(),
            'auth': {
                'token_valid': self.auth._is_token_valid(),
                'refresh_token_valid': self.auth._is_refresh_token_valid()
            }
        }

    def close(self):
        """
        Close client and clean up resources
        """
        self.auth.close()
        self.session.close()

    def __enter__(self):
        """
        Context manager entry
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Context manager exit
        """
        self.close()