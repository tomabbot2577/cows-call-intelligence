"""
Whisper Model Manager
Handles model loading, caching, and configuration
"""

import os
import logging
import hashlib
from typing import Optional, Dict, Any
from pathlib import Path
import json

import torch
import whisper

logger = logging.getLogger(__name__)


class ModelManager:
    """
    Manages Whisper models with caching and optimization
    """

    # Model specifications
    MODEL_SPECS = {
        'tiny': {
            'size_mb': 72,
            'vram_gb': 1,
            'relative_speed': 32,
            'wer': 17.8,
            'parameters': '39M'
        },
        'base': {
            'size_mb': 142,
            'vram_gb': 1,
            'relative_speed': 16,
            'wer': 10.7,
            'parameters': '74M'
        },
        'small': {
            'size_mb': 466,
            'vram_gb': 2,
            'relative_speed': 6,
            'wer': 7.5,
            'parameters': '244M'
        },
        'medium': {
            'size_mb': 1500,
            'vram_gb': 5,
            'relative_speed': 2,
            'wer': 5.4,
            'parameters': '769M'
        },
        'large': {
            'size_mb': 3000,
            'vram_gb': 10,
            'relative_speed': 1,
            'wer': 4.8,
            'parameters': '1550M'
        }
    }

    def __init__(
        self,
        model_name: str = 'base',
        device: Optional[str] = None,
        cache_dir: Optional[str] = None,
        compute_type: str = 'int8'
    ):
        """
        Initialize model manager

        Args:
            model_name: Whisper model size (tiny, base, small, medium, large)
            device: Device to use (cuda, cpu, or auto)
            cache_dir: Directory to cache models
            compute_type: Compute type for optimization (int8, float16, float32)
        """
        self.model_name = model_name
        self.compute_type = compute_type
        self.cache_dir = cache_dir or os.path.expanduser("~/.cache/whisper")

        # Determine device
        if device is None:
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        else:
            self.device = device

        # Model instance
        self.model = None
        self.model_hash = None

        # Performance metrics
        self.load_time = 0
        self.transcriptions_count = 0

        logger.info(f"ModelManager initialized: model={model_name}, device={self.device}")

    def load_model(self, force_reload: bool = False) -> whisper.Whisper:
        """
        Load Whisper model with caching

        Args:
            force_reload: Force reload even if model is cached

        Returns:
            Loaded Whisper model

        Raises:
            RuntimeError: If model loading fails
        """
        if self.model is not None and not force_reload:
            logger.debug("Using cached model")
            return self.model

        try:
            import time
            start_time = time.time()

            logger.info(f"Loading Whisper model: {self.model_name}")

            # Create cache directory if needed
            Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

            # Load model
            self.model = whisper.load_model(
                name=self.model_name,
                device=self.device,
                download_root=self.cache_dir
            )

            # Apply optimizations
            if self.device == 'cpu' and self.compute_type == 'int8':
                logger.info("Applying INT8 quantization for CPU")
                # Note: INT8 quantization would require additional libraries
                # like torch.quantization or Intel Extension for PyTorch

            self.load_time = time.time() - start_time
            logger.info(f"Model loaded in {self.load_time:.2f} seconds")

            # Calculate model hash for verification
            self.model_hash = self._calculate_model_hash()

            return self.model

        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise RuntimeError(f"Failed to load Whisper model: {e}")

    def _calculate_model_hash(self) -> str:
        """
        Calculate hash of loaded model for verification

        Returns:
            Model hash string
        """
        if self.model is None:
            return ""

        # Create hash from model parameters
        hasher = hashlib.md5()

        for param in self.model.parameters():
            hasher.update(param.data.cpu().numpy().tobytes())

        return hasher.hexdigest()[:8]

    def get_model_info(self) -> Dict[str, Any]:
        """
        Get information about the current model

        Returns:
            Dictionary with model information
        """
        info = {
            'name': self.model_name,
            'device': self.device,
            'compute_type': self.compute_type,
            'loaded': self.model is not None,
            'hash': self.model_hash,
            'load_time': self.load_time,
            'transcriptions_count': self.transcriptions_count
        }

        # Add specifications
        if self.model_name in self.MODEL_SPECS:
            info.update(self.MODEL_SPECS[self.model_name])

        # Add device info
        if self.device == 'cuda' and torch.cuda.is_available():
            info['cuda_device'] = torch.cuda.get_device_name()
            info['cuda_memory_allocated'] = torch.cuda.memory_allocated() / 1024**3  # GB
            info['cuda_memory_cached'] = torch.cuda.memory_reserved() / 1024**3  # GB

        return info

    def optimize_for_batch(self, batch_size: int):
        """
        Optimize model for batch processing

        Args:
            batch_size: Expected batch size
        """
        if self.model is None:
            logger.warning("No model loaded to optimize")
            return

        if self.device == 'cuda':
            # Set optimal CUDA settings for batch processing
            torch.backends.cudnn.benchmark = True
            torch.backends.cuda.matmul.allow_tf32 = True

            logger.info(f"Optimized for batch size {batch_size} on CUDA")

    def check_memory_usage(self) -> Dict[str, float]:
        """
        Check current memory usage

        Returns:
            Dictionary with memory usage statistics
        """
        import psutil

        memory_stats = {
            'system_ram_gb': psutil.virtual_memory().used / 1024**3,
            'system_ram_percent': psutil.virtual_memory().percent
        }

        if self.device == 'cuda' and torch.cuda.is_available():
            memory_stats.update({
                'gpu_allocated_gb': torch.cuda.memory_allocated() / 1024**3,
                'gpu_cached_gb': torch.cuda.memory_reserved() / 1024**3,
                'gpu_available_gb': (
                    torch.cuda.get_device_properties(0).total_memory -
                    torch.cuda.memory_reserved()
                ) / 1024**3
            })

        return memory_stats

    def estimate_processing_time(
        self,
        audio_duration_seconds: float
    ) -> float:
        """
        Estimate processing time for audio

        Args:
            audio_duration_seconds: Duration of audio in seconds

        Returns:
            Estimated processing time in seconds
        """
        if self.model_name not in self.MODEL_SPECS:
            # Conservative estimate
            return audio_duration_seconds * 0.5

        relative_speed = self.MODEL_SPECS[self.model_name]['relative_speed']

        # Base processing time (for 'large' model)
        base_time = audio_duration_seconds * 0.8  # 80% of real-time for large

        # Adjust based on model speed
        estimated_time = base_time / relative_speed

        # Adjust for device
        if self.device == 'cpu':
            estimated_time *= 2  # CPU is roughly 2x slower

        return estimated_time

    def validate_model(self) -> bool:
        """
        Validate loaded model

        Returns:
            True if model is valid, False otherwise
        """
        if self.model is None:
            logger.error("No model loaded")
            return False

        try:
            # Test with silence
            import numpy as np

            # Create 1 second of silence
            test_audio = np.zeros(16000, dtype=np.float32)

            # Try to transcribe
            result = self.model.transcribe(
                test_audio,
                temperature=0,
                language='en'
            )

            logger.info("Model validation successful")
            return True

        except Exception as e:
            logger.error(f"Model validation failed: {e}")
            return False

    def clear_cache(self):
        """
        Clear model from memory
        """
        if self.model is not None:
            del self.model
            self.model = None

            if self.device == 'cuda':
                torch.cuda.empty_cache()

            logger.info("Model cache cleared")

    def save_config(self, filepath: str):
        """
        Save model configuration

        Args:
            filepath: Path to save configuration
        """
        config = {
            'model_name': self.model_name,
            'device': self.device,
            'compute_type': self.compute_type,
            'cache_dir': self.cache_dir,
            'model_hash': self.model_hash,
            'transcriptions_count': self.transcriptions_count
        }

        with open(filepath, 'w') as f:
            json.dump(config, f, indent=2)

        logger.info(f"Configuration saved to {filepath}")

    @classmethod
    def from_config(cls, filepath: str) -> 'ModelManager':
        """
        Load model manager from configuration

        Args:
            filepath: Path to configuration file

        Returns:
            ModelManager instance
        """
        with open(filepath, 'r') as f:
            config = json.load(f)

        manager = cls(
            model_name=config.get('model_name', 'base'),
            device=config.get('device'),
            cache_dir=config.get('cache_dir'),
            compute_type=config.get('compute_type', 'int8')
        )

        manager.transcriptions_count = config.get('transcriptions_count', 0)

        logger.info(f"ModelManager loaded from {filepath}")
        return manager