import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from ..config.settings import Settings

logger = logging.getLogger(__name__)

class TranscriptionPipeline:
    def __init__(self, model_name: str = "base", device: str = "cpu"):
        # Load configuration
        self.settings = Settings()

        # Initialize appropriate transcriber based on config
        if self.settings.transcription_service == 'salad':
            from .salad_transcriber_enhanced import SaladTranscriberEnhanced
            self.transcriber = SaladTranscriberEnhanced(
                api_key=self.settings.salad_api_key,
                organization_name=self.settings.salad_org_name,
                engine='full',  # Always use full for best quality
                language=self.settings.salad_language,
                initial_prompt=self.settings.salad_initial_prompt,
                webhook_url=self.settings.salad_webhook_url,
                polling_interval=self.settings.salad_polling_interval,
                max_wait_time=self.settings.salad_max_wait_time,
                max_retries=self.settings.salad_max_retries,
                retry_delay=self.settings.salad_retry_delay,
                enable_monitoring=self.settings.salad_enable_monitoring,
                enable_diarization=self.settings.salad_enable_diarization,
                enable_summarization=self.settings.salad_enable_summarization,
                custom_vocabulary=self.settings.salad_custom_vocabulary
            )
            logger.info("Using Salad Cloud Enhanced transcription service with best practices")
        else:
            from .transcriber import WhisperTranscriber
            from .audio_processor import AudioProcessor
            self.transcriber = WhisperTranscriber(model_name=model_name, device=device)
            self.audio_processor = AudioProcessor()
            logger.info("Using Whisper transcription service")

        self.service_type = self.settings.transcription_service

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

    def get_service_info(self) -> Dict[str, str]:
        """Get information about the current transcription service"""
        return {
            'service': self.service_type,
            'engine': self.settings.salad_engine if self.service_type == 'salad' else self.settings.whisper_model
        }
