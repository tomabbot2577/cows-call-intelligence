# 🤖 AI/LLM Integration Guide - Call Transcript Processing

## Overview

This system provides a comprehensive structured data organization optimized for N8N workflows and AI/LLM processing. All transcripts are organized with rich metadata for easy retrieval, analysis, and machine learning applications.

## 📁 Directory Structure

The system organizes transcripts in multiple ways for optimal AI/LLM access:

```
/data/structured/
├── by_date/                    # Chronological organization
│   ├── 2025/
│   │   ├── 01/
│   │   │   ├── 19/
│   │   │   │   ├── call_abc123.json
│   │   │   │   └── call_def456.json
│   │   │   └── 20/
│   │   └── 02/
│   └── [year]/[month]/[day]/

├── by_customer/                # Customer-centric organization
│   ├── [customer_id]/
│   │   ├── metadata.json
│   │   ├── calls/
│   │   └── analytics/

├── by_phone/                   # Phone number organization
│   ├── +1234567890/
│   │   ├── inbound/
│   │   └── outbound/

├── n8n_workflows/              # N8N-ready data
│   ├── queue/                 # New items for processing
│   ├── processing/            # Currently being processed
│   ├── processed/             # Completed items
│   ├── failed/                # Failed processing
│   └── webhooks/              # Webhook payloads

├── ml_datasets/                # ML-ready formats
│   ├── training/              # Training data
│   ├── embeddings/            # Text embeddings
│   ├── classifications/       # Classification results
│   ├── ner_entities/          # Named Entity Recognition
│   ├── sentiment/             # Sentiment analysis
│   └── topics/                # Topic modeling

├── analytics/                  # Aggregated analytics
│   ├── daily_summaries/
│   ├── sentiment_analysis/
│   ├── topic_modeling/
│   └── customer_insights/

├── indexes/                    # Search indexes
│   ├── master_index.json
│   ├── by_phone.json
│   ├── by_customer.json
│   └── temporal/

└── exports/                    # Export formats
    ├── csv/                   # CSV exports
    ├── parquet/               # Parquet for big data
    ├── elasticsearch/         # Elasticsearch bulk format
    └── bigquery/              # BigQuery compatible
```

## 📊 JSON Document Structure

Each transcript is stored with comprehensive metadata optimized for AI processing:

```json
{
  "id": "call_abc123",
  "document_type": "call_transcript",
  "schema_version": "2.0",

  "content": {
    "text": "Full transcript text...",
    "segments": [
      {
        "id": 0,
        "start": 0.0,
        "end": 5.2,
        "text": "Hello, thank you for calling...",
        "confidence": 0.95,
        "speaker": "agent",
        "words": [...]
      }
    ],
    "summary": "Customer called about billing issue..."
  },

  "call_info": {
    "recording_id": "ring_12345",
    "start_time": "2025-01-19T10:30:00Z",
    "duration_seconds": 240,
    "direction": "inbound",
    "participants": {
      "from": {
        "number": "+12125551234",
        "name": "John Smith",
        "type": "caller"
      },
      "to": {
        "number": "+18005551234",
        "name": "Support Line",
        "type": "recipient"
      }
    }
  },

  "temporal": {
    "year": 2025,
    "month": 1,
    "day": 19,
    "hour": 10,
    "day_of_week": "Sunday",
    "week_of_year": 3,
    "quarter": 1,
    "is_business_hours": true,
    "timestamp_iso": "2025-01-19T10:30:00Z"
  },

  "features": {
    "entities": {
      "phone_numbers": ["+19175551234"],
      "emails": ["customer@example.com"],
      "amounts": ["$49.99", "$100.00"],
      "dates": ["01/19/2025", "next Monday"],
      "potential_names": ["John Smith", "Mary Johnson"]
    },
    "keywords": ["billing", "refund", "account", "service"],
    "metrics": {
      "word_count": 450,
      "duration_seconds": 240,
      "confidence_score": 0.92,
      "speaking_rate": 112.5
    }
  },

  "language_info": {
    "language": "en-US",
    "confidence": 0.99,
    "transcription_confidence": 0.92
  },

  "metadata": {
    "created_at": "2025-01-19T10:35:00Z",
    "processing": {
      "processed_at": "2025-01-19T10:34:00Z",
      "schema_version": "2.0",
      "organizer_version": "1.0"
    },
    "source": "salad_cloud",
    "audio_deleted": true,
    "retention_policy": "transcript_only"
  },

  "n8n_hints": {
    "workflow_ready": true,
    "requires_sentiment_analysis": true,
    "requires_entity_extraction": true,
    "requires_summarization": true,
    "priority": "high"
  },

  "search_tags": [
    "year:2025",
    "month:1",
    "day:19",
    "sunday",
    "from:+12125551234",
    "has_email",
    "has_amount",
    "high_confidence"
  ]
}
```

## 🔄 N8N Integration

### Webhook Endpoints

The system provides N8N-compatible webhook endpoints:

```javascript
// N8N Webhook URLs
const webhooks = {
  new_transcript: '/webhook/transcript/new',
  sentiment_analysis: '/webhook/analysis/sentiment',
  entity_extraction: '/webhook/analysis/entities',
  summarization: '/webhook/analysis/summary',
  customer_insights: '/webhook/insights/customer',
  alert_trigger: '/webhook/alerts/trigger',
  batch_process: '/webhook/batch/process'
};
```

### N8N Workflow Payload

Flat structure optimized for N8N node processing:

```json
{
  "transcript_id": "call_abc123",
  "recording_id": "ring_12345",
  "call_timestamp": "2025-01-19T10:30:00Z",
  "processing_timestamp": "2025-01-19T10:35:00Z",

  "from_number": "+12125551234",
  "from_name": "John Smith",
  "to_number": "+18005551234",
  "to_name": "Support Line",
  "call_direction": "inbound",
  "duration_seconds": 240,

  "transcript_text": "Full transcript text...",
  "word_count": 450,
  "confidence_score": 0.92,
  "language": "en-US",

  "year": 2025,
  "month": 1,
  "day": 19,
  "hour": 10,
  "day_of_week": "Sunday",
  "is_business_hours": true,

  "has_phone_numbers": true,
  "has_emails": true,
  "has_amounts": true,
  "phone_numbers_found": ["+19175551234"],
  "emails_found": ["customer@example.com"],
  "amounts_found": ["$49.99", "$100.00"],

  "keywords": ["billing", "refund", "account"],
  "workflow_type": "new_transcript",
  "priority": "high",

  "callback_url": "/api/n8n/callback/call_abc123",
  "webhook_source": "call_recording_system"
}
```

### N8N Workflow Examples

#### 1. Sentiment Analysis Workflow
```
Webhook Trigger → Extract Text → Sentiment Analysis → Update Database → Send Alert (if negative)
```

#### 2. Entity Extraction Workflow
```
Webhook Trigger → Extract Entities → Enrich CRM → Update Customer Profile → Trigger Follow-up
```

#### 3. Summarization Workflow
```
Webhook Trigger → GPT Summarization → Save Summary → Email Manager → Update Dashboard
```

## 🔍 Search Capabilities

### Full-Text Search

```python
from src.search.transcript_search_engine import TranscriptSearchEngine

search = TranscriptSearchEngine()

# Text search
results = search.search(
    query="billing refund",
    filters={
        'phone': '+12125551234',
        'date_from': '2025-01-01',
        'date_to': '2025-01-31',
        'has_email': True
    }
)
```

### Search by Metadata

```python
# By phone number
calls = search.search_by_phone('+12125551234')

# By date range
calls = search.search_by_date_range(
    start_date=datetime(2025, 1, 1),
    end_date=datetime(2025, 1, 31)
)

# Get analytics
analytics = search.get_analytics()
```

## 🤖 LLM Integration Patterns

### 1. Embedding Generation

```python
# Prepare for embeddings
from src.storage.structured_data_organizer import StructuredDataOrganizer

organizer = StructuredDataOrganizer()
document = organizer.process_transcription(transcript, metadata)

# Chunks are automatically created for embedding
# Location: /ml_datasets/embeddings/call_abc123_embed.json
```

### 2. Training Data Export

```python
# Export for LLM fine-tuning
export_path = search.export_for_llm(
    filters={'date_from': '2025-01-01'},
    format='jsonl'  # or 'csv', 'parquet'
)
```

### 3. Retrieval Augmented Generation (RAG)

```python
# Search relevant transcripts for context
relevant = search.search(
    query="customer complaint about service",
    limit=5
)

# Use as context for LLM
context = "\n".join([r.snippet for r in relevant])
prompt = f"Based on these customer interactions:\n{context}\n\nSummarize the main issues:"
```

## 📈 Analytics Integration

### Customer Analytics

```sql
-- Top customers by call volume
SELECT
    from_number,
    from_name,
    COUNT(*) as call_count,
    AVG(duration_seconds) as avg_duration
FROM call_info
GROUP BY from_number, from_name
ORDER BY call_count DESC;
```

### Temporal Analytics

```python
# Call patterns analysis
analytics = search.get_analytics()
temporal_dist = analytics['temporal_distribution']

# Business hours vs after hours
business_ratio = sum(d['business_hours_ratio'] for d in temporal_dist) / len(temporal_dist)
```

### Entity Analytics

```python
# Most mentioned entities
entity_stats = analytics['entity_stats']
# {'phone_numbers': 145, 'emails': 89, 'amounts': 234}
```

## 🔧 Configuration

### Environment Variables

```bash
# N8N Configuration
N8N_WEBHOOK_BASE_URL=https://n8n.example.com
N8N_API_KEY=your_n8n_api_key

# Search Configuration
SEARCH_INDEX_DIR=/var/www/call-recording-system/data/structured/indexes
SEARCH_DB_PATH=/var/www/call-recording-system/data/structured/search.db

# ML Configuration
ML_DATASETS_DIR=/var/www/call-recording-system/data/structured/ml_datasets
EMBEDDINGS_MODEL=text-embedding-ada-002
```

## 🚀 Quick Start

### 1. Process New Transcript

```python
from src.storage.structured_data_organizer import StructuredDataOrganizer
from src.integrations.n8n_integration import N8NIntegration
from src.search.transcript_search_engine import TranscriptSearchEngine

# Initialize components
organizer = StructuredDataOrganizer()
n8n = N8NIntegration()
search = TranscriptSearchEngine()

# Process transcript
result = organizer.process_transcription(transcript_data, call_metadata)

# Queue for N8N
n8n.process_transcript_for_n8n(result['document'])

# Index for search
search.index_transcript(result['document'])
```

### 2. Batch Processing

```python
# Create batch workflow
batch_result = n8n.create_batch_workflow(
    transcript_ids=['call_001', 'call_002', 'call_003'],
    workflow_type='batch_analysis'
)
```

### 3. Export for AI Training

```python
# Export last month's data
export_path = search.export_for_llm(
    filters={
        'date_from': '2025-01-01',
        'date_to': '2025-01-31'
    },
    format='jsonl'
)
```

## 📊 Monitoring

### Queue Status

```python
status = n8n.get_queue_status()
# {'queued': 10, 'processing': 3, 'processed': 145, 'failed': 2}
```

### Search Index Status

```python
index_stats = search.rebuild_indexes()
# {'total_documents': 1543, 'indexes_rebuilt': ['fts', 'phone', 'entity', 'temporal']}
```

## 🔐 Security Notes

- Audio files are NEVER stored (deleted after transcription)
- Only transcripts and metadata are retained
- All data is structured for compliance
- Audit trails maintained for all operations

## 📚 Additional Resources

- [N8N Workflow Templates](./n8n_workflows/templates/)
- [ML Model Examples](./ml_datasets/models/)
- [Search Query Examples](./docs/search_examples.md)
- [API Documentation](./docs/api.md)

---

**Version**: 2.0
**Last Updated**: 2025-01-19
**Status**: Production Ready