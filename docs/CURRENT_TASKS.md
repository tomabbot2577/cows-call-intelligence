# ConvoMetrics BLT Platform - Current Status

**Last Updated:** 2025-12-23

## Status: OPERATIONAL

All features are live and operational.

---

## Recent Updates

### Coaching & Learning Center (NEW)
- **URL:** `/learning`
- **Status:** Live
- Combined coaching insights for phone calls AND video meetings
- Joy-focused coaching approach (3:1 strengths to improvements ratio)

**Features:**
- **Coaching Feed Tab** - Strengths, growth areas, suggested phrases for all interactions
- **Needs Attention Tab** - High churn risk, high customer effort, struggling learners
- **Training Sessions Tab** - Video meeting learning analytics
- **Analytics Tab** - Sentiment distribution, top coaching topics

**New API Endpoints:**
- `GET /api/v1/coaching/feed` - Combined coaching data
- `GET /api/v1/coaching/employee/{name}` - Employee coaching progress
- `GET /api/v1/coaching/queue` - Needs attention queue
- `GET /api/v1/coaching/stats` - Summary statistics

**Metrics Tracked:**
- Customer Effort Score (1-10, lower is better)
- Empathy Score
- Loop Closure Score
- Learning Score/State (video meetings)
- Strengths and Growth Opportunities

---

## Video Meeting Intelligence

### 1. Video Transcription Pipeline
- **Status:** Operational
- **Cron:** `*/5 * * * *` - transcription_watchdog.sh
- **Workers:** 5 parallel via Salad API
- **Results:** 99/100 meetings transcribed

### 2. 6-Layer AI Analysis
- **Status:** Operational
- **Cron:** `*/10 * * * *` - layer_analysis_watchdog.sh
- **Workers:** 8 parallel
- **Results:** 97/99 meetings fully analyzed

### 3. Web UI
- `/video-meetings` - Video meetings dashboard with filters
- `/video-meetings/{id}` - Meeting detail with coaching insights card
- `/learning` - Coaching & Learning Center

### 4. Reports Integration
All reports now include video meeting data:
- Agent Performance Report - includes video meetings + Layer 6 learning stats
- Churn Risk Report - includes video meetings with churn risk
- Quality Report - includes low-quality video meetings
- Sentiment Report - includes video meeting sentiment
- Training Effectiveness Report - video-only learning metrics

### 5. Knowledge Base Integration
- Video meeting Q&A pairs included in KB search
- Source labels: "Call Recording", "Freshdesk Ticket", "Video Meeting"
- Automatic deduplication of Q&A entries

### 6. Layer 6 Learning Analytics
- Learning score (1-10)
- Learning states: aha_zone, building, stable, struggling, overwhelmed
- Training effectiveness tracking
- Sessions needing attention alerts

---

## Data Summary

| Metric | Value |
|--------|-------|
| Total Interactions (30 days) | 526 |
| Phone Calls | 519 |
| Video Meetings | 7 |
| Avg Quality Score | 8.2 |
| Q&A Pairs (Video) | 316 |

---

## API Endpoints

### Coaching API
| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/coaching/feed` | Combined coaching data (calls + video) |
| `GET /api/v1/coaching/employee/{name}` | Employee coaching progress |
| `GET /api/v1/coaching/queue` | Interactions needing attention |
| `GET /api/v1/coaching/stats` | Overall coaching statistics |

### Video Meeting API
| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/video-meetings` | Meetings list with filters |
| `GET /api/v1/video-meetings/stats` | Aggregate stats |
| `GET /api/v1/video-meetings/{id}` | Meeting detail |
| `GET /api/v1/rag/reports/training-effectiveness` | Training report |

---

## Key Files

| File | Purpose |
|------|---------|
| `rag_integration/api/templates/learning_module.html` | Coaching & Learning Center UI |
| `rag_integration/api/templates/video_meeting_detail.html` | Meeting detail with coaching |
| `rag_integration/services/db_reader.py` | Coaching data queries |
| `scripts/video_processing/batch_layer_analysis.py` | 6-layer AI analysis |
| `scripts/verify_cron_jobs.sh` | Cron job verification |

---

## Troubleshooting

### Kill Runaway AI Processes
```bash
ps aux | grep "process_all_layers" | grep -v grep
kill <PID>
```

### Check System Health
```bash
# Memory usage
free -h

# Database connection
source .env && source venv/bin/activate && python3 -c "
import psycopg2, os
conn = psycopg2.connect(os.environ.get('RAG_DATABASE_URL'))
print('OK')
"
```

### View Cron Logs
```bash
tail -50 logs/ai_layers_$(date +%Y%m%d).log
tail -50 logs/transcription_watchdog.log
```
