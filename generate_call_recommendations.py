#!/usr/bin/env python3
"""
Call Recommendations and Process Improvement System
Analyzes calls and generates actionable suggestions for employees and workflows
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
    'password': 'REDACTED_DB_PASSWORD',
    'host': 'localhost',
    'port': 5432
}

# OpenRouter configuration
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', 'REDACTED_OPENROUTER_KEY')
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


def generate_recommendations(transcript: str, sentiment: str, call_type: str,
                            customer_name: str = None, employee_name: str = None,
                            summary: str = None) -> Dict[str, any]:
    """
    Generate actionable recommendations based on call analysis
    """

    prompt = f"""As a call center quality analyst, analyze this customer service call and provide actionable recommendations.

CALL CONTEXT:
- Customer: {customer_name or 'Unknown'}
- Employee: {employee_name or 'Unknown'}
- Sentiment: {sentiment}
- Call Type: {call_type}
- Summary: {summary or 'Not available'}

Analyze the transcript and provide:

1. PROCESS IMPROVEMENTS (2-3 specific suggestions)
   - What workflow or system improvements would prevent this issue?
   - What documentation or training gaps exist?
   - What automation opportunities exist?

2. EMPLOYEE COACHING (2-3 specific points)
   - What did the employee do well?
   - What could be improved?
   - Specific phrases or techniques to use next time

3. FOLLOW-UP ACTIONS (1-3 specific tasks)
   - Immediate actions needed
   - Long-term preventive measures
   - Customer retention strategies

4. KNOWLEDGE BASE UPDATES
   - What FAQ or documentation should be created/updated?
   - Common issues to document

5. ESCALATION INDICATORS
   - Should this be escalated? (yes/no)
   - Risk level (low/medium/high)
   - Reason for escalation

Return ONLY JSON:
{{
    "process_improvements": [
        "Specific improvement 1",
        "Specific improvement 2"
    ],
    "employee_coaching": {{
        "strengths": ["What went well"],
        "improvements": ["Area for improvement"],
        "suggested_phrases": ["Better way to say something"]
    }},
    "follow_up_actions": [
        "Action item 1",
        "Action item 2"
    ],
    "knowledge_base_updates": [
        "Documentation to create/update"
    ],
    "escalation": {{
        "required": true/false,
        "risk_level": "low/medium/high",
        "reason": "Why escalate"
    }},
    "efficiency_score": 7.5,
    "training_priority": "low/medium/high"
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
                "model": "deepseek/deepseek-r1",  # Best reasoning model for recommendations
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.4,
                "max_tokens": 500
            },
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']

            # Parse JSON from response
            try:
                import re
                # More robust JSON extraction
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
                if json_match:
                    json_str = json_match.group()
                    # Clean up common JSON issues
                    json_str = re.sub(r',\s*}', '}', json_str)  # Remove trailing commas
                    json_str = re.sub(r',\s*]', ']', json_str)  # Remove trailing commas in arrays
                    recommendations = json.loads(json_str)
                    logger.info(f"Generated recommendations successfully")
                    return recommendations
            except Exception as e:
                logger.error(f"JSON parsing error: {e}, Content: {content[:500]}")

        else:
            logger.error(f"AI analysis failed: {response.status_code}")

    except Exception as e:
        logger.error(f"Error calling AI: {e}")

    # Default response
    return {
        "process_improvements": ["Review standard procedures"],
        "employee_coaching": {
            "strengths": ["Professional communication"],
            "improvements": ["Could improve response time"],
            "suggested_phrases": []
        },
        "follow_up_actions": ["Follow up with customer"],
        "knowledge_base_updates": [],
        "escalation": {
            "required": False,
            "risk_level": "low",
            "reason": ""
        },
        "efficiency_score": 5.0,
        "training_priority": "low"
    }


def save_recommendations_to_db(recording_id: str, recommendations: Dict[str, any]):
    """Save recommendations to database"""

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        # Check if we have a call_recommendations table, if not create it
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS call_recommendations (
                recording_id TEXT PRIMARY KEY,
                process_improvements TEXT[],
                employee_strengths TEXT[],
                employee_improvements TEXT[],
                suggested_phrases TEXT[],
                follow_up_actions TEXT[],
                knowledge_base_updates TEXT[],
                escalation_required BOOLEAN,
                risk_level TEXT,
                escalation_reason TEXT,
                efficiency_score REAL,
                training_priority TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Insert or update recommendations
        cursor.execute("""
            INSERT INTO call_recommendations (
                recording_id,
                process_improvements,
                employee_strengths,
                employee_improvements,
                suggested_phrases,
                follow_up_actions,
                knowledge_base_updates,
                escalation_required,
                risk_level,
                escalation_reason,
                efficiency_score,
                training_priority
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (recording_id) DO UPDATE SET
                process_improvements = EXCLUDED.process_improvements,
                employee_strengths = EXCLUDED.employee_strengths,
                employee_improvements = EXCLUDED.employee_improvements,
                suggested_phrases = EXCLUDED.suggested_phrases,
                follow_up_actions = EXCLUDED.follow_up_actions,
                knowledge_base_updates = EXCLUDED.knowledge_base_updates,
                escalation_required = EXCLUDED.escalation_required,
                risk_level = EXCLUDED.risk_level,
                escalation_reason = EXCLUDED.escalation_reason,
                efficiency_score = EXCLUDED.efficiency_score,
                training_priority = EXCLUDED.training_priority,
                updated_at = CURRENT_TIMESTAMP
        """, (
            recording_id,
            recommendations.get('process_improvements', []),
            recommendations.get('employee_coaching', {}).get('strengths', []),
            recommendations.get('employee_coaching', {}).get('improvements', []),
            recommendations.get('employee_coaching', {}).get('suggested_phrases', []),
            recommendations.get('follow_up_actions', []),
            recommendations.get('knowledge_base_updates', []),
            recommendations.get('escalation', {}).get('required', False),
            recommendations.get('escalation', {}).get('risk_level', 'low'),
            recommendations.get('escalation', {}).get('reason', ''),
            recommendations.get('efficiency_score', 5.0),
            recommendations.get('training_priority', 'low')
        ))

        conn.commit()
        logger.info(f"✅ Saved recommendations for {recording_id}")

    except Exception as e:
        logger.error(f"Database error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


def process_single_recording(recording_id: str):
    """Generate recommendations for a single recording"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Get transcript and insights
        cursor.execute("""
            SELECT
                t.recording_id,
                t.transcript_text,
                t.customer_name,
                t.employee_name,
                i.customer_sentiment,
                i.call_type,
                i.summary
            FROM transcripts t
            LEFT JOIN insights i ON t.recording_id = i.recording_id
            WHERE t.recording_id = %s
        """, (recording_id,))

        result = cursor.fetchone()

        if result and result['transcript_text']:
            logger.info(f"\n💡 Generating recommendations for {recording_id}")

            # Generate recommendations
            recommendations = generate_recommendations(
                result['transcript_text'],
                result.get('customer_sentiment', 'neutral'),
                result.get('call_type', 'general_inquiry'),
                result.get('customer_name'),
                result.get('employee_name'),
                result.get('summary')
            )

            # Save to database
            save_recommendations_to_db(recording_id, recommendations)

            return recommendations
        else:
            logger.warning(f"No transcript found for {recording_id}")

    except Exception as e:
        logger.error(f"Error processing {recording_id}: {e}")
    finally:
        cursor.close()
        conn.close()

    return None


def process_all_recordings(limit: int = 30):
    """Process all recordings needing recommendations"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Find transcripts without recommendations
        cursor.execute("""
            SELECT
                t.recording_id,
                t.transcript_text,
                t.customer_name,
                t.employee_name,
                i.customer_sentiment,
                i.call_type,
                i.summary
            FROM transcripts t
            LEFT JOIN insights i ON t.recording_id = i.recording_id
            LEFT JOIN call_recommendations r ON t.recording_id = r.recording_id
            WHERE t.transcript_text IS NOT NULL
            AND LENGTH(t.transcript_text) > 100
            AND r.recording_id IS NULL
            ORDER BY t.call_date DESC
            LIMIT %s
        """, (limit,))

        results = cursor.fetchall()
        logger.info(f"📊 Found {len(results)} recordings needing recommendations")

        high_priority_count = 0
        escalation_count = 0

        for i, result in enumerate(results, 1):
            logger.info(f"\n--- Processing {i}/{len(results)} ---")

            # Generate recommendations
            recommendations = generate_recommendations(
                result['transcript_text'],
                result.get('customer_sentiment', 'neutral'),
                result.get('call_type', 'general_inquiry'),
                result.get('customer_name'),
                result.get('employee_name'),
                result.get('summary')
            )

            # Save to database
            save_recommendations_to_db(result['recording_id'], recommendations)

            # Track statistics
            if recommendations.get('training_priority') == 'high':
                high_priority_count += 1
            if recommendations.get('escalation', {}).get('required'):
                escalation_count += 1

            logger.info(f"Recording {result['recording_id']}:")
            logger.info(f"  Training Priority: {recommendations.get('training_priority')}")
            logger.info(f"  Escalation Required: {recommendations.get('escalation', {}).get('required')}")

        logger.info(f"\n✅ Processed {len(results)} recordings")
        logger.info(f"📊 High Priority Training: {high_priority_count}")
        logger.info(f"⚠️ Escalations Required: {escalation_count}")

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()


def generate_team_report():
    """Generate a team-wide recommendations report"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Get common process improvements
        cursor.execute("""
            SELECT
                unnest(process_improvements) as improvement,
                COUNT(*) as frequency
            FROM call_recommendations
            WHERE process_improvements IS NOT NULL
            GROUP BY improvement
            ORDER BY frequency DESC
            LIMIT 10
        """)
        process_improvements = cursor.fetchall()

        # Get common training needs
        cursor.execute("""
            SELECT
                unnest(employee_improvements) as improvement,
                COUNT(*) as frequency
            FROM call_recommendations
            WHERE employee_improvements IS NOT NULL
            GROUP BY improvement
            ORDER BY frequency DESC
            LIMIT 10
        """)
        training_needs = cursor.fetchall()

        # Get escalation statistics
        cursor.execute("""
            SELECT
                risk_level,
                COUNT(*) as count
            FROM call_recommendations
            WHERE escalation_required = true
            GROUP BY risk_level
        """)
        escalations = cursor.fetchall()

        print("\n" + "="*60)
        print("📊 TEAM RECOMMENDATIONS REPORT")
        print("="*60)

        print("\n🔧 TOP PROCESS IMPROVEMENTS NEEDED:")
        for item in process_improvements[:5]:
            print(f"  • {item['improvement']} (mentioned {item['frequency']} times)")

        print("\n📚 TOP TRAINING OPPORTUNITIES:")
        for item in training_needs[:5]:
            print(f"  • {item['improvement']} (affects {item['frequency']} calls)")

        print("\n⚠️ ESCALATION SUMMARY:")
        for item in escalations:
            print(f"  • {item['risk_level'].title()} Risk: {item['count']} calls")

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
            logger.info(f"💡 Generating recommendations for {limit} recordings...")
            process_all_recordings(limit=limit)
        elif sys.argv[1] == '--report':
            # Generate team report
            generate_team_report()
        else:
            # Process specific recording
            recording_id = sys.argv[1]
            logger.info(f"Processing recommendations for: {recording_id}")
            result = process_single_recording(recording_id)

            if result:
                print("\n✅ Recommendations Generated:")
                print("\n🔧 Process Improvements:")
                for improvement in result.get('process_improvements', []):
                    print(f"  • {improvement}")

                print("\n👤 Employee Coaching:")
                print("  Strengths:")
                for strength in result.get('employee_coaching', {}).get('strengths', []):
                    print(f"    • {strength}")
                print("  Areas to Improve:")
                for improvement in result.get('employee_coaching', {}).get('improvements', []):
                    print(f"    • {improvement}")

                print("\n📋 Follow-up Actions:")
                for action in result.get('follow_up_actions', []):
                    print(f"  • {action}")

                if result.get('escalation', {}).get('required'):
                    print(f"\n⚠️ ESCALATION REQUIRED: {result['escalation']['reason']}")
                    print(f"   Risk Level: {result['escalation']['risk_level']}")
    else:
        # Process all recordings
        logger.info("💡 Generating recommendations for all recordings...")
        process_all_recordings(limit=20)
        generate_team_report()


if __name__ == "__main__":
    main()