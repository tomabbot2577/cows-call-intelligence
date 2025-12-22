"""
RingCentral API integration package

Provides access to RingCentral Voice and Video APIs.
"""

from .auth import RingCentralAuth
from .client import RingCentralClient
from .rate_limiter import RateLimiter
from .exceptions import (
    RingCentralAPIError,
    AuthenticationError,
    RateLimitError,
    RecordingNotFoundError
)
from .video_client import RCVideoClient
from .video_sync_job import RCVideoSyncJob

__all__ = [
    'RingCentralAuth',
    'RingCentralClient',
    'RateLimiter',
    'RingCentralAPIError',
    'AuthenticationError',
    'RateLimitError',
    'RecordingNotFoundError',
    'RCVideoClient',
    'RCVideoSyncJob'
]