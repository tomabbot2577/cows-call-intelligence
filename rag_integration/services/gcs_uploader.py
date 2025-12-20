"""GCS Uploader - Uploads JSONL files to Google Cloud Storage."""

import os
from pathlib import Path
from typing import Optional, List
import logging

from google.cloud import storage
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class GCSUploader:
    """Uploads JSONL files to Google Cloud Storage for RAG ingestion."""

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        prefix: str = "transcripts/",
        credentials_path: Optional[str] = None
    ):
        self.bucket_name = bucket_name or os.getenv("GCS_RAG_BUCKET", "call-recording-rag-data")
        self.prefix = prefix

        credentials_path = credentials_path or os.getenv(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "/var/www/call-recording-system/config/google_service_account.json"
        )

        if credentials_path and Path(credentials_path).exists():
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            self.client = storage.Client(credentials=credentials)
        else:
            # Fall back to default credentials
            self.client = storage.Client()

        self.bucket = self.client.bucket(self.bucket_name)

    def upload_file(self, local_path: Path, remote_name: Optional[str] = None) -> str:
        """
        Upload a single file to GCS.

        Args:
            local_path: Path to local file
            remote_name: Optional remote filename (defaults to local filename)

        Returns:
            GCS URI (gs://bucket/path)
        """
        local_path = Path(local_path)
        remote_name = remote_name or local_path.name
        blob_path = f"{self.prefix}{remote_name}"

        blob = self.bucket.blob(blob_path)
        blob.upload_from_filename(str(local_path))

        gcs_uri = f"gs://{self.bucket_name}/{blob_path}"
        logger.info(f"Uploaded {local_path} to {gcs_uri}")
        return gcs_uri

    def upload_directory(self, local_dir: Path, pattern: str = "*.jsonl") -> List[str]:
        """
        Upload all matching files from a directory.

        Args:
            local_dir: Local directory path
            pattern: Glob pattern for files to upload

        Returns:
            List of GCS URIs
        """
        uploaded = []
        for filepath in Path(local_dir).glob(pattern):
            try:
                gcs_uri = self.upload_file(filepath)
                uploaded.append(gcs_uri)
            except Exception as e:
                logger.error(f"Failed to upload {filepath}: {e}")
        return uploaded

    def upload_content(self, content: str, remote_name: str) -> str:
        """
        Upload string content directly to GCS.

        Args:
            content: String content to upload
            remote_name: Remote filename

        Returns:
            GCS URI
        """
        blob_path = f"{self.prefix}{remote_name}"
        blob = self.bucket.blob(blob_path)
        blob.upload_from_string(content, content_type="application/jsonl")

        gcs_uri = f"gs://{self.bucket_name}/{blob_path}"
        logger.info(f"Uploaded content to {gcs_uri}")
        return gcs_uri

    def list_files(self, prefix: Optional[str] = None) -> List[str]:
        """List all files in the bucket with given prefix."""
        prefix = prefix or self.prefix
        blobs = self.client.list_blobs(self.bucket_name, prefix=prefix)
        return [f"gs://{self.bucket_name}/{blob.name}" for blob in blobs]

    def delete_file(self, gcs_uri: str) -> bool:
        """Delete a file from GCS."""
        try:
            # Parse gs:// URI
            if gcs_uri.startswith("gs://"):
                path = gcs_uri[5:]  # Remove gs://
                bucket_name, blob_path = path.split("/", 1)
                blob = self.client.bucket(bucket_name).blob(blob_path)
                blob.delete()
                logger.info(f"Deleted {gcs_uri}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete {gcs_uri}: {e}")
            return False

    def file_exists(self, remote_name: str) -> bool:
        """Check if a file exists in GCS."""
        blob_path = f"{self.prefix}{remote_name}"
        blob = self.bucket.blob(blob_path)
        return blob.exists()

    def get_file_info(self, remote_name: str) -> Optional[dict]:
        """Get metadata about a file in GCS."""
        blob_path = f"{self.prefix}{remote_name}"
        blob = self.bucket.blob(blob_path)

        if blob.exists():
            blob.reload()
            return {
                "name": blob.name,
                "size": blob.size,
                "created": blob.time_created,
                "updated": blob.updated,
                "content_type": blob.content_type,
                "uri": f"gs://{self.bucket_name}/{blob.name}"
            }
        return None

    def test_connection(self) -> bool:
        """Test GCS connection and bucket access."""
        try:
            # Try to list blobs (limited to 1)
            list(self.bucket.list_blobs(max_results=1))
            logger.info(f"GCS connection successful to bucket: {self.bucket_name}")
            return True
        except Exception as e:
            logger.error(f"GCS connection test failed: {e}")
            return False

    def ensure_bucket_exists(self) -> bool:
        """Ensure the bucket exists, create if not."""
        try:
            if not self.bucket.exists():
                logger.info(f"Creating bucket: {self.bucket_name}")
                self.bucket = self.client.create_bucket(
                    self.bucket_name,
                    location="us-west1"
                )
            return True
        except Exception as e:
            logger.error(f"Failed to ensure bucket exists: {e}")
            return False


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    uploader = GCSUploader()

    print(f"Testing connection to bucket: {uploader.bucket_name}")

    if uploader.test_connection():
        print("Connection successful!")

        # List existing files
        files = uploader.list_files()
        print(f"\nExisting files ({len(files)}):")
        for f in files[:10]:
            print(f"  {f}")
        if len(files) > 10:
            print(f"  ... and {len(files) - 10} more")
    else:
        print("Connection failed!")
        sys.exit(1)
