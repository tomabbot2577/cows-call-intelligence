# 📞 Call Recording System with AI Transcription

**Version 5.0** | **Status: Production Ready + MASSIVE PARALLEL PROCESSING** | **Last Updated: September 22, 2025**

A production-ready automated call recording system that downloads, transcribes, analyzes, and organizes business phone calls with advanced AI transcription, insights generation, and cloud storage. Now powered by PostgreSQL for enterprise-scale operations.

## 🚀 Features

### Core Functionality
- **🎯 Automated Recording Downloads** - Fetches recordings from RingCentral API (6x daily via cron)
- **🤖 AI Transcription** - Salad Cloud API with advanced features:
  - Speaker diarization (identifies different speakers)
  - Word-level timing and confidence scores
  - Automatic summarization
  - SRT subtitle generation
  - Multi-language support (95+ languages)
- **📝 Dual Format Storage** - Saves transcriptions in:
  - JSON format for AI/LLM processing and N8N workflows
  - Markdown format for human readability
- **☁️ Google Drive Backup** - Automatic upload of all transcriptions
- **🐘 PostgreSQL Database** - Enterprise-grade database with:
  - Full-text search capabilities
  - JSONB metadata storage
  - Concurrent processing support
  - Complete audit trail of all processing stages
- **⚡ Batch Processing** - Optimized pipeline handling ~20 recordings/minute
- **🌐 Web Access** - Nginx server (port 8080) for serving audio files

### Advanced Features
- **🔒 4-Layer Duplicate Prevention** - Ensures no recording is processed twice
- **⏱️ Intelligent Rate Limiting** - Configurable throttling (3-15s intervals)
- **🔄 Error Recovery** - Automatic retry logic with exponential backoff
- **🗑️ Smart Cleanup** - Automatic MP3 deletion after successful transcription
- **🔐 Duplicate Prevention** - SHA256 hash-based duplicate detection
- **📈 Progress Tracking** - Real-time monitoring with JSON state files
- **🔗 N8N Integration** - Queue system for workflow automation
- **📝 Comprehensive Logging** - Detailed logs for debugging and monitoring
- **🗂️ Smart Organization** - Date-based directory structure (YYYY/MM/DD)

### 🧠 AI-Powered Insights with MASSIVE PARALLEL PROCESSING
**🚀 BREAKTHROUGH: 43+ Concurrent Processes Achieving 3.3x Speed Acceleration**

#### 4-Layer AI Analysis Pipeline:
- **🎯 Layer 1 - Entity Extraction** (Claude-3-Opus):
  - Employee name validation against known staff database
  - Customer name and company identification
  - Phone number extraction and validation

- **🎭 Layer 2 - Sentiment & Quality Analysis** (DeepSeek R1):
  - Customer sentiment detection (positive/negative/neutral)
  - Call quality scoring (1-10 scale)
  - Call type classification (support/billing/sales/complaint)
  - Key topics extraction (3-5 main discussion points)
  - One-sentence call summary generation

- **✅ Layer 3 - Resolution Tracking** (DeepSeek R1):
  - Problem identification and solution tracking
  - Issue resolution confirmation
  - Follow-up requirements assessment
  - Loop closure quality metrics (6 comprehensive checks)
  - Best practices compliance monitoring

- **💡 Layer 4 - Process Recommendations** (DeepSeek R1):
  - 2-3 process improvements per call
  - Employee coaching feedback (strengths + improvements)
  - Suggested communication phrases
  - Follow-up action items (1-3 tasks)
  - Knowledge base updates needed
  - Escalation requirements with risk assessment

#### 🔥 Performance Metrics:
- **Processing Rate:** 600 AI insights/hour (up from 180/hour)
- **Parallel Processes:** 43+ concurrent instances
- **API Integration:** OpenAI + OpenRouter + PostgreSQL
- **Vector Embeddings:** 1536-dimension semantic search ready

## 📊 Current Status (September 22, 2025) - MASSIVE PARALLEL PROCESSING ACTIVE

### 🚀 Processing Breakthrough Achieved:
- **Total Recordings:** 1,485 tracked in PostgreSQL database
- **Vector Embeddings:** 818/1,424 transcripts (57% complete, 20+ parallel processes)
- **AI Insights Generated:** 468/818 embedded transcripts (57% complete)
- **Call Recommendations:** 442/818 (54% complete)
- **Call Resolutions:** 534/818 (65% complete)
- **43+ Parallel Processes:** Currently running at maximum capacity
- **Performance Gain:** 3.3x acceleration achieved (600 insights/hour)

### 🎯 Real-Time Metrics:
```sql
-- Live database status
SELECT
    (SELECT COUNT(*) FROM transcript_embeddings) as embeddings,
    (SELECT COUNT(*) FROM insights) as insights,
    (SELECT COUNT(*) FROM call_recommendations) as recommendations,
    (SELECT COUNT(*) FROM call_resolutions) as resolutions;
```
- **Database Platform:** PostgreSQL 14 with full-text search
- **Processing Pipeline:** RingCentral → Salad Cloud → OpenRouter → Google Drive
- **Storage Management:** Automatic MP3 cleanup after transcription
- **Nginx Server:** Running at http://31.97.102.13:8080/audio/
- **Web Dashboard:** Operational at http://31.97.102.13:5001/
- **System Status:** ✅ FULLY OPERATIONAL WITH POSTGRESQL

## 🏗️ Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  RingCentral │────▶│   Processor  │────▶│ Salad Cloud  │
│     API      │     │   (Python)   │     │     API      │
└──────────────┘     └──────┬───────┘     └──────────────┘
                            │
                   ┌────────▼────────┐
                   │  Nginx Server   │
                   │  (Port 8080)    │
                   └────────┬────────┘
                            │
                  ┌─────────▼─────────────┐
                  │   Storage System      │
                  ├──────────────────────┤
                  │ • Local JSON/MD       │
                  │ • Google Drive        │
                  │ • PostgreSQL DB       │
                  │ • N8N Queue          │
                  └──────────────────────┘
```

## 📁 Directory Structure

```
/var/www/call-recording-system/
├── src/
│   ├── ringcentral/         # RingCentral API integration
│   ├── transcription/        # Salad Cloud transcription
│   ├── storage/              # Storage management & Google Drive
│   ├── database/             # Database models & tracking
│   └── scheduler/            # Automated scheduling & cron
├── data/
│   ├── audio_queue/          # Downloaded recordings (1,489 files)
│   ├── processed/            # Completed recordings
│   ├── failed/               # Failed recordings for retry
│   └── transcriptions/       # JSON and Markdown outputs
│       ├── json/            # Structured data for LLM/N8N
│       └── markdown/        # Human-readable transcripts
├── logs/                     # Application & batch processing logs
├── config/                   # Configuration files
└── docs/                     # Documentation
```

## 🚀 Quick Start

### Prerequisites
- Ubuntu 22.04 LTS (production) or macOS (development)
- Python 3.11+
- PostgreSQL 14+ (migrated from SQLite)
- Nginx
- Google Cloud service account
- RingCentral API credentials
- Salad Cloud API key
- OpenRouter API key (for AI insights)

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/a9422crow/call-recording-system.git
cd call-recording-system
```

2. **Set up Python environment**
```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. **Configure environment variables**
```bash
cp .env.example .env
# Edit .env with your credentials:
vim .env
```

Required environment variables:
```bash
# RingCentral
RC_CLIENT_ID=your_client_id
RC_CLIENT_SECRET=your_secret
RC_JWT_TOKEN=your_jwt_token
RC_SERVER_URL=https://platform.ringcentral.com

# Salad Cloud
SALAD_API_KEY=your_api_key
SALAD_ORG_NAME=your_org

# Google Drive
GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service_account.json
GOOGLE_DRIVE_FOLDER_ID=your_folder_id
GOOGLE_IMPERSONATE_EMAIL=user@domain.com

# PostgreSQL Database
DATABASE_URL=postgresql://call_insights_user:[your_password]@localhost/call_insights

# OpenRouter (AI Insights)
OPENROUTER_API_KEY=your_openrouter_key
```

4. **Set up Nginx for audio serving**
```bash
# Copy configuration
sudo cp /etc/nginx/sites-available/audio-queue /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/audio-queue /etc/nginx/sites-enabled/

# Update server IP in config
sudo vim /etc/nginx/sites-available/audio-queue

# Reload Nginx
sudo systemctl reload nginx
```

5. **Initialize PostgreSQL database**
```bash
# Create database and user
sudo -u postgres psql <<EOF
CREATE DATABASE call_insights;
CREATE USER call_insights_user WITH PASSWORD '[your_password]';
GRANT ALL PRIVILEGES ON DATABASE call_insights TO call_insights_user;
\c call_insights
GRANT ALL ON SCHEMA public TO call_insights_user;
EOF

# Run setup script
python setup_postgresql.py
```

6. **Set up automated schedule**
```bash
# Install cron jobs for 6x daily checks
./setup_cron_schedule.sh
```

## 📝 Usage

### Batch Processing

```bash
# Process 100 recordings with optimized rate limit
python process_queue_batch_final.py --limit 100 --rate-limit 3

# Check queue status
python process_queue_batch_final.py --status

# Process all pending recordings
python process_queue_batch_final.py --limit 1500 --rate-limit 3
```

### Monitor Progress

```bash
# Watch real-time logs
tail -f logs/batch_processing_*.log

# Check PostgreSQL database status
python database_visual_report.py

# View processing pipeline
psql -U call_insights_user -d call_insights -c "SELECT * FROM pipeline_status;"

# Check cleanup candidates
psql -U call_insights_user -d call_insights -c "SELECT * FROM cleanup_candidates LIMIT 10;"

# Access web dashboard
curl http://localhost:5001/
```

### Manual Operations

```bash
# Sync database and cleanup transcribed files
python sync_and_cleanup_database.py

# Generate visual database report
python database_visual_report.py

# Process recordings through Salad Cloud
python process_all_recordings_salad.py --batch-size 30 --workers 5

# Check for historical recordings
python historical_catchup_queue_only.py --start 2024-06-01 --end 2024-09-30

# Access web dashboard
python web/insights_dashboard.py
```

## ⚙️ Configuration

### Rate Limiting Options
The system supports configurable rate limiting for API calls:

| Delay | Requests/Min | Use Case | Risk Level |
|-------|-------------|----------|------------|
| 3s | 20 | **Recommended** (default) | Low |
| 1s | 60 | Fast processing | Medium |
| 0.26s | 230 | Maximum speed | High |
| 5s | 12 | Conservative | Very Low |
| 15s | 4 | Ultra-safe | None |

### Cron Schedule
Automated checks run 6 times daily:
```cron
# RingCentral recording checks
0 7,10,13,15,17,20 * * * /var/www/call-recording-system/run_ringcentral_check.sh

# Log cleanup (daily at 2am)
0 2 * * * find /var/www/call-recording-system/logs -name "*.log" -mtime +30 -delete
```

### Nginx Configuration
Audio files are served on port 8080:
- **URL Format:** `http://YOUR_SERVER_IP:8080/audio/filename.mp3`
- **Directory:** `/var/www/call-recording-system/data/audio_queue/`
- **Access:** Public (required for Salad API)

## 📊 API Integration Details

### RingCentral API
- **Authentication:** JWT Bearer Token
- **Endpoints:** `/restapi/v1.0/account/~/call-log` and `/recording/1`
- **Rate Limit:** 20 seconds between downloads
- **Duplicate Check:** Recording ID, URL, timestamp, and file hash

### Salad Cloud API
- **Engine:** Full (highest quality)
- **Features Enabled:**
  - Diarization (speaker separation)
  - Summarization
  - Word timing
  - Confidence scores
  - SRT generation
- **Rate Limit:** 240 requests/minute (we use 230 for safety)
- **Timeout:** 300 seconds per transcription

### Google Drive API
- **Authentication:** Service account with domain delegation
- **Upload:** JSON transcriptions only (not audio files)
- **Organization:** Date-based folder structure
- **Retry Logic:** 5 attempts with exponential backoff

## 🔍 Monitoring & Maintenance

### Health Checks
```bash
# Check system components
systemctl status nginx
systemctl status postgresql

# Verify Nginx audio access
curl -I http://localhost:8080/audio/test.mp3

# Test Salad API connection
python test_salad_simple.py

# Check Google Drive connection
python -c "from src.storage.google_drive import GoogleDriveManager;
          gdm = GoogleDriveManager();
          print(gdm.get_statistics())"
```

### Troubleshooting

#### Common Issues & Solutions

1. **Rate Limit Errors (429)**
```bash
# Increase delay between requests
python process_queue_batch_final.py --limit 50 --rate-limit 10
```

2. **Nginx Not Accessible**
```bash
# Check and restart Nginx
sudo systemctl status nginx
sudo systemctl restart nginx
sudo nginx -t  # Test configuration
```

3. **Google Drive Upload Failures**
```bash
# Verify credentials
cat config/google_service_account.json | jq .

# Test upload manually
python test_google_drive_upload.py
```

4. **Failed Transcriptions**
```bash
# Reprocess failed files
mv data/failed/*.mp3 data/audio_queue/

# Check error logs
grep ERROR logs/batch_processing_*.log | tail -20
```

5. **Reset Processing State**
```bash
# Clear progress tracking (careful!)
rm data/batch_progress.json
python process_queue_batch_final.py --limit 100 --rate-limit 3
```

## 🌐 PCR COWS Workflow Intelligence Platform

The system includes an AI-powered web platform for intelligent call analysis:

- **URL:** http://31.97.102.13:8081
- **Branding:** PCR COWS Workflow Intelligence Platform

### Features
| Module | Description |
|--------|-------------|
| **Query & Search** | Hybrid RAG with Gemini (semantic) + Vertex AI (structured) |
| **Knowledge Base** | 5,314+ Freshdesk Q&A pairs with AI-powered search |
| **Sales Intelligence** | Hormozi Blueprint analysis, competitor tracking, key quotes |
| **Reports** | Churn risk, agent performance, sentiment analysis |
| **Export** | JSONL export to GCS for RAG systems (Admin only) |
| **User Management** | Role-based access control (Admin only) |

See [RAG_INTEGRATION.md](RAG_INTEGRATION.md) for full documentation.

## 📚 Documentation

- [CLAUDE.md](CLAUDE.md) - Project context and current status
- [RAG_INTEGRATION.md](RAG_INTEGRATION.md) - PCR COWS platform documentation
- [BATCH_PROCESSING_GUIDE.md](BATCH_PROCESSING_GUIDE.md) - Detailed batch processing instructions
- [SYSTEM_DOCUMENTATION.md](SYSTEM_DOCUMENTATION.md) - Complete system architecture
- [N8N_API_DOCUMENTATION.md](N8N_API_DOCUMENTATION.md) - N8N workflow integration
- [TRANSCRIPTION_FILING_PLAN.md](TRANSCRIPTION_FILING_PLAN.md) - File organization structure
- [ENHANCED_METADATA_SUMMARY.md](ENHANCED_METADATA_SUMMARY.md) - All metadata fields

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📈 Performance Metrics

- **Processing Speed:** ~20 files/minute with 3s rate limit
- **Transcription Accuracy:** 95%+ confidence scores
- **Storage Efficiency:** Audio files deleted after processing
- **Uptime Target:** 99.9% availability
- **Error Rate:** <1% failure rate with retry logic

## 🎯 Roadmap

- [x] Core transcription pipeline
- [x] Google Drive integration
- [x] Batch processing optimization
- [x] Nginx audio serving
- [x] Rate limiting configuration
- [x] PostgreSQL migration from SQLite
- [x] Web dashboard with insights viewer
- [x] AI-powered call insights with OpenRouter
- [x] Automatic MP3 cleanup after transcription
- [x] SHA256-based duplicate detection
- [ ] Real-time transcription streaming
- [ ] Advanced search with vector embeddings
- [ ] Multi-tenant support
- [ ] Webhook notifications
- [ ] Custom AI model training

## 📄 License

This project is proprietary software. All rights reserved.

## 🆘 Support

For issues or questions:
- Check the [troubleshooting guide](#troubleshooting)
- Review logs in `/var/www/call-recording-system/logs/`
- Open an issue on [GitHub](https://github.com/a9422crow/call-recording-system/issues)

---

**Repository:** https://github.com/a9422crow/call-recording-system
**Version:** 4.0.0
**Status:** Production Ready & Actively Processing
**Last Updated:** September 21, 2025