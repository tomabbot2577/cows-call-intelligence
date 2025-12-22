#!/usr/bin/env python3
"""
Complete AI Insights Processing Pipeline
Handles ALL insight generation in one unified script:
- Name extraction (employees, customers, companies)
- Sentiment analysis & quality scoring
- Process recommendations & employee coaching
- Call resolution & loop closure analysis
- Vertex AI RAG indexing for semantic search
"""

import os
import sys
import json
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from typing import Dict, Optional, List
from datetime import datetime
import time

# Add project root to path for imports
sys.path.insert(0, '/var/www/call-recording-system')

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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

# Vertex AI RAG indexer (lazy loaded)
_vertex_indexer = None

def get_vertex_indexer():
    """Get or initialize Vertex AI RAG indexer"""
    global _vertex_indexer
    if _vertex_indexer is None:
        try:
            from src.vertex_ai.rag_indexer import VertexRAGIndexer
            _vertex_indexer = VertexRAGIndexer()
            logger.info("Vertex AI RAG indexer initialized")
        except Exception as e:
            logger.warning(f"Could not initialize Vertex AI indexer: {e}")
            _vertex_indexer = False  # Mark as failed to avoid retrying
    return _vertex_indexer if _vertex_indexer else None

def load_employee_database() -> List[Dict]:
    """Load employee database from config file"""
    try:
        with open('/var/www/call-recording-system/config/employees.json', 'r') as f:
            data = json.load(f)
            return data.get('employees', [])
    except Exception as e:
        logger.warning(f"Could not load employee database: {e}")
        return []

def load_company_database() -> List[Dict]:
    """Load known companies database"""
    try:
        with open('/var/www/call-recording-system/config/known_companies.json', 'r') as f:
            data = json.load(f)
            return data.get('companies', [])
    except Exception as e:
        logger.warning(f"Could not load company database: {e}")
        return []

def call_openrouter_api(model: str, prompt: str, max_tokens: int = 500) -> Dict:
    """Call OpenRouter API with specified model"""
    try:
        response = requests.post(
            OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": max_tokens
            },
            timeout=120
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"OpenRouter API error: {e}")
        return {"error": str(e)}

def extract_json_from_response(content: str) -> Dict:
    """Extract and parse JSON from AI response"""
    try:
        # Try to extract JSON from response
        if "```json" in content:
            json_start = content.find("```json") + 7
            json_end = content.find("```", json_start)
            json_content = content[json_start:json_end].strip()
        elif content.strip().startswith('{'):
            json_content = content.strip()
        else:
            # Look for JSON object in the response
            start = content.find('{')
            end = content.rfind('}') + 1
            if start != -1 and end > start:
                json_content = content[start:end]
            else:
                return {"error": "No JSON found in response", "raw_content": content}

        return json.loads(json_content)
    except Exception as e:
        return {"error": f"JSON parsing error: {e}", "raw_content": content}

def extract_names_with_ai(transcript: str, employee_list: List[Dict], company_list: List[Dict]) -> Dict:
    """Extract employee and customer names using Claude-3-Opus"""

    # Build employee names list for prompt
    employee_names = [emp['name'] for emp in employee_list]
    company_names = [comp['name'] for comp in company_list if comp['type'] in ['employer', 'customer']]

    prompt = f"""Analyze this customer service call transcript and identify the participants.

EMPLOYEE DATABASE (Main Sequence staff):
{', '.join(employee_names)}

KNOWN COMPANIES:
{', '.join(company_names)}

INSTRUCTIONS:
- Main Sequence employees are the ones providing support/service
- Customers are the ones calling for help/support
- Use exact names from the employee database when possible

Return ONLY JSON:
{{
    "employee_name": "exact name from employee database or Unknown",
    "employee_company": "Main Sequence",
    "customer_name": "first name or full name",
    "customer_company": "company name if mentioned or Unknown"
}}

Transcript:
{transcript[:3000]}"""

    # Layer 1: Names - Using Mistral 7B (excellent for extraction tasks, very cheap)
    response = call_openrouter_api("mistralai/mistral-7b-instruct", prompt, 200)

    if "error" not in response:
        content = response["choices"][0]["message"]["content"]
        names = extract_json_from_response(content)
        if "error" not in names:
            logger.info(f"AI Response: {names}")
            return names

    return {
        "employee_name": "Unknown",
        "employee_company": "Main Sequence",
        "customer_name": "Unknown",
        "customer_company": "Unknown"
    }

def analyze_sentiment(transcript: str, customer_name: str, employee_name: str) -> Dict:
    """Analyze sentiment and call quality using DeepSeek R1"""

    prompt = f"""Analyze this customer service call transcript and provide detailed insights.

Customer: {customer_name}
Employee: {employee_name}

Return ONLY JSON:
{{
    "customer_sentiment": "positive|negative|neutral",
    "customer_mood_description": "brief description",
    "call_quality_score": 8.5,
    "call_type": "support|billing|sales|complaint|general|follow_up",
    "key_topics": ["topic1", "topic2", "topic3"],
    "summary": "one sentence summary",
    "issue_resolved": true,
    "follow_up_needed": false,
    "agent_performance": "professional|needs_improvement|excellent",
    "escalation_risk": "low|medium|high"
}}

Transcript:
{transcript[:4000]}"""

    # Layer 2: Sentiment - Using Llama 3.1 8B (great for analysis, very cost-effective)
    response = call_openrouter_api("meta-llama/llama-3.1-8b-instruct", prompt, 400)

    if "error" not in response:
        content = response["choices"][0]["message"]["content"]
        analysis = extract_json_from_response(content)
        if "error" not in analysis:
            return analysis

    return {
        "customer_sentiment": "neutral",
        "call_quality_score": 5.0,
        "call_type": "general_inquiry",
        "key_topics": [],
        "summary": "Call transcript analyzed",
        "issue_resolved": False,
        "follow_up_needed": False
    }

def generate_recommendations(transcript: str, sentiment: str, call_type: str, customer_name: str, employee_name: str) -> Dict:
    """Generate process recommendations using DeepSeek R1"""

    prompt = f"""Analyze this call and provide actionable recommendations.

Customer: {customer_name}
Employee: {employee_name}
Sentiment: {sentiment}
Call Type: {call_type}

Return ONLY JSON:
{{
    "process_improvements": ["improvement1", "improvement2"],
    "employee_coaching": {{
        "strengths": ["strength1", "strength2"],
        "improvements": ["improvement1", "improvement2"],
        "suggested_phrases": ["phrase1", "phrase2"]
    }},
    "follow_up_actions": ["action1", "action2"],
    "knowledge_base_updates": ["update1", "update2"],
    "escalation": {{
        "required": false,
        "risk_level": "low|medium|high",
        "reason": "reason if needed"
    }},
    "efficiency_score": 8.0,
    "training_priority": "low|medium|high"
}}

Transcript:
{transcript[:4000]}"""

    # Layer 3/4: Recommendations/Resolution - Using DeepSeek Chat V3 (best balance for complex reasoning)
    response = call_openrouter_api("deepseek/deepseek-chat", prompt, 600)

    if "error" not in response:
        content = response["choices"][0]["message"]["content"]
        recommendations = extract_json_from_response(content)
        if "error" not in recommendations:
            return recommendations

    return {
        "process_improvements": ["Review standard procedures"],
        "employee_coaching": {
            "strengths": ["Professional communication"],
            "improvements": ["Could improve response time"],
            "suggested_phrases": []
        },
        "follow_up_actions": ["Follow up with customer"],
        "knowledge_base_updates": [],
        "escalation": {"required": False, "risk_level": "low", "reason": ""},
        "efficiency_score": 5.0,
        "training_priority": "low"
    }

def analyze_call_resolution(transcript: str, customer_name: str, employee_name: str, call_type: str) -> Dict:
    """Analyze call resolution and loop closure using DeepSeek R1"""

    prompt = f"""Analyze this call for resolution and closure quality.

Customer: {customer_name}
Employee: {employee_name}
Call Type: {call_type}

Return ONLY JSON:
{{
    "problem_statement": "what was the customer's issue",
    "resolution_status": "resolved|partially_resolved|unresolved|pending",
    "resolution_details": "how was it resolved",
    "follow_up": {{
        "type": "none|employee_callback|customer_action|email_followup",
        "details": "follow-up details",
        "timeline": "when to follow up"
    }},
    "loop_closure": {{
        "solution_summarized": true,
        "understanding_confirmed": true,
        "asked_if_anything_else": true,
        "next_steps_provided": true,
        "timeline_given": true,
        "contact_info_provided": true,
        "closure_score": 8.5
    }},
    "quality_assessment": {{
        "missed_best_practices": ["practice1", "practice2"],
        "improvement_suggestions": ["suggestion1", "suggestion2"],
        "customer_satisfaction_likely": "high|medium|low",
        "call_back_risk": "low|medium|high",
        "escalation_probability": "low|medium|high"
    }}
}}

Transcript:
{transcript[:4000]}"""

    # Layer 3/4: Recommendations/Resolution - Using DeepSeek Chat V3 (best balance for complex reasoning)
    response = call_openrouter_api("deepseek/deepseek-chat", prompt, 600)

    if "error" not in response:
        content = response["choices"][0]["message"]["content"]
        resolution = extract_json_from_response(content)
        if "error" not in resolution:
            return resolution

    return {
        "problem_statement": "Customer inquiry processed",
        "resolution_status": "unresolved",
        "resolution_details": "",
        "follow_up": {"type": "none", "details": "", "timeline": ""},
        "loop_closure": {
            "solution_summarized": False,
            "understanding_confirmed": False,
            "asked_if_anything_else": False,
            "next_steps_provided": False,
            "timeline_given": False,
            "contact_info_provided": False,
            "closure_score": 5.0
        },
        "quality_assessment": {
            "missed_best_practices": [],
            "improvement_suggestions": [],
            "customer_satisfaction_likely": "medium",
            "call_back_risk": "medium",
            "escalation_probability": "low"
        }
    }

def generate_embeddings(text: str) -> List[float]:
    """Generate embeddings using OpenAI"""
    if not OPENAI_API_KEY:
        return []

    try:
        import openai
        openai.api_key = OPENAI_API_KEY

        response = openai.Embedding.create(
            input=text[:8000],  # Limit text length
            model="text-embedding-ada-002"
        )
        return response['data'][0]['embedding']
    except Exception as e:
        logger.warning(f"Embeddings generation failed: {e}")
        return []

def save_complete_insights(recording_id: str, names: Dict, sentiment: Dict, recommendations: Dict, resolution: Dict):
    """Save all insights to database"""

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        # Update transcript names
        cursor.execute("""
            UPDATE transcripts
            SET customer_name = %s, employee_name = %s, customer_company = %s
            WHERE recording_id = %s
        """, (names['customer_name'], names['employee_name'], names['customer_company'], recording_id))

        # Insert/update insights
        cursor.execute("""
            INSERT INTO insights (
                recording_id, customer_sentiment, call_quality_score, call_type,
                key_topics, summary, follow_up_needed, escalation_required
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (recording_id) DO UPDATE SET
                customer_sentiment = EXCLUDED.customer_sentiment,
                call_quality_score = EXCLUDED.call_quality_score,
                call_type = EXCLUDED.call_type,
                key_topics = EXCLUDED.key_topics,
                summary = EXCLUDED.summary,
                follow_up_needed = EXCLUDED.follow_up_needed,
                escalation_required = EXCLUDED.escalation_required
        """, (
            recording_id, sentiment['customer_sentiment'], sentiment['call_quality_score'],
            sentiment['call_type'], sentiment['key_topics'], sentiment['summary'],
            sentiment['follow_up_needed'], sentiment.get('escalation_risk') == 'high'
        ))

        # Insert/update recommendations
        cursor.execute("""
            INSERT INTO call_recommendations (
                recording_id, process_improvements, employee_strengths, employee_improvements,
                suggested_phrases, follow_up_actions, knowledge_base_updates,
                escalation_required, risk_level, escalation_reason, efficiency_score, training_priority
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
                training_priority = EXCLUDED.training_priority
        """, (
            recording_id, recommendations['process_improvements'],
            recommendations['employee_coaching']['strengths'],
            recommendations['employee_coaching']['improvements'],
            recommendations['employee_coaching']['suggested_phrases'],
            recommendations['follow_up_actions'], recommendations['knowledge_base_updates'],
            recommendations['escalation']['required'], recommendations['escalation']['risk_level'],
            recommendations['escalation']['reason'], recommendations['efficiency_score'],
            recommendations['training_priority']
        ))

        # Insert/update resolutions
        loop_closure = resolution['loop_closure']
        quality = resolution['quality_assessment']
        cursor.execute("""
            INSERT INTO call_resolutions (
                recording_id, problem_statement, resolution_status, resolution_details,
                follow_up_type, follow_up_details, follow_up_timeline,
                solution_summarized, understanding_confirmed, asked_if_anything_else,
                next_steps_provided, timeline_given, contact_info_provided, closure_score,
                missed_best_practices, improvement_suggestions, customer_satisfaction_likely,
                call_back_risk, escalation_probability
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
                escalation_probability = EXCLUDED.escalation_probability
        """, (
            recording_id, resolution['problem_statement'], resolution['resolution_status'],
            resolution['resolution_details'], resolution['follow_up']['type'],
            resolution['follow_up']['details'], resolution['follow_up']['timeline'],
            loop_closure['solution_summarized'], loop_closure['understanding_confirmed'],
            loop_closure['asked_if_anything_else'], loop_closure['next_steps_provided'],
            loop_closure['timeline_given'], loop_closure['contact_info_provided'],
            loop_closure['closure_score'], quality['missed_best_practices'],
            quality['improvement_suggestions'], quality['customer_satisfaction_likely'],
            quality['call_back_risk'], quality['escalation_probability']
        ))

        conn.commit()
        logger.info(f"✅ Complete insights saved for {recording_id}")

    except Exception as e:
        logger.error(f"Database error for {recording_id}: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def process_single_transcript(recording_id: str) -> bool:
    """Process complete insights for a single transcript"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Get transcript
        cursor.execute("""
            SELECT recording_id, transcript_text, customer_name, employee_name
            FROM transcripts
            WHERE recording_id = %s AND transcript_text IS NOT NULL AND LENGTH(transcript_text) > 100
        """, (recording_id,))

        result = cursor.fetchone()
        if not result:
            logger.warning(f"No valid transcript for {recording_id}")
            return False

        transcript = result['transcript_text']
        logger.info(f"\n🔥 Processing complete insights for {recording_id}")

        # Load databases
        employee_list = load_employee_database()
        company_list = load_company_database()

        # Step 1: Extract names
        logger.info("  🔍 1/4 Extracting names...")
        names = extract_names_with_ai(transcript, employee_list, company_list)

        # Step 2: Analyze sentiment
        logger.info("  🎭 2/4 Analyzing sentiment...")
        sentiment = analyze_sentiment(transcript, names['customer_name'], names['employee_name'])

        # Step 3: Generate recommendations
        logger.info("  💡 3/4 Generating recommendations...")
        recommendations = generate_recommendations(
            transcript, sentiment['customer_sentiment'], sentiment['call_type'],
            names['customer_name'], names['employee_name']
        )

        # Step 4: Analyze resolution
        logger.info("  ✅ 4/4 Analyzing resolution...")
        resolution = analyze_call_resolution(
            transcript, names['customer_name'], names['employee_name'], sentiment['call_type']
        )

        # Save all insights
        save_complete_insights(recording_id, names, sentiment, recommendations, resolution)

        # Index in Vertex AI RAG for semantic search
        indexer = get_vertex_indexer()
        if indexer:
            try:
                # Get call metadata from database
                cursor.execute("""
                    SELECT call_date, call_time, duration_seconds, direction,
                           from_number, to_number, word_count
                    FROM transcripts WHERE recording_id = %s
                """, (recording_id,))
                call_meta = cursor.fetchone()

                # Build metadata for Vertex AI
                metadata = {
                    # Call info
                    'call_date': str(call_meta.get('call_date', '')) if call_meta else '',
                    'call_time': str(call_meta.get('call_time', '')) if call_meta else '',
                    'duration_seconds': call_meta.get('duration_seconds', 0) if call_meta else 0,
                    'direction': call_meta.get('direction', '') if call_meta else '',
                    'from_number': call_meta.get('from_number', '') if call_meta else '',
                    'to_number': call_meta.get('to_number', '') if call_meta else '',
                    'word_count': call_meta.get('word_count', 0) if call_meta else 0,

                    # Layer 1: Names
                    'customer_name': names.get('customer_name', ''),
                    'customer_company': names.get('customer_company', ''),
                    'employee_name': names.get('employee_name', ''),

                    # Layer 2: Sentiment
                    'customer_sentiment': sentiment.get('customer_sentiment', ''),
                    'call_quality_score': sentiment.get('call_quality_score', 0),
                    'call_type': sentiment.get('call_type', ''),
                    'key_topics': sentiment.get('key_topics', []),
                    'summary': sentiment.get('summary', ''),
                    'follow_up_needed': sentiment.get('follow_up_needed', False),
                    'coaching_notes': sentiment.get('coaching_notes', ''),

                    # Layer 3: Resolution
                    'resolution_status': resolution.get('resolution_status', ''),
                    'closure_score': resolution.get('loop_closure', {}).get('closure_score', 0),
                    'empathy_score': resolution.get('performance_scores', {}).get('empathy_score', 0),
                    'churn_risk': resolution.get('risk_assessment', {}).get('churn_risk', ''),

                    # Layer 4: Recommendations
                    'process_improvements': recommendations.get('process_improvements', []),
                    'employee_strengths': recommendations.get('employee_coaching', {}).get('strengths', []),
                    'employee_improvements': recommendations.get('employee_coaching', {}).get('improvements', []),
                    'efficiency_score': recommendations.get('efficiency_score', 0),
                    'escalation_required': recommendations.get('escalation', {}).get('required', False),
                }

                indexer.index_transcript(recording_id, transcript, metadata)
                logger.info(f"  📤 Indexed in Vertex AI RAG")
            except Exception as e:
                logger.warning(f"  ⚠️ Vertex AI indexing failed: {e}")

        logger.info(f"  ✅ Complete processing finished for {recording_id}")
        logger.info(f"     Employee: {names['employee_name']}, Customer: {names['customer_name']}")
        logger.info(f"     Sentiment: {sentiment['customer_sentiment']}, Quality: {sentiment['call_quality_score']}/10")
        logger.info(f"     Resolution: {resolution['resolution_status']}, Closure: {resolution['loop_closure']['closure_score']}/10")

        return True

    except Exception as e:
        logger.error(f"Error processing {recording_id}: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def process_batch(limit: int = 50):
    """Process a batch of transcripts needing complete insights"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Find transcripts without complete insights (no longer requires embeddings table)
        cursor.execute("""
            SELECT t.recording_id
            FROM transcripts t
            WHERE t.transcript_text IS NOT NULL
            AND LENGTH(t.transcript_text) > 100
            AND NOT EXISTS (
                SELECT 1 FROM insights i
                WHERE i.recording_id = t.recording_id
                AND i.customer_sentiment IS NOT NULL
            )
            ORDER BY t.call_date DESC
            LIMIT %s
        """, (limit,))

        recording_ids = [row['recording_id'] for row in cursor.fetchall()]

        if not recording_ids:
            logger.info("✅ No transcripts need processing")
            return

        logger.info(f"🚀 Processing {len(recording_ids)} transcripts with complete AI pipeline")

        success_count = 0
        for i, recording_id in enumerate(recording_ids, 1):
            logger.info(f"\n--- Processing {i}/{len(recording_ids)} ---")

            if process_single_transcript(recording_id):
                success_count += 1

            # Rate limiting
            time.sleep(2)

        logger.info(f"\n🎉 Batch complete: {success_count}/{len(recording_ids)} successful")

    finally:
        cursor.close()
        conn.close()

def main():
    """Main function"""

    if len(sys.argv) > 1:
        if sys.argv[1] == '--all':
            # Process all transcripts
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
            logger.info(f"🔥 Starting complete AI pipeline for {limit} transcripts")
            process_batch(limit=limit)
        else:
            # Process specific recording
            recording_id = sys.argv[1]
            logger.info(f"Processing complete insights for: {recording_id}")
            success = process_single_transcript(recording_id)
            if success:
                logger.info("✅ Complete insights generated successfully!")
            else:
                logger.error("❌ Processing failed")
    else:
        # Process batch
        logger.info("🔥 Starting complete AI pipeline...")
        process_batch(limit=50)

if __name__ == "__main__":
    main()