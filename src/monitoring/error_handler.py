"""
Error handling and classification system
"""

import logging
import time
import traceback
from enum import Enum
from typing import Optional, Dict, Any, Callable, Type
from datetime import datetime, timedelta
from dataclasses import dataclass
import json

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error categories"""
    TRANSIENT = "transient"  # Temporary errors that may resolve
    PERMANENT = "permanent"  # Errors that won't resolve without intervention
    CRITICAL = "critical"    # System-critical errors requiring immediate action


@dataclass
class ErrorContext:
    """Context information for an error"""
    error_type: str
    error_message: str
    category: ErrorCategory
    severity: ErrorSeverity
    component: str
    operation: str
    retry_count: int = 0
    max_retries: int = 3
    metadata: Optional[Dict[str, Any]] = None
    timestamp: datetime = None
    traceback: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'error_type': self.error_type,
            'error_message': self.error_message,
            'category': self.category.value,
            'severity': self.severity.value,
            'component': self.component,
            'operation': self.operation,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries,
            'metadata': self.metadata,
            'timestamp': self.timestamp.isoformat(),
            'traceback': self.traceback
        }


class ErrorClassifier:
    """
    Classifies errors into categories and severities
    """

    # Error classification rules
    ERROR_RULES = {
        # Network errors
        'ConnectionError': {
            'category': ErrorCategory.TRANSIENT,
            'severity': ErrorSeverity.MEDIUM,
            'retryable': True
        },
        'TimeoutError': {
            'category': ErrorCategory.TRANSIENT,
            'severity': ErrorSeverity.MEDIUM,
            'retryable': True
        },
        'HTTPError': {
            'category': ErrorCategory.TRANSIENT,
            'severity': ErrorSeverity.MEDIUM,
            'retryable': True
        },

        # Authentication errors
        'AuthenticationError': {
            'category': ErrorCategory.PERMANENT,
            'severity': ErrorSeverity.HIGH,
            'retryable': False
        },
        'InvalidJWTError': {
            'category': ErrorCategory.PERMANENT,
            'severity': ErrorSeverity.HIGH,
            'retryable': False
        },
        'TokenExpiredError': {
            'category': ErrorCategory.TRANSIENT,
            'severity': ErrorSeverity.LOW,
            'retryable': True
        },

        # Rate limiting
        'RateLimitError': {
            'category': ErrorCategory.TRANSIENT,
            'severity': ErrorSeverity.LOW,
            'retryable': True
        },

        # File system errors
        'FileNotFoundError': {
            'category': ErrorCategory.PERMANENT,
            'severity': ErrorSeverity.MEDIUM,
            'retryable': False
        },
        'PermissionError': {
            'category': ErrorCategory.PERMANENT,
            'severity': ErrorSeverity.HIGH,
            'retryable': False
        },
        'OSError': {
            'category': ErrorCategory.CRITICAL,
            'severity': ErrorSeverity.CRITICAL,
            'retryable': False
        },

        # Database errors
        'DatabaseError': {
            'category': ErrorCategory.CRITICAL,
            'severity': ErrorSeverity.CRITICAL,
            'retryable': True
        },
        'IntegrityError': {
            'category': ErrorCategory.PERMANENT,
            'severity': ErrorSeverity.HIGH,
            'retryable': False
        },

        # Resource errors
        'MemoryError': {
            'category': ErrorCategory.CRITICAL,
            'severity': ErrorSeverity.CRITICAL,
            'retryable': False
        },
        'RuntimeError': {
            'category': ErrorCategory.PERMANENT,
            'severity': ErrorSeverity.HIGH,
            'retryable': False
        }
    }

    @classmethod
    def classify(
        cls,
        error: Exception,
        component: str = "unknown",
        operation: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None
    ) -> ErrorContext:
        """
        Classify an error

        Args:
            error: Exception to classify
            component: Component where error occurred
            operation: Operation being performed
            metadata: Additional metadata

        Returns:
            ErrorContext object
        """
        error_type = type(error).__name__
        error_message = str(error)

        # Get classification rules
        rules = cls.ERROR_RULES.get(
            error_type,
            {
                'category': ErrorCategory.PERMANENT,
                'severity': ErrorSeverity.MEDIUM,
                'retryable': False
            }
        )

        # Special handling for HTTP errors
        if hasattr(error, 'response') and hasattr(error.response, 'status_code'):
            status_code = error.response.status_code
            if status_code >= 500:
                rules['category'] = ErrorCategory.TRANSIENT
                rules['severity'] = ErrorSeverity.HIGH
            elif status_code == 429:
                rules['category'] = ErrorCategory.TRANSIENT
                rules['severity'] = ErrorSeverity.LOW
            elif status_code >= 400:
                rules['category'] = ErrorCategory.PERMANENT
                rules['severity'] = ErrorSeverity.MEDIUM

        # Get traceback
        tb = traceback.format_exc()

        return ErrorContext(
            error_type=error_type,
            error_message=error_message,
            category=rules['category'],
            severity=rules['severity'],
            component=component,
            operation=operation,
            max_retries=3 if rules.get('retryable', False) else 0,
            metadata=metadata,
            traceback=tb
        )


class RecoveryStrategy:
    """Base class for recovery strategies"""

    def execute(self, context: ErrorContext) -> bool:
        """
        Execute recovery strategy

        Args:
            context: Error context

        Returns:
            True if recovery successful
        """
        raise NotImplementedError


class RetryStrategy(RecoveryStrategy):
    """Retry with exponential backoff"""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base

    def execute(self, context: ErrorContext) -> bool:
        if context.retry_count >= context.max_retries:
            return False

        delay = min(
            self.base_delay * (self.exponential_base ** context.retry_count),
            self.max_delay
        )

        logger.info(f"Retrying in {delay} seconds (attempt {context.retry_count + 1}/{context.max_retries})")
        time.sleep(delay)

        return True


class RefreshTokenStrategy(RecoveryStrategy):
    """Refresh authentication token"""

    def __init__(self, auth_handler: Callable):
        self.auth_handler = auth_handler

    def execute(self, context: ErrorContext) -> bool:
        if context.error_type in ['TokenExpiredError', 'AuthenticationError']:
            try:
                logger.info("Refreshing authentication token")
                self.auth_handler()
                return True
            except Exception as e:
                logger.error(f"Failed to refresh token: {e}")
                return False
        return False


class CleanupStrategy(RecoveryStrategy):
    """Clean up resources"""

    def __init__(self, cleanup_handler: Callable):
        self.cleanup_handler = cleanup_handler

    def execute(self, context: ErrorContext) -> bool:
        if context.severity == ErrorSeverity.CRITICAL:
            try:
                logger.info("Executing cleanup strategy")
                self.cleanup_handler()
                return True
            except Exception as e:
                logger.error(f"Cleanup failed: {e}")
                return False
        return False


class ErrorHandler:
    """
    Main error handler with recovery strategies
    """

    def __init__(self):
        """Initialize error handler"""
        self.classifier = ErrorClassifier()
        self.recovery_strategies = []
        self.error_history = []
        self.error_callbacks = []
        self.max_history_size = 1000

        # Add default strategies
        self.add_recovery_strategy(RetryStrategy())

        logger.info("ErrorHandler initialized")

    def add_recovery_strategy(self, strategy: RecoveryStrategy):
        """
        Add recovery strategy

        Args:
            strategy: Recovery strategy instance
        """
        self.recovery_strategies.append(strategy)

    def add_error_callback(self, callback: Callable[[ErrorContext], None]):
        """
        Add error callback

        Args:
            callback: Function called when error occurs
        """
        self.error_callbacks.append(callback)

    def handle_error(
        self,
        error: Exception,
        component: str = "unknown",
        operation: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None,
        retry_func: Optional[Callable] = None
    ) -> Any:
        """
        Handle an error with recovery strategies

        Args:
            error: Exception to handle
            component: Component where error occurred
            operation: Operation being performed
            metadata: Additional metadata
            retry_func: Function to retry if applicable

        Returns:
            Result of retry_func if successful, None otherwise
        """
        # Classify error
        context = self.classifier.classify(error, component, operation, metadata)

        # Log error
        self._log_error(context)

        # Add to history
        self._add_to_history(context)

        # Call callbacks
        for callback in self.error_callbacks:
            try:
                callback(context)
            except Exception as e:
                logger.error(f"Error callback failed: {e}")

        # Apply recovery strategies
        if context.category == ErrorCategory.TRANSIENT and retry_func:
            for strategy in self.recovery_strategies:
                if strategy.execute(context):
                    try:
                        logger.info(f"Retrying {operation} after recovery")
                        context.retry_count += 1
                        result = retry_func()
                        logger.info(f"Recovery successful for {operation}")
                        return result
                    except Exception as retry_error:
                        logger.error(f"Retry failed: {retry_error}")
                        # Update context for next strategy
                        context.error_message = str(retry_error)
                        context.retry_count += 1

        # Recovery failed or not applicable
        if context.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
            logger.critical(f"Unrecoverable error in {component}: {context.error_message}")

        return None

    def _log_error(self, context: ErrorContext):
        """
        Log error based on severity

        Args:
            context: Error context
        """
        log_message = (
            f"Error in {context.component}.{context.operation}: "
            f"{context.error_type} - {context.error_message}"
        )

        if context.severity == ErrorSeverity.CRITICAL:
            logger.critical(log_message)
        elif context.severity == ErrorSeverity.HIGH:
            logger.error(log_message)
        elif context.severity == ErrorSeverity.MEDIUM:
            logger.warning(log_message)
        else:
            logger.info(log_message)

    def _add_to_history(self, context: ErrorContext):
        """
        Add error to history

        Args:
            context: Error context
        """
        self.error_history.append(context)

        # Limit history size
        if len(self.error_history) > self.max_history_size:
            self.error_history = self.error_history[-self.max_history_size:]

    def get_error_statistics(self) -> Dict[str, Any]:
        """
        Get error statistics

        Returns:
            Dictionary with error statistics
        """
        if not self.error_history:
            return {
                'total_errors': 0,
                'by_category': {},
                'by_severity': {},
                'by_component': {}
            }

        stats = {
            'total_errors': len(self.error_history),
            'by_category': {},
            'by_severity': {},
            'by_component': {},
            'recent_errors': []
        }

        # Count by category
        for context in self.error_history:
            category = context.category.value
            stats['by_category'][category] = stats['by_category'].get(category, 0) + 1

            severity = context.severity.value
            stats['by_severity'][severity] = stats['by_severity'].get(severity, 0) + 1

            component = context.component
            stats['by_component'][component] = stats['by_component'].get(component, 0) + 1

        # Get recent errors
        stats['recent_errors'] = [
            ctx.to_dict() for ctx in self.error_history[-10:]
        ]

        return stats

    def save_error_report(self, output_path: str):
        """
        Save error report to file

        Args:
            output_path: Path to save report
        """
        report = {
            'generated_at': datetime.utcnow().isoformat(),
            'statistics': self.get_error_statistics(),
            'error_history': [ctx.to_dict() for ctx in self.error_history]
        }

        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)

        logger.info(f"Error report saved to {output_path}")

    def clear_history(self):
        """Clear error history"""
        self.error_history.clear()
        logger.info("Error history cleared")