#!/usr/bin/env python3
"""
Call Resolution and Loop Closure Analysis System
Tracks problem resolution, follow-ups, and ensures employees close the loop with customers
"""

import os
import sys
import json
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from typing import Dict, List, Optional

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': 'call_insights_pass',
    'host': 'localhost',
    'port': 5432
}

# OpenRouter configuration
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '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')
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


def analyze_call_resolution(transcript: str, customer_name: str = None,
                           employee_name: str = None, call_type: str = None) -> Dict[str, any]:
    """
    Analyze call resolution status and loop closure
    """

    prompt = f"""Analyze this customer service call for resolution and closure quality.

Customer: {customer_name or 'Unknown'}
Employee: {employee_name or 'Unknown'}
Call Type: {call_type or 'Unknown'}

Analyze the transcript for:

1. PROBLEM IDENTIFICATION
   - What was the customer's issue/request?
   - Was it clearly understood by the employee?
   - Were all concerns addressed?

2. RESOLUTION STATUS
   - resolved: Problem completely solved during the call
   - partially_resolved: Some progress made but not fully resolved
   - unresolved: No solution provided
   - escalated: Transferred to another department/person
   - pending: Awaiting customer action or callback

3. FOLLOW-UP REQUIREMENTS
   - none: No follow-up needed
   - customer_action: Customer needs to do something
   - employee_callback: Employee needs to call back
   - email_followup: Email follow-up promised
   - escalation_needed: Needs manager/specialist attention

4. LOOP CLOSURE ANALYSIS
   - Did the employee:
     * Summarize the solution?
     * Confirm customer understanding?
     * Ask if there's anything else?
     * Provide clear next steps?
     * Give timeline expectations?
     * Offer contact information?

5. QUALITY ISSUES
   - What best practices were missed?
   - How could the call have been handled better?

Return ONLY JSON:
{{
    "problem_statement": "Clear description of the issue",
    "resolution_status": "resolved/partially_resolved/unresolved/escalated/pending",
    "resolution_details": "What was done to resolve",
    "follow_up_type": "none/customer_action/employee_callback/email_followup/escalation_needed",
    "follow_up_details": "Specific follow-up actions needed",
    "follow_up_timeline": "When follow-up should happen",
    "loop_closure": {{
        "solution_summarized": true/false,
        "understanding_confirmed": true/false,
        "asked_if_anything_else": true/false,
        "next_steps_provided": true/false,
        "timeline_given": true/false,
        "contact_info_provided": true/false,
        "closure_score": 8.5
    }},
    "missed_best_practices": [
        "Specific practice missed",
        "Another practice missed"
    ],
    "improvement_suggestions": [
        "Specific suggestion for this call",
        "Another improvement"
    ],
    "customer_satisfaction_likely": "high/medium/low",
    "call_back_risk": "high/medium/low",
    "escalation_probability": "high/medium/low"
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
                "model": "anthropic/claude-3-haiku",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 600
            },
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']

            # Parse JSON from response
            try:
                import re
                # Extract nested JSON properly
                json_match = re.search(r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}', content, re.DOTALL)
                if json_match:
                    json_str = json_match.group()
                    # Clean up JSON
                    json_str = re.sub(r',\s*}', '}', json_str)
                    json_str = re.sub(r',\s*]', ']', json_str)

                    resolution_data = json.loads(json_str)
                    logger.info(f"Resolution analysis complete")
                    return resolution_data
            except Exception as e:
                logger.error(f"JSON parsing error: {e}")

        else:
            logger.error(f"AI analysis failed: {response.status_code}")

    except Exception as e:
        logger.error(f"Error calling AI: {e}")

    # Default response
    return {
        "problem_statement": "Unable to determine",
        "resolution_status": "unresolved",
        "resolution_details": "",
        "follow_up_type": "none",
        "follow_up_details": "",
        "follow_up_timeline": "",
        "loop_closure": {
            "solution_summarized": False,
            "understanding_confirmed": False,
            "asked_if_anything_else": False,
            "next_steps_provided": False,
            "timeline_given": False,
            "contact_info_provided": False,
            "closure_score": 5.0
        },
        "missed_best_practices": [],
        "improvement_suggestions": [],
        "customer_satisfaction_likely": "medium",
        "call_back_risk": "medium",
        "escalation_probability": "low"
    }


def save_resolution_to_db(recording_id: str, resolution_data: Dict[str, any]):
    """Save resolution analysis to database"""

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        # Create table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS call_resolutions (
                recording_id TEXT PRIMARY KEY,
                problem_statement TEXT,
                resolution_status TEXT,
                resolution_details TEXT,
                follow_up_type TEXT,
                follow_up_details TEXT,
                follow_up_timeline TEXT,
                solution_summarized BOOLEAN,
                understanding_confirmed BOOLEAN,
                asked_if_anything_else BOOLEAN,
                next_steps_provided BOOLEAN,
                timeline_given BOOLEAN,
                contact_info_provided BOOLEAN,
                closure_score REAL,
                missed_best_practices TEXT[],
                improvement_suggestions TEXT[],
                customer_satisfaction_likely TEXT,
                call_back_risk TEXT,
                escalation_probability TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Extract loop closure data
        loop_closure = resolution_data.get('loop_closure', {})

        # Insert or update resolution data
        cursor.execute("""
            INSERT INTO call_resolutions (
                recording_id, problem_statement, resolution_status, resolution_details,
                follow_up_type, follow_up_details, follow_up_timeline,
                solution_summarized, understanding_confirmed, asked_if_anything_else,
                next_steps_provided, timeline_given, contact_info_provided,
                closure_score, missed_best_practices, improvement_suggestions,
                customer_satisfaction_likely, call_back_risk, escalation_probability
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (recording_id) DO UPDATE SET
                problem_statement = EXCLUDED.problem_statement,
                resolution_status = EXCLUDED.resolution_status,
                resolution_details = EXCLUDED.resolution_details,
                follow_up_type = EXCLUDED.follow_up_type,
                follow_up_details = EXCLUDED.follow_up_details,
                follow_up_timeline = EXCLUDED.follow_up_timeline,
                solution_summarized = EXCLUDED.solution_summarized,
                understanding_confirmed = EXCLUDED.understanding_confirmed,
                asked_if_anything_else = EXCLUDED.asked_if_anything_else,
                next_steps_provided = EXCLUDED.next_steps_provided,
                timeline_given = EXCLUDED.timeline_given,
                contact_info_provided = EXCLUDED.contact_info_provided,
                closure_score = EXCLUDED.closure_score,
                missed_best_practices = EXCLUDED.missed_best_practices,
                improvement_suggestions = EXCLUDED.improvement_suggestions,
                customer_satisfaction_likely = EXCLUDED.customer_satisfaction_likely,
                call_back_risk = EXCLUDED.call_back_risk,
                escalation_probability = EXCLUDED.escalation_probability,
                updated_at = CURRENT_TIMESTAMP
        """, (
            recording_id,
            resolution_data.get('problem_statement', ''),
            resolution_data.get('resolution_status', 'unresolved'),
            resolution_data.get('resolution_details', ''),
            resolution_data.get('follow_up_type', 'none'),
            resolution_data.get('follow_up_details', ''),
            resolution_data.get('follow_up_timeline', ''),
            loop_closure.get('solution_summarized', False),
            loop_closure.get('understanding_confirmed', False),
            loop_closure.get('asked_if_anything_else', False),
            loop_closure.get('next_steps_provided', False),
            loop_closure.get('timeline_given', False),
            loop_closure.get('contact_info_provided', False),
            loop_closure.get('closure_score', 5.0),
            resolution_data.get('missed_best_practices', []),
            resolution_data.get('improvement_suggestions', []),
            resolution_data.get('customer_satisfaction_likely', 'medium'),
            resolution_data.get('call_back_risk', 'medium'),
            resolution_data.get('escalation_probability', 'low')
        ))

        conn.commit()
        logger.info(f"✅ Saved resolution analysis for {recording_id}")

    except Exception as e:
        logger.error(f"Database error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


def process_single_recording(recording_id: str):
    """Process resolution analysis for a single recording"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Get transcript and metadata
        cursor.execute("""
            SELECT
                t.recording_id,
                t.transcript_text,
                t.customer_name,
                t.employee_name,
                i.call_type
            FROM transcripts t
            LEFT JOIN insights i ON t.recording_id = i.recording_id
            WHERE t.recording_id = %s
        """, (recording_id,))

        result = cursor.fetchone()

        if result and result['transcript_text']:
            logger.info(f"\n🔍 Analyzing resolution for {recording_id}")

            # Analyze resolution
            resolution_data = analyze_call_resolution(
                result['transcript_text'],
                result.get('customer_name'),
                result.get('employee_name'),
                result.get('call_type')
            )

            # Save to database
            save_resolution_to_db(recording_id, resolution_data)

            return resolution_data
        else:
            logger.warning(f"No transcript found for {recording_id}")

    except Exception as e:
        logger.error(f"Error processing {recording_id}: {e}")
    finally:
        cursor.close()
        conn.close()

    return None


def process_all_recordings(limit: int = 30):
    """Process all recordings needing resolution analysis"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Find transcripts without resolution analysis
        cursor.execute("""
            SELECT
                t.recording_id,
                t.transcript_text,
                t.customer_name,
                t.employee_name,
                i.call_type
            FROM transcripts t
            LEFT JOIN insights i ON t.recording_id = i.recording_id
            LEFT JOIN call_resolutions r ON t.recording_id = r.recording_id
            WHERE t.transcript_text IS NOT NULL
            AND LENGTH(t.transcript_text) > 100
            AND r.recording_id IS NULL
            ORDER BY t.call_date DESC
            LIMIT %s
        """, (limit,))

        results = cursor.fetchall()
        logger.info(f"📊 Found {len(results)} recordings needing resolution analysis")

        stats = {
            'resolved': 0,
            'partially_resolved': 0,
            'unresolved': 0,
            'poor_closure': 0,
            'high_risk': 0
        }

        for i, result in enumerate(results, 1):
            logger.info(f"\n--- Processing {i}/{len(results)} ---")

            # Analyze resolution
            resolution_data = analyze_call_resolution(
                result['transcript_text'],
                result.get('customer_name'),
                result.get('employee_name'),
                result.get('call_type')
            )

            # Save to database
            save_resolution_to_db(result['recording_id'], resolution_data)

            # Track statistics
            status = resolution_data.get('resolution_status')
            if status == 'resolved':
                stats['resolved'] += 1
            elif status == 'partially_resolved':
                stats['partially_resolved'] += 1
            else:
                stats['unresolved'] += 1

            if resolution_data.get('loop_closure', {}).get('closure_score', 10) < 6:
                stats['poor_closure'] += 1

            if resolution_data.get('call_back_risk') == 'high':
                stats['high_risk'] += 1

            logger.info(f"  Status: {status}")
            logger.info(f"  Closure Score: {resolution_data.get('loop_closure', {}).get('closure_score', 0)}/10")
            logger.info(f"  Follow-up: {resolution_data.get('follow_up_type')}")

        # Print summary
        logger.info(f"\n✅ Processed {len(results)} recordings")
        logger.info(f"📊 Resolution Statistics:")
        logger.info(f"  - Resolved: {stats['resolved']}")
        logger.info(f"  - Partially Resolved: {stats['partially_resolved']}")
        logger.info(f"  - Unresolved: {stats['unresolved']}")
        logger.info(f"  - Poor Loop Closure: {stats['poor_closure']}")
        logger.info(f"  - High Call-back Risk: {stats['high_risk']}")

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()


def generate_closure_report():
    """Generate a report on loop closure quality"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Get closure statistics
        cursor.execute("""
            SELECT
                AVG(closure_score) as avg_closure_score,
                COUNT(*) FILTER (WHERE solution_summarized = true) as summarized_count,
                COUNT(*) FILTER (WHERE understanding_confirmed = true) as confirmed_count,
                COUNT(*) FILTER (WHERE asked_if_anything_else = true) as asked_else_count,
                COUNT(*) FILTER (WHERE next_steps_provided = true) as next_steps_count,
                COUNT(*) FILTER (WHERE timeline_given = true) as timeline_count,
                COUNT(*) FILTER (WHERE contact_info_provided = true) as contact_count,
                COUNT(*) as total_calls
            FROM call_resolutions
        """)
        stats = cursor.fetchone()

        # Get common missed practices
        cursor.execute("""
            SELECT
                unnest(missed_best_practices) as practice,
                COUNT(*) as frequency
            FROM call_resolutions
            WHERE missed_best_practices IS NOT NULL
            GROUP BY practice
            ORDER BY frequency DESC
            LIMIT 10
        """)
        missed_practices = cursor.fetchall()

        # Get high-risk calls
        cursor.execute("""
            SELECT
                r.recording_id,
                t.customer_name,
                t.employee_name,
                r.problem_statement,
                r.resolution_status,
                r.closure_score
            FROM call_resolutions r
            JOIN transcripts t ON r.recording_id = t.recording_id
            WHERE r.call_back_risk = 'high'
            OR r.escalation_probability = 'high'
            OR r.closure_score < 5
            ORDER BY r.closure_score ASC
            LIMIT 10
        """)
        high_risk = cursor.fetchall()

        print("\n" + "="*60)
        print("📊 CALL CLOSURE QUALITY REPORT")
        print("="*60)

        if stats:
            total = stats['total_calls']
            print(f"\n📈 OVERALL METRICS ({total} calls analyzed):")
            print(f"  Average Closure Score: {stats['avg_closure_score']:.1f}/10")
            print(f"  Solution Summarized: {stats['summarized_count']}/{total} ({stats['summarized_count']*100//total}%)")
            print(f"  Understanding Confirmed: {stats['confirmed_count']}/{total} ({stats['confirmed_count']*100//total}%)")
            print(f"  Asked If Anything Else: {stats['asked_else_count']}/{total} ({stats['asked_else_count']*100//total}%)")
            print(f"  Next Steps Provided: {stats['next_steps_count']}/{total} ({stats['next_steps_count']*100//total}%)")
            print(f"  Timeline Given: {stats['timeline_count']}/{total} ({stats['timeline_count']*100//total}%)")
            print(f"  Contact Info Provided: {stats['contact_count']}/{total} ({stats['contact_count']*100//total}%)")

        print("\n❌ TOP MISSED BEST PRACTICES:")
        for practice in missed_practices[:5]:
            print(f"  • {practice['practice']} ({practice['frequency']} occurrences)")

        print("\n⚠️ HIGH-RISK CALLS (Need immediate attention):")
        for call in high_risk[:5]:
            print(f"\n  Recording: {call['recording_id']}")
            print(f"  Customer: {call['customer_name']}")
            print(f"  Employee: {call['employee_name']}")
            print(f"  Issue: {call['problem_statement'][:80]}...")
            print(f"  Status: {call['resolution_status']}, Closure Score: {call['closure_score']}/10")

        print("\n" + "="*60)

    except Exception as e:
        logger.error(f"Error generating report: {e}")
    finally:
        cursor.close()
        conn.close()


def main():
    """Main function"""

    if len(sys.argv) > 1:
        if sys.argv[1] == '--all':
            # Process all recordings
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 30
            logger.info(f"🔍 Analyzing resolution for {limit} recordings...")
            process_all_recordings(limit=limit)
        elif sys.argv[1] == '--report':
            # Generate closure report
            generate_closure_report()
        else:
            # Process specific recording
            recording_id = sys.argv[1]
            logger.info(f"Analyzing resolution for: {recording_id}")
            result = process_single_recording(recording_id)

            if result:
                print("\n✅ Resolution Analysis Complete:")
                print(f"\n📋 Problem: {result['problem_statement']}")
                print(f"✓ Resolution Status: {result['resolution_status']}")
                print(f"📞 Follow-up Type: {result['follow_up_type']}")

                print("\n🔄 Loop Closure Quality:")
                loop = result.get('loop_closure', {})
                print(f"  • Solution Summarized: {'✓' if loop.get('solution_summarized') else '✗'}")
                print(f"  • Understanding Confirmed: {'✓' if loop.get('understanding_confirmed') else '✗'}")
                print(f"  • Asked If Anything Else: {'✓' if loop.get('asked_if_anything_else') else '✗'}")
                print(f"  • Next Steps Provided: {'✓' if loop.get('next_steps_provided') else '✗'}")
                print(f"  • Timeline Given: {'✓' if loop.get('timeline_given') else '✗'}")
                print(f"  • Contact Info Provided: {'✓' if loop.get('contact_info_provided') else '✗'}")
                print(f"  📊 Closure Score: {loop.get('closure_score', 0)}/10")

                if result.get('improvement_suggestions'):
                    print("\n💡 Improvement Suggestions:")
                    for suggestion in result['improvement_suggestions']:
                        print(f"  • {suggestion}")

                print(f"\n⚠️ Risk Assessment:")
                print(f"  • Customer Satisfaction: {result.get('customer_satisfaction_likely')}")
                print(f"  • Call-back Risk: {result.get('call_back_risk')}")
                print(f"  • Escalation Risk: {result.get('escalation_probability')}")
    else:
        # Process all and generate report
        logger.info("🔍 Analyzing call resolutions...")
        process_all_recordings(limit=20)
        generate_closure_report()


if __name__ == "__main__":
    main()