#!/usr/bin/env python3
"""
Sentiment Analysis for Call Transcripts
Analyzes customer sentiment and updates database
"""

import os
import sys
import json
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from typing import Dict, Optional, List

# Import name extraction functions
sys.path.insert(0, '/var/www/call-recording-system')
try:
    from extract_names_advanced import load_employee_database, load_company_database, extract_names_with_ai
    NAME_EXTRACTION_AVAILABLE = True
except ImportError:
    print("⚠️ Name extraction not available")
    NAME_EXTRACTION_AVAILABLE = False

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': os.getenv('PG_PASSWORD', ''),
    'host': 'localhost',
    'port': 5432
}

# OpenRouter configuration
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', 'REDACTED_OPENROUTER_KEY')
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


def analyze_sentiment(transcript: str, customer_name: str = None, employee_name: str = None) -> Dict[str, any]:
    """
    Analyze sentiment and call quality from transcript
    """

    prompt = f"""Analyze this customer service call transcript and provide:

1. CUSTOMER SENTIMENT: (positive, negative, or neutral)
   - positive: Customer is satisfied, happy, thankful
   - negative: Customer is frustrated, angry, disappointed
   - neutral: Customer is calm, matter-of-fact, just seeking information

2. CALL QUALITY SCORE: (1-10)
   - Consider: Problem resolution, agent helpfulness, professionalism

3. CALL TYPE: Identify the type of call
   - technical_support
   - billing_inquiry
   - sales_inquiry
   - complaint
   - general_inquiry
   - follow_up

4. KEY TOPICS: List 3-5 main topics discussed

5. SUMMARY: One sentence describing what happened in the call

Customer: {customer_name or 'Unknown'}
Employee: {employee_name or 'Unknown'}

Return ONLY JSON:
{{
    "customer_sentiment": "positive/negative/neutral",
    "call_quality_score": 8.5,
    "call_type": "technical_support",
    "key_topics": ["topic1", "topic2", "topic3"],
    "summary": "One sentence summary",
    "issue_resolved": true/false,
    "follow_up_needed": true/false
}}

Transcript:
{transcript[:4000]}"""

    try:
        response = requests.post(
            OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek/deepseek-r1",  # Best reasoning model for sentiment analysis
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 300
            },
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']

            # Parse JSON from response
            try:
                import re
                json_match = re.search(r'\{.*?\}', content, re.DOTALL)
                if json_match:
                    analysis = json.loads(json_match.group())
                    logger.info(f"Sentiment analysis: {analysis}")
                    return analysis
            except Exception as e:
                logger.error(f"JSON parsing error: {e}")

        else:
            logger.error(f"AI analysis failed: {response.status_code}")

    except Exception as e:
        logger.error(f"Error calling AI: {e}")

    # Default response
    return {
        "customer_sentiment": "neutral",
        "call_quality_score": 5.0,
        "call_type": "general_inquiry",
        "key_topics": [],
        "summary": "Call transcript analyzed",
        "issue_resolved": False,
        "follow_up_needed": False
    }


def update_sentiment_in_db(recording_id: str, analysis: Dict[str, any]):
    """Update sentiment and analysis in database"""

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        # Update insights table
        cursor.execute("""
            UPDATE insights
            SET
                customer_sentiment = %s,
                call_quality_score = %s,
                call_type = %s,
                key_topics = %s,
                summary = %s
            WHERE recording_id = %s
        """, (
            analysis.get('customer_sentiment', 'neutral'),
            analysis.get('call_quality_score', 5.0),
            analysis.get('call_type', 'general_inquiry'),
            analysis.get('key_topics', []),
            analysis.get('summary', ''),
            recording_id
        ))

        # If insights record doesn't exist, insert it
        if cursor.rowcount == 0:
            cursor.execute("""
                INSERT INTO insights (
                    recording_id,
                    customer_sentiment,
                    call_quality_score,
                    call_type,
                    key_topics,
                    summary
                ) VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                recording_id,
                analysis.get('customer_sentiment', 'neutral'),
                analysis.get('call_quality_score', 5.0),
                analysis.get('call_type', 'general_inquiry'),
                analysis.get('key_topics', []),
                analysis.get('summary', '')
            ))

        conn.commit()
        logger.info(f"✅ Updated sentiment for {recording_id}: {analysis['customer_sentiment']}")

    except Exception as e:
        logger.error(f"Database update failed: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


def process_single_recording(recording_id: str):
    """Process sentiment for a single recording with name extraction"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Get transcript
        cursor.execute("""
            SELECT recording_id, transcript_text, customer_name, employee_name
            FROM transcripts
            WHERE recording_id = %s
        """, (recording_id,))

        result = cursor.fetchone()

        if result and result['transcript_text']:
            logger.info(f"\n🎭 Analyzing sentiment for {recording_id}")

            # Extract names first if needed and available
            customer_name = result.get('customer_name', 'Unknown')
            employee_name = result.get('employee_name', 'Unknown')

            if NAME_EXTRACTION_AVAILABLE and (not customer_name or customer_name == 'Unknown' or not employee_name or employee_name == 'Unknown'):
                logger.info(f"  🔍 Extracting names first...")
                try:
                    employee_list = load_employee_database()
                    company_list = load_company_database()
                    names = extract_names_with_ai(result['transcript_text'], employee_list, company_list)

                    if names:
                        customer_name = names.get('customer_name', customer_name)
                        employee_name = names.get('employee_name', employee_name)

                        # Update names in database
                        cursor.execute("""
                            UPDATE transcripts
                            SET customer_name = %s, employee_name = %s, customer_company = %s
                            WHERE recording_id = %s
                        """, (customer_name, employee_name, names.get('customer_company', ''), recording_id))
                        conn.commit()

                        logger.info(f"  ✅ Names extracted: Employee: {employee_name}, Customer: {customer_name}")
                except Exception as e:
                    logger.warning(f"  ⚠️ Name extraction failed: {e}")

            # Analyze sentiment with proper names
            analysis = analyze_sentiment(
                result['transcript_text'],
                customer_name,
                employee_name
            )

            # Update database
            update_sentiment_in_db(recording_id, analysis)

            return analysis
        else:
            logger.warning(f"No transcript found for {recording_id}")

    except Exception as e:
        logger.error(f"Error processing {recording_id}: {e}")
    finally:
        cursor.close()
        conn.close()

    return None


def process_all_unknown_sentiments(limit: int = 50):
    """Process all transcripts with unknown sentiment"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Find transcripts without sentiment analysis
        cursor.execute("""
            SELECT t.recording_id, t.transcript_text, t.customer_name, t.employee_name
            FROM transcripts t
            LEFT JOIN insights i ON t.recording_id = i.recording_id
            WHERE t.transcript_text IS NOT NULL
            AND LENGTH(t.transcript_text) > 100
            AND (i.customer_sentiment IS NULL OR i.customer_sentiment = 'Unknown')
            ORDER BY t.call_date DESC
            LIMIT %s
        """, (limit,))

        results = cursor.fetchall()
        logger.info(f"📊 Found {len(results)} transcripts needing sentiment analysis")

        success_count = 0
        for i, result in enumerate(results, 1):
            logger.info(f"\n--- Analyzing {i}/{len(results)} ---")

            # Analyze sentiment
            analysis = analyze_sentiment(
                result['transcript_text'],
                result.get('customer_name'),
                result.get('employee_name')
            )

            # Update database
            update_sentiment_in_db(result['recording_id'], analysis)

            if analysis['customer_sentiment'] != 'neutral' or analysis['call_quality_score'] > 5:
                success_count += 1

        logger.info(f"\n✅ Analyzed {len(results)} transcripts")
        logger.info(f"📊 Analysis complete: {success_count} with clear sentiment")

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()


def main():
    """Main function"""

    if len(sys.argv) > 1:
        if sys.argv[1] == '--all':
            # Process all unknown sentiments
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 50
            logger.info(f"🎭 Analyzing sentiment for {limit} transcripts...")
            process_all_unknown_sentiments(limit=limit)
        else:
            # Process specific recording
            recording_id = sys.argv[1]
            logger.info(f"Analyzing sentiment for: {recording_id}")
            result = process_single_recording(recording_id)

            if result:
                print("\n✅ Sentiment Analysis Complete:")
                print(f"  Sentiment: {result['customer_sentiment']}")
                print(f"  Quality Score: {result['call_quality_score']}/10")
                print(f"  Call Type: {result['call_type']}")
                print(f"  Summary: {result['summary']}")
    else:
        # Process all unknown sentiments
        logger.info("🎭 Analyzing sentiment for all transcripts...")
        process_all_unknown_sentiments(limit=30)

        print("\n✅ Batch sentiment analysis complete!")


if __name__ == "__main__":
    main()