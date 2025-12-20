# Call Recording System - Progress Status
## Last Updated: December 19, 2025 23:58 UTC

## CURRENT STATUS

### 1. Recordings Count
- **In Database:** 1,485 transcripts (1,475 with content)
- **In Audio Queue:** ~1,713 MP3s waiting
- **Total Target:** ~3,100 recordings

### 2. Transcription with Metadata
**Script:** `/var/www/call-recording-system/process_queue_with_metadata.py`
- ✅ Includes RingCentral metadata (date, time, direction, from/to)
- ✅ Tested successfully with Salad Cloud
- **Run command:**
```bash
source /var/www/call-recording-system/venv/bin/activate
python /var/www/call-recording-system/process_queue_with_metadata.py --limit 100 --rate-limit 5
```

### 3. AI Insights Status

#### Layers 1-4 (Existing)
| Layer | Description | Processed | Pending |
|-------|-------------|-----------|---------|
| Layer 1 | Names (customer/employee) | 1,409 | 66 |
| Layer 2 | Sentiment & Quality | 1,424 | 51 |
| Layer 3 | Resolution & Closure | 426 | 1,049 |
| Layer 4 | Recommendations | 1,340 | 135 |
| Embeddings | Vector embeddings | 1,424 | 51 |

#### Layer 5 (NEW - Advanced Metrics) ✅ READY
**Script:** `/var/www/call-recording-system/layer5_advanced_metrics.py`
**Table:** `call_advanced_metrics`

**8 New Metrics:**
| Metric | Purpose | Field |
|--------|---------|-------|
| Buying signals | Sales opportunities | `buying_signals` |
| Competitor mentions | Competitive intelligence | `competitor_intelligence` |
| Talk-to-listen ratio | Agent effectiveness | `talk_listen_ratio` |
| Compliance score | Risk management | `compliance` |
| Key quotes | Better RAG retrieval | `key_quotes` |
| Q&A pairs | Training data | `qa_pairs` |
| Urgency classification | Prioritization | `urgency` |
| Hold time analysis | Quality monitoring | (from segments) |

**Run command:**
```bash
python /var/www/call-recording-system/layer5_advanced_metrics.py --limit 50
```

### 4. Vertex AI RAG Status
- **Corpus exists:** `projects/call-insights-rag-prod/locations/us-west1/ragCorpora/...`
- **Current files:** 1,424 indexed (old format)
- **Action needed:** Re-export with full metadata after processing complete

## RECOMMENDED WORKFLOW

### Step 1: Transcribe New Recordings (1,713 files)
```bash
cd /var/www/call-recording-system
source venv/bin/activate

# Run in batches of 100
nohup python process_queue_with_metadata.py --limit 100 --rate-limit 5 > logs/transcribe_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# Monitor progress
tail -f logs/transcribe_*.log
```

### Step 2: Complete Layer 3 (needs most work - 426/1475)
```bash
python layer3_resolution_enhanced.py --limit 100
```

### Step 3: Run Layer 5 on all transcripts
```bash
python layer5_advanced_metrics.py --limit 100
```

### Step 4: Check Progress
```bash
PGPASSWORD=call_insights_pass psql -U call_insights_user -d call_insights -h localhost -c "
SELECT 
    (SELECT COUNT(*) FROM transcripts WHERE transcript_text IS NOT NULL) as transcribed,
    (SELECT COUNT(*) FROM insights) as layer2,
    (SELECT COUNT(*) FROM call_resolutions) as layer3,
    (SELECT COUNT(*) FROM call_recommendations) as layer4,
    (SELECT COUNT(*) FROM call_advanced_metrics) as layer5;"
```

### Step 5: Export to Vertex AI RAG (after all processing)
```bash
# Will need to re-export with full metadata
python src/migration/export_to_vertex.py
python src/migration/import_to_rag.py
```

## KEY FILES

| File | Purpose |
|------|---------|
| `process_queue_with_metadata.py` | Salad transcription with RC metadata |
| `process_with_metadata.py` | Update existing transcripts with metadata |
| `layer3_resolution_enhanced.py` | Layer 3 resolution analysis |
| `layer5_advanced_metrics.py` | Layer 5 new metrics (8 types) |
| `src/migration/export_to_vertex.py` | Export to Vertex AI format |

## DATABASE INFO

- **Connection:** `postgresql://call_insights_user:call_insights_pass@localhost/call_insights`
- **Tables:** transcripts, insights, call_resolutions, call_recommendations, call_advanced_metrics, transcript_embeddings

## CREDENTIALS
- **PostgreSQL:** call_insights_user / call_insights_pass @ localhost
- **Sudo:** !@#Pokey123
- **Vertex AI project:** call-insights-rag-prod
- **GCS bucket:** call-insights-rag-data-west
- **OpenRouter API:** Uses `google/gemini-2.5-flash` model
