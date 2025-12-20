#!/usr/bin/env python3
"""
Layer 3: Enhanced Call Resolution and Loop Closure Analysis
Provides comprehensive resolution tracking with improved insights and cost optimization
"""

import os
import sys
import json
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
import time
import argparse
from typing import Dict, List, Optional
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
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

# OpenRouter configuration
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', 'REDACTED_OPENROUTER_KEY')
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# MODEL CONFIGURATION - Updated 2025-12-20
# Primary: FREE model with best quality
# Secondary: Low-cost backup
PRIMARY_MODEL = 'google/gemma-3-12b-it:free'
SECONDARY_MODEL = 'meta-llama/llama-3.1-8b-instruct'

MODELS = {
    'primary': PRIMARY_MODEL,      # FREE - Best quality, reliable JSON
    'secondary': SECONDARY_MODEL,  # $0.02/1M - Good backup
    'gemma-12b': 'google/gemma-3-12b-it:free',
    'llama-8b': 'meta-llama/llama-3.1-8b-instruct',
}

def call_model(model_key: str, prompt: str, max_tokens: int = 700) -> dict:
    """Call the specified model through OpenRouter"""
    model = MODELS.get(model_key, PRIMARY_MODEL)

    try:
        response = requests.post(
            OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are an expert call center analyst specializing in resolution quality and customer satisfaction. Analyze calls for complete problem resolution and proper closure techniques."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": max_tokens
            },
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            if 'choices' in result and result['choices']:
                return {"success": True, "content": result['choices'][0]['message']['content']}

        return {"success": False, "error": f"API error: {response.status_code}"}

    except Exception as e:
        logger.error(f"Model call failed: {e}")
        return {"success": False, "error": str(e)}

def analyze_call_resolution_enhanced(transcript: str, customer_name: str = None,
                                    employee_name: str = None, call_type: str = None,
                                    sentiment: str = None, model_key: str = 'gemini-flash') -> Dict:
    """
    Enhanced call resolution analysis with additional insights
    """

    # Take first 4500 chars for better context
    transcript_sample = transcript[:4500] if len(transcript) > 4500 else transcript

    prompt = f"""Analyze this customer service call for resolution quality and closure effectiveness.

CONTEXT:
Customer: {customer_name or 'Unknown'}
Employee: {employee_name or 'Unknown'}
Call Type: {call_type or 'Unknown'}
Sentiment: {sentiment or 'Unknown'}

TRANSCRIPT:
{transcript_sample}

Provide detailed analysis of:

1. PROBLEM IDENTIFICATION
   - What specific issue/request did the customer have?
   - Was it clearly understood and acknowledged?
   - Were all concerns addressed?

2. RESOLUTION STATUS (choose one)
   - resolved: Problem completely solved during call
   - partially_resolved: Progress made but not fully resolved
   - unresolved: No solution provided
   - escalated: Transferred to another department/person
   - pending: Awaiting customer action or callback
   - no_issue: No problem to resolve (informational call)

3. RESOLUTION EFFECTIVENESS
   - How effective was the solution provided? (1-10)
   - Was it the best possible solution?
   - Were alternatives offered?

4. FOLLOW-UP REQUIREMENTS
   - none: No follow-up needed
   - customer_action: Customer needs to do something
   - employee_callback: Employee needs to call back
   - email_followup: Email follow-up promised
   - documentation_needed: Need to send docs/instructions
   - escalation_needed: Needs manager/specialist

5. LOOP CLOSURE QUALITY (true/false for each)
   - Solution summarized?
   - Customer understanding confirmed?
   - Asked if anything else needed?
   - Clear next steps provided?
   - Timeline expectations given?
   - Contact information offered?
   - Thank customer for their time?
   - Confirm customer satisfaction?

6. EMPATHY & SOFT SKILLS
   - Did employee show empathy?
   - Was the tone appropriate?
   - Active listening demonstrated?

7. KNOWLEDGE & COMPETENCY
   - Employee knowledge level (1-10)
   - Confidence in solution (1-10)
   - Need for additional training?

8. BEST PRACTICES ASSESSMENT
   - What was done well?
   - What was missed?
   - Specific improvements needed?

9. RISK ASSESSMENT
   - Customer satisfaction likelihood (high/medium/low)
   - Call-back probability (high/medium/low)
   - Escalation risk (high/medium/low)
   - Churn risk (high/medium/low)

10. BUSINESS IMPACT
    - Revenue impact (positive/neutral/negative)
    - Customer lifetime value impact
    - Potential upsell/cross-sell opportunities missed

Return ONLY valid JSON:
{{
    "problem_statement": "Clear description of the customer's issue",
    "problem_complexity": "simple/moderate/complex",
    "resolution_status": "resolved/partially_resolved/unresolved/escalated/pending/no_issue",
    "resolution_details": "What was done to resolve the issue",
    "resolution_effectiveness": 8.5,
    "alternatives_offered": true,
    "follow_up_type": "none/customer_action/employee_callback/email_followup/documentation_needed/escalation_needed",
    "follow_up_details": "Specific follow-up actions needed",
    "follow_up_timeline": "When follow-up should happen",
    "follow_up_owner": "customer/employee/manager/specialist",
    "loop_closure": {{
        "solution_summarized": true,
        "understanding_confirmed": true,
        "asked_if_anything_else": true,
        "next_steps_provided": true,
        "timeline_given": true,
        "contact_info_provided": true,
        "thanked_customer": true,
        "confirmed_satisfaction": true,
        "closure_score": 8.5
    }},
    "empathy_demonstrated": true,
    "empathy_score": 8,
    "tone_appropriate": true,
    "active_listening_score": 8,
    "employee_knowledge_level": 9,
    "confidence_in_solution": 9,
    "training_needed": "none/product/process/soft_skills",
    "training_specifics": "Details if training needed",
    "missed_best_practices": [
        "Specific practice missed"
    ],
    "done_well": [
        "What employee did well"
    ],
    "improvement_suggestions": [
        "Specific actionable improvement"
    ],
    "customer_satisfaction_likely": "high/medium/low",
    "call_back_risk": "high/medium/low",
    "escalation_probability": "high/medium/low",
    "churn_risk": "high/medium/low",
    "revenue_impact": "positive/neutral/negative",
    "ltv_impact": "positive/neutral/negative",
    "upsell_opportunity_missed": true,
    "cross_sell_opportunity_missed": false,
    "resolution_time_appropriate": true,
    "first_contact_resolution": true,
    "customer_effort_score": 3
}}"""

    response = call_model(model_key, prompt, 700)

    if response["success"]:
        try:
            content = response["content"]

            # Extract JSON from response
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                json_str = content[json_start:json_end].strip()
            elif "{" in content and "}" in content:
                json_start = content.find("{")
                json_end = content.rfind("}") + 1
                json_str = content[json_start:json_end]
            else:
                json_str = content.strip()

            # Parse and validate JSON
            resolution_data = json.loads(json_str)

            # Ensure all required fields exist
            if 'loop_closure' not in resolution_data:
                resolution_data['loop_closure'] = {}

            # Set defaults for loop closure
            loop_defaults = {
                'solution_summarized': False,
                'understanding_confirmed': False,
                'asked_if_anything_else': False,
                'next_steps_provided': False,
                'timeline_given': False,
                'contact_info_provided': False,
                'thanked_customer': False,
                'confirmed_satisfaction': False,
                'closure_score': 5.0
            }

            for key, default in loop_defaults.items():
                if key not in resolution_data['loop_closure']:
                    resolution_data['loop_closure'][key] = default

            logger.info(f"✅ Resolution analysis complete - Status: {resolution_data.get('resolution_status', 'unknown')}")
            return resolution_data

        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed: {e}")
            return get_default_resolution()
    else:
        # Try fallback model if primary fails
        if model_key == 'gemini-flash':
            logger.info("Trying fallback model...")
            return analyze_call_resolution_enhanced(
                transcript, customer_name, employee_name, call_type, sentiment, 'gemini-flash-8b'
            )
        return get_default_resolution()

def get_default_resolution():
    """Return default resolution data structure"""
    return {
        "problem_statement": "Unable to determine",
        "problem_complexity": "moderate",
        "resolution_status": "unresolved",
        "resolution_details": "",
        "resolution_effectiveness": 5.0,
        "alternatives_offered": False,
        "follow_up_type": "none",
        "follow_up_details": "",
        "follow_up_timeline": "",
        "follow_up_owner": "unknown",
        "loop_closure": {
            "solution_summarized": False,
            "understanding_confirmed": False,
            "asked_if_anything_else": False,
            "next_steps_provided": False,
            "timeline_given": False,
            "contact_info_provided": False,
            "thanked_customer": False,
            "confirmed_satisfaction": False,
            "closure_score": 5.0
        },
        "empathy_demonstrated": False,
        "empathy_score": 5,
        "tone_appropriate": True,
        "active_listening_score": 5,
        "employee_knowledge_level": 5,
        "confidence_in_solution": 5,
        "training_needed": "unknown",
        "training_specifics": "",
        "missed_best_practices": [],
        "done_well": [],
        "improvement_suggestions": [],
        "customer_satisfaction_likely": "medium",
        "call_back_risk": "medium",
        "escalation_probability": "low",
        "churn_risk": "medium",
        "revenue_impact": "neutral",
        "ltv_impact": "neutral",
        "upsell_opportunity_missed": False,
        "cross_sell_opportunity_missed": False,
        "resolution_time_appropriate": True,
        "first_contact_resolution": False,
        "customer_effort_score": 5
    }

def update_database_schema(cursor):
    """Add new columns to call_resolutions table if they don't exist"""

    new_columns = [
        ("problem_complexity", "TEXT"),
        ("resolution_effectiveness", "REAL"),
        ("alternatives_offered", "BOOLEAN"),
        ("follow_up_owner", "TEXT"),
        ("thanked_customer", "BOOLEAN"),
        ("confirmed_satisfaction", "BOOLEAN"),
        ("empathy_demonstrated", "BOOLEAN"),
        ("empathy_score", "REAL"),
        ("tone_appropriate", "BOOLEAN"),
        ("active_listening_score", "REAL"),
        ("employee_knowledge_level", "REAL"),
        ("confidence_in_solution", "REAL"),
        ("training_needed", "TEXT"),
        ("training_specifics", "TEXT"),
        ("done_well", "TEXT[]"),
        ("churn_risk", "TEXT"),
        ("revenue_impact", "TEXT"),
        ("ltv_impact", "TEXT"),
        ("upsell_opportunity_missed", "BOOLEAN"),
        ("cross_sell_opportunity_missed", "BOOLEAN"),
        ("resolution_time_appropriate", "BOOLEAN"),
        ("first_contact_resolution", "BOOLEAN"),
        ("customer_effort_score", "REAL"),
        ("model_version", "TEXT"),
        ("processing_timestamp", "TIMESTAMP")
    ]

    for column_name, column_type in new_columns:
        try:
            cursor.execute(f"""
                ALTER TABLE call_resolutions
                ADD COLUMN IF NOT EXISTS {column_name} {column_type}
            """)
            logger.info(f"Added/verified column: {column_name}")
        except Exception as e:
            logger.warning(f"Column {column_name} might already exist: {e}")

def save_resolution_to_db(recording_id: str, resolution_data: Dict):
    """Save enhanced resolution analysis to database"""

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        # Ensure schema is updated
        update_database_schema(cursor)

        # Extract loop closure data
        loop_closure = resolution_data.get('loop_closure', {})

        # Prepare the INSERT/UPDATE query
        cursor.execute("""
            INSERT INTO call_resolutions (
                recording_id, problem_statement, problem_complexity, resolution_status,
                resolution_details, resolution_effectiveness, alternatives_offered,
                follow_up_type, follow_up_details, follow_up_timeline, follow_up_owner,
                solution_summarized, understanding_confirmed, asked_if_anything_else,
                next_steps_provided, timeline_given, contact_info_provided,
                thanked_customer, confirmed_satisfaction, closure_score,
                empathy_demonstrated, empathy_score, tone_appropriate, active_listening_score,
                employee_knowledge_level, confidence_in_solution, training_needed, training_specifics,
                missed_best_practices, done_well, improvement_suggestions,
                customer_satisfaction_likely, call_back_risk, escalation_probability, churn_risk,
                revenue_impact, ltv_impact, upsell_opportunity_missed, cross_sell_opportunity_missed,
                resolution_time_appropriate, first_contact_resolution, customer_effort_score,
                model_version, processing_timestamp, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (recording_id) DO UPDATE SET
                problem_statement = EXCLUDED.problem_statement,
                problem_complexity = EXCLUDED.problem_complexity,
                resolution_status = EXCLUDED.resolution_status,
                resolution_details = EXCLUDED.resolution_details,
                resolution_effectiveness = EXCLUDED.resolution_effectiveness,
                alternatives_offered = EXCLUDED.alternatives_offered,
                follow_up_type = EXCLUDED.follow_up_type,
                follow_up_details = EXCLUDED.follow_up_details,
                follow_up_timeline = EXCLUDED.follow_up_timeline,
                follow_up_owner = EXCLUDED.follow_up_owner,
                solution_summarized = EXCLUDED.solution_summarized,
                understanding_confirmed = EXCLUDED.understanding_confirmed,
                asked_if_anything_else = EXCLUDED.asked_if_anything_else,
                next_steps_provided = EXCLUDED.next_steps_provided,
                timeline_given = EXCLUDED.timeline_given,
                contact_info_provided = EXCLUDED.contact_info_provided,
                thanked_customer = EXCLUDED.thanked_customer,
                confirmed_satisfaction = EXCLUDED.confirmed_satisfaction,
                closure_score = EXCLUDED.closure_score,
                empathy_demonstrated = EXCLUDED.empathy_demonstrated,
                empathy_score = EXCLUDED.empathy_score,
                tone_appropriate = EXCLUDED.tone_appropriate,
                active_listening_score = EXCLUDED.active_listening_score,
                employee_knowledge_level = EXCLUDED.employee_knowledge_level,
                confidence_in_solution = EXCLUDED.confidence_in_solution,
                training_needed = EXCLUDED.training_needed,
                training_specifics = EXCLUDED.training_specifics,
                missed_best_practices = EXCLUDED.missed_best_practices,
                done_well = EXCLUDED.done_well,
                improvement_suggestions = EXCLUDED.improvement_suggestions,
                customer_satisfaction_likely = EXCLUDED.customer_satisfaction_likely,
                call_back_risk = EXCLUDED.call_back_risk,
                escalation_probability = EXCLUDED.escalation_probability,
                churn_risk = EXCLUDED.churn_risk,
                revenue_impact = EXCLUDED.revenue_impact,
                ltv_impact = EXCLUDED.ltv_impact,
                upsell_opportunity_missed = EXCLUDED.upsell_opportunity_missed,
                cross_sell_opportunity_missed = EXCLUDED.cross_sell_opportunity_missed,
                resolution_time_appropriate = EXCLUDED.resolution_time_appropriate,
                first_contact_resolution = EXCLUDED.first_contact_resolution,
                customer_effort_score = EXCLUDED.customer_effort_score,
                model_version = EXCLUDED.model_version,
                processing_timestamp = EXCLUDED.processing_timestamp,
                updated_at = CURRENT_TIMESTAMP
        """, (
            recording_id,
            resolution_data.get('problem_statement', ''),
            resolution_data.get('problem_complexity', 'moderate'),
            resolution_data.get('resolution_status', 'unresolved'),
            resolution_data.get('resolution_details', ''),
            resolution_data.get('resolution_effectiveness', 5.0),
            resolution_data.get('alternatives_offered', False),
            resolution_data.get('follow_up_type', 'none'),
            resolution_data.get('follow_up_details', ''),
            resolution_data.get('follow_up_timeline', ''),
            resolution_data.get('follow_up_owner', 'unknown'),
            loop_closure.get('solution_summarized', False),
            loop_closure.get('understanding_confirmed', False),
            loop_closure.get('asked_if_anything_else', False),
            loop_closure.get('next_steps_provided', False),
            loop_closure.get('timeline_given', False),
            loop_closure.get('contact_info_provided', False),
            loop_closure.get('thanked_customer', False),
            loop_closure.get('confirmed_satisfaction', False),
            loop_closure.get('closure_score', 5.0),
            resolution_data.get('empathy_demonstrated', False),
            resolution_data.get('empathy_score', 5),
            resolution_data.get('tone_appropriate', True),
            resolution_data.get('active_listening_score', 5),
            resolution_data.get('employee_knowledge_level', 5),
            resolution_data.get('confidence_in_solution', 5),
            resolution_data.get('training_needed', 'unknown'),
            resolution_data.get('training_specifics', ''),
            resolution_data.get('missed_best_practices', []),
            resolution_data.get('done_well', []),
            resolution_data.get('improvement_suggestions', []),
            resolution_data.get('customer_satisfaction_likely', 'medium'),
            resolution_data.get('call_back_risk', 'medium'),
            resolution_data.get('escalation_probability', 'low'),
            resolution_data.get('churn_risk', 'medium'),
            resolution_data.get('revenue_impact', 'neutral'),
            resolution_data.get('ltv_impact', 'neutral'),
            resolution_data.get('upsell_opportunity_missed', False),
            resolution_data.get('cross_sell_opportunity_missed', False),
            resolution_data.get('resolution_time_appropriate', True),
            resolution_data.get('first_contact_resolution', False),
            resolution_data.get('customer_effort_score', 5),
            'layer3_enhanced_gemini_v1',
            datetime.now()
        ))

        conn.commit()
        logger.info(f"✅ Saved enhanced resolution for {recording_id}")

    except Exception as e:
        logger.error(f"Database error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def process_batch(limit: int = 50, offset: int = 0):
    """Process a batch of recordings"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Get recordings that need Layer 3 analysis
        # Prioritize those with transcripts and embeddings
        cursor.execute("""
            SELECT
                t.recording_id,
                t.transcript_text,
                t.customer_name,
                t.employee_name,
                i.call_type,
                i.customer_sentiment
            FROM transcripts t
            INNER JOIN transcript_embeddings te ON t.recording_id = te.recording_id
            LEFT JOIN insights i ON t.recording_id = i.recording_id
            LEFT JOIN call_resolutions cr ON t.recording_id = cr.recording_id
            WHERE t.transcript_text IS NOT NULL
            AND LENGTH(t.transcript_text) > 100
            AND (cr.recording_id IS NULL OR cr.model_version IS NULL OR cr.model_version != 'layer3_enhanced_gemini_v1')
            ORDER BY t.recording_id
            LIMIT %s OFFSET %s
        """, (limit, offset))

        records = cursor.fetchall()

        logger.info(f"\n🔍 Layer 3: Enhanced Resolution Analysis")
        logger.info(f"📊 Processing {len(records)} recordings (offset: {offset})\n")

        success_count = 0

        for idx, record in enumerate(records, 1):
            rec_id = record['recording_id']

            try:
                logger.info(f"[{idx}/{len(records)}] Processing {rec_id}")
                logger.info(f"  Customer: {record.get('customer_name', 'Unknown')}")
                logger.info(f"  Employee: {record.get('employee_name', 'Unknown')}")

                # Analyze resolution with enhanced insights
                resolution_data = analyze_call_resolution_enhanced(
                    record['transcript_text'],
                    record.get('customer_name'),
                    record.get('employee_name'),
                    record.get('call_type'),
                    record.get('customer_sentiment')
                )

                # Save to database
                save_resolution_to_db(rec_id, resolution_data)
                success_count += 1

                # Log key findings
                logger.info(f"  Status: {resolution_data.get('resolution_status', 'unknown')}")
                logger.info(f"  Closure Score: {resolution_data.get('loop_closure', {}).get('closure_score', 0)}/10")
                logger.info(f"  Churn Risk: {resolution_data.get('churn_risk', 'unknown')}")

            except Exception as e:
                logger.error(f"  ❌ Error processing {rec_id}: {e}")

            # Rate limiting
            time.sleep(3)

        logger.info(f"\n✅ Layer 3 Batch Complete:")
        logger.info(f"  Processed: {len(records)} recordings")
        logger.info(f"  Successful: {success_count}")
        logger.info(f"  Success Rate: {(success_count/len(records)*100):.1f}%")

        return success_count

    except Exception as e:
        logger.error(f"Batch processing error: {e}")
        return 0
    finally:
        cursor.close()
        conn.close()

def get_statistics():
    """Get current Layer 3 processing statistics"""

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT
                (SELECT COUNT(*) FROM transcripts WHERE transcript_text IS NOT NULL) as total_transcripts,
                (SELECT COUNT(*) FROM call_resolutions) as total_resolutions,
                (SELECT COUNT(*) FROM call_resolutions WHERE model_version = 'layer3_enhanced_gemini_v1') as enhanced_resolutions,
                (SELECT AVG(closure_score) FROM call_resolutions WHERE closure_score IS NOT NULL) as avg_closure_score,
                (SELECT COUNT(*) FROM call_resolutions WHERE resolution_status = 'resolved') as fully_resolved,
                (SELECT COUNT(*) FROM call_resolutions WHERE churn_risk = 'high') as high_churn_risk
        """)

        stats = cursor.fetchone()

        print("\n📊 Layer 3 Resolution Analysis Statistics:")
        print(f"  Total Transcripts: {stats[0]}")
        print(f"  Total Resolutions Analyzed: {stats[1]}")
        print(f"  Enhanced Analysis: {stats[2]}")
        print(f"  Average Closure Score: {stats[3]:.1f}/10" if stats[3] else "  Average Closure Score: N/A")
        print(f"  Fully Resolved Calls: {stats[4]}")
        print(f"  High Churn Risk: {stats[5]}")

        return stats

    finally:
        cursor.close()
        conn.close()

def main():
    parser = argparse.ArgumentParser(description='Layer 3: Enhanced Call Resolution Analysis')
    parser.add_argument('--limit', type=int, default=50, help='Number of records to process')
    parser.add_argument('--offset', type=int, default=0, help='Offset for batch processing')
    parser.add_argument('--stats', action='store_true', help='Show statistics only')
    parser.add_argument('--test', type=str, help='Test on specific recording ID')

    args = parser.parse_args()

    if args.stats:
        get_statistics()
    elif args.test:
        # Test on specific recording
        conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT t.*, i.call_type, i.customer_sentiment
            FROM transcripts t
            LEFT JOIN insights i ON t.recording_id = i.recording_id
            WHERE t.recording_id = %s
        """, (args.test,))

        record = cursor.fetchone()

        if record:
            logger.info(f"Testing on {args.test}")
            resolution = analyze_call_resolution_enhanced(
                record['transcript_text'],
                record.get('customer_name'),
                record.get('employee_name'),
                record.get('call_type'),
                record.get('customer_sentiment')
            )
            save_resolution_to_db(args.test, resolution)
            print(json.dumps(resolution, indent=2))
        else:
            print(f"Recording {args.test} not found")

        cursor.close()
        conn.close()
    else:
        # Process batch
        process_batch(args.limit, args.offset)

if __name__ == "__main__":
    main()