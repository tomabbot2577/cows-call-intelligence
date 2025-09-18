"""
Batch Upload Manager for Google Drive
Handles bulk uploads with retry logic and progress tracking
"""

import os
import logging
import json
import time
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue, Empty
import threading

from .google_drive import GoogleDriveManager

logger = logging.getLogger(__name__)


class UploadTask:
    """
    Represents a single upload task
    """

    def __init__(
        self,
        file_path: str,
        file_name: Optional[str] = None,
        folder_id: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
        priority: int = 0
    ):
        self.file_path = file_path
        self.file_name = file_name or os.path.basename(file_path)
        self.folder_id = folder_id
        self.metadata = metadata or {}
        self.priority = priority

        # Status tracking
        self.status = 'pending'  # pending, uploading, completed, failed
        self.file_id = None
        self.error = None
        self.attempts = 0
        self.start_time = None
        self.end_time = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'file_path': self.file_path,
            'file_name': self.file_name,
            'folder_id': self.folder_id,
            'metadata': self.metadata,
            'status': self.status,
            'file_id': self.file_id,
            'error': str(self.error) if self.error else None,
            'attempts': self.attempts,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None
        }


class BatchUploader:
    """
    Manages batch uploads to Google Drive with concurrency and retry logic
    """

    def __init__(
        self,
        drive_manager: GoogleDriveManager,
        max_workers: int = 4,
        max_retries: int = 3,
        retry_delay: int = 5
    ):
        """
        Initialize batch uploader

        Args:
            drive_manager: GoogleDriveManager instance
            max_workers: Maximum concurrent uploads
            max_retries: Maximum retry attempts per file
            retry_delay: Delay between retries in seconds
        """
        self.drive_manager = drive_manager
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Task queue and tracking
        self.task_queue = Queue()
        self.tasks = {}  # file_path -> UploadTask
        self.completed_count = 0
        self.failed_count = 0
        self.total_bytes_uploaded = 0

        # Threading
        self.executor = None
        self.futures = []
        self.stop_event = threading.Event()

        # Progress callback
        self.progress_callback = None

        logger.info(f"BatchUploader initialized with {max_workers} workers")

    def add_task(
        self,
        file_path: str,
        file_name: Optional[str] = None,
        folder_id: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
        priority: int = 0
    ) -> UploadTask:
        """
        Add upload task to queue

        Args:
            file_path: Path to file
            file_name: Name in Drive
            folder_id: Target folder
            metadata: File metadata
            priority: Task priority (higher = more important)

        Returns:
            UploadTask object

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        task = UploadTask(
            file_path=file_path,
            file_name=file_name,
            folder_id=folder_id,
            metadata=metadata,
            priority=priority
        )

        self.tasks[file_path] = task
        self.task_queue.put((-priority, task))  # Negative for priority queue

        logger.debug(f"Added upload task: {file_path}")
        return task

    def add_transcript(
        self,
        recording_id: str,
        transcript_data: Dict[str, Any],
        audio_file_path: Optional[str] = None,
        folder_id: Optional[str] = None
    ) -> List[UploadTask]:
        """
        Add transcript and optionally audio file for upload

        Args:
            recording_id: Recording ID
            transcript_data: Transcript data dictionary
            audio_file_path: Optional audio file path
            folder_id: Target folder

        Returns:
            List of created tasks
        """
        tasks = []

        # Prepare metadata
        metadata = {
            'recording_id': recording_id,
            'call_id': transcript_data.get('call_id', ''),
            'start_time': transcript_data.get('start_time', ''),
            'duration': str(transcript_data.get('duration', 0)),
            'language': transcript_data.get('language', ''),
            'confidence': str(transcript_data.get('confidence', 0))
        }

        # Generate file names
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_name = f"{timestamp}_{recording_id}"

        # Create transcript JSON file
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.json',
            delete=False,
            prefix=f"{base_name}_transcript_"
        ) as tmp_file:
            json.dump(transcript_data, tmp_file, indent=2, ensure_ascii=False)
            transcript_path = tmp_file.name

        # Add transcript upload task
        transcript_task = self.add_task(
            file_path=transcript_path,
            file_name=f"{base_name}_transcript.json",
            folder_id=folder_id,
            metadata=metadata,
            priority=1  # Higher priority for transcripts
        )
        tasks.append(transcript_task)

        # Add audio file if provided
        if audio_file_path and os.path.exists(audio_file_path):
            audio_task = self.add_task(
                file_path=audio_file_path,
                file_name=f"{base_name}_audio{Path(audio_file_path).suffix}",
                folder_id=folder_id,
                metadata=metadata,
                priority=0
            )
            tasks.append(audio_task)

        return tasks

    def start(self, wait: bool = True) -> Dict[str, Any]:
        """
        Start batch upload process

        Args:
            wait: Whether to wait for completion

        Returns:
            Summary of results
        """
        if self.executor:
            logger.warning("Batch upload already running")
            return {}

        total_tasks = self.task_queue.qsize()
        logger.info(f"Starting batch upload of {total_tasks} files")

        self.stop_event.clear()
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self.futures = []

        # Start workers
        for i in range(min(self.max_workers, total_tasks)):
            future = self.executor.submit(self._worker)
            self.futures.append(future)

        if wait:
            return self.wait_for_completion()

        return {'started': True, 'total_tasks': total_tasks}

    def _worker(self):
        """
        Worker thread for processing upload tasks
        """
        while not self.stop_event.is_set():
            try:
                # Get task from queue (timeout to check stop event)
                priority, task = self.task_queue.get(timeout=1)

            except Empty:
                # Queue empty, exit
                break

            # Process task
            self._process_task(task)
            self.task_queue.task_done()

    def _process_task(self, task: UploadTask):
        """
        Process single upload task with retry logic

        Args:
            task: Upload task to process
        """
        task.start_time = datetime.now()
        task.status = 'uploading'

        for attempt in range(self.max_retries):
            task.attempts = attempt + 1

            try:
                logger.info(f"Uploading {task.file_name} (attempt {task.attempts})")

                # Upload file
                file_id = self.drive_manager.upload_file(
                    file_path=task.file_path,
                    file_name=task.file_name,
                    folder_id=task.folder_id,
                    metadata=task.metadata
                )

                # Success
                task.file_id = file_id
                task.status = 'completed'
                task.end_time = datetime.now()

                # Update statistics
                self.completed_count += 1
                file_size = os.path.getsize(task.file_path)
                self.total_bytes_uploaded += file_size

                logger.info(f"Successfully uploaded {task.file_name} (ID: {file_id})")

                # Call progress callback
                if self.progress_callback:
                    self.progress_callback(task)

                # Clean up temp file if it's a transcript
                if 'transcript' in task.file_path and '/tmp/' in task.file_path:
                    try:
                        os.remove(task.file_path)
                    except:
                        pass

                break

            except Exception as e:
                logger.error(f"Upload failed for {task.file_name}: {e}")
                task.error = e

                if attempt < self.max_retries - 1:
                    logger.info(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                else:
                    # Final failure
                    task.status = 'failed'
                    task.end_time = datetime.now()
                    self.failed_count += 1

                    if self.progress_callback:
                        self.progress_callback(task)

    def wait_for_completion(self) -> Dict[str, Any]:
        """
        Wait for all uploads to complete

        Returns:
            Summary of results
        """
        if not self.executor:
            return {}

        # Wait for all tasks to complete
        self.task_queue.join()

        # Wait for workers to finish
        for future in as_completed(self.futures):
            try:
                future.result()
            except Exception as e:
                logger.error(f"Worker error: {e}")

        # Shutdown executor
        self.executor.shutdown(wait=True)
        self.executor = None

        return self.get_summary()

    def stop(self):
        """
        Stop batch upload process
        """
        logger.info("Stopping batch upload")
        self.stop_event.set()

        if self.executor:
            self.executor.shutdown(wait=False)
            self.executor = None

    def get_summary(self) -> Dict[str, Any]:
        """
        Get upload summary

        Returns:
            Summary dictionary
        """
        completed_tasks = [
            task for task in self.tasks.values()
            if task.status == 'completed'
        ]

        failed_tasks = [
            task for task in self.tasks.values()
            if task.status == 'failed'
        ]

        pending_tasks = [
            task for task in self.tasks.values()
            if task.status == 'pending'
        ]

        return {
            'total_tasks': len(self.tasks),
            'completed': self.completed_count,
            'failed': self.failed_count,
            'pending': len(pending_tasks),
            'total_bytes_uploaded': self.total_bytes_uploaded,
            'completed_tasks': [task.to_dict() for task in completed_tasks],
            'failed_tasks': [task.to_dict() for task in failed_tasks]
        }

    def save_results(self, output_path: str):
        """
        Save upload results to file

        Args:
            output_path: Path to save results
        """
        summary = self.get_summary()

        with open(output_path, 'w') as f:
            json.dump(summary, f, indent=2, default=str)

        logger.info(f"Results saved to {output_path}")

    def set_progress_callback(self, callback: Callable[[UploadTask], None]):
        """
        Set progress callback function

        Args:
            callback: Function called after each task completes
        """
        self.progress_callback = callback

    def organize_uploads_by_date(self) -> Dict[str, str]:
        """
        Organize uploads into date-based folder structure

        Returns:
            Dictionary mapping dates to folder IDs
        """
        folders = {}

        # Group tasks by date
        tasks_by_date = {}

        for task in self.tasks.values():
            # Extract date from metadata or use current date
            date_str = task.metadata.get('start_time', '')

            if date_str:
                try:
                    date = datetime.fromisoformat(date_str).date()
                except:
                    date = datetime.now().date()
            else:
                date = datetime.now().date()

            if date not in tasks_by_date:
                tasks_by_date[date] = []

            tasks_by_date[date].append(task)

        # Create folders for each date
        for date, date_tasks in tasks_by_date.items():
            folder_id = self.drive_manager.organize_by_date()
            folders[str(date)] = folder_id

            # Update tasks with folder ID
            for task in date_tasks:
                task.folder_id = folder_id

        return folders

    def cleanup(self):
        """
        Clean up resources
        """
        self.stop()

        # Clear queues and tasks
        while not self.task_queue.empty():
            try:
                self.task_queue.get_nowait()
            except Empty:
                break

        self.tasks.clear()

        logger.info("BatchUploader cleaned up")