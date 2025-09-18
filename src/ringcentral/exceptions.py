"""
Custom exceptions for RingCentral API integration
"""


class RingCentralAPIError(Exception):
    """
    Base exception for RingCentral API errors
    """
    def __init__(self, message: str, status_code: int = None, response_data: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class AuthenticationError(RingCentralAPIError):
    """
    Raised when authentication fails
    """
    pass


class RateLimitError(RingCentralAPIError):
    """
    Raised when API rate limit is exceeded
    """
    def __init__(self, message: str, retry_after: int = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class RecordingNotFoundError(RingCentralAPIError):
    """
    Raised when a recording cannot be found
    """
    pass


class TokenExpiredError(AuthenticationError):
    """
    Raised when the access token has expired
    """
    pass


class InvalidJWTError(AuthenticationError):
    """
    Raised when the JWT token is invalid
    """
    pass