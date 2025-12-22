"""
Rate limiting handler for RingCentral API
Implements adaptive rate limiting based on API response headers
"""

import time
import logging
from typing import Dict, Optional, Callable
from threading import Lock
from collections import deque
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Rate limiter for RingCentral API requests

    RingCentral Rate Limits (per user/extension):
    - Heavy: 10 requests/60 secs, penalty 60 secs
    - Medium: 40 requests/60 secs, penalty 60 secs
    - Light: 50 requests/60 secs, penalty 60 secs
    - Auth: 5 requests/60 secs, penalty 60 secs
    - SMS: 40 requests/60 secs, penalty 30 secs
    """

    # Rate limit groups (requests per 60 seconds)
    RATE_LIMITS = {
        'heavy': 10,
        'medium': 40,
        'light': 50,
        'auth': 5,
        'sms': 40,
        'default': 40  # Conservative default
    }

    # Penalty intervals (seconds) - time to wait after rate limit hit
    PENALTY_INTERVALS = {
        'heavy': 60,
        'medium': 60,
        'light': 60,
        'auth': 60,
        'sms': 30,
        'default': 60
    }

    # Endpoint to rate limit group mapping
    ENDPOINT_GROUPS = {
        # Auth endpoints
        '/restapi/oauth/token': 'auth',
        '/restapi/oauth/revoke': 'auth',
        '/restapi/oauth/authorize': 'auth',

        # Call log endpoints (medium)
        '/account/~/call-log': 'medium',
        '/account/~/extension/~/call-log': 'medium',

        # Recording endpoints (heavy)
        '/recording/': 'heavy',
        '/content': 'heavy',

        # Video API endpoints (light)
        '/rcvideo/v1/history/meetings': 'light',
        '/rcvideo/v1/account/': 'light',
        '/rcvideo/v1/recordings': 'light',

        # Account/Extension info (light)
        '/restapi/v1.0/account/': 'light',
        '/restapi/v2/accounts/': 'light',
        '/extension/': 'light',

        # SMS endpoints
        '/sms': 'sms',
        '/mms': 'sms',
    }

    def __init__(self, default_group: str = 'medium'):
        """
        Initialize rate limiter

        Args:
            default_group: Default rate limit group for unmapped endpoints
        """
        self.default_group = default_group
        self.request_history = {}  # Track request times per endpoint
        self.locks = {}  # Locks per endpoint
        self.rate_limit_resets = {}  # Track rate limit reset times
        self.global_lock = Lock()

        logger.info(f"RateLimiter initialized with default group: {default_group}")

    def _get_endpoint_group(self, endpoint: str) -> str:
        """
        Determine rate limit group for an endpoint

        Args:
            endpoint: API endpoint

        Returns:
            Rate limit group name
        """
        # Check exact match first
        if endpoint in self.ENDPOINT_GROUPS:
            return self.ENDPOINT_GROUPS[endpoint]

        # Check partial matches
        for pattern, group in self.ENDPOINT_GROUPS.items():
            if pattern in endpoint:
                return group

        return self.default_group

    def _get_or_create_lock(self, endpoint: str) -> Lock:
        """
        Get or create a lock for an endpoint

        Args:
            endpoint: API endpoint

        Returns:
            Thread lock for the endpoint
        """
        with self.global_lock:
            if endpoint not in self.locks:
                self.locks[endpoint] = Lock()
            return self.locks[endpoint]

    def wait_if_needed(self, endpoint: str) -> float:
        """
        Wait if rate limit would be exceeded

        Args:
            endpoint: API endpoint

        Returns:
            Time waited in seconds
        """
        group = self._get_endpoint_group(endpoint)
        limit = self.RATE_LIMITS.get(group, self.RATE_LIMITS['default'])

        lock = self._get_or_create_lock(endpoint)

        with lock:
            current_time = time.time()

            # Initialize history for this endpoint if needed
            if endpoint not in self.request_history:
                self.request_history[endpoint] = deque()

            # Remove requests older than 1 minute
            history = self.request_history[endpoint]
            cutoff_time = current_time - 60

            while history and history[0] < cutoff_time:
                history.popleft()

            # Check if we need to wait
            wait_time = 0

            if len(history) >= limit:
                # Calculate wait time based on oldest request in window
                oldest_request = history[0]
                wait_time = max(0, 60 - (current_time - oldest_request) + 0.1)

                if wait_time > 0:
                    logger.info(f"Rate limit for {endpoint} ({group}): waiting {wait_time:.2f} seconds")
                    time.sleep(wait_time)
                    current_time = time.time()

            # Record this request
            history.append(current_time)

            return wait_time

    def handle_rate_limit_response(
        self,
        endpoint: str,
        status_code: int,
        headers: Dict[str, str]
    ) -> Optional[float]:
        """
        Handle rate limit response from API

        Args:
            endpoint: API endpoint
            status_code: HTTP status code
            headers: Response headers

        Returns:
            Retry after time in seconds if rate limited, None otherwise
        """
        if status_code != 429:
            return None

        # Check for Retry-After header
        retry_after = headers.get('Retry-After', headers.get('retry-after'))

        if retry_after:
            try:
                # Try to parse as integer (seconds)
                retry_seconds = int(retry_after)
            except ValueError:
                # Try to parse as HTTP date
                try:
                    retry_date = datetime.strptime(
                        retry_after,
                        '%a, %d %b %Y %H:%M:%S GMT'
                    )
                    retry_seconds = (retry_date - datetime.utcnow()).total_seconds()
                except ValueError:
                    retry_seconds = 60  # Default to 1 minute

            logger.warning(f"Rate limit hit for {endpoint}. Retry after {retry_seconds} seconds")

            # Store rate limit reset time
            with self._get_or_create_lock(endpoint):
                self.rate_limit_resets[endpoint] = time.time() + retry_seconds

            return retry_seconds

        # No Retry-After header, use penalty interval for this endpoint group
        group = self._get_endpoint_group(endpoint)
        return self.PENALTY_INTERVALS.get(group, self.PENALTY_INTERVALS['default'])

    def check_rate_limit_reset(self, endpoint: str) -> Optional[float]:
        """
        Check if endpoint is in rate limit reset period

        Args:
            endpoint: API endpoint

        Returns:
            Remaining wait time if in reset period, None otherwise
        """
        with self._get_or_create_lock(endpoint):
            if endpoint in self.rate_limit_resets:
                reset_time = self.rate_limit_resets[endpoint]
                current_time = time.time()

                if current_time < reset_time:
                    wait_time = reset_time - current_time
                    logger.info(f"Endpoint {endpoint} in rate limit reset period. Wait {wait_time:.2f} seconds")
                    return wait_time
                else:
                    # Reset period expired
                    del self.rate_limit_resets[endpoint]

        return None

    def reset_endpoint_history(self, endpoint: str):
        """
        Reset request history for an endpoint

        Args:
            endpoint: API endpoint
        """
        with self._get_or_create_lock(endpoint):
            if endpoint in self.request_history:
                self.request_history[endpoint].clear()
                logger.debug(f"Reset request history for {endpoint}")

            if endpoint in self.rate_limit_resets:
                del self.rate_limit_resets[endpoint]

    def get_statistics(self) -> Dict[str, any]:
        """
        Get rate limiting statistics

        Returns:
            Dictionary with statistics
        """
        stats = {}

        for endpoint, history in self.request_history.items():
            # Clean old entries
            current_time = time.time()
            cutoff_time = current_time - 60

            active_requests = [
                req for req in history
                if req >= cutoff_time
            ]

            group = self._get_endpoint_group(endpoint)
            limit = self.RATE_LIMITS.get(group, self.RATE_LIMITS['default'])

            stats[endpoint] = {
                'group': group,
                'limit': limit,
                'requests_last_minute': len(active_requests),
                'utilization': len(active_requests) / limit * 100 if limit > 0 else 0,
                'in_reset': endpoint in self.rate_limit_resets
            }

        return stats


class AdaptiveRateLimiter(RateLimiter):
    """
    Adaptive rate limiter that adjusts based on API responses
    """

    def __init__(self, default_group: str = 'medium'):
        """
        Initialize adaptive rate limiter

        Args:
            default_group: Default rate limit group
        """
        super().__init__(default_group)
        self.adaptive_limits = {}  # Store learned limits
        self.success_counts = {}  # Track successful requests
        self.failure_counts = {}  # Track rate limit failures

    def update_adaptive_limit(self, endpoint: str, success: bool):
        """
        Update adaptive limits based on request outcome

        Args:
            endpoint: API endpoint
            success: Whether request succeeded without rate limit
        """
        with self._get_or_create_lock(endpoint):
            if endpoint not in self.success_counts:
                self.success_counts[endpoint] = 0
                self.failure_counts[endpoint] = 0

            if success:
                self.success_counts[endpoint] += 1

                # After 100 successful requests, try to increase limit slightly
                if self.success_counts[endpoint] % 100 == 0:
                    current_limit = self.adaptive_limits.get(
                        endpoint,
                        self.RATE_LIMITS[self._get_endpoint_group(endpoint)]
                    )
                    self.adaptive_limits[endpoint] = min(
                        current_limit + 1,
                        self.RATE_LIMITS['light']  # Max at light limit
                    )
                    logger.info(f"Increased adaptive limit for {endpoint} to {self.adaptive_limits[endpoint]}")

            else:
                self.failure_counts[endpoint] += 1

                # After 3 failures, reduce limit
                if self.failure_counts[endpoint] % 3 == 0:
                    current_limit = self.adaptive_limits.get(
                        endpoint,
                        self.RATE_LIMITS[self._get_endpoint_group(endpoint)]
                    )
                    self.adaptive_limits[endpoint] = max(
                        current_limit - 2,
                        self.RATE_LIMITS['auth']  # Min at auth limit
                    )
                    logger.warning(f"Reduced adaptive limit for {endpoint} to {self.adaptive_limits[endpoint]}")

    def get_effective_limit(self, endpoint: str) -> int:
        """
        Get effective rate limit for endpoint

        Args:
            endpoint: API endpoint

        Returns:
            Effective rate limit
        """
        if endpoint in self.adaptive_limits:
            return self.adaptive_limits[endpoint]

        group = self._get_endpoint_group(endpoint)
        return self.RATE_LIMITS.get(group, self.RATE_LIMITS['default'])