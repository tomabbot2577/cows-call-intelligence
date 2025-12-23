# Video Meeting Intelligence Module

**Last Updated:** 2025-12-23

## Status: COMPLETED

All video meeting intelligence features are now live and operational.

---

## Completed Features

### 1. Video Transcription Pipeline
- **Status:** Operational
- **Cron:** `*/5 * * * *` - transcription_watchdog.sh
- **Workers:** 5 parallel via Salad API
- **Results:** 99/100 meetings transcribed

### 2. 6-Layer AI Analysis
- **Status:** Operational
- **Cron:** `*/10 * * * *` - layer_analysis_watchdog.sh
- **Workers:** 8 parallel
- **Results:** 97/99 meetings fully analyzed (2 JSON parse errors)

### 3. Web UI
- `/video-meetings` - Video meetings dashboard with filters
- `/video-meetings/{id}` - Meeting detail with transcript, participants, Q&A, Layer 6 analysis
- `/learning` - Training & learning analytics dashboard

### 4. Reports Integration
All reports now include video meeting data alongside calls and tickets:
- Agent Performance Report - includes video meetings + Layer 6 learning stats
- Churn Risk Report - includes video meetings with churn risk
- Quality Report - includes low-quality video meetings
- Sentiment Report - includes video meeting sentiment
- Training Effectiveness Report (new) - video-only learning metrics

### 5. Knowledge Base Integration
- Video meeting Q&A pairs included in KB search
- Source labels: "Call Recording", "Freshdesk Ticket", "Video Meeting"
- Automatic deduplication to prevent duplicate Q&A entries

### 6. Layer 6 Learning Analytics
- Learning score (1-10)
- Learning states: aha_zone, building, stable, struggling, overwhelmed
- Training effectiveness tracking
- Sessions needing attention alerts

---

## Data Summary

| Metric | Value |
|--------|-------|
| Total Video Meetings | 100 |
| Transcribed | 99 |
| AI Analyzed | 97 |
| Q&A Pairs Generated | 316 |
| Unique Trainers | 5 |
| Avg Learning Score | 6.9/10 |

---

## Cron Jobs

| Schedule | Script | Purpose |
|----------|--------|---------|
| `*/5 * * * *` | `transcription_watchdog.sh` | Transcribe new recordings |
| `*/10 * * * *` | `layer_analysis_watchdog.sh` | 6-layer AI analysis |

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /video-meetings` | Video meetings list page |
| `GET /video-meetings/{id}` | Meeting detail page |
| `GET /learning` | Learning module page |
| `GET /api/v1/video-meetings` | Meetings API (filters: trainer, sentiment, learning_state, date_range) |
| `GET /api/v1/video-meetings/stats` | Aggregate stats API |
| `GET /api/v1/video-meetings/{id}` | Meeting detail API |
| `GET /api/v1/rag/reports/training-effectiveness` | Training effectiveness report |

---

## Key Files

| File | Purpose |
|------|---------|
| `scripts/video_processing/batch_layer_analysis.py` | 6-layer AI analysis with parallel workers |
| `scripts/video_processing/transcription_watchdog.sh` | Transcription cron script |
| `scripts/video_processing/layer_analysis_watchdog.sh` | Analysis cron script |
| `rag_integration/api/templates/video_meetings.html` | Meetings list UI |
| `rag_integration/api/templates/video_meeting_detail.html` | Meeting detail UI |
| `rag_integration/api/templates/learning_module.html` | Learning analytics UI |
| `docs/VIDEO_6_LAYER_EXTRACTION_SCHEMA.md` | Full 279-field schema documentation |

---

## Database Tables

- `video_meetings` - Main meeting data, transcripts, all layer scores
- `video_meeting_participants` - Participant details, speaking time, engagement
- `video_meeting_qa_pairs` - Extracted Q&A for knowledge base

---

## Recovery Commands

Check status:
```bash
PGPASSWORD='REDACTED_DB_PASSWORD' psql -U call_insights_user -h localhost -d call_insights -t -c \
"SELECT 'Transcribed: ' || COUNT(*) FILTER (WHERE transcript_text IS NOT NULL) ||
        ' | Analyzed: ' || COUNT(*) FILTER (WHERE layer1_complete = TRUE) ||
        ' | Pending: ' || COUNT(*) FILTER (WHERE layer1_complete IS NULL OR layer1_complete = FALSE)
FROM video_meetings WHERE source='ringcentral';"
```

View logs:
```bash
tail -50 logs/transcription_watchdog.log
tail -50 logs/layer_analysis_watchdog.log
```

Manual runs:
```bash
# Transcription
python scripts/video_processing/batch_transcribe_videos.py --limit 10 --workers 5

# Layer analysis
python scripts/video_processing/batch_layer_analysis.py --limit 50 --workers 8
```
