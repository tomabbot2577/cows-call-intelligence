import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

class Settings:
    def __init__(self):
        # Database
        self.database_url = os.getenv('DATABASE_URL')
        
        # RingCentral
        self.ringcentral_client_id = os.getenv('RINGCENTRAL_CLIENT_ID')
        self.ringcentral_client_secret = os.getenv('RINGCENTRAL_CLIENT_SECRET')
        self.ringcentral_jwt_token = os.getenv('RINGCENTRAL_JWT_TOKEN')
        self.ringcentral_server_url = os.getenv('RINGCENTRAL_SERVER_URL', 'https://platform.ringcentral.com')
        self.ringcentral_account_id = os.getenv('RINGCENTRAL_ACCOUNT_ID', '')
        
        # Google Drive
        self.google_credentials_path = os.getenv('GOOGLE_CREDENTIALS_PATH', '/var/www/call-recording-system/config/google_service_account.json')
        self.google_drive_folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
        
        # Transcription Settings
        self.transcription_service = os.getenv('TRANSCRIPTION_SERVICE', 'salad')  # 'salad' or 'whisper'

        # Salad Cloud Settings (Best Practices Configuration)
        self.salad_api_key = os.getenv('SALAD_API_KEY', 'salad_cloud_user_eG0tAkgYi0w0IPPUHpikdfhZG2Auw9MIin9Ld8PdLDQ0HGYCn')
        self.salad_org_name = os.getenv('SALAD_ORG_NAME', 'default')
        self.salad_engine = 'full'  # Always use 'full' for best quality
        self.salad_language = os.getenv('SALAD_LANGUAGE', 'en-US')  # American English
        self.salad_webhook_url = os.getenv('SALAD_WEBHOOK_URL', '')

        # Salad Advanced Features
        self.salad_enable_diarization = os.getenv('SALAD_ENABLE_DIARIZATION', 'false').lower() == 'true'
        self.salad_enable_summarization = os.getenv('SALAD_ENABLE_SUMMARIZATION', 'false').lower() == 'true'
        self.salad_custom_vocabulary = os.getenv('SALAD_CUSTOM_VOCABULARY', '')
        self.salad_initial_prompt = os.getenv('SALAD_INITIAL_PROMPT',
            'Professional business call transcription. Focus on accuracy, proper names, and technical terms.')

        # Salad Performance Settings
        self.salad_max_retries = int(os.getenv('SALAD_MAX_RETRIES', '3'))
        self.salad_retry_delay = int(os.getenv('SALAD_RETRY_DELAY', '5'))
        self.salad_polling_interval = int(os.getenv('SALAD_POLLING_INTERVAL', '3'))
        self.salad_max_wait_time = int(os.getenv('SALAD_MAX_WAIT_TIME', '3600'))

        # Monitoring and Metrics
        self.salad_enable_monitoring = os.getenv('SALAD_ENABLE_MONITORING', 'true').lower() == 'true'

        # Whisper Settings (kept for backward compatibility)
        self.whisper_model = os.getenv('WHISPER_MODEL', 'base')
        self.whisper_device = os.getenv('WHISPER_DEVICE', 'cpu')
        self.whisper_compute_type = os.getenv('WHISPER_COMPUTE_TYPE', 'int8')
        
        # Processing Settings
        self.batch_size = int(os.getenv('BATCH_SIZE', '50'))
        self.max_workers = int(os.getenv('MAX_WORKERS', '4'))
        self.daily_schedule_time = os.getenv('DAILY_SCHEDULE_TIME', '02:00')
        self.historical_days = int(os.getenv('HISTORICAL_DAYS', '60'))
        self.max_retries = int(os.getenv('MAX_RETRIES', '3'))
        
        # Storage Paths
        self.audio_storage_path = os.getenv('AUDIO_STORAGE_PATH', '/var/www/call-recording-system/data/audio')
        self.transcript_storage_path = os.getenv('TRANSCRIPT_STORAGE_PATH', '/var/www/call-recording-system/data/transcripts')
        self.log_file_path = os.getenv('LOG_FILE_PATH', '/var/www/call-recording-system/logs/app.log')
        
        # Monitoring
        self.prometheus_enabled = os.getenv('PROMETHEUS_ENABLED', 'false').lower() == 'true'
        self.smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.smtp_user = os.getenv('SMTP_USER', '')
        self.smtp_password = os.getenv('SMTP_PASSWORD', '')
        self.alert_email = os.getenv('ALERT_EMAIL', '')
        self.slack_webhook = os.getenv('SLACK_WEBHOOK', '')
