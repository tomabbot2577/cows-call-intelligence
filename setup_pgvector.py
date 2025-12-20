#!/usr/bin/env python3
"""
Setup pgvector for semantic search with comprehensive metadata
Stores embeddings along with all call metadata for intelligent searching
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import sys

print("=" * 80)
print("SETTING UP PGVECTOR WITH COMPREHENSIVE METADATA")
print("=" * 80)

# Database configuration
PG_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': 'call_insights_pass',
    'host': 'localhost',
    'port': 5432
}

try:
    # Connect to PostgreSQL
    conn = psycopg2.connect(**PG_CONFIG)
    cursor = conn.cursor()

    print("\n1. ENABLING PGVECTOR EXTENSION")
    print("-" * 40)

    # Enable pgvector extension
    cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
    print("  ✅ pgvector extension enabled")

    # Create embeddings table with comprehensive metadata
    print("\n2. CREATING EMBEDDINGS TABLE WITH METADATA")
    print("-" * 40)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transcript_embeddings (
        id SERIAL PRIMARY KEY,
        recording_id TEXT NOT NULL UNIQUE,

        -- Embedding vector (1536 dimensions for OpenAI ada-002)
        embedding vector(1536),

        -- Full transcript text
        transcript_text TEXT,
        chunk_text TEXT,  -- For chunked embeddings
        chunk_index INTEGER DEFAULT 0,

        -- Call metadata
        customer_name TEXT,
        employee_name TEXT,
        call_date TIMESTAMPTZ,
        duration_seconds INTEGER,
        word_count INTEGER,

        -- AI Insights
        customer_sentiment TEXT,
        call_quality_score REAL,
        customer_satisfaction_score REAL,
        call_type TEXT,
        issue_category TEXT,
        summary TEXT,
        key_topics TEXT[],

        -- Additional metadata (JSONB for flexibility)
        metadata JSONB DEFAULT '{}',

        -- Processing metadata
        embedding_model TEXT DEFAULT 'openai/text-embedding-ada-002',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),

        -- Indexes for searching
        FOREIGN KEY (recording_id) REFERENCES transcripts(recording_id) ON DELETE CASCADE
    )
    """)
    print("  ✅ Created transcript_embeddings table")

    # Create indexes for performance
    print("\n3. CREATING INDEXES")
    print("-" * 40)

    # Vector similarity index using IVFFlat
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_embedding_vector
    ON transcript_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100)
    """)
    print("  ✅ Created IVFFlat index for vector similarity")

    # B-tree indexes for metadata filtering
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_embedding_customer
    ON transcript_embeddings(customer_name)
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_embedding_employee
    ON transcript_embeddings(employee_name)
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_embedding_date
    ON transcript_embeddings(call_date)
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_embedding_sentiment
    ON transcript_embeddings(customer_sentiment)
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_embedding_call_type
    ON transcript_embeddings(call_type)
    """)

    # GIN index for JSONB metadata
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_embedding_metadata
    ON transcript_embeddings USING GIN (metadata)
    """)

    print("  ✅ Created metadata indexes")

    # Create semantic search function
    print("\n4. CREATING SEARCH FUNCTIONS")
    print("-" * 40)

    cursor.execute("""
    CREATE OR REPLACE FUNCTION semantic_search(
        query_embedding vector(1536),
        match_count INTEGER DEFAULT 10,
        filter_employee TEXT DEFAULT NULL,
        filter_customer TEXT DEFAULT NULL,
        filter_sentiment TEXT DEFAULT NULL,
        filter_date_from DATE DEFAULT NULL,
        filter_date_to DATE DEFAULT NULL,
        min_quality_score REAL DEFAULT NULL
    )
    RETURNS TABLE (
        recording_id TEXT,
        similarity FLOAT,
        transcript_text TEXT,
        customer_name TEXT,
        employee_name TEXT,
        call_date TIMESTAMPTZ,
        customer_sentiment TEXT,
        call_quality_score REAL,
        summary TEXT,
        metadata JSONB
    )
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RETURN QUERY
        SELECT
            e.recording_id,
            1 - (e.embedding <=> query_embedding) as similarity,
            e.transcript_text,
            e.customer_name,
            e.employee_name,
            e.call_date,
            e.customer_sentiment,
            e.call_quality_score,
            e.summary,
            e.metadata
        FROM transcript_embeddings e
        WHERE
            (filter_employee IS NULL OR e.employee_name ILIKE '%' || filter_employee || '%')
            AND (filter_customer IS NULL OR e.customer_name ILIKE '%' || filter_customer || '%')
            AND (filter_sentiment IS NULL OR e.customer_sentiment = filter_sentiment)
            AND (filter_date_from IS NULL OR e.call_date >= filter_date_from)
            AND (filter_date_to IS NULL OR e.call_date <= filter_date_to)
            AND (min_quality_score IS NULL OR e.call_quality_score >= min_quality_score)
        ORDER BY e.embedding <=> query_embedding
        LIMIT match_count;
    END;
    $$;
    """)
    print("  ✅ Created semantic_search function")

    # Create aggregation function for employee/customer analysis
    cursor.execute("""
    CREATE OR REPLACE FUNCTION aggregate_transcript_analysis(
        target_type TEXT,  -- 'employee' or 'customer'
        target_name TEXT,
        date_from DATE DEFAULT NULL,
        date_to DATE DEFAULT NULL
    )
    RETURNS TABLE (
        total_calls INTEGER,
        avg_quality_score REAL,
        avg_satisfaction_score REAL,
        sentiment_distribution JSONB,
        common_topics TEXT[],
        common_issues TEXT[],
        metadata_summary JSONB
    )
    LANGUAGE plpgsql
    AS $$
    BEGIN
        IF target_type = 'employee' THEN
            RETURN QUERY
            SELECT
                COUNT(*)::INTEGER as total_calls,
                AVG(call_quality_score) as avg_quality_score,
                AVG(customer_satisfaction_score) as avg_satisfaction_score,
                jsonb_object_agg(customer_sentiment, sentiment_count) as sentiment_distribution,
                ARRAY(
                    SELECT UNNEST(key_topics)
                    FROM transcript_embeddings
                    WHERE employee_name ILIKE '%' || target_name || '%'
                    GROUP BY UNNEST(key_topics)
                    ORDER BY COUNT(*) DESC
                    LIMIT 10
                ) as common_topics,
                ARRAY(
                    SELECT DISTINCT issue_category
                    FROM transcript_embeddings
                    WHERE employee_name ILIKE '%' || target_name || '%'
                        AND issue_category IS NOT NULL
                    LIMIT 10
                ) as common_issues,
                jsonb_build_object(
                    'date_range', jsonb_build_object(
                        'from', MIN(call_date),
                        'to', MAX(call_date)
                    ),
                    'total_duration_minutes', SUM(duration_seconds) / 60,
                    'total_words', SUM(word_count)
                ) as metadata_summary
            FROM (
                SELECT *,
                       COUNT(*) OVER (PARTITION BY customer_sentiment) as sentiment_count
                FROM transcript_embeddings
                WHERE employee_name ILIKE '%' || target_name || '%'
                    AND (date_from IS NULL OR call_date >= date_from)
                    AND (date_to IS NULL OR call_date <= date_to)
            ) t
            GROUP BY customer_sentiment, sentiment_count;

        ELSIF target_type = 'customer' THEN
            RETURN QUERY
            SELECT
                COUNT(*)::INTEGER as total_calls,
                AVG(call_quality_score) as avg_quality_score,
                AVG(customer_satisfaction_score) as avg_satisfaction_score,
                jsonb_object_agg(customer_sentiment, sentiment_count) as sentiment_distribution,
                ARRAY(
                    SELECT UNNEST(key_topics)
                    FROM transcript_embeddings
                    WHERE customer_name ILIKE '%' || target_name || '%'
                    GROUP BY UNNEST(key_topics)
                    ORDER BY COUNT(*) DESC
                    LIMIT 10
                ) as common_topics,
                ARRAY(
                    SELECT DISTINCT issue_category
                    FROM transcript_embeddings
                    WHERE customer_name ILIKE '%' || target_name || '%'
                        AND issue_category IS NOT NULL
                    LIMIT 10
                ) as common_issues,
                jsonb_build_object(
                    'date_range', jsonb_build_object(
                        'from', MIN(call_date),
                        'to', MAX(call_date)
                    ),
                    'total_duration_minutes', SUM(duration_seconds) / 60,
                    'total_words', SUM(word_count),
                    'employees_contacted', ARRAY(
                        SELECT DISTINCT employee_name
                        FROM transcript_embeddings
                        WHERE customer_name ILIKE '%' || target_name || '%'
                    )
                ) as metadata_summary
            FROM (
                SELECT *,
                       COUNT(*) OVER (PARTITION BY customer_sentiment) as sentiment_count
                FROM transcript_embeddings
                WHERE customer_name ILIKE '%' || target_name || '%'
                    AND (date_from IS NULL OR call_date >= date_from)
                    AND (date_to IS NULL OR call_date <= date_to)
            ) t
            GROUP BY customer_sentiment, sentiment_count;
        END IF;
    END;
    $$;
    """)
    print("  ✅ Created aggregate_transcript_analysis function")

    # Create example queries view
    print("\n5. CREATING EXAMPLE QUERIES")
    print("-" * 40)

    cursor.execute("""
    CREATE OR REPLACE VIEW semantic_search_examples AS
    SELECT
        'Find frustrated customers about billing' as query_description,
        'customer frustration with billing issues, overcharges, payment problems' as search_text,
        'filter_sentiment => negative' as filters
    UNION ALL
    SELECT
        'High-quality support calls' as query_description,
        'excellent customer service, problem resolved, satisfied customer' as search_text,
        'min_quality_score => 8.0' as filters
    UNION ALL
    SELECT
        'Technical issues requiring escalation' as query_description,
        'technical problem, system error, needs escalation, urgent issue' as search_text,
        'filter_sentiment => negative' as filters
    UNION ALL
    SELECT
        'Sales opportunities' as query_description,
        'interested in upgrading, wants more features, asking about pricing' as search_text,
        'call_type => sales' as filters
    UNION ALL
    SELECT
        'Employee performance review' as query_description,
        'agent performance, customer interaction quality, resolution rate' as search_text,
        'filter_employee => [employee_name]' as filters
    UNION ALL
    SELECT
        'Customer journey analysis' as query_description,
        'customer experience over time, recurring issues, satisfaction trend' as search_text,
        'filter_customer => [customer_name]' as filters
    """)
    print("  ✅ Created example queries view")

    # Commit changes
    conn.commit()

    # Check current status
    print("\n6. CHECKING PGVECTOR STATUS")
    print("-" * 40)

    cursor.execute("SELECT version()")
    pg_version = cursor.fetchone()[0]
    print(f"  PostgreSQL: {pg_version.split(',')[0]}")

    cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    vector_version = cursor.fetchone()
    if vector_version:
        print(f"  pgvector: v{vector_version[0]}")

    cursor.execute("""
        SELECT COUNT(*) FROM transcript_embeddings
    """)
    embedding_count = cursor.fetchone()[0]
    print(f"  Embeddings stored: {embedding_count}")

    print("\n" + "=" * 80)
    print("✅ PGVECTOR SETUP COMPLETE!")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Install Python packages: pip install openai pgvector psycopg2-binary")
    print("2. Generate embeddings: python generate_embeddings.py")
    print("3. Access semantic search in dashboard")
    print("=" * 80)

except Exception as e:
    print(f"\n❌ Error: {e}")
    sys.exit(1)
finally:
    if 'cursor' in locals():
        cursor.close()
    if 'conn' in locals():
        conn.close()