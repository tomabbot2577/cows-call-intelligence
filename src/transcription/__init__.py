"""
Transcription package for audio processing and speech-to-text
"""

# Lazy imports to avoid loading unnecessary dependencies
__all__ = [
    'WhisperTranscriber',
    'AudioProcessor',
    'ModelManager',
    'SaladTranscriber'
]

def __getattr__(name):
    """Lazy import to avoid loading unnecessary dependencies"""
    if name == 'WhisperTranscriber':
        from .transcriber import WhisperTranscriber
        return WhisperTranscriber
    elif name == 'AudioProcessor':
        from .audio_processor import AudioProcessor
        return AudioProcessor
    elif name == 'ModelManager':
        from .model_manager import ModelManager
        return ModelManager
    elif name == 'SaladTranscriber':
        from .salad_transcriber import SaladTranscriber
        return SaladTranscriber
    raise AttributeError(f"module {__name__} has no attribute {name}")