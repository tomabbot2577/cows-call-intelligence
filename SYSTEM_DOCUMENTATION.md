# 📞 Call Recording System - Complete Documentation
## RingCentral → Salad Transcription → Google Drive Pipeline

---

## 🏗️ System Architecture Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   RingCentral   │────▶│  Audio Queue     │────▶│ Salad Cloud API │
│   Call Records  │     │  (.mp3 files)    │     │  Transcription  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                │                          │
                                ▼                          ▼
                    ┌──────────────────┐       ┌─────────────────┐
                    │   PostgreSQL     │       │  Enhanced       │
                    │   Database       │◀──────│  Storage        │
                    │   (tracking)     │       │  Organizer      │
                    └──────────────────┘       └─────────────────┘
                                                          │
                                ┌─────────────────────────┼─────────────────┐
                                ▼                         ▼                 ▼
                    ┌──────────────────┐     ┌──────────────────┐  ┌──────────────┐
                    │  JSON Files      │     │  Markdown Files  │  │ Google Drive │
                    │  (LLM/N8N)       │     │  (Human Review)  │  │   Storage    │
                    └──────────────────┘     └──────────────────┘  └──────────────┘
```

---

## 📁 Project Structure

```
/var/www/call-recording-system/
├── src/
│   ├── scheduler/              # Scheduling and automation
│   │   ├── ringcentral_checker.py    # Checks for new recordings (runs 6x daily)
│   │   ├── transcription_processor.py # Processes queue through pipeline
│   │   ├── batch_processor.py        # Batch processing utilities
│   │   └── scheduler.py              # Main scheduler coordinator
│   │
│   ├── ringcentral/            # RingCentral integration
│   │   ├── auth.py                   # JWT authentication
│   │   ├── client.py                 # API client wrapper
│   │   ├── rate_limiter.py          # Rate limiting (429 handling)
│   │   └── exceptions.py            # Custom exceptions
│   │
│   ├── transcription/          # Transcription services
│   │   ├── salad_transcriber_enhanced.py  # Enhanced Salad Cloud integration
│   │   ├── salad_transcriber.py          # Basic Salad transcriber
│   │   ├── pipeline.py                   # Transcription pipeline
│   │   └── audio_processor.py           # Audio preprocessing
│   │
│   ├── storage/                # Storage and organization
│   │   ├── enhanced_organizer.py        # Dual format storage (JSON/MD)
│   │   ├── google_drive.py             # Google Drive API integration
│   │   ├── structured_data_organizer.py # Data organization
│   │   └── markdown_transcript_generator.py # MD generation
│   │
│   ├── database/               # Database management
│   │   ├── models.py                    # SQLAlchemy models
│   │   ├── session.py                   # Session management
│   │   ├── connection.py               # Connection handling
│   │   └── manager.py                  # Database operations
│   │
│   ├── monitoring/             # System monitoring
│   │   ├── salad_monitor.py            # Salad API monitoring
│   │   ├── health_check.py             # System health checks
│   │   ├── metrics.py                  # Performance metrics
│   │   └── alerts.py                   # Alert system
│   │
│   └── integrations/           # External integrations
│       └── n8n_integration.py          # N8N workflow hooks
│
├── data/                       # Data storage
│   ├── audio_queue/                    # Downloaded MP3 files
│   ├── processed/                      # Processed audio files
│   ├── failed/                         # Failed processing
│   ├── transcriptions/                 # Transcription storage
│   │   ├── json/                       # JSON format (by date)
│   │   ├── markdown/                   # Markdown format (by date)
│   │   └── indexes/                    # Search indexes
│   ├── n8n_integration/                # N8N workflow queues
│   │   ├── queue/                      # New items
│   │   ├── processing/                 # In progress
│   │   ├── completed/                  # Completed
│   │   └── failed/                     # Failed items
│   └── scheduler/                      # Scheduler state
│       ├── last_check.json             # Last check timestamp
│       └── processing_summary.json     # Processing stats
│
├── logs/                       # System logs
│   └── ringcentral_checker_YYYYMMDD.log
│
├── scripts/                    # Utility scripts
│   ├── setup_cron_schedule.sh         # Setup cron jobs
│   ├── run_ringcentral_check.sh       # Manual check script
│   ├── finish_downloads.py            # Complete batch downloads
│   └── process_batch_transcriptions.py # Batch transcription
│
└── docs/                       # Documentation
    ├── SYSTEM_DOCUMENTATION.md        # This file
    ├── TRANSCRIPTION_FILING_PLAN.md   # Filing structure
    ├── N8N_API_DOCUMENTATION.md       # N8N integration
    └── ENHANCED_METADATA_SUMMARY.md   # Metadata fields
```

---

## 🔄 Complete Process Flow

### 1. Recording Capture (RingCentral)

**Automated Schedule:** Runs 6 times daily (7am, 10am, 1pm, 3pm, 5pm, 8pm)

**Script:** `src/scheduler/ringcentral_checker.py`

**Process:**
1. Authenticates with RingCentral using JWT
2. Checks for new recordings since last check
3. **Duplicate Prevention:**
   - Checks if file already exists in queue
   - Checks database by RingCentral ID
   - Checks by session ID (same call, different ID)
   - Checks by call details (time/numbers/duration within 5s window)
4. Downloads new recordings to `/data/audio_queue/`
5. Creates database entry with status `DOWNLOADED`
6. Updates state file with last check timestamp

**Rate Limiting:** 20-second delay between downloads

### 2. Transcription Processing (Salad Cloud)

**Trigger:** Automatically after RingCentral check if queue has files

**Script:** `src/scheduler/transcription_processor.py`

**Process:**
1. Queries database for recordings with status `DOWNLOADED`
2. **Duplicate Check:** Verifies not already transcribed
3. Updates status to `TRANSCRIBING`
4. Uploads audio to temporary storage for Salad access
5. Calls Salad API with enhanced features:
   - Engine: Full (highest quality)
   - Diarization: Enabled (speaker separation)
   - Summarization: Enabled
   - Language: en-US
6. Waits for transcription completion (polling)
7. Extracts all metadata:
   - Text, segments, word timing
   - Speaker information
   - Summary, SRT content
   - Confidence scores

**Rate Limiting:** 5-second delay between transcriptions

### 3. Storage & Organization

**Component:** `src/storage/enhanced_organizer.py`

**Creates Three Outputs:**

#### A. JSON File (LLM/N8N Processing)
Location: `/data/transcriptions/json/YYYY/MM/DD/[recording_id].json`

Contains:
- Complete transcription text
- Segment-by-segment breakdown
- Speaker diarization
- Word-level timing
- AI analysis fields
- Support metrics
- N8N triggers

#### B. Markdown File (Human Review)
Location: `/data/transcriptions/markdown/YYYY/MM/DD/[recording_id].md`

Contains:
- Formatted transcript
- Call summary
- Participants info
- Action items
- Analytics summary
- Easy-to-read layout

#### C. N8N Queue Entry
Location: `/data/n8n_integration/queue/[timestamp]_[recording_id].json`

Contains:
- Recording ID
- File paths
- Automation triggers
- Priority level

### 4. Google Drive Upload

**Component:** `src/storage/google_drive.py`

**Process:**
1. Authenticates using service account
2. Creates folder structure: `/Call Transcripts/YYYY/Month/`
3. Uploads JSON transcription
4. Sets permissions for shared access
5. Returns file ID for reference
6. Updates database with Google Drive ID

### 5. Database Tracking

**Model:** `src/database/models.py` - Recording table

**Tracks:**
- RingCentral ID (unique)
- Session ID (for duplicate detection)
- Call metadata (time, duration, participants)
- Processing status (DOWNLOADED → TRANSCRIBING → COMPLETED/FAILED)
- File paths (audio, transcription)
- Google Drive ID
- Timestamps (created, transcribed, updated)
- Error messages if failed

**Status Flow:**
```
DOWNLOADED → TRANSCRIBING → COMPLETED
                    ↓
                 FAILED (with retry)
```

---

## 🔑 Key Python Files

### Core Processing

| File | Purpose | Key Functions |
|------|---------|---------------|
| `ringcentral_checker.py` | Checks for new recordings | `check_for_new_recordings()`, `download_recording()` |
| `transcription_processor.py` | Processes audio queue | `process_recording()`, `process_queue()` |
| `salad_transcriber_enhanced.py` | Salad API integration | `transcribe_file()`, `_wait_for_completion()` |
| `enhanced_organizer.py` | Dual format storage | `save_transcription()`, `_create_json_document()` |
| `google_drive.py` | Drive uploads | `upload_transcription()`, `create_folder()` |

### Batch Processing (Historical)

| File | Purpose | When Used |
|------|---------|-----------|
| `finish_downloads.py` | Complete batch downloads | One-time catchup |
| `process_batch_transcriptions.py` | Batch transcription | Processing backlog |
| `historical_catchup.py` | Historical data import | Initial setup |

### Testing & Utilities

| File | Purpose |
|------|---------|
| `test_enhanced_storage.py` | Test dual format storage |
| `test_salad_complete.py` | Test Salad integration |
| `check_ringcentral_queue.py` | Check queue status |
| `check_schema.py` | Verify database schema |

---

## 🛡️ Duplicate Prevention

The system implements **4-layer duplicate checking**:

1. **File System Check:** Prevents re-downloading existing files
2. **Database ID Check:** Uses unique RingCentral ID
3. **Session ID Check:** Catches same call with different IDs
4. **Call Detail Check:** Matches time/numbers/duration (5s window)

This ensures no recording is processed twice, saving API calls and storage.

---

## ⚙️ Configuration

### Environment Variables (.env)

```bash
# RingCentral
RC_CLIENT_ID=your_client_id
RC_CLIENT_SECRET=your_client_secret
RC_JWT_TOKEN=your_jwt_token
RC_SERVER_URL=https://platform.ringcentral.com

# Salad Cloud
SALAD_API_KEY=your_salad_api_key
SALAD_ORG_NAME=mst

# Google Drive
GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/credentials.json
GOOGLE_DRIVE_FOLDER_ID=root_folder_id

# Database
DATABASE_URL=postgresql://user:pass@localhost/call_recordings

# N8N (optional)
N8N_WEBHOOK_URL=https://n8n.example.com/webhook/
```

### Cron Schedule

```cron
# RingCentral checks - 6 times daily
0 7,10,13,15,17,20 * * * /var/www/call-recording-system/run_ringcentral_check.sh

# Cleanup old logs (keep 30 days)
0 2 * * * find /var/www/call-recording-system/logs -name "*.log" -mtime +30 -delete
```

---

## 📊 Monitoring & Logs

### Log Files
- **Location:** `/var/www/call-recording-system/logs/`
- **Format:** `ringcentral_checker_YYYYMMDD.log`
- **Retention:** 30 days

### State Files
- **Last Check:** `/data/scheduler/last_check.json`
- **Processing Summary:** `/data/scheduler/processing_summary.json`
- **Check Summary:** `/data/scheduler/check_summary.json`

### Queue Status
Check with: `python src/scheduler/transcription_processor.py --status`

```
=== Transcription Queue Status ===
  audio_queue: 15
  downloaded: 10
  transcribing: 2
  completed: 1273
  failed: 3
  total: 1288
```

---

## 🚨 Error Handling

### Retry Logic
1. **Immediate Retry:** On transient errors (network, timeout)
2. **Queue for Later:** On API errors (rate limit, service down)
3. **Manual Review:** After 3 failed attempts

### Failed Recording Recovery
```bash
# Check failed recordings
ls -la /var/www/call-recording-system/data/failed/

# Reprocess failed recording
python src/scheduler/transcription_processor.py --reprocess [recording_id]
```

---

## 🚀 Manual Operations

### Check for New Recordings
```bash
cd /var/www/call-recording-system
source venv/bin/activate
python src/scheduler/ringcentral_checker.py --limit 20
```

### Process Transcription Queue
```bash
python src/scheduler/transcription_processor.py --limit 10
```

### View System Status
```bash
# Queue status
python src/scheduler/transcription_processor.py --status

# Check recent logs
tail -f logs/ringcentral_checker_$(date +%Y%m%d).log
```

### Force Recheck Historical Data
```bash
python src/scheduler/ringcentral_checker.py --hours-back 168  # 7 days
```

---

## 📈 Performance Metrics

### Typical Processing Times
- **Download:** 2-5 seconds per recording
- **Transcription:** 20-60 seconds per minute of audio
- **Storage:** <1 second per file
- **Google Drive Upload:** 2-3 seconds per file

### Daily Capacity
- **Downloads:** ~250 recordings/day (with rate limiting)
- **Transcriptions:** ~200 recordings/day (Salad API limits)
- **Storage:** Unlimited (local)
- **Google Drive:** 750GB/day upload limit

---

## 🔐 Security Considerations

1. **Credentials:** All stored in environment variables
2. **JWT Tokens:** Rotated periodically
3. **Service Account:** Limited Google Drive permissions
4. **Database:** Connection pooling with timeout
5. **Audio Files:** Moved to processed folder after completion
6. **PII:** No sensitive data in logs

---

## 🆘 Troubleshooting

### Common Issues

| Problem | Solution |
|---------|----------|
| Rate limiting (429) | Automatic 20s delays, will retry |
| Salad timeout | Increases wait time, max 10 min |
| Drive quota exceeded | Waits until next day |
| Database connection lost | Automatic reconnect with backoff |
| Duplicate recordings | 4-layer checking prevents |
| Missing audio file | Marked as FAILED, logged |

### Debug Commands
```bash
# Check last RingCentral check
cat data/scheduler/last_check.json

# View processing summary
cat data/scheduler/processing_summary.json

# Count files in queue
ls -1 data/audio_queue/*.mp3 | wc -l

# Check database status
psql -U user -d call_recordings -c "SELECT status, COUNT(*) FROM recordings GROUP BY status;"
```

---

## 📝 Maintenance Tasks

### Daily
- Monitor logs for errors
- Check queue size
- Verify cron jobs running

### Weekly
- Review failed recordings
- Check storage usage
- Verify Google Drive sync

### Monthly
- Rotate credentials
- Clean old logs
- Database vacuum
- Performance review

---

*Last Updated: 2025-09-21*
*Version: 2.0*
*Status: Production Ready*