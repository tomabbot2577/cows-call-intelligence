# Database Upgrade Recommendations for AI/LLM Insights System

## Current State Analysis

### What We're Currently Using:
- **SQLite** for insights storage (limited capabilities)
- **JSON files** for transcripts and metadata (inefficient for querying)
- **File system** for transcript storage (no full-text search)
- **No transcript text in database** (missing crucial data)

### Critical Issues:
1. ❌ **No full-text search** across transcripts
2. ❌ **Limited concurrent access** with SQLite
3. ❌ **No vector embeddings support** for semantic search
4. ❌ **Poor scalability** for large-scale analytics
5. ❌ **No native JSON/JSONB support** for flexible schemas

## Recommended Open-Source Database Upgrades

### 🏆 **Option 1: PostgreSQL + pgvector (RECOMMENDED)**

**Why PostgreSQL is Perfect for AI/LLM Systems:**
- **Full-text search** with tsvector/tsquery
- **Vector similarity search** via pgvector extension
- **JSONB support** for flexible AI insights
- **Excellent concurrency** for multiple users
- **Battle-tested** in production environments
- **Free and open-source**

**Key Features for AI/LLM:**
```sql
-- Full-text search on transcripts
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Vector embeddings for semantic search
CREATE EXTENSION IF NOT EXISTS vector;

-- Example schema
CREATE TABLE transcripts (
    recording_id TEXT PRIMARY KEY,
    transcript_text TEXT,
    transcript_vector vector(1536),  -- For OpenAI embeddings
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Full-text search index
CREATE INDEX idx_transcript_fts ON transcripts
USING gin(to_tsvector('english', transcript_text));

-- Vector similarity index
CREATE INDEX idx_transcript_vector ON transcripts
USING ivfflat (transcript_vector vector_cosine_ops);
```

### 🔍 **Option 2: Elasticsearch (For Advanced Search)**

**Best for:**
- Complex search queries
- Real-time analytics
- Distributed deployments

**Pros:**
- Powerful full-text search
- Built-in analytics engine
- Scales horizontally

**Cons:**
- Higher resource usage
- More complex setup

### 💡 **Option 3: ChromaDB (AI-Native Database)**

**Purpose-built for AI:**
```python
import chromadb

# Initialize
client = chromadb.PersistentClient(path="/var/www/call-recording-system/data/chromadb")

# Create collection for transcripts
collection = client.create_collection(
    name="call_transcripts",
    metadata={"hnsw:space": "cosine"}
)

# Add transcripts with embeddings
collection.add(
    documents=[transcript_text],
    metadatas=[{"customer": customer_name, "date": call_date}],
    ids=[recording_id]
)

# Semantic search
results = collection.query(
    query_texts=["customer complaint about billing"],
    n_results=10
)
```

## Implementation Plan for PostgreSQL Upgrade

### Step 1: Install PostgreSQL with Extensions
```bash
# Install PostgreSQL 15+
sudo apt update
sudo apt install postgresql-15 postgresql-contrib-15

# Install pgvector
sudo apt install postgresql-15-pgvector

# Create database
sudo -u postgres createdb call_insights
```

### Step 2: Database Schema
```sql
-- Main transcripts table with full capabilities
CREATE TABLE transcripts (
    recording_id TEXT PRIMARY KEY,
    call_date DATE NOT NULL,
    transcript_text TEXT NOT NULL,
    word_count INTEGER,
    confidence_score REAL,
    duration_seconds INTEGER,

    -- Participants
    customer_name TEXT,
    customer_phone TEXT,
    employee_name TEXT,
    employee_id TEXT,

    -- AI Insights
    summary TEXT,
    sentiment TEXT,
    key_topics TEXT[],
    action_items JSONB,

    -- Embeddings for semantic search
    transcript_embedding vector(1536),

    -- Full metadata
    metadata JSONB,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_call_date ON transcripts(call_date);
CREATE INDEX idx_customer_name ON transcripts(customer_name);
CREATE INDEX idx_employee_name ON transcripts(employee_name);
CREATE INDEX idx_sentiment ON transcripts(sentiment);
CREATE INDEX idx_metadata ON transcripts USING gin(metadata);

-- Full-text search
CREATE INDEX idx_transcript_search ON transcripts
USING gin(to_tsvector('english', transcript_text || ' ' || COALESCE(summary, '')));
```

### Step 3: Migration Strategy

```python
# migrate_to_postgresql.py
import psycopg2
import sqlite3
import json
from pathlib import Path

# Connect to both databases
sqlite_conn = sqlite3.connect('/var/www/call-recording-system/data/insights/insights.db')
pg_conn = psycopg2.connect(
    dbname="call_insights",
    user="postgres",
    password="your_password",
    host="localhost"
)

# Migrate data
cursor_sqlite = sqlite_conn.cursor()
cursor_pg = pg_conn.cursor()

# 1. Migrate existing insights
cursor_sqlite.execute("SELECT * FROM insights")
for row in cursor_sqlite.fetchall():
    # Insert into PostgreSQL
    cursor_pg.execute("""
        INSERT INTO transcripts (recording_id, call_date, summary, sentiment, ...)
        VALUES (%s, %s, %s, %s, ...)
    """, row)

# 2. Load transcript files
transcript_dir = Path('/var/www/call-recording-system/data/transcriptions/json')
for json_file in transcript_dir.glob('**/*.json'):
    with open(json_file) as f:
        data = json.load(f)
    # Insert transcript data
    cursor_pg.execute("""
        INSERT INTO transcripts (recording_id, transcript_text, metadata)
        VALUES (%s, %s, %s)
        ON CONFLICT (recording_id) DO UPDATE
        SET transcript_text = EXCLUDED.transcript_text
    """, (data['recording_id'], data.get('transcript'), json.dumps(data)))

pg_conn.commit()
```

## Benefits of PostgreSQL for Your System

### 1. **Advanced Search Capabilities**
```sql
-- Find all calls mentioning billing issues for a specific customer
SELECT * FROM transcripts
WHERE customer_name ILIKE '%john smith%'
AND to_tsvector('english', transcript_text) @@ to_tsquery('billing & issue');

-- Date range analysis with aggregation
SELECT
    customer_name,
    COUNT(*) as call_count,
    AVG(duration_seconds) as avg_duration,
    array_agg(DISTINCT sentiment) as sentiments
FROM transcripts
WHERE call_date BETWEEN '2025-01-01' AND '2025-09-30'
GROUP BY customer_name
HAVING COUNT(*) > 3;
```

### 2. **Semantic Search with Embeddings**
```python
# Generate embedding for search query
query_embedding = openai.Embedding.create(
    input="customer complaint about service",
    model="text-embedding-ada-002"
)['data'][0]['embedding']

# Find similar calls
cursor.execute("""
    SELECT recording_id, transcript_text,
           1 - (transcript_embedding <=> %s::vector) as similarity
    FROM transcripts
    WHERE transcript_embedding IS NOT NULL
    ORDER BY transcript_embedding <=> %s::vector
    LIMIT 10
""", (query_embedding, query_embedding))
```

### 3. **Real-time Analytics**
```sql
-- Customer sentiment trends over time
SELECT
    date_trunc('week', call_date) as week,
    customer_name,
    COUNT(*) as calls,
    COUNT(*) FILTER (WHERE sentiment = 'positive') as positive,
    COUNT(*) FILTER (WHERE sentiment = 'negative') as negative
FROM transcripts
WHERE customer_name = 'ABC Corp'
GROUP BY week, customer_name
ORDER BY week DESC;
```

## Quick Start Commands

```bash
# 1. Install PostgreSQL
sudo apt install postgresql-15 postgresql-15-pgvector

# 2. Create database
sudo -u postgres psql -c "CREATE DATABASE call_insights;"

# 3. Run migration script
python /var/www/call-recording-system/migrate_to_postgresql.py

# 4. Update configuration
# Edit config to point to PostgreSQL instead of SQLite
```

## Performance Comparison

| Feature | SQLite | PostgreSQL | Improvement |
|---------|---------|------------|-------------|
| Concurrent Users | 1-5 | 100+ | 20x+ |
| Full-text Search | No | Yes | ∞ |
| Vector Search | No | Yes | ∞ |
| Query Speed (1M records) | 5-10s | 0.1-1s | 10-100x |
| JSONB Support | Limited | Native | ∞ |
| Scalability | Limited | Excellent | 100x+ |

## Conclusion

**PostgreSQL with pgvector** is the ideal upgrade for your AI/LLM call insights system because it provides:
1. ✅ Full-text search for transcripts
2. ✅ Vector embeddings for semantic search
3. ✅ JSONB for flexible AI insights
4. ✅ Excellent performance at scale
5. ✅ Open-source and free
6. ✅ Production-ready with great tooling

This upgrade will enable powerful features like:
- Semantic search across all calls
- Real-time customer/employee analytics
- Advanced date range analysis
- Similarity matching for patterns
- Fast aggregations for dashboards