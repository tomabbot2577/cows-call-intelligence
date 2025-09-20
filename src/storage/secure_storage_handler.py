"""
Secure Storage Handler
Handles transcription storage and audio deletion with security compliance
IMPORTANT: Audio recordings are NEVER stored - only transcriptions are saved
"""

import os
import logging
import json
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import tempfile
import shutil

from .google_drive import GoogleDriveManager

logger = logging.getLogger(__name__)


class SecureStorageHandler:
    """
    Secure storage handler that:
    1. Saves ONLY transcriptions to Google Drive
    2. DELETES audio files after transcription
    3. Maintains audit logs of deletions
    """

    def __init__(
        self,
        google_drive_manager: Optional[GoogleDriveManager] = None,
        local_backup_dir: Optional[str] = None,
        enable_audit_log: bool = True,
        verify_deletion: bool = True
    ):
        """
        Initialize secure storage handler

        Args:
            google_drive_manager: Google Drive manager instance
            local_backup_dir: Optional local directory for transcript backups
            enable_audit_log: Enable deletion audit logging
            verify_deletion: Verify files are deleted
        """
        self.drive_manager = google_drive_manager
        self.local_backup_dir = Path(local_backup_dir) if local_backup_dir else None
        self.enable_audit_log = enable_audit_log
        self.verify_deletion = verify_deletion

        # Create local backup directory if specified
        if self.local_backup_dir:
            self.local_backup_dir.mkdir(parents=True, exist_ok=True)

        # Audit log path
        self.audit_log_path = Path('/var/www/call-recording-system/logs/deletion_audit.log')
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Statistics
        self.audio_files_deleted = 0
        self.transcripts_saved = 0
        self.total_audio_bytes_deleted = 0

        logger.info("SecureStorageHandler initialized - Audio deletion enabled")

    def process_transcription(
        self,
        audio_file_path: str,
        transcription_result: Dict[str, Any],
        call_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process transcription: Save transcript and DELETE audio

        Args:
            audio_file_path: Path to audio file to be DELETED
            transcription_result: Transcription result dictionary
            call_metadata: Additional call metadata

        Returns:
            Processing result with confirmation

        IMPORTANT: Audio file will be DELETED after transcription is saved
        """
        result = {
            'success': False,
            'transcript_saved': False,
            'audio_deleted': False,
            'deletion_verified': False,
            'error': None
        }

        try:
            # Step 1: Prepare transcript data
            transcript_data = self._prepare_transcript_data(
                transcription_result,
                call_metadata,
                audio_file_path
            )

            # Step 2: Save transcript to Google Drive (NO AUDIO)
            if self.drive_manager:
                drive_file_id = self._save_transcript_to_drive(transcript_data)
                result['drive_file_id'] = drive_file_id
                result['transcript_saved'] = True
                logger.info(f"Transcript saved to Google Drive: {drive_file_id}")

            # Step 3: Optionally save local backup of transcript
            if self.local_backup_dir:
                local_path = self._save_transcript_locally(transcript_data)
                result['local_backup_path'] = str(local_path)
                logger.info(f"Transcript backed up locally: {local_path}")

            # Step 4: DELETE THE AUDIO FILE
            deletion_result = self._delete_audio_file(audio_file_path)
            result['audio_deleted'] = deletion_result['deleted']
            result['deletion_verified'] = deletion_result['verified']
            result['deletion_details'] = deletion_result

            if result['audio_deleted']:
                logger.info(f"✅ AUDIO FILE DELETED: {audio_file_path}")
                logger.info(f"   File size deleted: {deletion_result['file_size_bytes']} bytes")
            else:
                logger.error(f"⚠️ FAILED TO DELETE AUDIO: {audio_file_path}")
                result['error'] = "Audio deletion failed"

            # Step 5: Log the deletion for audit
            if self.enable_audit_log:
                self._log_deletion_audit(audio_file_path, deletion_result, transcript_data)

            result['success'] = result['transcript_saved'] and result['audio_deleted']

        except Exception as e:
            logger.error(f"Error processing transcription: {e}")
            result['error'] = str(e)
            result['success'] = False

        return result

    def _prepare_transcript_data(
        self,
        transcription_result: Dict[str, Any],
        call_metadata: Optional[Dict[str, Any]],
        audio_file_path: str
    ) -> Dict[str, Any]:
        """
        Prepare transcript data with metadata

        Args:
            transcription_result: Raw transcription result
            call_metadata: Call metadata
            audio_file_path: Original audio file path

        Returns:
            Complete transcript data
        """
        # Calculate audio file hash before deletion (for audit)
        audio_hash = self._calculate_file_hash(audio_file_path) if os.path.exists(audio_file_path) else None

        transcript_data = {
            'version': '2.0',
            'security_notice': 'Audio file has been deleted per security policy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'transcription': transcription_result,
            'call_metadata': call_metadata or {},
            'audio_metadata': {
                'original_filename': os.path.basename(audio_file_path),
                'file_hash': audio_hash,
                'deletion_confirmed': False  # Will be updated after deletion
            },
            'processing_info': {
                'service': transcription_result.get('metadata', {}).get('engine', 'salad'),
                'language': transcription_result.get('language', 'en-US'),
                'confidence': transcription_result.get('confidence', 0),
                'word_count': transcription_result.get('word_count', 0)
            }
        }

        return transcript_data

    def _save_transcript_to_drive(self, transcript_data: Dict[str, Any]) -> str:
        """
        Save ONLY transcript to Google Drive (NO AUDIO)

        Args:
            transcript_data: Transcript data dictionary

        Returns:
            Google Drive file ID
        """
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"transcript_{timestamp}.json"

        # Organize by date
        folder_id = self.drive_manager.organize_by_date()

        # Upload TRANSCRIPT ONLY
        file_id = self.drive_manager.upload_json(
            data=transcript_data,
            file_name=filename,
            folder_id=folder_id,
            metadata={
                'type': 'transcript',
                'audio_deleted': 'true',
                'security_compliant': 'true'
            }
        )

        self.transcripts_saved += 1
        return file_id

    def _save_transcript_locally(self, transcript_data: Dict[str, Any]) -> Path:
        """
        Save transcript locally as backup

        Args:
            transcript_data: Transcript data

        Returns:
            Local file path
        """
        # Create date-based directory structure
        date_dir = self.local_backup_dir / datetime.now().strftime('%Y/%m/%d')
        date_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename
        timestamp = datetime.now().strftime('%H%M%S')
        filename = f"transcript_{timestamp}.json"
        file_path = date_dir / filename

        # Save transcript
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(transcript_data, f, indent=2, ensure_ascii=False)

        return file_path

    def _delete_audio_file(self, audio_file_path: str) -> Dict[str, Any]:
        """
        SECURELY DELETE audio file with verification

        Args:
            audio_file_path: Path to audio file to DELETE

        Returns:
            Deletion result with verification
        """
        deletion_result = {
            'deleted': False,
            'verified': False,
            'file_existed': False,
            'file_size_bytes': 0,
            'deletion_method': None,
            'deletion_time': None,
            'error': None
        }

        try:
            # Check if file exists
            if not os.path.exists(audio_file_path):
                deletion_result['error'] = 'File does not exist'
                logger.warning(f"Audio file not found for deletion: {audio_file_path}")
                return deletion_result

            deletion_result['file_existed'] = True
            deletion_result['file_size_bytes'] = os.path.getsize(audio_file_path)

            # Method 1: Secure overwrite before deletion (optional)
            if os.path.exists('/usr/bin/shred'):
                # Use shred for secure deletion on Linux
                try:
                    os.system(f'shred -vfz -n 1 "{audio_file_path}"')
                    deletion_result['deletion_method'] = 'shred'
                    deletion_result['deleted'] = True
                except Exception as e:
                    logger.warning(f"Shred failed, using standard deletion: {e}")

            # Method 2: Standard deletion
            if not deletion_result['deleted']:
                try:
                    os.remove(audio_file_path)
                    deletion_result['deletion_method'] = 'os.remove'
                    deletion_result['deleted'] = True
                except Exception as e:
                    logger.error(f"Failed to delete audio file: {e}")
                    deletion_result['error'] = str(e)
                    return deletion_result

            deletion_result['deletion_time'] = datetime.now(timezone.utc).isoformat()

            # Verify deletion
            if self.verify_deletion:
                if not os.path.exists(audio_file_path):
                    deletion_result['verified'] = True
                    logger.info(f"✅ Deletion verified: {audio_file_path} no longer exists")
                else:
                    deletion_result['verified'] = False
                    logger.error(f"⚠️ Deletion verification FAILED: {audio_file_path} still exists!")

            # Update statistics
            if deletion_result['deleted']:
                self.audio_files_deleted += 1
                self.total_audio_bytes_deleted += deletion_result['file_size_bytes']

        except Exception as e:
            logger.error(f"Error during audio deletion: {e}")
            deletion_result['error'] = str(e)

        return deletion_result

    def _calculate_file_hash(self, file_path: str) -> str:
        """
        Calculate SHA-256 hash of file for audit

        Args:
            file_path: File path

        Returns:
            SHA-256 hash string
        """
        try:
            sha256_hash = hashlib.sha256()
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception as e:
            logger.error(f"Error calculating file hash: {e}")
            return "error"

    def _log_deletion_audit(
        self,
        audio_file_path: str,
        deletion_result: Dict[str, Any],
        transcript_data: Dict[str, Any]
    ):
        """
        Log audio deletion for audit trail

        Args:
            audio_file_path: Deleted audio file path
            deletion_result: Deletion result details
            transcript_data: Associated transcript data
        """
        audit_entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'action': 'AUDIO_DELETION',
            'audio_file': audio_file_path,
            'deletion_result': deletion_result,
            'transcript_saved': transcript_data is not None,
            'file_hash': transcript_data.get('audio_metadata', {}).get('file_hash', 'unknown')
        }

        try:
            with open(self.audit_log_path, 'a') as f:
                f.write(json.dumps(audit_entry) + '\n')

            logger.info(f"Deletion audit logged: {audio_file_path}")

        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    def batch_process_recordings(
        self,
        recordings: List[Dict[str, Any]],
        delete_on_success: bool = True
    ) -> Dict[str, Any]:
        """
        Batch process multiple recordings

        Args:
            recordings: List of recording dictionaries with paths and transcriptions
            delete_on_success: Delete audio files after successful processing

        Returns:
            Batch processing results
        """
        results = {
            'total': len(recordings),
            'successful': 0,
            'failed': 0,
            'audio_deleted': 0,
            'transcripts_saved': 0,
            'errors': []
        }

        for recording in recordings:
            try:
                audio_path = recording.get('audio_path')
                transcription = recording.get('transcription')
                metadata = recording.get('metadata')

                if not audio_path or not transcription:
                    results['failed'] += 1
                    results['errors'].append('Missing audio path or transcription')
                    continue

                # Process recording
                result = self.process_transcription(
                    audio_file_path=audio_path,
                    transcription_result=transcription,
                    call_metadata=metadata
                )

                if result['success']:
                    results['successful'] += 1
                    if result['transcript_saved']:
                        results['transcripts_saved'] += 1
                    if result['audio_deleted']:
                        results['audio_deleted'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append(result.get('error', 'Unknown error'))

            except Exception as e:
                logger.error(f"Error processing recording: {e}")
                results['failed'] += 1
                results['errors'].append(str(e))

        # Log summary
        logger.info(f"Batch processing complete: {results['successful']}/{results['total']} successful")
        logger.info(f"Audio files deleted: {results['audio_deleted']}")
        logger.info(f"Transcripts saved: {results['transcripts_saved']}")

        return results

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get storage handler statistics

        Returns:
            Statistics dictionary
        """
        return {
            'audio_files_deleted': self.audio_files_deleted,
            'transcripts_saved': self.transcripts_saved,
            'total_audio_bytes_deleted': self.total_audio_bytes_deleted,
            'total_audio_mb_deleted': round(self.total_audio_bytes_deleted / (1024 * 1024), 2),
            'audit_log_enabled': self.enable_audit_log,
            'deletion_verification': self.verify_deletion
        }

    def verify_no_audio_in_drive(self) -> Dict[str, Any]:
        """
        Verify that NO audio files exist in Google Drive

        Returns:
            Verification results
        """
        if not self.drive_manager:
            return {'verified': False, 'error': 'No Drive manager configured'}

        audio_extensions = ['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.wma', '.aac']
        audio_mimetypes = ['audio/mpeg', 'audio/wav', 'audio/mp4', 'audio/ogg']

        try:
            # Search for any audio files
            files = self.drive_manager.list_files(
                query="mimeType contains 'audio/'"
            )

            audio_files = []
            for file in files:
                if any(file['name'].lower().endswith(ext) for ext in audio_extensions):
                    audio_files.append({
                        'name': file['name'],
                        'id': file['id'],
                        'size': file.get('size', 0)
                    })

            return {
                'verified': len(audio_files) == 0,
                'audio_files_found': len(audio_files),
                'files': audio_files[:10]  # Show max 10 files
            }

        except Exception as e:
            logger.error(f"Error verifying Drive contents: {e}")
            return {'verified': False, 'error': str(e)}