# Call Recording System - Claude Context

## Quick Reference

| Resource | URL | Auth |
|----------|-----|------|
| COWS Web UI | http://31.97.102.13:8081 | Username/password |
| Legacy Dashboard | http://31.97.102.13:5001 | Password: `[see .env]` |
| Audio Server | http://31.97.102.13:8080/audio/ | - |

## System Overview

AI-powered call recording system that:
1. Downloads calls from RingCentral (2x daily at 6am/6pm)
2. Transcribes via Salad Cloud API
3. Runs 5-layer AI analysis (names, sentiment, resolution, recommendations, metrics)
4. Exports to Vertex AI RAG for intelligent querying
5. Syncs Freshdesk KB with AI enrichment
6. Sends email alerts on pipeline failures

**Status**: Fully automated 2x daily pipeline

## Database

```
PostgreSQL 14 with pgvector
Connection: postgresql://[user]:[password]@localhost/call_insights (see .env)
```

**Key Tables:**
- `call_log` - All RingCentral calls with metadata
- `transcripts` - Recording metadata and full text
- `insights` - Sentiment, quality scores, topics
- `call_resolutions` - 25+ resolution metrics including churn risk
- `call_recommendations` - Process improvements, coaching
- `transcript_embeddings` - Vector embeddings (1536d)
- `kb_freshdesk_qa` - Freshdesk ticket Q&A pairs

## Project Structure

```
/var/www/call-recording-system/
├── src/
│   ├── scheduler/
│   │   ├── ringcentral_checker.py    # RingCentral download
│   │   └── transcription_processor.py # Transcription queue
│   ├── transcription/
│   │   └── salad_transcriber_enhanced.py
│   ├── storage/
│   │   ├── enhanced_organizer.py
│   │   └── google_drive.py
│   ├── insights/
│   │   └── insights_manager_postgresql.py
│   └── database/
│       └── models.py
├── rag_integration/
│   ├── api/
│   │   ├── main.py               # FastAPI app (COWS platform)
│   │   └── templates/            # Jinja2 templates
│   ├── services/
│   │   ├── db_reader.py          # Read-only PostgreSQL
│   │   ├── kb_simple.py          # Knowledge base search
│   │   ├── vertex_rag.py         # Vertex AI RAG
│   │   ├── gemini_file_search.py # Gemini RAG
│   │   └── query_router.py       # Auto-routing
│   ├── config/
│   │   └── employee_names.py     # Canonical employee list + variations
│   └── jobs/
│       ├── freshdesk_sync_cron.py
│       └── freshdesk_vertex_import.py
├── scripts/                       # Cron job scripts
├── web/
│   └── insights_dashboard.py     # Legacy dashboard
├── logs/
└── data/
    ├── audio_queue/              # Pending MP3s
    ├── transcriptions/           # JSON/MD output
    └── alerts/                   # Pipeline alert files
```

## Cron Schedule (2x Daily)

| Time | Script | Purpose |
|------|--------|---------|
| 6:00am/pm | `run_ringcentral_v2.sh` | Download calls + recordings |
| 6:30am/pm | `run_transcription_v2.sh` | Transcribe new recordings |
| 7:30am/pm | `run_ai_layers.sh` | AI layers 1-5 |
| 8:30am/pm | `run_vertex_rag_export.sh` | Export to Vertex AI RAG |
| 9:00am/pm | `run_freshdesk_pipeline.sh` | Freshdesk sync + enrich |
| 10:00am/pm | `verify_cron_jobs.sh` | Verify + email alerts |
| Every 5min | `db_health_monitor.sh` | Database health |

**Alerts**: Sent to `sabbey@mainsequence.net` on failure

## AI Analysis Layers

| Layer | Purpose | Key Fields |
|-------|---------|------------|
| 1 | Entity Extraction | employee_name, customer_name, company |
| 2 | Sentiment & Quality | customer_sentiment, call_quality_score (1-10), call_type, topics |
| 3 | Resolution Tracking | churn_risk, resolution_effectiveness, empathy_score, loop_closure |
| 4 | Recommendations | process_improvements, coaching_points, follow_up_actions |
| 5 | Advanced Metrics | Layer 5 metrics for detailed analysis |

## COWS Platform Features

### Knowledge Base (`/knowledge-base`)
- Full-text search across Freshdesk tickets + call transcripts
- AI summaries via Google Gemini
- 5,300+ Q&A pairs from Freshdesk

### Reports (`/reports`, `/sales-intelligence`)
- Churn Risk: `/api/v1/rag/reports/churn`
- Agent Performance: `/api/v1/rag/reports/agent/{name}`
- Sales Pipeline: `/api/v1/rag/reports/sales-pipeline`
- Key Quotes: `/api/v1/rag/reports/key-quotes`
- Q&A Training: `/api/v1/rag/reports/qa-training`
- Hormozi Analysis: `/api/v1/rag/reports/sales-call-analysis?recording_id=<id>`

### Vertex RAG Filters
Supported natural language filters:
- `churn_risk` (none/low/medium/high)
- `customer_sentiment` (positive/neutral/negative)
- `call_quality_score` (1-10)
- `escalation_required` (boolean)
- `call_type` (support/billing/sales/etc.)
- `employee_name`

### Employee Name Handling
Canonical names in dropdowns map to database variations:
```python
# "James Lombardo" matches: "Jim", "Jim Lombardo", etc.
from rag_integration.config.employee_names import get_employee_name_variations
```

### User Activity Dashboard

Real-time agent productivity tracking with call + ticket metrics.

**URLs:**
| Route | Access | Description |
|-------|--------|-------------|
| `/dashboard` | All users | Personal metrics dashboard |
| `/dashboard/admin` | Admins only | Team overview with all agents |
| `/dashboard/admin/user/{name}` | Admins only | Drill-down to specific user |
| `/admin/triggers` | Admins only | Email trigger management |
| `/admin/agent-mapping` | Admins only | Freshdesk agent → PCR employee mapping |

**Metrics Tracked:**
- **Calls:** Total, answered, missed, answer rate, avg duration, hourly volume
- **Tickets:** Opened, closed, open total, overdue (>5 days), aging distribution
- **Quality:** Avg quality score, sentiment distribution, FCR, escalations
- **Productivity:** Score (0-100), Grade (A-F)

**Period Filters:** Today, WTD, Last Week, MTD, QTD, YTD

**Email Triggers:**
- Types: Below/Meets/Exceeds Expectations, Daily/Weekly Summary, Threshold Alert
- Frequencies: Realtime (15 min), Hourly, Daily, Weekly
- Recipients: Admin, User, All Admins, Custom emails

**Database Tables:**
- `user_daily_metrics` - Pre-aggregated daily metrics per employee
- `user_hourly_call_volume` - Hourly breakdown for charts
- `dashboard_email_triggers` - Trigger configuration
- `dashboard_trigger_log` - Trigger execution history
- `freshdesk_agent_map` - Maps Freshdesk agents to PCR employees

**Cron Jobs:**
```cron
# Dashboard metrics - every 15 min (6am-10pm)
*/15 6-22 * * * /var/www/call-recording-system/scripts/run_dashboard_metrics.sh

# Full daily aggregation - midnight
0 0 * * * /var/www/call-recording-system/scripts/run_dashboard_metrics.sh --full

# Trigger evaluation - realtime, daily, weekly
*/15 * * * * scripts/run_trigger_evaluator.sh --frequency realtime
0 7 * * * scripts/run_trigger_evaluator.sh --frequency daily
0 7 * * 1 scripts/run_trigger_evaluator.sh --frequency weekly
```

**Key Files:**
- `rag_integration/services/dashboard_metrics.py` - Metrics aggregation
- `rag_integration/services/dashboard_triggers.py` - Email trigger service
- `rag_integration/api/templates/dashboard_user.html` - User dashboard UI
- `rag_integration/api/templates/dashboard_admin.html` - Admin dashboard UI
- `rag_integration/jobs/aggregate_daily_metrics.py` - Daily cron job
- `rag_integration/jobs/evaluate_triggers.py` - Trigger evaluation cron

## Common Commands

```bash
# Activate environment
cd /var/www/call-recording-system && source venv/bin/activate

# Service management
sudo systemctl status cows-rag-api.service
sudo systemctl restart cows-rag-api.service
tail -f /var/log/cows/rag-api.log

# Database queries
PGPASSWORD=$PG_PASSWORD psql -U call_insights_user -d call_insights -h localhost

# Check processing status
python src/scheduler/transcription_processor.py --status

# Manual RingCentral check
python src/scheduler/ringcentral_checker.py --limit 30

# View cron jobs
crontab -l

# Check today's logs
tail -f logs/ringcentral_checker_$(date +%Y%m%d).log
```

## Vertex AI RAG

```
Project: call-recording-481713
Location: us-west1
Corpus: mst_call_intelligence
GCS Bucket: gs://call-recording-rag-data
```

**Import commands:**
```bash
# Full export + import
python -m rag_integration.jobs.freshdesk_vertex_import

# Export only
python -m rag_integration.jobs.freshdesk_vertex_import --export-only

# Import only
python -m rag_integration.jobs.freshdesk_vertex_import --import-only
```

**Constraint**: JSONL files must be < 10MB (split into ~2000 record parts)

## Environment Variables

Key variables in `.env`:
- `RC_CLIENT_ID`, `RC_CLIENT_SECRET`, `RC_JWT_TOKEN` - RingCentral
- `SALAD_API_KEY`, `SALAD_ORG_NAME` - Transcription
- `DATABASE_URL`, `PG_*` - PostgreSQL
- `GOOGLE_CREDENTIALS_PATH`, `GOOGLE_DRIVE_*` - Drive upload
- `OPENAI_API_KEY` - Embeddings
- `OPENROUTER_API_KEY` - AI models
- `GEMINI_API_KEY` - RAG queries

## Troubleshooting

**Queue stuck:**
```bash
python src/scheduler/transcription_processor.py --reprocess-failed
```

**Check pipeline status:**
```bash
cat data/scheduler/last_check.json
```

**Disk space:**
```bash
df -h /var/www/call-recording-system/data
find /data/processed -name "*.mp3" -mtime +30 -delete
```

**Database health:**
```bash
curl http://localhost:8081/health
```

## PC Recruiter Employees (Canonical List)

Bill Kubicek, Dylan Bello, James Blair, Nicholas Bradach, Robin Montoni,
Garrett Komyati, Jim Blair, John Blair, Mackenzie Scalise, Tyler Fleig,
Matt Lester, Chris Morrison, Michael Depto, Angela Mc Aleer, Linda Bailey,
Victoria Eck, Kathy Harden, John Turk, Andrew Blair, Davisha, Lisa Rogers,
Samuel Barnes

## Related Documentation

- `RAG_INTEGRATION.md` - Detailed RAG setup
- `N8N_API_DOCUMENTATION.md` - API endpoints for N8N
- `SYSTEM_DOCUMENTATION.md` - Full system overview
