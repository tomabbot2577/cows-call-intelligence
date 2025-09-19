import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from .transcriber import WhisperTranscriber
from .audio_processor import AudioProcessor

logger = logging.getLogger(__name__)

class TranscriptionPipeline:
    def __init__(self, model_name: str = "base", device: str = "cpu"):
        self.transcriber = WhisperTranscriber(model_name=model_name, device=device)
        self.audio_processor = AudioProcessor()
    
    def process(self, audio_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """Process an audio file through the transcription pipeline"""
        try:
            # Transcribe the audio file
            result = self.transcriber.transcribe_file(audio_path)

            # Convert TranscriptionResult to dictionary
            result_dict = result.to_dict() if hasattr(result, 'to_dict') else result

            # Save output if directory specified
            if output_dir:
                output_path = Path(output_dir) / f"{Path(audio_path).stem}.txt"
                with open(output_path, 'w') as f:
                    f.write(result_dict.get('text', ''))

            return result_dict

        except Exception as e:
            logger.error(f"Pipeline processing failed: {e}")
            raise
