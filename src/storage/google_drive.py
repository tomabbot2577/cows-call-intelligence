"""
Google Drive Manager
Handles authentication and file operations for Google Drive
"""

import os
import logging
import json
import time
from pathlib import Path
from typing import Optional, Dict, List, Any, BinaryIO
from datetime import datetime, timedelta
import tempfile
import mimetypes

from google.oauth2 import service_account
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

logger = logging.getLogger(__name__)


class GoogleDriveManager:
    """
    Manages Google Drive operations with service account authentication
    """

    # OAuth2 scopes for Google Drive
    SCOPES = [
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/drive.file',
        'https://www.googleapis.com/auth/drive.metadata'
    ]

    # MIME types
    MIME_TYPES = {
        '.json': 'application/json',
        '.txt': 'text/plain',
        '.pdf': 'application/pdf',
        '.csv': 'text/csv',
        '.mp3': 'audio/mpeg',
        '.wav': 'audio/wav',
        '.m4a': 'audio/mp4'
    }

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        folder_id: Optional[str] = None,
        impersonate_email: Optional[str] = None,
        upload_timeout: int = 300,
        chunk_size: int = 5 * 1024 * 1024  # 5MB chunks
    ):
        """
        Initialize Google Drive manager

        Args:
            credentials_path: Path to service account JSON file
            folder_id: Default folder ID for uploads
            impersonate_email: Email to impersonate via domain-wide delegation
            upload_timeout: Timeout for uploads in seconds
            chunk_size: Chunk size for resumable uploads
        """
        self.credentials_path = credentials_path or os.getenv('GOOGLE_CREDENTIALS_PATH')
        self.folder_id = folder_id or os.getenv('GOOGLE_DRIVE_FOLDER_ID')
        self.impersonate_email = impersonate_email or os.getenv('GOOGLE_IMPERSONATE_EMAIL')
        self.upload_timeout = upload_timeout
        self.chunk_size = chunk_size

        if not self.credentials_path:
            raise ValueError("Service account credentials path is required")

        if not os.path.exists(self.credentials_path):
            raise FileNotFoundError(f"Credentials file not found: {self.credentials_path}")

        # Initialize service
        self.service = None
        self.credentials = None
        self._initialize_service()

        # Statistics
        self.upload_count = 0
        self.total_bytes_uploaded = 0

        logger.info("GoogleDriveManager initialized")

    def _initialize_service(self):
        """
        Initialize Google Drive service with service account
        """
        try:
            # Load service account credentials
            self.credentials = service_account.Credentials.from_service_account_file(
                self.credentials_path,
                scopes=self.SCOPES
            )

            # If impersonate_email is provided, use domain-wide delegation
            if self.impersonate_email:
                self.credentials = self.credentials.with_subject(self.impersonate_email)
                logger.info(f"Using domain-wide delegation to impersonate: {self.impersonate_email}")

            # Build Drive service
            self.service = build('drive', 'v3', credentials=self.credentials)

            logger.info("Google Drive service initialized successfully")

            # Verify access by listing files (limited to 1)
            self._verify_access()

        except Exception as e:
            logger.error(f"Failed to initialize Google Drive service: {e}")
            raise

    def _verify_access(self):
        """
        Verify access to Google Drive and folder
        """
        try:
            # Try to get folder metadata if folder_id is provided
            if self.folder_id:
                folder = self.service.files().get(
                    fileId=self.folder_id,
                    fields='id,name,mimeType'
                ).execute()

                if folder.get('mimeType') != 'application/vnd.google-apps.folder':
                    raise ValueError(f"ID {self.folder_id} is not a folder")

                logger.info(f"Verified access to folder: {folder.get('name')}")

            else:
                # Just list one file to verify access
                results = self.service.files().list(
                    pageSize=1,
                    fields="files(id, name)"
                ).execute()

                logger.info("Verified Google Drive access")

        except HttpError as e:
            if e.resp.status == 404:
                raise ValueError(f"Folder not found: {self.folder_id}")
            elif e.resp.status == 403:
                raise PermissionError("No access to Google Drive or folder")
            else:
                raise

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        retry=retry_if_exception_type(HttpError),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    def upload_file(
        self,
        file_path: str,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        folder_id: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
        resumable: bool = True
    ) -> str:
        """
        Upload file to Google Drive with retry logic

        Args:
            file_path: Path to file to upload
            file_name: Name for file in Drive (default: use local name)
            mime_type: MIME type (default: auto-detect)
            folder_id: Folder ID (default: use instance folder)
            metadata: Additional metadata
            resumable: Use resumable upload for large files

        Returns:
            File ID of uploaded file

        Raises:
            FileNotFoundError: If file doesn't exist
            HttpError: On API errors
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # Determine file properties
        if not file_name:
            file_name = os.path.basename(file_path)

        if not mime_type:
            mime_type = self._get_mime_type(file_path)

        if not folder_id:
            folder_id = self.folder_id

        file_size = os.path.getsize(file_path)

        logger.info(f"Uploading {file_name} ({file_size} bytes) to Google Drive")

        # Prepare file metadata
        file_metadata = {
            'name': file_name
        }

        if folder_id:
            file_metadata['parents'] = [folder_id]

        # Add custom properties
        if metadata:
            file_metadata['properties'] = metadata

        # Create media upload
        media = MediaFileUpload(
            file_path,
            mimetype=mime_type,
            resumable=resumable and file_size > self.chunk_size,
            chunksize=self.chunk_size
        )

        try:
            # Upload file
            start_time = time.time()

            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id,name,webViewLink,size'
            ).execute()

            upload_time = time.time() - start_time

            # Update statistics
            self.upload_count += 1
            self.total_bytes_uploaded += file_size

            logger.info(
                f"Upload successful: {file.get('name')} "
                f"(ID: {file.get('id')}, "
                f"Size: {file.get('size', file_size)} bytes, "
                f"Time: {upload_time:.2f}s)"
            )

            return file.get('id')

        except HttpError as e:
            if e.resp.status == 403:
                logger.error("Insufficient permissions or quota exceeded")
            elif e.resp.status == 404:
                logger.error(f"Parent folder not found: {folder_id}")
            else:
                logger.error(f"Upload failed: {e}")
            raise

    def upload_json(
        self,
        data: Dict[str, Any],
        file_name: str,
        folder_id: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Upload JSON data to Google Drive

        Args:
            data: Dictionary to save as JSON
            file_name: Name for file in Drive
            folder_id: Folder ID (default: use instance folder)
            metadata: Additional metadata

        Returns:
            File ID of uploaded file
        """
        # Create temporary file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.json',
            delete=False
        ) as tmp_file:
            json.dump(data, tmp_file, indent=2, ensure_ascii=False)
            tmp_path = tmp_file.name

        try:
            # Upload temporary file
            file_id = self.upload_file(
                tmp_path,
                file_name=file_name,
                mime_type='application/json',
                folder_id=folder_id,
                metadata=metadata
            )

            return file_id

        finally:
            # Clean up temporary file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def create_folder(
        self,
        folder_name: str,
        parent_id: Optional[str] = None
    ) -> str:
        """
        Create folder in Google Drive

        Args:
            folder_name: Folder name
            parent_id: Parent folder ID (default: use instance folder)

        Returns:
            Folder ID
        """
        if not parent_id:
            parent_id = self.folder_id

        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }

        if parent_id:
            file_metadata['parents'] = [parent_id]

        try:
            folder = self.service.files().create(
                body=file_metadata,
                fields='id,name'
            ).execute()

            logger.info(f"Created folder: {folder.get('name')} (ID: {folder.get('id')})")
            return folder.get('id')

        except HttpError as e:
            logger.error(f"Failed to create folder: {e}")
            raise

    def get_or_create_folder(
        self,
        folder_name: str,
        parent_id: Optional[str] = None
    ) -> str:
        """
        Get existing folder or create if not exists

        Args:
            folder_name: Folder name
            parent_id: Parent folder ID

        Returns:
            Folder ID
        """
        if not parent_id:
            parent_id = self.folder_id

        # Search for existing folder
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'"

        if parent_id:
            query += f" and '{parent_id}' in parents"

        query += " and trashed=false"

        try:
            results = self.service.files().list(
                q=query,
                fields='files(id, name)',
                pageSize=1
            ).execute()

            files = results.get('files', [])

            if files:
                folder_id = files[0].get('id')
                logger.debug(f"Found existing folder: {folder_name} (ID: {folder_id})")
                return folder_id

            # Create new folder
            return self.create_folder(folder_name, parent_id)

        except HttpError as e:
            logger.error(f"Error getting/creating folder: {e}")
            raise

    def organize_by_date(
        self,
        base_folder_id: Optional[str] = None
    ) -> str:
        """
        Create folder structure organized by date (Year/Month/Day)

        Args:
            base_folder_id: Base folder ID

        Returns:
            Today's folder ID
        """
        if not base_folder_id:
            base_folder_id = self.folder_id

        now = datetime.now()

        # Create year folder
        year_folder = self.get_or_create_folder(
            str(now.year),
            base_folder_id
        )

        # Create month folder
        month_name = now.strftime("%m-%B")
        month_folder = self.get_or_create_folder(
            month_name,
            year_folder
        )

        # Create day folder
        day_name = now.strftime("%d")
        day_folder = self.get_or_create_folder(
            day_name,
            month_folder
        )

        return day_folder

    def list_files(
        self,
        folder_id: Optional[str] = None,
        query: Optional[str] = None,
        page_size: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List files in Google Drive

        Args:
            folder_id: Folder to list (default: all accessible files)
            query: Additional query parameters
            page_size: Number of results per page

        Returns:
            List of file metadata dictionaries
        """
        files_list = []

        # Build query
        q_parts = []

        if folder_id:
            q_parts.append(f"'{folder_id}' in parents")

        if query:
            q_parts.append(query)

        q_parts.append("trashed=false")

        full_query = " and ".join(q_parts)

        try:
            page_token = None

            while True:
                results = self.service.files().list(
                    q=full_query,
                    pageSize=page_size,
                    fields="nextPageToken, files(id, name, mimeType, size, createdTime, modifiedTime, webViewLink)",
                    pageToken=page_token
                ).execute()

                files_list.extend(results.get('files', []))

                page_token = results.get('nextPageToken')
                if not page_token:
                    break

            logger.info(f"Found {len(files_list)} files")
            return files_list

        except HttpError as e:
            logger.error(f"Failed to list files: {e}")
            raise

    def delete_file(self, file_id: str):
        """
        Delete file from Google Drive

        Args:
            file_id: File ID to delete
        """
        try:
            self.service.files().delete(fileId=file_id).execute()
            logger.info(f"Deleted file: {file_id}")

        except HttpError as e:
            if e.resp.status == 404:
                logger.warning(f"File not found: {file_id}")
            else:
                logger.error(f"Failed to delete file: {e}")
                raise

    def get_file_metadata(
        self,
        file_id: str,
        fields: str = "id,name,size,mimeType,createdTime,modifiedTime,webViewLink"
    ) -> Dict[str, Any]:
        """
        Get file metadata

        Args:
            file_id: File ID
            fields: Fields to retrieve

        Returns:
            File metadata dictionary
        """
        try:
            file = self.service.files().get(
                fileId=file_id,
                fields=fields
            ).execute()

            return file

        except HttpError as e:
            if e.resp.status == 404:
                logger.error(f"File not found: {file_id}")
            else:
                logger.error(f"Failed to get file metadata: {e}")
            raise

    def _get_mime_type(self, file_path: str) -> str:
        """
        Get MIME type for file

        Args:
            file_path: File path

        Returns:
            MIME type string
        """
        # Check extension first
        ext = Path(file_path).suffix.lower()
        if ext in self.MIME_TYPES:
            return self.MIME_TYPES[ext]

        # Use mimetypes library
        mime_type, _ = mimetypes.guess_type(file_path)
        return mime_type or 'application/octet-stream'

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get upload statistics

        Returns:
            Statistics dictionary
        """
        return {
            'upload_count': self.upload_count,
            'total_bytes_uploaded': self.total_bytes_uploaded,
            'folder_id': self.folder_id,
            'service_account': self.credentials.service_account_email if self.credentials else None
        }

    def close(self):
        """
        Clean up resources
        """
        if self.service:
            self.service.close()
            logger.info("Google Drive service closed")