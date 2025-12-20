# COWS Hybrid RAG Integration

## Overview

The COWS (Call Observation & Workflow System) Hybrid RAG Integration adds intelligent querying capabilities to the call recording system using a dual RAG (Retrieval Augmented Generation) approach:

- **Gemini RAG** - For semantic, open-ended queries (Primary)
- **Vertex AI RAG** - For structured, filtered queries (Secondary)

The system automatically routes queries to the optimal backend based on query patterns.

## Current Status (December 2025)

| Metric | Value |
|--------|-------|
| Total Transcripts | 3,194 |
| All 5 Layers Complete | **1,341 calls** |
| Files in Gemini | 16 JSONL files |
| Files in GCS | 16 JSONL files |
| GCS Bucket | `call-recording-rag-data` |
| Web UI | http://31.97.102.13:8081 |
| Status | **Fully Operational** |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Web UI (Port 8081)                           │
│                    FastAPI + Jinja2 Templates                       │
│                    http://31.97.102.13:8081                         │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│                         Query Router                                 │
│           (Automatic routing based on query patterns)                │
└───────────┬─────────────────────────────────────────┬───────────────┘
            │                                         │
┌───────────▼───────────┐               ┌─────────────▼───────────────┐
│      Gemini RAG       │               │      Vertex AI RAG          │
│   (Semantic queries)  │               │   (Structured queries)      │
│   google.genai SDK    │               │   google-cloud-aiplatform   │
│   gemini-2.0-flash    │               │   gemini-2.0-flash-001      │
│                       │               │                             │
│ - What are customers  │               │ - Calls with score > 7      │
│   complaining about?  │               │ - Agent John's calls        │
│ - Summarize trends    │               │ - This week's escalations   │
└───────────────────────┘               └─────────────────────────────┘
            │                                         │
┌───────────▼─────────────────────────────────────────▼───────────────┐
│                    Google Cloud Storage                              │
│                 gs://call-recording-rag-data                         │
│                    transcripts/*.jsonl                               │
│                      (16 files)                                      │
└─────────────────────────────────────────────────────────────────────┘
                                ▲
┌───────────────────────────────┴─────────────────────────────────────┐
│                      Export Pipeline                                 │
│           (Database → JSONL → GCS → RAG Systems)                     │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│                      PostgreSQL Database                             │
│           (1,341 calls with ALL 5 LAYERS complete)                   │
│                                                                      │
│  Tables: transcripts, insights, call_resolutions,                    │
│          call_recommendations, call_advanced_metrics                 │
└─────────────────────────────────────────────────────────────────────┘
```

## 5-Layer Analysis Requirement

**IMPORTANT**: Only calls with ALL 5 LAYERS of analysis complete are exported to the RAG systems:

| Layer | Table | Description | Current Count |
|-------|-------|-------------|---------------|
| 1 | `transcripts` | Names extracted (employee_name or customer_name) | 2,468 |
| 2 | `insights` | Sentiment analysis, quality score, call type | 2,461 |
| 3 | `call_resolutions` | Problem complexity, empathy score, churn risk | 1,803 |
| 4 | `call_recommendations` | Process improvements, coaching notes | 2,289 |
| 5 | `call_advanced_metrics` | Advanced metrics | 1,651 |
| **All 5 Complete** | - | Ready for RAG export | **1,341** |

## Installation

```bash
# 1. Install dependencies
cd /var/www/call-recording-system
source venv/bin/activate
pip install -r rag_integration/requirements.txt

# 2. Configure environment variables (see Configuration section)

# 3. Start the service
python -m uvicorn rag_integration.api.main:app --host 0.0.0.0 --port 8081

# 4. Access Web UI
# http://your-server:8081
# Password: !pcr123
```

## Components

### Services (`rag_integration/services/`)

| File | Description |
|------|-------------|
| `db_reader.py` | Read-only PostgreSQL access with 5-layer verification |
| `jsonl_formatter.py` | Converts database records to RAG-ready JSONL |
| `gcs_uploader.py` | Uploads JSONL files to Google Cloud Storage |
| `gemini_file_search.py` | Gemini RAG integration using `google.genai` SDK |
| `vertex_rag.py` | Vertex AI RAG integration with filtering |
| `query_router.py` | Automatic query routing to optimal system |

### Jobs (`rag_integration/jobs/`)

| File | Description |
|------|-------------|
| `export_pipeline.py` | Orchestrates full export: DB → JSONL → GCS → RAG |
| `reports.py` | Report generation (churn risk, agent performance, etc.) |
| `email_sender.py` | Email delivery for reports and alerts |

### API (`rag_integration/api/`)

| File | Description |
|------|-------------|
| `main.py` | FastAPI application with Web UI |
| `routes.py` | API endpoints |
| `templates/` | Jinja2 HTML templates |
| `static/` | CSS styles |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Dashboard home |
| GET | `/query` | Query interface |
| GET | `/health` | Health check |
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
- "Which customers seem at risk of churning?"

### Structured Queries (Routed to Vertex)
- "Show all calls with churn risk > 7"
- "Agent John's performance this week"
- "All escalated calls from last month"
- "Calls with quality score < 5"

## Configuration

Environment variables in `.env`:

```bash
# Google Cloud Project
GOOGLE_CLOUD_PROJECT=call-recording-481713

# Gemini API (using google.genai SDK)
GEMINI_API_KEY=your_gemini_api_key
GEMINI_FILE_SEARCH_STORE=mst_call_intelligence

# Google Cloud Storage
GCS_RAG_BUCKET=call-recording-rag-data
GCS_RAG_PREFIX=transcripts/

# Vertex AI RAG
VERTEX_AI_LOCATION=us-west1
VERTEX_CORPUS_NAME=mst_call_intelligence

# RAG API
RAG_API_PORT=8081
RAG_API_PASSWORD=!pcr123

# Database (read-only access)
RAG_DATABASE_URL=postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights

# Email Reports (optional)
REPORT_FROM_EMAIL=reports@example.com
REPORT_RECIPIENTS=manager@example.com

# Google Service Account
GOOGLE_APPLICATION_CREDENTIALS=/var/www/call-recording-system/config/google_service_account.json
```

## Google Cloud Setup

### Service Account
- **Email**: `call-recording-uploader@snappy-elf-472517-r8.iam.gserviceaccount.com`
- **Credentials**: `/var/www/call-recording-system/config/google_service_account.json`

### GCS Bucket
- **Bucket**: `gs://call-recording-rag-data`
- **Location**: `us-west1`
- **Project**: `call-recording-481713`

### Vertex AI RAG Corpus
- **Project**: `call-recording-481713`
- **Location**: `us-west1`
- **Corpus Name**: `mst_call_intelligence`
- **Corpus ID**: `projects/536223716282/locations/us-west1/ragCorpora/6917529027641081856`
- **Model**: `gemini-2.0-flash-001`

### Required Permissions
The service account needs:

**GCS Permissions:**
- `storage.objects.create`
- `storage.objects.get`
- `storage.objects.list`
- `storage.objects.delete`
- `storage.buckets.get`

**Vertex AI Permissions:**
- `aiplatform.ragCorpora.create`
- `aiplatform.ragCorpora.get`
- `aiplatform.ragCorpora.list`
- `aiplatform.ragFiles.import`
- `aiplatform.ragFiles.list`

Grant with:
```bash
# GCS permissions
gsutil iam ch serviceAccount:call-recording-uploader@snappy-elf-472517-r8.iam.gserviceaccount.com:objectAdmin gs://call-recording-rag-data
gsutil iam ch serviceAccount:call-recording-uploader@snappy-elf-472517-r8.iam.gserviceaccount.com:legacyBucketReader gs://call-recording-rag-data

# Vertex AI permissions (run in Cloud Shell)
gcloud projects add-iam-policy-binding call-recording-481713 \
  --member="serviceAccount:call-recording-uploader@snappy-elf-472517-r8.iam.gserviceaccount.com" \
  --role="roles/aiplatform.admin"
```

## Manual Operations

```bash
cd /var/www/call-recording-system
source venv/bin/activate

# Check database statistics
python -c "
from rag_integration.services.db_reader import DatabaseReader
reader = DatabaseReader()
stats = reader.get_statistics()
print(f'Total transcripts: {stats[\"total_transcripts\"]}')
print(f'All 5 layers complete: {stats[\"all_5_layers_complete\"]}')
print(f'Ready for export: {stats[\"ready_for_export\"]}')
"

# Export new calls to JSONL
python -c "
from rag_integration.services.db_reader import DatabaseReader
from rag_integration.services.jsonl_formatter import JSONLFormatter
import json
from pathlib import Path

db = DatabaseReader()
fmt = JSONLFormatter()
export_dir = Path('rag_integration/exports')

calls = list(db.get_calls_for_export(limit=100, require_all_layers=True, min_layers=5))
print(f'Exporting {len(calls)} calls...')

with open(export_dir / 'new_export.jsonl', 'w') as f:
    for call in calls:
        f.write(json.dumps(fmt.format_call(call)) + '\n')
"

# Upload to GCS
python -c "
from rag_integration.services.gcs_uploader import GCSUploader
from pathlib import Path

uploader = GCSUploader()
files = uploader.upload_directory(Path('rag_integration/exports'))
print(f'Uploaded {len(files)} files')
"

# Upload to Gemini
python -c "
from rag_integration.services.gemini_file_search import GeminiFileSearchService
from pathlib import Path

service = GeminiFileSearchService()
for f in Path('rag_integration/exports').glob('*.jsonl'):
    result = service.upload_file(str(f))
    print(f'Uploaded: {result[\"name\"]}')
"

# Test a query
python -c "
from rag_integration.services.gemini_file_search import GeminiFileSearchService
from rag_integration.services.db_reader import DatabaseReader

db = DatabaseReader()
service = GeminiFileSearchService()

calls = list(db.get_calls_for_export(limit=50, require_all_layers=True, min_layers=5))
summaries = [{
    'call_id': c.get('recording_id'),
    'call_date': str(c.get('call_date')),
    'employee_name': c.get('employee_name'),
    'customer_sentiment': c.get('customer_sentiment'),
    'summary': c.get('summary', '')[:200]
} for c in calls]

result = service.analyze_calls_batch('What are the top customer complaints?', summaries)
print(result['response'])
"

# List files in Gemini
python -c "
from rag_integration.services.gemini_file_search import GeminiFileSearchService
service = GeminiFileSearchService()
for f in service.list_files():
    print(f\"{f['display_name']}: {f['state']}\")
"

# List files in GCS
python -c "
from rag_integration.services.gcs_uploader import GCSUploader
uploader = GCSUploader()
for f in uploader.list_files():
    print(f)
"
```

## Service Management

```bash
# Start manually (foreground)
source venv/bin/activate
python -m uvicorn rag_integration.api.main:app --host 0.0.0.0 --port 8081

# Start in background
nohup python -m uvicorn rag_integration.api.main:app --host 0.0.0.0 --port 8081 > logs/rag_api.log 2>&1 &

# Stop service
pkill -f "uvicorn rag_integration"

# Check if running
curl http://localhost:8081/health

# View logs
tail -f logs/rag_api.log
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
│   ├── db_reader.py          # Read-only PostgreSQL access
│   ├── jsonl_formatter.py    # JSONL formatting
│   ├── gcs_uploader.py       # GCS upload
│   ├── gemini_file_search.py # Gemini RAG (google.genai)
│   ├── vertex_rag.py         # Vertex AI RAG
│   └── query_router.py       # Query routing
├── jobs/
│   ├── __init__.py
│   ├── export_pipeline.py    # Export orchestration
│   ├── reports.py            # Report generation
│   └── email_sender.py       # Email delivery
├── api/
│   ├── __init__.py
│   ├── main.py               # FastAPI app
│   ├── routes.py             # API endpoints
│   ├── templates/
│   │   ├── base.html
│   │   ├── login.html
│   │   ├── index.html
│   │   ├── query.html
│   │   ├── reports.html
│   │   └── export.html
│   └── static/
│       └── style.css
├── exports/                   # JSONL export files (16 files)
├── requirements.txt
└── install.sh
```

## Troubleshooting

### Database connection fails
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Test connection
PGPASSWORD='REDACTED_DB_PASSWORD' psql -U call_insights_user -d call_insights -h localhost -c "SELECT 1"

# Check RAG_DATABASE_URL in .env
```

### GCS upload fails
```bash
# Check credentials file exists
ls -la config/google_service_account.json

# Test GCS access
source venv/bin/activate
python -c "
from rag_integration.services.gcs_uploader import GCSUploader
uploader = GCSUploader()
print(f'Bucket: {uploader.bucket_name}')
print(f'Connected: {uploader.test_connection()}')
"

# Grant permissions if needed
gsutil iam ch serviceAccount:call-recording-uploader@snappy-elf-472517-r8.iam.gserviceaccount.com:admin gs://call-recording-rag-data
```

### Gemini API errors
```bash
# Check API key is set
grep GEMINI_API_KEY .env

# Test Gemini connection
source venv/bin/activate
python -c "
from google import genai
from google.genai import types
import os
from dotenv import load_dotenv
load_dotenv()

client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
response = client.models.generate_content(
    model='gemini-2.0-flash',
    contents='Hello, are you working?'
)
print(response.text)
"
```

### Port 8081 already in use
```bash
# Find and kill existing process
sudo lsof -i :8081
sudo pkill -f "uvicorn rag_integration"

# Restart
source venv/bin/activate
python -m uvicorn rag_integration.api.main:app --host 0.0.0.0 --port 8081
```

### No calls ready for export
If 0 calls are ready for export, run the analysis pipelines:
```bash
# Check layer counts
PGPASSWORD='REDACTED_DB_PASSWORD' psql -U call_insights_user -d call_insights -h localhost -c "
SELECT 'Layer 5' as layer, COUNT(*) FROM call_advanced_metrics
UNION ALL
SELECT 'Layer 4', COUNT(*) FROM call_recommendations
UNION ALL
SELECT 'Layer 3', COUNT(*) FROM call_resolutions
UNION ALL
SELECT 'Layer 2', COUNT(*) FROM insights;
"

# Process missing layers
python layer2_sentiment_enhanced.py
python layer3_resolution_enhanced.py
python generate_call_recommendations.py
python process_advanced_metrics.py
```

## Technology Stack

| Component | Technology |
|-----------|------------|
| Web Framework | FastAPI + Uvicorn |
| Templates | Jinja2 |
| Database | PostgreSQL 14 with pgvector |
| Gemini SDK | `google-genai` (latest) |
| Vertex AI | `google-cloud-aiplatform` |
| Cloud Storage | `google-cloud-storage` |
| Model | `gemini-2.0-flash` |

## Security Notes

- Read-only database access enforced in `db_reader.py`
- Session-based authentication on Web UI
- API requires authentication cookie
- Credentials stored in `.env` (not in git)
- Service account JSON excluded from git
- Password: `!pcr123` (same as main dashboard)

## Version History

| Date | Version | Changes |
|------|---------|---------|
| Dec 20, 2025 | 2.1 | Updated Vertex AI to us-west1, added null query validation, agent dropdown in reports |
| Dec 2025 | 2.0 | Upgraded to google.genai SDK, gemini-2.0-flash, new GCS bucket (call-recording-rag-data) |
| Dec 2025 | 1.0 | Initial implementation with Gemini File Search and Vertex AI RAG |
