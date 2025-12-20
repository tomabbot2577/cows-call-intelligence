# 📞 AI-Powered Call Recording System - Claude Context File
## Complete Project Status & Next Steps

---

## 🚀 PROJECT OVERVIEW

This is a **production-ready AI-powered call recording system** that automatically:
1. Downloads recordings from RingCentral (6x daily)
2. Transcribes them using Salad Cloud API (with all enhanced features)
3. **🧠 Generates AI insights using GPT-3.5-turbo**
4. **📊 Provides web analytics dashboard**
5. Stores in dual format (JSON for AI/LLM, Markdown for humans)
6. Uploads to Google Drive for backup
7. Tracks everything in PostgreSQL database
8. Integrates with N8N for workflow automation

**Current Status:** ✅ FULLY IMPLEMENTED & DOCUMENTED WITH AI INSIGHTS

---

## 📊 CURRENT SYSTEM STATE

### Database Migration ✅
- **NEW:** Migrated from SQLite to PostgreSQL
- **Database:** PostgreSQL 14 with full-text search
- **Total Records:** 1,485 recordings tracked
- **Duplicate Detection:** SHA256 hash-based
- **Audio Cleanup:** Automatic deletion after transcription
- **Connection:** `postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights`

### Downloaded Recordings
- **Total Downloaded:** 1,485 MP3 files (all registered in PostgreSQL)
- **Location:** `/data/audio_queue/`
- **Date Range:** June - September 2024
- **Status:** Ready for transcription

### Processing Status (As of Dec 20, 2025 - 5-LAYER AI PROCESSING COMPLETE) 🚀
- **Downloaded:** 3,194+ recordings total
- **Total Transcripts:** 3,194 with content
- **Layer 1 Name Extraction:** 2,468/3,194 (77% complete) ✅
- **Layer 2 Sentiment Analysis:** 2,461/3,194 (77% complete) ✅
- **Layer 3 Call Resolution:** 1,803/3,194 (56% complete) ✅
- **Layer 4 Recommendations:** 2,289/3,194 (72% complete) ✅
- **Layer 5 Advanced Metrics:** 1,651/3,194 (52% complete) ✅
- **All 5 Layers Complete:** 1,341 calls ready for RAG export ✅
- **RAG Integration:** Gemini + Vertex AI with 16 JSONL files ✅
- **Cost Optimization:** Using Google Gemini Flash via direct API
- **Processing Rate:** 10-20 parallel processes per layer
- **Total Cost:** <$0.001 per call with optimized models

#### 🧠 AI Analysis Per Call (5 Layers):

**Layer 1 - Entity Extraction:**
- ✅ Employee names validated against list
- ✅ Customer names and companies identified
- ✅ Phone numbers extracted when available

**Layer 2 - Enhanced Sentiment & Quality (NEW FEATURES):**
- ✅ Customer mood analysis with 1-sentence reasoning
- ✅ Call quality scoring (1-10) with performance justification
- ✅ Overall call rating (1-10) combining all factors
- ✅ Call type classification (support/billing/complaint/etc)
- ✅3-5 key topics extracted
- ✅ One-sentence summary generated
- ✅ Enhanced coaching notes with actionable insights

**Layer 3 - Enhanced Resolution Tracking (25+ NEW INSIGHTS):**
- ✅ Problem complexity assessment (simple/medium/complex)
- ✅ Resolution effectiveness scoring (0-10)
- ✅ Empathy score & emotional intelligence (0-10)
- ✅ Communication clarity rating (0-10)
- ✅ Active listening score (0-10)
- ✅ Employee knowledge level & training needs
- ✅ Churn risk assessment (none/low/medium/high)
- ✅ Revenue impact analysis
- ✅ Customer lifetime value impact
- ✅ Customer effort score (1-10, lower is better)
- ✅ Upsell/cross-sell opportunities identified
- ✅ Frustration points & delight moments tracked
- ✅ Process gaps & automation opportunities
- ✅ Knowledge base gaps identified
- ✅ Handoff quality & callback commitments
- ✅ Loop closure quality (8 enhanced metrics):
  - Solution summarized
  - Understanding confirmed
  - Asked if anything else
  - Next steps provided
  - Timeline given
  - Contact info provided
  - Thanked customer
  - Confirmed satisfaction

**Layer 4 - Recommendations:**
- ✅ 2-3 process improvements per call
- ✅ Employee coaching points (strengths & improvements)
- ✅ Suggested communication phrases
- ✅ 1-3 follow-up action items
- ✅ Knowledge base updates needed
- ✅ Escalation requirements with risk assessment
- **Web Dashboard:** Running at http://31.97.102.13:5001 (PostgreSQL-powered)
  - Enhanced semantic search with call summaries
  - Transcript viewer with full context
  - Customer analytics and phone tracking
- **Google Drive:** Organized folder structure (Year/Month/Day)
- **Audio Server:** Nginx serving files at http://31.97.102.13:8080/audio/
- **Audio Deletion:** ✅ SECURE SHRED - Files deleted after transcription
- **Rate Limit:** Adaptive (3-5 seconds between requests)
- **Status:** FULL AI PIPELINE WITH COMPREHENSIVE ANALYSIS

### Storage
- **JSON Files:** `/data/transcriptions/json/YYYY/MM/DD/`
  - Standard: `[recording_id].json`
  - Enhanced: `[recording_id].enhanced.json` (with AI metadata)
- **Markdown Files:** `/data/transcriptions/markdown/YYYY/MM/DD/`
- **AI Insights:** `/data/transcriptions/insights/` (JSON format)
- **Analytics Database:** PostgreSQL with comprehensive tracking
  - `transcripts` table: All recordings with metadata
  - `insights` table: AI-generated insights
  - `processing_status` table: Pipeline tracking
  - `transcript_embeddings` table: Vector embeddings (1536 dimensions)
- **Web Dashboard:** Password-protected interface (!pcr123)
  - Semantic search enabled at `/semantic-search`
  - Customer analytics at `/customer-analytics/[customer_id]`
  - Real-time insights dashboard
- **Google Drive:** Organized uploads (Year/Month-MonthName/Day/)
  - `[recording_id]_full.json` - Complete enhanced data
  - `[recording_id]_summary.md` - Human-readable summary
- **N8N Queue:** `/data/n8n_integration/queue/`
- **Audio Cleanup:** ✅ MP3s securely deleted after transcription (shred)

---

## 🔄 AUTOMATED SCHEDULE (RUNNING)

### Cron Jobs Active
```cron
# RingCentral checks - 6 times daily
0 7,10,13,15,17,20 * * * /var/www/call-recording-system/run_ringcentral_check.sh

# Log cleanup - daily at 2am
0 2 * * * find /var/www/call-recording-system/logs -name "*.log" -mtime +30 -delete
```

**Next Check:** Will run automatically at scheduled times
**Logs:** `/var/www/call-recording-system/logs/`

---

## 🏗️ ARCHITECTURE IMPLEMENTED

### 1. RingCentral Integration ✅
- **File:** `src/scheduler/ringcentral_checker.py`
- **Features:**
  - JWT authentication
  - 4-layer duplicate prevention
  - Rate limiting (20s between downloads)
  - Automatic retry on failures
  - State tracking in `/data/scheduler/last_check.json`

### 2. Salad Cloud Transcription ✅
- **File:** `src/transcription/salad_transcriber_enhanced.py`
- **Features Enabled:**
  - Engine: Full (highest quality)
  - Diarization: ON (speaker separation)
  - Summarization: ON
  - Word-level timing: ON
  - SRT generation: ON
  - Confidence scoring: ON

### 3. AI Insights Generation ✅ COST-OPTIMIZED
- **Smart Model Selection via OpenRouter:**
  - **Google Gemini Flash 1.5:** Primary model for ALL layers (often FREE)
  - **Gemini Flash 8B:** Backup for extraction ($0.00002/1K tokens)
  - **Mistral 7B:** Complex analysis fallback ($0.00006/1K tokens)
  - **DeepSeek/Claude:** Only for advanced reasoning when needed
- **Total Cost:** $0-$0.001 per call (vs $0.01+ with premium models)

#### 🔍 Name & Entity Extraction (`extract_names_advanced.py`)
- **Employee Identification:**
  - Validates against known employee list
  - Distinguishes PC Recruiter/Main Sequence staff from customers
  - Extracts employee extensions and departments
- **Customer Identification:**
  - Extracts customer names and companies
  - Identifies recruiting/staffing firm clients
  - Captures phone numbers when available
- **Company Recognition:**
  - Differentiates vendors (PCR/Main Sequence) from clients
  - Maps company aliases to canonical names

#### 🎭 Sentiment & Quality Analysis (`analyze_sentiment.py`)
- **Customer Sentiment:** Positive/Negative/Neutral mood detection
- **Call Quality Score:** 1-10 rating based on:
  - Problem resolution effectiveness
  - Agent helpfulness and professionalism
  - Customer satisfaction indicators
- **Call Classification:**
  - Technical support
  - Billing inquiry
  - Sales inquiry
  - Complaint
  - General inquiry
  - Follow-up
- **Key Topics:** 3-5 main discussion points extracted
- **Issue Resolution:** Tracks if problem was solved
- **Follow-up Need:** Identifies if additional action required

#### ✅ Call Resolution & Loop Closure (`analyze_call_resolution.py`)
- **Problem Resolution Tracking:**
  - `issue_identified`: Was the problem clearly understood?
  - `solution_provided`: Was a solution offered?
  - `issue_resolved`: Was the problem actually fixed?
  - `follow_up_required`: Does it need additional attention?
  - `escalation_needed`: Should it be escalated?
- **Loop Closure Quality (6 Metrics):**
  - `solution_summarized`: Did agent recap the solution?
  - `understanding_confirmed`: Did agent verify customer understood?
  - `asked_if_anything_else`: Did agent check for other issues?
  - `next_steps_provided`: Were clear next steps given?
  - `timeline_given`: Was a timeline communicated?
  - `contact_info_provided`: Was follow-up contact info shared?
  - `closure_score`: Overall loop closure quality (1-10)
- **Best Practices Analysis:**
  - Identifies missed opportunities
  - Suggests improvements for incomplete closures
  - Tracks compliance with support standards

#### 💡 Process & Workflow Recommendations (`generate_call_recommendations.py`)
- **Process Improvements (2-3 per call):**
  - Workflow optimizations to prevent recurring issues
  - System improvements and automation opportunities
  - Documentation and training gaps identified
- **Employee Coaching:**
  - **Strengths:** What the employee did well
  - **Improvements:** Areas needing development
  - **Suggested Phrases:** Better ways to communicate
- **Follow-up Actions (1-3 tasks):**
  - Immediate actions needed
  - Long-term preventive measures
  - Customer retention strategies
- **Knowledge Base Updates:**
  - FAQs to create or update
  - Common issues to document
- **Escalation Requirements:**
  - Escalation needed: Yes/No
  - Risk level: Low/Medium/High
  - Reason for escalation
- **Performance Metrics:**
  - Efficiency score (1-10)
  - Training priority level

### 4. Web Analytics Dashboard ✅
- **File:** `web/insights_dashboard.py`
- **URL:** http://31.97.102.13:5001
- **Password:** !pcr123
- **Enhanced Features:**
  - **Semantic Search:** Find calls by context ("angry customers", "billing issues")
  - **Call Summaries:** AI-generated summaries with clickable transcript links
  - **Transcript Viewer:** Full transcript with metadata and sentiment
  - **Customer Analytics:** Track customer interactions and phone numbers
  - **Resolution Tracking:** Monitor problem resolution and follow-ups
  - **Process Insights:** View recommended improvements per call
  - **Agent Performance:** Track loop closure and quality scores
  - **RESTful API:** Full integration endpoints for N8N

### 5. Enhanced Storage ✅
- **File:** `src/storage/enhanced_organizer.py`
- **Creates:**
  - JSON with 40+ metadata fields
  - Human-readable Markdown
  - N8N queue entries
  - Search indexes
  - Google Drive uploads

### 6. Insights Management System ✅
- **File:** `src/insights/insights_manager_postgresql.py`
- **Features:**
  - PostgreSQL-based storage with full-text search
  - Dashboard statistics with real-time metrics
  - Pipeline status tracking
  - Advanced querying with multiple filters
  - Analytics and reporting
  - Search across transcripts using tsvector

### 7. Database Tracking ✅
- **Platform:** PostgreSQL 14 with pgvector

#### Database Tables & Fields:

**`transcripts` Table:**
- Recording metadata (ID, dates, duration)
- Customer & employee names with companies
- Phone numbers (from/to)
- Full transcript text
- Word count and confidence scores

**`insights` Table:**
- Customer sentiment (positive/negative/neutral)
- Call quality score (1-10)
- Call type classification
- Key topics array
- Summary text
- Issue resolution status
- Follow-up requirements

**`call_resolutions` Table (25+ NEW COLUMNS):**
- Problem complexity (simple/medium/complex)
- Resolution effectiveness (0-10)
- Empathy score & demonstration (0-10)
- Communication clarity (0-10)
- Active listening score (0-10)
- Employee knowledge level (0-10)
- Confidence in solution (0-10)
- Training needs identified
- Churn risk assessment (none/low/medium/high)
- Revenue impact (positive/neutral/negative)
- Customer lifetime value impact
- Customer effort score (1-10)
- Upsell/cross-sell opportunities
- Frustration points array
- Delight moments array
- Process gaps found
- Automation opportunities
- Knowledge base gaps
- Handoff quality assessment
- Callback commitments and timeframes
- First contact resolution status
- Loop closure metrics (8 enhanced fields):
  - Solution summarized
  - Understanding confirmed
  - Asked if anything else
  - Next steps provided
  - Timeline given
  - Contact info provided
  - Thanked customer
  - Confirmed satisfaction

**`call_recommendations` Table:**
- Process improvements array
- Employee strengths array
- Employee improvements array
- Suggested phrases array
- Follow-up actions array
- Knowledge base updates array
- Escalation status and reason
- Risk level (low/medium/high)
- Efficiency score (1-10)
- Training priority level

**`transcript_embeddings` Table:**
- Vector embeddings (1536 dimensions)
- OpenAI text-embedding-ada-002
- Enables semantic search

**Enhanced Features:**
- All insights cached to avoid repeated LLM calls
- Semantic search with pgvector
- Full-text search with tsvector
- JSONB for flexible metadata
- SHA256 hash-based duplicate prevention
- Secure audio deletion audit trail

---

## 📁 KEY FILES TO KNOW

### Core Components
```python
# Main scheduler that checks RingCentral
src/scheduler/ringcentral_checker.py

# Processes transcription queue
src/scheduler/transcription_processor.py

# MASSIVE PARALLEL AI PROCESSING (ENHANCED!)
process_complete_insights.py          # Unified 4-layer AI pipeline
generate_all_embeddings.py           # Vector embeddings generation
layer2_sentiment_enhanced.py         # Enhanced sentiment with reasoning
layer3_resolution_enhanced.py        # 25+ new resolution insights
generate_call_recommendations.py     # Process improvement recommendations
analyze_call_resolution.py           # Loop closure tracking
monitor_layer2_processing.sh         # Auto-restart Layer 2 monitoring
monitor_layer3_processing.sh         # Auto-restart Layer 3 monitoring

# Enhanced storage with dual format
src/storage/enhanced_organizer.py

# Salad Cloud integration
src/transcription/salad_transcriber_enhanced.py

# Google Drive uploads
src/storage/google_drive.py

# Database models
src/database/models.py
```

### Documentation
```markdown
SYSTEM_DOCUMENTATION.md       # Complete system overview
TRANSCRIPTION_FILING_PLAN.md  # File organization plan
N8N_API_DOCUMENTATION.md      # N8N integration APIs
ENHANCED_METADATA_SUMMARY.md  # All metadata fields
```

### Scripts
```bash
setup_cron_schedule.sh         # Setup automated schedule
run_ringcentral_check.sh       # Manual check script
finish_downloads.py            # Complete batch downloads
process_batch_transcriptions.py # Batch transcription
```

---

## 🔧 ENVIRONMENT VARIABLES NEEDED

```bash
# RingCentral
RC_CLIENT_ID=Fmr5r8QoS_aZ4OncrN5-uw
RC_CLIENT_SECRET=[stored in .env]
RC_JWT_TOKEN=[stored in .env]
RC_SERVER_URL=https://platform.ringcentral.com

# Salad Cloud
SALAD_API_KEY=salad_lnk3x1io5f12mlp3zcukcbfraxzizf5jdcbwqw8pehrbsjddnhj6k8w6f5
SALAD_ORG_NAME=mst

# Google Drive
GOOGLE_CREDENTIALS_PATH=/var/www/call-recording-system/config/google_service_account.json
GOOGLE_DRIVE_FOLDER_ID=1P0GGzxJdEXxJOdMsKNMZhF2JGE5x4M1A
GOOGLE_DRIVE_TRANSCRIPTS_FOLDER=1obRW7K6EQFLtMlgYaO21aYS_o-77hOJ1
GOOGLE_IMPERSONATE_EMAIL=sabbey@mainsequence.net

# Database (PostgreSQL)
DATABASE_URL=postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights
PG_DBNAME=call_insights
PG_USER=call_insights_user
PG_PASSWORD=REDACTED_DB_PASSWORD
PG_HOST=localhost
PG_PORT=5432

# OpenAI API for embeddings and insights
OPENAI_API_KEY=[stored in .env - required for semantic search]

# OpenRouter API for advanced AI models
OPENROUTER_API_KEY=REDACTED_OPENROUTER_KEY
```

---

## ✅ WHAT'S COMPLETED

1. **Historical Data Import** - 1,485 recordings downloaded
2. **Automated Schedule** - Runs 6x daily via cron
3. **Duplicate Prevention** - SHA256 hash-based system
4. **Enhanced Transcription** - All Salad Cloud features enabled
5. **Multi-Model AI Analysis:**
   - Claude-3-Opus for name extraction
   - Claude-3-Haiku for sentiment and recommendations
   - GPT-3.5-turbo for general insights
6. **Comprehensive Call Analysis:**
   - Employee/customer identification
   - Sentiment and quality scoring
   - Problem resolution tracking
   - Loop closure analysis (6 metrics)
   - Process improvement recommendations
7. **Enhanced Web Dashboard:**
   - Semantic search with summaries
   - Full transcript viewer
   - Customer phone tracking
   - Resolution analytics
8. **Secure Audio Management:**
   - GNU shred for secure deletion
   - SHA256 hash audit logging
   - Automatic cleanup after transcription
9. **PostgreSQL with pgvector:**
   - Semantic search (1536d embeddings)
   - Full-text search
   - Cached AI insights
10. **Google Drive Integration:**
    - Organized folder structure
    - Domain-wide delegation
11. **N8N Ready:**
    - Queue system implemented
    - RESTful API endpoints
12. **Complete Documentation**
13. **🔍 COWS Hybrid RAG Integration** (NEW - December 2025)
    - Gemini RAG for semantic queries
    - Vertex AI RAG for structured queries
    - 1,341 calls with all 5 layers ready
    - Web UI at http://31.97.102.13:8081
    - GCS bucket: `call-recording-rag-data`

---

## 🔍 RAG INTEGRATION (COWS - December 2025)

### Overview
The COWS (Call Observation & Workflow System) Hybrid RAG adds intelligent querying:
- **Gemini RAG**: Semantic queries ("What are customers complaining about?")
- **Vertex AI RAG**: Structured queries ("Calls with churn risk > 7")

### Current Status
| Metric | Value |
|--------|-------|
| Total Transcripts | 3,194 |
| All 5 Layers Complete | **1,341 calls** |
| Files in Gemini | 16 JSONL files |
| Files in GCS | 16 JSONL files |
| GCS Bucket | `gs://call-recording-rag-data` |
| Web UI | http://31.97.102.13:8081 |

### Quick Start
```bash
# Access RAG Web UI
http://31.97.102.13:8081
Password: !pcr123

# Check RAG status
source venv/bin/activate
python -c "
from rag_integration.services.db_reader import DatabaseReader
stats = DatabaseReader().get_statistics()
print(f'Ready for RAG: {stats[\"all_5_layers_complete\"]} calls')
"

# Test a query
python -c "
from rag_integration.services.gemini_file_search import GeminiFileSearchService
from rag_integration.services.db_reader import DatabaseReader

db = DatabaseReader()
service = GeminiFileSearchService()
calls = list(db.get_calls_for_export(limit=50, require_all_layers=True, min_layers=5))
summaries = [{'call_id': c.get('recording_id'), 'summary': c.get('summary', '')[:200]} for c in calls]
result = service.analyze_calls_batch('What are top customer complaints?', summaries)
print(result['response'][:500])
"
```

### Key Files
```
rag_integration/
├── services/
│   ├── db_reader.py          # Read-only PostgreSQL (5-layer verification)
│   ├── gemini_file_search.py # Gemini RAG (google.genai SDK)
│   ├── gcs_uploader.py       # GCS upload
│   └── query_router.py       # Auto-routing
├── api/
│   ├── main.py               # FastAPI + Web UI
│   └── templates/            # Jinja2 templates
└── exports/                  # 16 JSONL files
```

### Environment Variables
```bash
# RAG Integration
GEMINI_API_KEY=your_key
GCS_RAG_BUCKET=call-recording-rag-data
GCS_RAG_PREFIX=transcripts/
RAG_API_PORT=8081
RAG_API_PASSWORD=!pcr123
RAG_DATABASE_URL=postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights
```

### Service Management
```bash
# Start RAG API
source venv/bin/activate
nohup python -m uvicorn rag_integration.api.main:app --host 0.0.0.0 --port 8081 > logs/rag_api.log 2>&1 &

# Stop RAG API
pkill -f "uvicorn rag_integration"

# Check health
curl http://localhost:8081/health
```

See `RAG_INTEGRATION.md` for full documentation.

---

## 🎯 NEXT STEPS & TASKS

### Current Operations
1. **🚀 FULL AI PIPELINE RUNNING**
   ```bash
   cd /var/www/call-recording-system
   source venv/bin/activate

   # Multiple batch processors running with AI insights:
   python process_queue_batch_final.py --limit 100 --rate-limit 3

   # Monitor progress
   tail -f logs/batch_processing_*.log

   # Check queue status
   python process_queue_batch_final.py --status
   ```

   **Nginx Setup:** Audio files served at http://31.97.102.13:8080/audio/
   **Rate Limit:** 3 seconds between requests (safe for API limits)
   **AI Insights:** Generated for every transcribed call

2. **📊 WEB DASHBOARD ACCESS**
   ```
   URL: http://31.97.102.13:5001
   Password: !pcr123

   Features:
   - Real-time insights dashboard
   - Filtering and search
   - Analytics and reporting
   - Agent performance metrics
   - Interactive charts
   ```

3. **Monitor Daily Operations**
   ```bash
   # Check today's logs
   tail -f logs/ringcentral_checker_$(date +%Y%m%d).log

   # View insights generation
   tail -f logs/batch_processing_*.log | grep "🧠\|AI insights"

   # Access web dashboard
   curl -I http://31.97.102.13:5001
   ```

4. **Setup N8N Workflows**
   - Configure webhooks using endpoints in `N8N_API_DOCUMENTATION.md`
   - Use insights API: http://31.97.102.13:5001/api/insights
   - Create workflows for:
     - High churn risk alerts
     - Escalation notifications
     - Follow-up reminders
     - Daily analytics summaries

### Future Enhancements
1. **Advanced AI Features**
   - Real-time sentiment monitoring
   - Predictive churn modeling
   - Topic clustering and trending
   - Intent classification
   - Automated action recommendations

2. **Enhanced Dashboard**
   - Real-time call monitoring
   - Advanced filtering and search
   - Custom report generation
   - Export capabilities
   - Mobile-responsive design

3. **CRM Integration**
   - Automatic ticket creation from high-risk calls
   - Customer history linking
   - Agent notes synchronization
   - Salesforce/HubSpot integration

---

## 🐛 TROUBLESHOOTING

### Common Issues & Solutions

**Queue not processing:**
```bash
# Check for failed recordings
python -c "from src.database.session import SessionLocal; from src.database.models import Recording, ProcessingStatus; db = SessionLocal(); print(f'Failed: {db.query(Recording).filter_by(status=ProcessingStatus.FAILED).count()}')"

# Reprocess failed
python src/scheduler/transcription_processor.py --reprocess-failed
```

**RingCentral rate limiting:**
```bash
# Already handled - 20s delays between downloads
# Check last error in:
cat data/scheduler/last_check.json
```

**Salad timeout:**
```bash
# Increase timeout in salad_transcriber_enhanced.py
# Current: 600s (10 min)
```

**Disk space:**
```bash
# Check usage
df -h /var/www/call-recording-system/data

# Clean old processed files (>30 days)
find /data/processed -name "*.mp3" -mtime +30 -delete
```

---

## 📝 QUICK COMMANDS

### Status Checks
```bash
# Queue status
python src/scheduler/transcription_processor.py --status

# AI insights status
find data/transcriptions/insights -name "*.json" | wc -l

# Web dashboard status
curl -s http://31.97.102.13:5001/api/insights | jq '.count'

# Database status
psql -U call_user -d call_recordings -c "SELECT status, COUNT(*) FROM recordings GROUP BY status;"

# Files in queue
ls -1 data/audio_queue/*.mp3 | wc -l

# Today's AI activity
grep "$(date +%Y-%m-%d)" logs/batch_processing_*.log | grep "🧠\|AI insights" | tail -10
```

### Manual Operations
```bash
# Check for new recordings NOW
python src/scheduler/ringcentral_checker.py --limit 30

# MASSIVE PARALLEL PROCESSING (NEW!)
# Launch 20+ embedding processes
python generate_all_embeddings.py --limit 1000 &
python generate_all_embeddings.py --limit 800 &
python generate_all_embeddings.py --limit 600 &

# Launch 30+ AI insights processes
python process_complete_insights.py --limit 150 --batch-id ai_batch_1 &
python process_complete_insights.py --limit 150 --batch-id ai_batch_2 &
python process_complete_insights.py --limit 150 --batch-id ai_batch_3 &

# Monitor progress
PGPASSWORD=REDACTED_DB_PASSWORD psql -U call_insights_user -d call_insights -h localhost -c "
SELECT
    (SELECT COUNT(*) FROM transcript_embeddings) as embeddings,
    (SELECT COUNT(*) FROM insights) as insights,
    (SELECT COUNT(*) FROM call_recommendations) as recommendations;"

# Access web dashboard
open http://31.97.102.13:5001 (password: !pcr123)

# Test insights API
curl "http://31.97.102.13:5001/api/insights?limit=5" -H "Cookie: session=[your-session]"
```

### Monitoring
```bash
# Watch real-time logs
tail -f logs/ringcentral_checker_$(date +%Y%m%d).log

# Check cron jobs
crontab -l

# System health
python src/monitoring/health_check.py
```

---

## 🔐 SECURITY NOTES

1. **Credentials:** All in `.env` file (not in Git)
2. **Audio Files:** Automatically moved after processing
3. **PII Protection:** No sensitive data in logs
4. **Access Control:** Service account has limited permissions
5. **Database:** Using connection pooling with timeout

---

## 📞 SUPPORT CONTACTS

- **RingCentral API:** https://developers.ringcentral.com/support
- **Salad Cloud:** support@salad.com
- **Google Cloud:** https://cloud.google.com/support
- **PostgreSQL:** Local database on same server

---

## 🎉 PROJECT SUCCESS METRICS

- ✅ **3,194** recordings downloaded and registered
- ✅ **1,341** recordings with all 5 layers complete
- ✅ **5-Layer AI Analysis Per Call:**
  - Name extraction (employee/customer/company)
  - Sentiment analysis (mood, quality, topics)
  - Resolution tracking (problems, follow-ups, loop closure)
  - Process recommendations (improvements, coaching)
  - Advanced metrics (detailed performance analysis)
- ✅ **Enhanced Dashboard Features:**
  - Semantic search with call summaries
  - Full transcript viewer with metadata
  - Customer phone number tracking
  - Resolution and loop closure metrics
- ✅ **Security & Performance:**
  - Secure audio deletion (GNU shred)
  - SHA256 duplicate prevention
  - Cached AI insights (no repeated API calls)
  - Rate-limited processing (3-5s delays)
- ✅ **Database Architecture:**
  - PostgreSQL with pgvector (1536d)
  - 5 specialized tables for tracking
  - Full-text and semantic search
- ✅ **Integration Ready:**
  - Google Drive with folder structure
  - N8N queue system
  - RESTful API endpoints
- ✅ **COWS RAG Integration:**
  - Gemini RAG for semantic queries
  - Vertex AI RAG for structured queries
  - 16 JSONL files in GCS bucket
  - Web UI at http://31.97.102.13:8081
- ⏳ **~1,853** recordings pending 5-layer completion
- ✅ **6x** daily automated checks
- ✅ **100%** documentation coverage

---

## 💡 TIPS FOR NEXT SESSION

When you return to this project:

1. **Start with status check:**
   ```bash
   python src/scheduler/transcription_processor.py --status
   ```

2. **Review recent logs:**
   ```bash
   tail -n 100 logs/ringcentral_checker_$(date +%Y%m%d).log
   ```

3. **Check Git status:**
   ```bash
   git status
   git log --oneline -5
   ```

4. **Verify cron is running:**
   ```bash
   ps aux | grep run_ringcentral_check
   crontab -l
   ```

5. **Test system health:**
   ```bash
   python src/monitoring/health_check.py
   ```

---

## 📚 REFERENCE LINKS

- **GitHub Repository:** https://github.com/a9422crow/call-recording-system
- **RingCentral API Docs:** https://developers.ringcentral.com/api-reference
- **Salad Cloud Docs:** https://docs.salad.com/api
- **Google Drive API:** https://developers.google.com/drive/api/v3/reference
- **N8N Documentation:** https://docs.n8n.io

---

*Last Updated: 2025-09-21 (Latest)*
*Version: 3.0*
*Status: Production Ready*
*Next Review: Check daily operations and queue processing*

---

## 🚦 FULL AI SYSTEM IS LIVE AND RUNNING

The system is currently:
- ✅ Checking RingCentral 6x daily (automated)
- ✅ Processing transcriptions with Salad Cloud (automated)
- ✅ **Generating AI insights with GPT-3.5-turbo (automated)**
- ✅ **Web dashboard serving real-time analytics**
- ✅ Uploading to Google Drive (automated)
- ✅ Creating multi-format files (JSON + MD + SQLite)
- ✅ **RESTful API endpoints for integration**
- ✅ Ready for N8N workflows with insights data

**🧠 AI-POWERED CALL ANALYSIS IS FULLY OPERATIONAL!**

**Access:** http://31.97.102.13:5001 (password: !pcr123)