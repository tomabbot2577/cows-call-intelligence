"""
RingCentral JWT Authentication Module
Implements JWT Bearer Token authentication for RingCentral API
"""

import os
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

from .exceptions import (
    AuthenticationError,
    TokenExpiredError,
    InvalidJWTError,
    RingCentralAPIError
)

load_dotenv()
logger = logging.getLogger(__name__)


class RingCentralAuth:
    """
    JWT Bearer Token Authentication for RingCentral API

    Documentation: https://developers.ringcentral.com/guide/authentication/jwt-flow
    """

    # API Endpoints
    BASE_URL = "https://platform.ringcentral.com"
    SANDBOX_URL = "https://platform.devtest.ringcentral.com"
    TOKEN_ENDPOINT = "/restapi/oauth/token"
    REVOKE_ENDPOINT = "/restapi/oauth/revoke"

    # Token settings
    TOKEN_EXPIRY_BUFFER = 300  # Refresh token 5 minutes before expiry

    def __init__(
        self,
        jwt_token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        sandbox: bool = False,
        timeout: int = 30,
        max_retries: int = 3
    ):
        """
        Initialize RingCentral authentication

        Args:
            jwt_token: JWT token for authentication
            client_id: Client ID for the app
            client_secret: Client secret for the app
            sandbox: Whether to use sandbox environment
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
        """
        self.jwt_token = jwt_token or os.getenv('RINGCENTRAL_JWT')
        self.client_id = client_id or os.getenv('RINGCENTRAL_CLIENT_ID')
        self.client_secret = client_secret or os.getenv('RINGCENTRAL_CLIENT_SECRET')

        if not self.jwt_token:
            raise ValueError("JWT token is required")

        self.sandbox = sandbox
        self.base_url = self.SANDBOX_URL if sandbox else self.BASE_URL
        self.timeout = timeout

        # Token storage
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = 0
        self.refresh_token_expires_at = 0

        # Setup session with retry logic
        self.session = self._create_session(max_retries)

        logger.info(f"RingCentralAuth initialized for {'sandbox' if sandbox else 'production'} environment")

    def _create_session(self, max_retries: int) -> requests.Session:
        """
        Create a requests session with retry logic

        Args:
            max_retries: Maximum number of retry attempts

        Returns:
            Configured requests Session
        """
        session = requests.Session()

        # Configure retry strategy
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"]
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def get_access_token(self) -> str:
        """
        Get valid access token, refreshing if necessary

        Returns:
            Valid access token

        Raises:
            AuthenticationError: If authentication fails
        """
        # Check if we have a valid token
        if self.access_token and self._is_token_valid():
            return self.access_token

        # Try to refresh using refresh token if available
        if self.refresh_token and self._is_refresh_token_valid():
            try:
                self._refresh_access_token()
                return self.access_token
            except Exception as e:
                logger.warning(f"Failed to refresh token: {e}")

        # Exchange JWT for new tokens
        self._exchange_jwt_for_token()
        return self.access_token

    def _exchange_jwt_for_token(self):
        """
        Exchange JWT for access and refresh tokens

        Raises:
            AuthenticationError: If JWT exchange fails
        """
        url = urljoin(self.base_url, self.TOKEN_ENDPOINT)

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }

        # Add Basic authentication if client credentials are available
        if self.client_id and self.client_secret:
            import base64
            credentials = f"{self.client_id}:{self.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded_credentials}"

        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": self.jwt_token
        }

        try:
            logger.info("Exchanging JWT for access token")

            response = self.session.post(
                url,
                headers=headers,
                data=data,
                timeout=self.timeout
            )

            if response.status_code == 200:
                token_data = response.json()
                self._store_tokens(token_data)
                logger.info("Successfully obtained access token")
            else:
                error_data = response.json() if response.content else {}
                error_message = error_data.get('error_description', 'JWT exchange failed')

                logger.error(f"JWT exchange failed: {error_message}")

                if response.status_code == 400:
                    raise InvalidJWTError(
                        f"Invalid JWT token: {error_message}",
                        status_code=response.status_code,
                        response_data=error_data
                    )
                else:
                    raise AuthenticationError(
                        f"Authentication failed: {error_message}",
                        status_code=response.status_code,
                        response_data=error_data
                    )

        except requests.RequestException as e:
            logger.error(f"Network error during JWT exchange: {e}")
            raise AuthenticationError(f"Network error during authentication: {e}")

    def _refresh_access_token(self):
        """
        Refresh access token using refresh token

        Raises:
            AuthenticationError: If token refresh fails
        """
        if not self.refresh_token:
            raise AuthenticationError("No refresh token available")

        url = urljoin(self.base_url, self.TOKEN_ENDPOINT)

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token
        }

        try:
            logger.info("Refreshing access token")

            response = self.session.post(
                url,
                headers=headers,
                data=data,
                timeout=self.timeout
            )

            if response.status_code == 200:
                token_data = response.json()
                self._store_tokens(token_data)
                logger.info("Successfully refreshed access token")
            else:
                error_data = response.json() if response.content else {}
                error_message = error_data.get('error_description', 'Token refresh failed')

                logger.error(f"Token refresh failed: {error_message}")

                # Clear invalid tokens
                self.access_token = None
                self.refresh_token = None

                raise TokenExpiredError(
                    f"Token refresh failed: {error_message}",
                    status_code=response.status_code,
                    response_data=error_data
                )

        except requests.RequestException as e:
            logger.error(f"Network error during token refresh: {e}")
            raise AuthenticationError(f"Network error during token refresh: {e}")

    def _store_tokens(self, token_data: Dict[str, Any]):
        """
        Store tokens from API response

        Args:
            token_data: Token response from API
        """
        self.access_token = token_data.get('access_token')
        self.refresh_token = token_data.get('refresh_token')

        # Calculate expiry times
        current_time = time.time()

        expires_in = token_data.get('expires_in', 3600)
        self.token_expires_at = current_time + expires_in - self.TOKEN_EXPIRY_BUFFER

        refresh_expires_in = token_data.get('refresh_token_expires_in', 604800)
        self.refresh_token_expires_at = current_time + refresh_expires_in - self.TOKEN_EXPIRY_BUFFER

        logger.debug(f"Tokens stored. Access token expires in {expires_in} seconds")

    def _is_token_valid(self) -> bool:
        """
        Check if current access token is valid

        Returns:
            True if token is valid, False otherwise
        """
        return (
            self.access_token is not None and
            time.time() < self.token_expires_at
        )

    def _is_refresh_token_valid(self) -> bool:
        """
        Check if current refresh token is valid

        Returns:
            True if refresh token is valid, False otherwise
        """
        return (
            self.refresh_token is not None and
            time.time() < self.refresh_token_expires_at
        )

    def revoke_token(self):
        """
        Revoke current access token
        """
        if not self.access_token:
            logger.warning("No access token to revoke")
            return

        url = urljoin(self.base_url, self.REVOKE_ENDPOINT)

        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }

        data = {
            "token": self.access_token
        }

        try:
            response = self.session.post(
                url,
                headers=headers,
                data=data,
                timeout=self.timeout
            )

            if response.status_code == 200:
                logger.info("Access token revoked successfully")
                self.access_token = None
                self.token_expires_at = 0
            else:
                logger.warning(f"Failed to revoke token: {response.status_code}")

        except requests.RequestException as e:
            logger.error(f"Error revoking token: {e}")

    def get_auth_headers(self) -> Dict[str, str]:
        """
        Get authorization headers for API requests

        Returns:
            Dictionary with Authorization header
        """
        token = self.get_access_token()
        return {
            "Authorization": f"Bearer {token}"
        }

    def close(self):
        """
        Close the session and clean up
        """
        self.revoke_token()
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