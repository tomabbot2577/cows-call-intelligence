# COWS Hybrid RAG Integration

## Overview

The COWS (Call Observation & Workflow System) Hybrid RAG Integration adds intelligent querying capabilities to the call recording system using a dual RAG (Retrieval Augmented Generation) approach:

- **Gemini File Search** - For semantic, open-ended queries
- **Vertex AI RAG** - For structured, filtered queries

The system automatically routes queries to the optimal backend based on query patterns.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Web UI (Port 8081)                           │
│                    FastAPI + Jinja2 Templates                       │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│                         Query Router                                 │
│           (Automatic routing based on query patterns)                │
└───────────┬─────────────────────────────────────────┬───────────────┘
            │                                         │
┌───────────▼───────────┐               ┌─────────────▼───────────────┐
│   Gemini File Search  │               │      Vertex AI RAG          │
│   (Semantic queries)  │               │   (Structured queries)      │
│                       │               │                             │
│ - What are customers  │               │ - Calls with score > 7      │
│   complaining about?  │               │ - Agent John's calls        │
│ - Summarize trends    │               │ - This week's escalations   │
└───────────────────────┘               └─────────────────────────────┘
            │                                         │
┌───────────▼─────────────────────────────────────────▼───────────────┐
│                    Google Cloud Storage                              │
│                 (mst-call-intelligence bucket)                       │
│                    transcripts/*.jsonl                               │
└─────────────────────────────────────────────────────────────────────┘
                                ▲
┌───────────────────────────────┴─────────────────────────────────────┐
│                      Export Pipeline                                 │
│           (Database → JSONL → GCS → RAG Systems)                     │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│                      PostgreSQL Database                             │
│        (103 calls with ALL 5 LAYERS of analysis complete)            │
│                                                                      │
│  Tables: transcripts, insights, call_resolutions,                    │
│          call_recommendations, call_advanced_metrics                 │
└─────────────────────────────────────────────────────────────────────┘
```

## 5-Layer Analysis Requirement

**CRITICAL**: Only calls with ALL 5 LAYERS of analysis complete are exported to the RAG systems:

| Layer | Table | Description |
|-------|-------|-------------|
| 1 | `transcripts` | Names extracted (employee_name or customer_name) |
| 2 | `insights` | Sentiment analysis, quality score, call type |
| 3 | `call_resolutions` | Problem complexity, empathy score, churn risk |
| 4 | `call_recommendations` | Process improvements, coaching notes |
| 5 | `call_advanced_metrics` | Advanced metrics (must exist) |

Current status: **103 calls** ready for RAG export (all 5 layers complete).

## Installation

```bash
# 1. Install dependencies
cd /var/www/call-recording-system
source venv/bin/activate
pip install -r rag_integration/requirements.txt

# 2. Run full installation (systemd service, cron jobs)
sudo ./rag_integration/install.sh

# 3. Access Web UI
# http://your-server:8081
# Password: !pcr123 (same as main dashboard)
```

## Components

### Services (`rag_integration/services/`)

- **`db_reader.py`** - Read-only PostgreSQL access with 5-layer verification
- **`jsonl_formatter.py`** - Converts database records to RAG-ready JSONL
- **`gcs_uploader.py`** - Uploads JSONL files to Google Cloud Storage
- **`gemini_file_search.py`** - Gemini File Search integration
- **`vertex_rag.py`** - Vertex AI RAG integration with filtering
- **`query_router.py`** - Automatic query routing to optimal system

### Jobs (`rag_integration/jobs/`)

- **`export_pipeline.py`** - Orchestrates full export: DB → JSONL → GCS → RAG
- **`reports.py`** - Report generation (churn risk, agent performance, etc.)
- **`email_sender.py`** - Email delivery for reports and alerts

### API (`rag_integration/api/`)

- **`main.py`** - FastAPI application with Web UI
- **`routes.py`** - API endpoints
- **`templates/`** - Jinja2 HTML templates
- **`static/`** - CSS styles

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Dashboard home |
| GET | `/query` | Query interface |
| POST | `/api/v1/rag/query` | Execute RAG query |
| POST | `/api/v1/rag/export` | Trigger export pipeline |
| GET | `/api/v1/rag/status` | System status |
| GET | `/api/v1/rag/reports/churn` | Churn risk report |
| GET | `/api/v1/rag/reports/agent/{name}` | Agent performance report |
| GET | `/reports` | Reports page |
| GET | `/export` | Export management page |

## Query Examples

### Semantic Queries (Routed to Gemini)
- "What are the most common customer complaints?"
- "Summarize competitor mentions in calls"
- "Find patterns in calls that resulted in escalation"
- "What training do agents need?"

### Structured Queries (Routed to Vertex)
- "Show all calls with churn risk > 7"
- "Agent John's performance this week"
- "All escalated calls from last month"
- "Calls with quality score < 5"

## Configuration

Environment variables in `.env`:

```bash
# Gemini
GEMINI_API_KEY=your_api_key

# Google Cloud Storage
GCS_RAG_BUCKET=mst-call-intelligence
GCS_RAG_PREFIX=transcripts/

# RAG API
RAG_API_PORT=8081
RAG_API_PASSWORD=!pcr123

# Database
RAG_DATABASE_URL=postgresql://user:pass@localhost/call_insights

# Email Reports
REPORT_FROM_EMAIL=reports@example.com
REPORT_RECIPIENTS=manager@example.com
```

## Scheduled Jobs

Configured in `/etc/cron.d/cows-rag`:

| Schedule | Job | Description |
|----------|-----|-------------|
| 2:00 AM daily | Incremental export | Export last 24 hours |
| 3:00 AM Sunday | Full export | Re-export all data |

## Manual Operations

```bash
cd /var/www/call-recording-system
source venv/bin/activate

# Run incremental export (last 24 hours)
python -m rag_integration.jobs.export_pipeline

# Run full export (all data)
python -m rag_integration.jobs.export_pipeline --full

# Test database connection
python -c "
from rag_integration.services.db_reader import DatabaseReader
reader = DatabaseReader()
stats = reader.get_statistics()
print(f'Ready for export: {stats[\"ready_for_export\"]} calls')
"

# Test query routing
python -c "
import asyncio
from rag_integration.services.query_router import QueryRouter
router = QueryRouter()
result = asyncio.run(router.route_query('What are customers complaining about?'))
print(result)
"
```

## Service Management

```bash
# Start service
sudo systemctl start cows-rag-api

# Stop service
sudo systemctl stop cows-rag-api

# Restart service
sudo systemctl restart cows-rag-api

# Check status
sudo systemctl status cows-rag-api

# View logs
tail -f /var/log/cows/rag-api.log
tail -f /var/log/cows/rag-export.log
```

## Directory Structure

```
rag_integration/
├── __init__.py
├── config/
│   ├── __init__.py
│   └── settings.py
├── services/
│   ├── __init__.py
│   ├── db_reader.py
│   ├── jsonl_formatter.py
│   ├── gcs_uploader.py
│   ├── gemini_file_search.py
│   ├── vertex_rag.py
│   └── query_router.py
├── jobs/
│   ├── __init__.py
│   ├── export_pipeline.py
│   ├── reports.py
│   └── email_sender.py
├── api/
│   ├── __init__.py
│   ├── main.py
│   ├── routes.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── login.html
│   │   ├── index.html
│   │   ├── query.html
│   │   ├── reports.html
│   │   └── export.html
│   └── static/
│       └── style.css
├── exports/                    # JSONL export files
├── tests/
│   └── __init__.py
├── requirements.txt
├── install.sh
├── setup_cron.sh
└── cows-rag-api.service
```

## Troubleshooting

### Database connection fails
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Test connection
psql -U call_insights_user -d call_insights -h localhost -c "SELECT 1"

# Check RAG_DATABASE_URL in .env
```

### GCS upload fails
```bash
# Check credentials
cat config/google_service_account.json | head -5

# Test GCS access
gsutil ls gs://mst-call-intelligence/
```

### Gemini API errors
```bash
# Check API key
echo $GEMINI_API_KEY

# Test Gemini connection
python -c "
import google.generativeai as genai
genai.configure(api_key='YOUR_KEY')
model = genai.GenerativeModel('gemini-1.5-flash')
print(model.generate_content('Hello').text)
"
```

### No calls ready for export
If 0 calls are ready for export, it means no calls have completed all 5 layers of analysis. Run the analysis pipelines:
```bash
# Process Layer 2 (sentiment)
python layer2_sentiment_enhanced.py

# Process Layer 3 (resolution)
python layer3_resolution_enhanced.py

# Process Layer 4 (recommendations)
python generate_call_recommendations.py

# Process Layer 5 (advanced metrics)
python process_advanced_metrics.py
```

## Security Notes

- Read-only database access enforced in `db_reader.py`
- Session-based authentication on Web UI
- API requires authentication cookie
- Credentials stored in `.env` (not in git)
- Service account JSON excluded from git
