#!/usr/bin/env python3
"""
Master Script: Process All 5 AI Layers for Call Transcripts
============================================================
Does NOT export to Vertex AI - that's done separately after all layers complete.

Usage:
    python process_all_layers_master.py --status           # Show status only
    python process_all_layers_master.py --all --limit 100  # Process all layers
    python process_all_layers_master.py --layer 3 --limit 50  # Process specific layer
    python process_all_layers_master.py --continuous       # Run until all complete

Models Used:
    Primary:   google/gemma-3-12b-it:free (FREE)
    Secondary: meta-llama/llama-3.1-8b-instruct ($0.02/1M)
"""

import os
import sys
import argparse
import logging
import time
import json
from datetime import datetime

sys.path.insert(0, '/var/www/call-recording-system')

import psycopg2
from psycopg2.extras import RealDictCursor, Json
import requests

# Set up logging
log_dir = '/var/www/call-recording-system/logs'
os.makedirs(log_dir, exist_ok=True)
log_file = f'{log_dir}/master_processing_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file)
    ]
)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': 'REDACTED_DB_PASSWORD',
    'host': 'localhost',
    'port': 5432
}

# Model configuration - Using OpenRouter (paid Gemini for speed)
PRIMARY_MODEL = 'google/gemini-2.0-flash-001'
SECONDARY_MODEL = 'google/gemini-2.0-flash-001'
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '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')
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


def call_llm(prompt: str, max_tokens: int = 500, model: str = None) -> dict:
    """Call OpenRouter LLM with fallback to secondary model"""
    model = model or PRIMARY_MODEL

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.1
            },
            timeout=60
        )

        # Rate limit handling - wait and retry on 429
        if response.status_code == 429:
            logger.warning(f"Rate limited on {model}, waiting 5s...")
            time.sleep(5)
            return call_llm(prompt, max_tokens, model)  # Retry same model

        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content']
            return {"success": True, "content": content}
        else:
            # Try secondary model
            if model == PRIMARY_MODEL:
                logger.warning(f"Primary model failed ({response.status_code}), trying secondary...")
                return call_llm(prompt, max_tokens, SECONDARY_MODEL)
            return {"success": False, "error": f"HTTP {response.status_code}"}

    except Exception as e:
        if model == PRIMARY_MODEL:
            logger.warning(f"Primary model error: {e}, trying secondary...")
            return call_llm(prompt, max_tokens, SECONDARY_MODEL)
        return {"success": False, "error": str(e)}


def parse_json_response(content: str) -> dict:
    """Parse JSON from LLM response"""
    try:
        # Remove markdown code blocks
        if '```json' in content:
            content = content.split('```json')[1].split('```')[0]
        elif '```' in content:
            content = content.split('```')[1].split('```')[0]

        # Find JSON object
        start = content.find('{')
        end = content.rfind('}') + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
    except:
        pass
    return {}


def get_layer_status() -> dict:
    """Get current status of all layers"""
    conn = get_db_connection()
    cur = conn.cursor()

    status = {}

    # Total transcribed
    cur.execute("SELECT COUNT(*) FROM transcripts WHERE transcript_text IS NOT NULL AND LENGTH(transcript_text) > 100")
    status['total'] = list(cur.fetchone().values())[0]

    # Layer 1 - Names (both must be valid)
    cur.execute("""
        SELECT COUNT(*) FROM transcripts
        WHERE transcript_text IS NOT NULL AND LENGTH(transcript_text) > 100
        AND (customer_name IS NULL OR customer_name = '' OR customer_name = 'Unknown')
        AND (employee_name IS NULL OR employee_name = '' OR employee_name = 'Unknown')
    """)
    status['layer1_pending'] = list(cur.fetchone().values())[0]

    # Layer 2 - Sentiment
    cur.execute("""
        SELECT COUNT(*) FROM transcripts t
        WHERE t.transcript_text IS NOT NULL AND LENGTH(t.transcript_text) > 100
        AND NOT EXISTS (SELECT 1 FROM insights i WHERE i.recording_id = t.recording_id)
    """)
    status['layer2_pending'] = list(cur.fetchone().values())[0]

    # Layer 3 - Resolution
    cur.execute("""
        SELECT COUNT(*) FROM transcripts t
        WHERE t.transcript_text IS NOT NULL AND LENGTH(t.transcript_text) > 100
        AND NOT EXISTS (SELECT 1 FROM call_resolutions cr WHERE cr.recording_id = t.recording_id)
    """)
    status['layer3_pending'] = list(cur.fetchone().values())[0]

    # Layer 4 - Recommendations
    cur.execute("""
        SELECT COUNT(*) FROM transcripts t
        WHERE t.transcript_text IS NOT NULL AND LENGTH(t.transcript_text) > 100
        AND NOT EXISTS (SELECT 1 FROM call_recommendations r WHERE r.recording_id = t.recording_id)
    """)
    status['layer4_pending'] = list(cur.fetchone().values())[0]

    # Layer 5 - Advanced Metrics
    cur.execute("""
        SELECT COUNT(*) FROM transcripts t
        WHERE t.transcript_text IS NOT NULL AND LENGTH(t.transcript_text) > 100
        AND NOT EXISTS (SELECT 1 FROM call_advanced_metrics m WHERE m.recording_id = t.recording_id)
    """)
    status['layer5_pending'] = list(cur.fetchone().values())[0]

    conn.close()
    return status


def print_status():
    """Print formatted status"""
    status = get_layer_status()
    total = status['total']

    print("\n" + "=" * 70)
    print("AI LAYER PROCESSING STATUS")
    print("=" * 70)
    print(f"Total Transcribed: {total:,}")
    print("-" * 70)
    print(f"{'Layer':<35} {'Pending':>12} {'Complete':>12} {'%':>8}")
    print("-" * 70)

    layers = [
        ('Layer 1 - Name Extraction', 'layer1_pending'),
        ('Layer 2 - Sentiment Analysis', 'layer2_pending'),
        ('Layer 3 - Resolution & Closure', 'layer3_pending'),
        ('Layer 4 - Recommendations', 'layer4_pending'),
        ('Layer 5 - Advanced Metrics', 'layer5_pending'),
    ]

    all_complete = True
    total_pending = 0
    for name, key in layers:
        pending = status[key]
        complete = total - pending
        pct = (complete / total * 100) if total > 0 else 0
        if pending > 0:
            all_complete = False
        total_pending += pending
        print(f"{name:<35} {pending:>12,} {complete:>12,} {pct:>7.1f}%")

    print("=" * 70)
    if all_complete:
        print("✅ ALL LAYERS COMPLETE - Ready for Vertex AI export!")
    else:
        print(f"⏳ Total pending across all layers: {total_pending:,}")
    print("=" * 70 + "\n")

    return status


# ============================================================
# LAYER 1: Name Extraction
# ============================================================
def process_layer1(limit: int = 50) -> int:
    """Extract customer and employee names"""
    logger.info(f"Layer 1: Processing up to {limit} records...")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT recording_id, transcript_text
        FROM transcripts
        WHERE transcript_text IS NOT NULL AND LENGTH(transcript_text) > 100
        AND (customer_name IS NULL OR customer_name = '' OR customer_name = 'Unknown')
        AND (employee_name IS NULL OR employee_name = '' OR employee_name = 'Unknown')
        LIMIT %s
    """, (limit,))

    records = cur.fetchall()
    logger.info(f"Layer 1: Found {len(records)} records to process")

    success = 0
    for i, rec in enumerate(records, 1):
        try:
            prompt = f"""Extract names from this call transcript. Return ONLY JSON:
{{"employee_name": "name or Unknown", "customer_name": "name or Unknown", "customer_company": "company or Unknown"}}

Transcript (first 2500 chars):
{rec['transcript_text'][:2500]}"""

            result = call_llm(prompt, max_tokens=150)
            if result['success']:
                data = parse_json_response(result['content'])
                customer = data.get('customer_name', 'Unknown')
                employee = data.get('employee_name', 'Unknown')
                company = data.get('customer_company', 'Unknown')

                if customer and customer != 'Unknown' or employee and employee != 'Unknown':
                    cur.execute("""
                        UPDATE transcripts
                        SET customer_name = %s, employee_name = %s, customer_company = %s
                        WHERE recording_id = %s
                    """, (customer, employee, company, rec['recording_id']))
                    conn.commit()
                    success += 1
                    logger.info(f"  [{i}/{len(records)}] {rec['recording_id']}: {customer} / {employee}")

            time.sleep(1)
        except Exception as e:
            logger.error(f"  [{i}] Error: {e}")
            conn.rollback()

    conn.close()
    logger.info(f"Layer 1: Completed {success}/{len(records)}")
    return success


# ============================================================
# LAYER 2: Sentiment Analysis
# ============================================================
def process_layer2(limit: int = 50) -> int:
    """Analyze sentiment and call quality"""
    logger.info(f"Layer 2: Processing up to {limit} records...")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT t.recording_id, t.transcript_text, t.customer_name, t.employee_name
        FROM transcripts t
        WHERE t.transcript_text IS NOT NULL AND LENGTH(t.transcript_text) > 100
        AND NOT EXISTS (SELECT 1 FROM insights i WHERE i.recording_id = t.recording_id)
        LIMIT %s
    """, (limit,))

    records = cur.fetchall()
    logger.info(f"Layer 2: Found {len(records)} records to process")

    success = 0
    for i, rec in enumerate(records, 1):
        try:
            prompt = f"""Analyze this customer service call. Return ONLY JSON:
{{
    "customer_sentiment": "positive/negative/neutral",
    "call_quality_score": 1-10,
    "call_type": "support/sales/billing/complaint/general",
    "summary": "2 sentence summary",
    "key_topics": ["topic1", "topic2", "topic3"],
    "first_call_resolution": true/false,
    "follow_up_needed": true/false
}}

Customer: {rec.get('customer_name', 'Unknown')}
Employee: {rec.get('employee_name', 'Unknown')}

Transcript:
{rec['transcript_text'][:4000]}"""

            result = call_llm(prompt, max_tokens=400)
            if result['success']:
                data = parse_json_response(result['content'])
                if data:
                    cur.execute("""
                        INSERT INTO insights (recording_id, customer_sentiment, call_quality_score,
                            call_type, summary, key_topics, first_call_resolution, follow_up_needed)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (recording_id) DO UPDATE SET
                            customer_sentiment = EXCLUDED.customer_sentiment,
                            call_quality_score = EXCLUDED.call_quality_score,
                            call_type = EXCLUDED.call_type,
                            summary = EXCLUDED.summary,
                            key_topics = EXCLUDED.key_topics,
                            first_call_resolution = EXCLUDED.first_call_resolution,
                            follow_up_needed = EXCLUDED.follow_up_needed
                    """, (
                        rec['recording_id'],
                        data.get('customer_sentiment', 'neutral'),
                        data.get('call_quality_score', 5),
                        data.get('call_type', 'general'),
                        data.get('summary', ''),
                        data.get('key_topics', []),
                        data.get('first_call_resolution', False),
                        data.get('follow_up_needed', False)
                    ))
                    conn.commit()
                    success += 1
                    logger.info(f"  [{i}/{len(records)}] {rec['recording_id']}: {data.get('customer_sentiment')} / {data.get('call_quality_score')}")

            time.sleep(1)
        except Exception as e:
            logger.error(f"  [{i}] Error: {e}")
            conn.rollback()

    conn.close()
    logger.info(f"Layer 2: Completed {success}/{len(records)}")
    return success


# ============================================================
# LAYER 3: Resolution Analysis
# ============================================================
def process_layer3(limit: int = 50) -> int:
    """Analyze call resolution and closure"""
    logger.info(f"Layer 3: Processing up to {limit} records...")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT t.recording_id, t.transcript_text, t.customer_name, t.employee_name
        FROM transcripts t
        WHERE t.transcript_text IS NOT NULL AND LENGTH(t.transcript_text) > 100
        AND NOT EXISTS (SELECT 1 FROM call_resolutions cr WHERE cr.recording_id = t.recording_id)
        LIMIT %s
    """, (limit,))

    records = cur.fetchall()
    logger.info(f"Layer 3: Found {len(records)} records to process")

    success = 0
    for i, rec in enumerate(records, 1):
        try:
            prompt = f"""Analyze call resolution quality. Return ONLY JSON:
{{
    "resolution_status": "resolved/partial/unresolved",
    "first_contact_resolution": true/false,
    "closure_score": 1-10,
    "empathy_score": 1-10,
    "solution_summarized": true/false,
    "understanding_confirmed": true/false,
    "churn_risk": "none/low/medium/high",
    "problem_complexity": "simple/medium/complex"
}}

Transcript:
{rec['transcript_text'][:4000]}"""

            result = call_llm(prompt, max_tokens=350)
            if result['success']:
                data = parse_json_response(result['content'])
                if data:
                    cur.execute("""
                        INSERT INTO call_resolutions (recording_id, resolution_status, first_contact_resolution,
                            closure_score, empathy_score, solution_summarized, understanding_confirmed,
                            churn_risk, problem_complexity)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (recording_id) DO UPDATE SET
                            resolution_status = EXCLUDED.resolution_status,
                            first_contact_resolution = EXCLUDED.first_contact_resolution,
                            closure_score = EXCLUDED.closure_score,
                            empathy_score = EXCLUDED.empathy_score,
                            churn_risk = EXCLUDED.churn_risk
                    """, (
                        rec['recording_id'],
                        data.get('resolution_status', 'unresolved'),
                        data.get('first_contact_resolution', False),
                        data.get('closure_score', 5),
                        data.get('empathy_score', 5),
                        data.get('solution_summarized', False),
                        data.get('understanding_confirmed', False),
                        data.get('churn_risk', 'none'),
                        data.get('problem_complexity', 'medium')
                    ))
                    conn.commit()
                    success += 1
                    logger.info(f"  [{i}/{len(records)}] {rec['recording_id']}: {data.get('resolution_status')} / closure:{data.get('closure_score')}")

            time.sleep(1)
        except Exception as e:
            logger.error(f"  [{i}] Error: {e}")
            conn.rollback()

    conn.close()
    logger.info(f"Layer 3: Completed {success}/{len(records)}")
    return success


# ============================================================
# LAYER 4: Recommendations
# ============================================================
def process_layer4(limit: int = 50) -> int:
    """Generate coaching recommendations"""
    logger.info(f"Layer 4: Processing up to {limit} records...")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT t.recording_id, t.transcript_text, t.customer_name, t.employee_name,
               i.customer_sentiment, i.call_type, i.summary
        FROM transcripts t
        LEFT JOIN insights i ON t.recording_id = i.recording_id
        WHERE t.transcript_text IS NOT NULL AND LENGTH(t.transcript_text) > 100
        AND NOT EXISTS (SELECT 1 FROM call_recommendations r WHERE r.recording_id = t.recording_id)
        LIMIT %s
    """, (limit,))

    records = cur.fetchall()
    logger.info(f"Layer 4: Found {len(records)} records to process")

    success = 0
    for i, rec in enumerate(records, 1):
        try:
            prompt = f"""Generate coaching recommendations for this call. Return ONLY JSON:
{{
    "process_improvements": ["improvement1", "improvement2"],
    "employee_strengths": ["strength1", "strength2"],
    "employee_improvements": ["area1"],
    "suggested_phrases": ["phrase1"],
    "follow_up_actions": ["action1"],
    "escalation_required": true/false,
    "risk_level": "low/medium/high",
    "efficiency_score": 1-10
}}

Customer: {rec.get('customer_name', 'Unknown')}
Employee: {rec.get('employee_name', 'Unknown')}
Sentiment: {rec.get('customer_sentiment', 'unknown')}

Transcript:
{rec['transcript_text'][:4000]}"""

            result = call_llm(prompt, max_tokens=450)
            if result['success']:
                data = parse_json_response(result['content'])
                if data:
                    cur.execute("""
                        INSERT INTO call_recommendations (recording_id, process_improvements,
                            employee_strengths, employee_improvements, suggested_phrases,
                            follow_up_actions, escalation_required, risk_level, efficiency_score)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (recording_id) DO UPDATE SET
                            process_improvements = EXCLUDED.process_improvements,
                            employee_strengths = EXCLUDED.employee_strengths,
                            employee_improvements = EXCLUDED.employee_improvements
                    """, (
                        rec['recording_id'],
                        data.get('process_improvements', []),
                        data.get('employee_strengths', []),
                        data.get('employee_improvements', []),
                        data.get('suggested_phrases', []),
                        data.get('follow_up_actions', []),
                        data.get('escalation_required', False),
                        data.get('risk_level', 'low'),
                        data.get('efficiency_score', 5)
                    ))
                    conn.commit()
                    success += 1
                    logger.info(f"  [{i}/{len(records)}] {rec['recording_id']}: efficiency:{data.get('efficiency_score')}")

            time.sleep(1)
        except Exception as e:
            logger.error(f"  [{i}] Error: {e}")
            conn.rollback()

    conn.close()
    logger.info(f"Layer 4: Completed {success}/{len(records)}")
    return success


# ============================================================
# LAYER 5: Advanced Metrics
# ============================================================
def process_layer5(limit: int = 50) -> int:
    """Extract advanced metrics for RAG optimization"""
    logger.info(f"Layer 5: Processing up to {limit} records...")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT t.recording_id, t.transcript_text
        FROM transcripts t
        WHERE t.transcript_text IS NOT NULL AND LENGTH(t.transcript_text) > 100
        AND NOT EXISTS (SELECT 1 FROM call_advanced_metrics m WHERE m.recording_id = t.recording_id)
        LIMIT %s
    """, (limit,))

    records = cur.fetchall()
    logger.info(f"Layer 5: Found {len(records)} records to process")

    success = 0
    for i, rec in enumerate(records, 1):
        try:
            prompt = f"""Extract advanced metrics from this call. Return ONLY JSON:
{{
    "buying_signals": ["signal1"] or [],
    "competitor_mentions": ["competitor1"] or [],
    "urgency_level": "low/medium/high",
    "urgency_score": 1-10,
    "compliance_score": 1-10,
    "key_quotes": ["quote1", "quote2"],
    "sales_opportunity_score": 1-10
}}

Transcript:
{rec['transcript_text'][:4000]}"""

            result = call_llm(prompt, max_tokens=400)
            if result['success']:
                data = parse_json_response(result['content'])
                if data:
                    cur.execute("""
                        INSERT INTO call_advanced_metrics (recording_id, buying_signals,
                            competitor_intelligence, urgency, urgency_score, compliance_score,
                            key_quotes, sales_opportunity_score)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (recording_id) DO UPDATE SET
                            buying_signals = EXCLUDED.buying_signals,
                            urgency = EXCLUDED.urgency,
                            key_quotes = EXCLUDED.key_quotes
                    """, (
                        rec['recording_id'],
                        Json(data.get('buying_signals', [])),
                        Json({'competitors': data.get('competitor_mentions', [])}),
                        Json({'level': data.get('urgency_level', 'low')}),
                        data.get('urgency_score', 5),
                        data.get('compliance_score', 8),
                        Json(data.get('key_quotes', [])),
                        data.get('sales_opportunity_score', 5)
                    ))
                    conn.commit()
                    success += 1
                    logger.info(f"  [{i}/{len(records)}] {rec['recording_id']}: urgency:{data.get('urgency_level')}")

            time.sleep(1)
        except Exception as e:
            logger.error(f"  [{i}] Error: {e}")
            conn.rollback()

    conn.close()
    logger.info(f"Layer 5: Completed {success}/{len(records)}")
    return success


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='Process all AI layers for transcripts')
    parser.add_argument('--status', action='store_true', help='Show status only')
    parser.add_argument('--layer', type=int, choices=[1, 2, 3, 4, 5], help='Process specific layer')
    parser.add_argument('--limit', type=int, default=50, help='Records per batch (default: 50)')
    parser.add_argument('--all', action='store_true', help='Process all layers')
    parser.add_argument('--continuous', action='store_true', help='Run until all complete')

    args = parser.parse_args()

    # Always show status
    status = print_status()

    if args.status:
        return

    # Process specific layer
    if args.layer:
        layer_funcs = {1: process_layer1, 2: process_layer2, 3: process_layer3,
                       4: process_layer4, 5: process_layer5}
        result = layer_funcs[args.layer](args.limit)
        print_status()
        return

    # Process all layers
    if args.all or args.continuous:
        while True:
            status = get_layer_status()
            total_pending = sum(status[f'layer{i}_pending'] for i in range(1, 6))

            if total_pending == 0:
                logger.info("All layers complete!")
                break

            # Process each layer in order
            for layer_num in [1, 2, 3, 4, 5]:
                pending_key = f'layer{layer_num}_pending'
                if status[pending_key] > 0:
                    layer_funcs = {1: process_layer1, 2: process_layer2, 3: process_layer3,
                                   4: process_layer4, 5: process_layer5}
                    layer_funcs[layer_num](args.limit)

            if not args.continuous:
                break

            print_status()
            logger.info("Continuing to next batch...")

        print_status()
        return

    parser.print_help()


if __name__ == '__main__':
    main()
