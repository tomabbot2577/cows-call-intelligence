# RingCentral Call Recording Transcription System

Automated system for downloading, transcribing, and archiving RingCentral call recordings using OpenAI's Whisper.

## Features

- 🎯 Automated daily retrieval of RingCentral call recordings
- 🎙️ Local transcription using OpenAI Whisper
- ☁️ Google Drive integration for transcript storage
- 🔄 Complete error handling and recovery mechanisms
- 📊 Monitoring and alerting capabilities
- 🔐 Secure credential management

## Architecture

```
RingCentral API → Download → Transcribe (Whisper) → Upload (Google Drive)
                     ↓            ↓                      ↓
                PostgreSQL Database (State Management)
```

## Quick Start

### Prerequisites

- Ubuntu 22.04 LTS or macOS (for development)
- Python 3.10+
- PostgreSQL 12+
- ffmpeg
- 8GB RAM minimum
- 200GB storage

### Installation

1. Clone the repository:
```bash
git clone <repository_url>
cd call_recording_system
```

2. Run the setup script:
```bash
./scripts/setup.sh
```

3. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your credentials
```

4. Add Google Service Account credentials:
```bash
# Place your service account JSON in:
credentials/google_sa.json
```

5. Initialize the database:
```bash
source venv/bin/activate
alembic upgrade head
```

6. Test the setup:
```bash
python src/main.py --test
```

## Configuration

### RingCentral Setup

1. Create a RingCentral app at https://developers.ringcentral.com
2. Enable JWT authentication
3. Copy the JWT token to `.env`

### Google Drive Setup

1. Create a Google Cloud project
2. Enable Google Drive API
3. Create a service account
4. Download credentials JSON
5. Share target folder with service account email

### Environment Variables

See `.env.example` for all configuration options.

## Usage

### Manual Processing

```bash
# Process recordings from the last 7 days
python src/main.py --days 7

# Process specific date range
python src/main.py --from 2025-01-01 --to 2025-01-31
```

### Automated Processing

The system runs automatically via systemd:

```bash
# Start the service
sudo systemctl start call-recording-processor

# Enable on boot
sudo systemctl enable call-recording-processor

# Check status
sudo systemctl status call-recording-processor
```

## Project Structure

```
call_recording_system/
├── src/                 # Source code
│   ├── main.py         # Entry point
│   ├── config.py       # Configuration management
│   ├── ringcentral/    # RingCentral API integration
│   ├── transcription/  # Whisper transcription
│   ├── storage/        # Google Drive integration
│   └── database/       # Database models and operations
├── tests/              # Test suite
├── config/             # Configuration files
├── scripts/            # Utility scripts
├── systemd/            # Service definitions
└── logs/               # Application logs
```

## Monitoring

### Health Checks

```bash
# Check system health
curl http://localhost:8080/health

# View metrics
curl http://localhost:9090/metrics
```

### Logs

```bash
# View processor logs
tail -f logs/processor.log

# View error logs
tail -f logs/error.log
```

## Troubleshooting

### Common Issues

1. **High Memory Usage**
   - Reduce Whisper model size in config
   - Decrease batch size

2. **API Rate Limiting**
   - Check rate limit settings
   - Implement backoff strategy

3. **Disk Space Issues**
   - Run cleanup script: `./scripts/cleanup.sh`
   - Check archive retention policy

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src tests/
```

### Contributing

1. Create a feature branch
2. Make changes
3. Add tests
4. Submit pull request

## License

[Your License]

## Support

For issues or questions, please contact: admin@yourcompany.com