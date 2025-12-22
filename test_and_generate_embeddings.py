#!/usr/bin/env python3
"""
Test and generate embeddings for completed transcripts
"""

import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from datetime import datetime
import json

sys.path.insert(0, '/var/www/call-recording-system')
from dotenv import load_dotenv
load_dotenv('/var/www/call-recording-system/.env')

# Database configuration
DB_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': os.getenv('PG_PASSWORD', ''),
    'host': 'localhost',
    'port': 5432
}

# OpenAI configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

def get_connection():
    """Get database connection"""
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

def generate_embedding(text):
    """Generate embedding using OpenAI API directly"""
    try:
        headers = {
            'Authorization': f'Bearer {OPENAI_API_KEY}',
            'Content-Type': 'application/json'
        }

        data = {
            'input': text,
            'model': 'text-embedding-ada-002'
        }

        response = requests.post(
            'https://api.openai.com/v1/embeddings',
            headers=headers,
            json=data
        )

        if response.status_code == 200:
            return response.json()['data'][0]['embedding']
        else:
            print(f"API error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return None

def process_transcripts():
    """Process transcripts and generate embeddings"""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Get transcripts with content but no embeddings
        cursor.execute("""
            SELECT t.recording_id, t.transcript_text, t.customer_name, t.employee_name,
                   t.call_date, t.duration_seconds, t.word_count, i.customer_sentiment,
                   i.call_quality_score, i.customer_satisfaction_score, i.call_type,
                   i.issue_category, i.summary, i.key_topics
            FROM transcripts t
            LEFT JOIN insights i ON t.recording_id = i.recording_id
            WHERE t.transcript_text IS NOT NULL
                AND LENGTH(t.transcript_text) > 100
                AND NOT EXISTS (
                    SELECT 1 FROM transcript_embeddings te
                    WHERE te.recording_id = t.recording_id
                )
            LIMIT 100
        """)

        records = cursor.fetchall()
        print(f"\n📊 Found {len(records)} transcripts to process\n")

        success_count = 0

        for record in records:
            recording_id = record['recording_id']
            transcript_text = record['transcript_text']

            # Truncate text if too long (max 8000 tokens ~ 32000 chars)
            if len(transcript_text) > 30000:
                transcript_text = transcript_text[:30000]

            print(f"Processing {recording_id}...")

            # Generate embedding
            embedding = generate_embedding(transcript_text)

            if embedding:
                # Convert embedding to PostgreSQL vector format
                # Note: text-embedding-ada-002 produces 1536 dimensions, not 3072
                embedding_str = '[' + ','.join(map(str, embedding)) + ']'

                # Store in database
                cursor.execute("""
                    INSERT INTO transcript_embeddings (
                        recording_id, embedding, transcript_text, customer_name,
                        employee_name, call_date, duration_seconds, word_count,
                        customer_sentiment, call_quality_score, customer_satisfaction_score,
                        call_type, issue_category, summary, key_topics,
                        embedding_model, created_at
                    ) VALUES (
                        %s, %s::vector(1536), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                    )
                    ON CONFLICT (recording_id) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        updated_at = NOW()
                """, (
                    recording_id, embedding_str, transcript_text,
                    record['customer_name'], record['employee_name'],
                    record['call_date'], record['duration_seconds'],
                    record['word_count'], record['customer_sentiment'],
                    record['call_quality_score'], record['customer_satisfaction_score'],
                    record['call_type'], record['issue_category'],
                    record['summary'], record['key_topics'] or [],
                    'text-embedding-ada-002'
                ))

                conn.commit()
                success_count += 1
                print(f"  ✅ Embedding generated and stored")
            else:
                print(f"  ❌ Failed to generate embedding")

        print(f"\n✅ Successfully processed {success_count}/{len(records)} transcripts")

        # Show current statistics
        cursor.execute("SELECT COUNT(*) as total FROM transcript_embeddings")
        total = cursor.fetchone()['total']
        print(f"📊 Total embeddings in database: {total}\n")

    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def test_semantic_search(query="customer complaint about service"):
    """Test semantic search functionality"""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        print(f"\n🔍 Testing semantic search with query: '{query}'\n")

        # Generate embedding for query
        query_embedding = generate_embedding(query)

        if not query_embedding:
            print("Failed to generate query embedding")
            return

        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'

        # Perform semantic search using cosine similarity
        cursor.execute("""
            SELECT recording_id, customer_name, employee_name,
                   call_date, customer_sentiment, summary,
                   1 - (embedding <=> %s::vector(1536)) as similarity
            FROM transcript_embeddings
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector(1536)
            LIMIT 5
        """, (embedding_str, embedding_str))

        results = cursor.fetchall()

        if results:
            print("Top 5 most relevant results:\n")
            for i, result in enumerate(results, 1):
                print(f"{i}. Recording: {result['recording_id']}")
                print(f"   Similarity: {result['similarity']:.3f}")
                print(f"   Customer: {result['customer_name'] or 'Unknown'}")
                print(f"   Sentiment: {result['customer_sentiment'] or 'N/A'}")
                if result['summary']:
                    print(f"   Summary: {result['summary'][:200]}...")
                print()
        else:
            print("No results found")

    except Exception as e:
        print(f"Search error: {e}")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    print("=" * 60)
    print("EMBEDDING GENERATION AND TESTING")
    print("=" * 60)

    # First, fix the embedding column size if needed
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Drop and recreate with correct dimensions for ada-002
        cursor.execute("ALTER TABLE transcript_embeddings DROP COLUMN IF EXISTS embedding")
        cursor.execute("ALTER TABLE transcript_embeddings ADD COLUMN embedding vector(1536)")
        conn.commit()
        print("✅ Updated embedding column to 1536 dimensions\n")
    except Exception as e:
        print(f"Note: {e}\n")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

    # Process transcripts
    process_transcripts()

    # Test semantic search
    test_semantic_search("angry customer billing issue")
    test_semantic_search("technical support internet connection")

    print("=" * 60)
    print("✅ TESTING COMPLETE")
    print("=" * 60)