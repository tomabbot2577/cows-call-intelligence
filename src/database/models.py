"""
SQLAlchemy models for RingCentral Call Recording System
"""

from datetime import datetime
from typing import Optional
from enum import Enum

from sqlalchemy import (
    Column, String, Integer, BigInteger, Float, Boolean,
    DateTime, Text, JSON, Index, ForeignKey, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

Base = declarative_base()


class ProcessingStatus(str, Enum):
    """
    Enum for processing status
    """
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class CallDirection(str, Enum):
    """
    Enum for call direction
    """
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"


class CallRecording(Base):
    """
    Model for call recording metadata and processing status
    """
    __tablename__ = "call_recordings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # RingCentral identifiers
    call_id = Column(String(100), unique=True, nullable=False, index=True)
    recording_id = Column(String(100), unique=True, nullable=False, index=True)
    session_id = Column(String(100))
    telephony_session_id = Column(String(100))

    # Call metadata
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    duration = Column(Integer, nullable=False)  # Duration in seconds
    direction = Column(String(20))
    from_number = Column(String(50))
    to_number = Column(String(50))
    from_name = Column(String(200))
    to_name = Column(String(200))
    recording_type = Column(String(20))  # Automatic, OnDemand

    # File metadata
    file_size_bytes = Column(BigInteger)
    audio_format = Column(String(10))  # mp3, wav, etc.

    # Download status
    download_status = Column(String(20), default=ProcessingStatus.PENDING)
    download_attempts = Column(Integer, default=0)
    download_completed_at = Column(DateTime(timezone=True))
    download_error = Column(Text)
    local_file_path = Column(String(500))

    # Transcription status
    transcription_status = Column(String(20), default=ProcessingStatus.PENDING)
    transcription_attempts = Column(Integer, default=0)
    transcription_completed_at = Column(DateTime(timezone=True))
    transcription_error = Column(Text)
    transcript_word_count = Column(Integer)
    transcript_confidence = Column(Float)
    language_detected = Column(String(10))
    transcription_duration_ms = Column(Integer)

    # Upload status
    upload_status = Column(String(20), default=ProcessingStatus.PENDING)
    upload_attempts = Column(Integer, default=0)
    upload_completed_at = Column(DateTime(timezone=True))
    upload_error = Column(Text)
    google_drive_file_id = Column(String(100))
    google_drive_url = Column(String(500))

    # General metadata
    error_message = Column(Text)
    processing_notes = Column(JSON)  # Additional metadata as JSON
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    processing_history = relationship(
        "ProcessingHistory",
        back_populates="call_recording",
        cascade="all, delete-orphan"
    )

    # Indexes
    __table_args__ = (
        Index('idx_processing_status',
              'download_status', 'transcription_status', 'upload_status'),
        Index('idx_start_time_direction', 'start_time', 'direction'),
        Index('idx_created_at', 'created_at'),
    )

    def __repr__(self):
        return (f"<CallRecording(id={self.id}, call_id={self.call_id}, "
                f"recording_id={self.recording_id}, start_time={self.start_time})>")


class ProcessingHistory(Base):
    """
    Model for tracking processing history and audit trail
    """
    __tablename__ = "processing_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    recording_id = Column(String(100), ForeignKey('call_recordings.recording_id'), nullable=False)

    # Action details
    action = Column(String(50), nullable=False)  # download, transcribe, upload, etc.
    status = Column(String(20), nullable=False)  # success, failed, skipped
    details = Column(JSON)  # Additional details as JSON
    error_message = Column(Text)

    # Timing
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    duration_ms = Column(Integer)

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(String(50), default='system')

    # Relationships
    call_recording = relationship("CallRecording", back_populates="processing_history")

    # Indexes
    __table_args__ = (
        Index('idx_recording_action', 'recording_id', 'action'),
        Index('idx_created_at_history', 'created_at'),
    )

    def __repr__(self):
        return (f"<ProcessingHistory(id={self.id}, recording_id={self.recording_id}, "
                f"action={self.action}, status={self.status})>")


class SystemMetric(Base):
    """
    Model for storing system metrics and performance data
    """
    __tablename__ = "system_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Metric information
    metric_name = Column(String(50), nullable=False, index=True)
    metric_value = Column(Float, nullable=False)
    metric_unit = Column(String(20))  # seconds, bytes, percent, etc.

    # Context
    tags = Column(JSON)  # Additional tags as JSON
    component = Column(String(50))  # Component that generated the metric

    # Timestamp
    recorded_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Indexes
    __table_args__ = (
        Index('idx_metric_time', 'metric_name', 'recorded_at'),
        Index('idx_component_metric', 'component', 'metric_name'),
    )

    def __repr__(self):
        return (f"<SystemMetric(id={self.id}, metric_name={self.metric_name}, "
                f"metric_value={self.metric_value}, recorded_at={self.recorded_at})>")


class ProcessingState(Base):
    """
    Model for maintaining processing state and checkpoints
    """
    __tablename__ = "processing_state"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # State information
    state_key = Column(String(50), unique=True, nullable=False)
    state_value = Column(JSON, nullable=False)
    is_active = Column(Boolean, default=True)

    # Metadata
    description = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by = Column(String(50), default='system')

    # Indexes
    __table_args__ = (
        UniqueConstraint('state_key', name='uq_state_key'),
    )

    def __repr__(self):
        return f"<ProcessingState(id={self.id}, state_key={self.state_key})>"


class FailedDownload(Base):
    """
    Model for tracking permanently failed downloads
    """
    __tablename__ = "failed_downloads"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Recording information
    call_id = Column(String(100), unique=True, nullable=False)
    recording_id = Column(String(100), unique=True, nullable=False)

    # Failure information
    failure_reason = Column(Text, nullable=False)
    last_error = Column(Text)
    attempt_count = Column(Integer, default=0)

    # Metadata
    first_attempted_at = Column(DateTime(timezone=True))
    last_attempted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Indexes
    __table_args__ = (
        Index('idx_failed_recording_id', 'recording_id'),
        Index('idx_failed_created_at', 'created_at'),
    )

    def __repr__(self):
        return (f"<FailedDownload(id={self.id}, recording_id={self.recording_id}, "
                f"failure_reason={self.failure_reason})>")