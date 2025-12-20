#!/usr/bin/env python3
"""
Layer 2: Enhanced Sentiment Analysis with Reasoning Fields
Updates existing insights records with reasoning explanations
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import requests
import json
import sys
import time
import os
from datetime import datetime

# OpenRouter configuration
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', 'REDACTED_OPENROUTER_KEY')
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# Database configuration
DB_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': 'REDACTED_DB_PASSWORD',
    'host': 'localhost',
    'port': 5432
}

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

def call_model(model_key: str, prompt: str, max_tokens: int = 500) -> dict:
    """Call the specified model through OpenRouter"""
    model = MODELS.get(model_key, PRIMARY_MODEL)

    try:
        print(f"    📡 Calling {model_key} for enhanced sentiment analysis...")
        response = requests.post(
            OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a call center analyst expert. Analyze customer service calls for sentiment, quality, and key insights with detailed reasoning. Return structured JSON data only."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3  # Lower temp for more consistent analysis
            },
            timeout=30
        )

        response.raise_for_status()
        result = response.json()

        if 'choices' in result and result['choices']:
            content = result['choices'][0]['message']['content']
            print(f"    ✅ Response received: {len(content)} chars")
            return {"success": True, "content": content}
        else:
            return {"success": False, "error": "Invalid response structure"}

    except requests.exceptions.HTTPError as e:
        error_text = e.response.text if e.response else str(e)
        print(f"    ❌ HTTP Error: {e.response.status_code if e.response else 'N/A'}")
        return {"success": False, "error": f"HTTP {e.response.status_code if e.response else 'N/A'}", "details": error_text}
    except Exception as e:
        print(f"    ❌ API Error: {e}")
        return {"success": False, "error": str(e)}

def analyze_sentiment(transcript_text: str, customer_name: str = None, employee_name: str = None, model_key: str = 'primary') -> dict:
    """Analyze sentiment and quality with reasoning explanations"""

    # Take first 4000 chars for analysis (longer = better context but more cost)
    transcript_sample = transcript_text[:4000] if len(transcript_text) > 4000 else transcript_text

    # Include names if available for better context
    context_info = []
    if customer_name and customer_name != 'Unknown':
        context_info.append(f"Customer: {customer_name}")
    if employee_name and employee_name != 'Unknown':
        context_info.append(f"Employee: {employee_name}")

    context = " | ".join(context_info) if context_info else "Names not identified"

    # Enhanced prompt for reasoning
    prompt = f"""Analyze this customer service call transcript carefully.

{context}

TRANSCRIPT:
{transcript_sample}

Analyze and extract:

1. CUSTOMER SENTIMENT: Determine the customer's emotional state
   - positive: Happy, satisfied, grateful, pleased
   - negative: Angry, frustrated, upset, disappointed
   - neutral: Calm, indifferent, business-like

2. SENTIMENT REASONING: Provide a 1 sentence explanation of WHY you gave this sentiment score, citing specific evidence from the call

3. CALL QUALITY SCORE (1-10):
   - 1-3: Poor (unresolved, rude, unprofessional)
   - 4-6: Average (partial resolution, some issues)
   - 7-8: Good (resolved well, professional)
   - 9-10: Excellent (exceeded expectations, great service)

4. QUALITY REASONING: Provide a 1 sentence explanation of WHY you gave this quality score, citing specific agent behaviors or outcomes

5. CALL TYPE: Classify the primary purpose
   - technical_support: Software/hardware issues
   - billing_inquiry: Payment, invoices, charges
   - account_management: Settings, access, permissions
   - complaint: Expressing dissatisfaction
   - sales_inquiry: Pricing, features, purchasing
   - follow_up: Continuing previous conversation
   - cancellation: Ending service/subscription
   - general_inquiry: General questions

6. KEY TOPICS: Extract 3-5 specific topics discussed (e.g., "password reset", "invoice discrepancy", "software bug")

7. ISSUE RESOLUTION:
   - resolved: Problem completely fixed
   - partially_resolved: Some progress made
   - unresolved: No solution provided
   - no_issue: No problem to resolve

8. OVERALL CALL RATING (1-10): Provide a single overall rating combining customer experience and agent performance
   - 1-3: Failed call (angry customer, unresolved issues, poor service)
   - 4-6: Below average (some issues, partial resolution, mediocre service)
   - 7-8: Good call (satisfied customer, good resolution, professional service)
   - 9-10: Excellent call (delighted customer, exceeded expectations)

9. SUMMARY: Write a 1-2 sentence summary focusing on:
   - What the customer needed
   - What action was taken
   - The outcome

10. COACHING NOTES: Provide 2-3 specific, actionable coaching insights for the agent, such as:
    - What they did well and should continue
    - Areas where they could improve
    - Specific phrases or techniques to try

Return ONLY valid JSON:
{{
  "customer_sentiment": "positive|negative|neutral",
  "sentiment_reasoning": "1 sentence explanation with specific evidence",
  "call_quality_score": number (1-10),
  "quality_reasoning": "1 sentence explanation of quality score",
  "overall_call_rating": number (1-10),
  "call_type": "type_from_list",
  "key_topics": ["topic1", "topic2", "topic3"],
  "resolution_status": "resolved|partially_resolved|unresolved|no_issue",
  "first_call_resolution": true|false,
  "follow_up_needed": true|false,
  "escalation_required": true|false,
  "summary": "Clear 1-2 sentence summary",
  "coaching_notes": ["insight1", "insight2", "insight3"]
}}"""

    response = call_model(model_key, prompt)

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

            # Parse JSON
            analysis = json.loads(json_str)

            # Validate and clean results
            sentiment = analysis.get('customer_sentiment', 'neutral')
            if sentiment not in ['positive', 'negative', 'neutral']:
                sentiment = 'neutral'

            sentiment_reasoning = analysis.get('sentiment_reasoning', '')
            if not sentiment_reasoning:
                sentiment_reasoning = f"Sentiment detected as {sentiment} based on call analysis"

            quality_score = analysis.get('call_quality_score', 5)
            if not isinstance(quality_score, (int, float)) or quality_score < 1 or quality_score > 10:
                quality_score = 5

            quality_reasoning = analysis.get('quality_reasoning', '')
            if not quality_reasoning:
                quality_reasoning = f"Call quality rated {quality_score}/10 based on agent performance"

            call_type = analysis.get('call_type', 'general_inquiry')
            valid_types = ['technical_support', 'billing_inquiry', 'account_management',
                          'complaint', 'sales_inquiry', 'follow_up', 'cancellation', 'general_inquiry']
            if call_type not in valid_types:
                call_type = 'general_inquiry'

            key_topics = analysis.get('key_topics', [])
            if not isinstance(key_topics, list):
                key_topics = []
            key_topics = [str(topic) for topic in key_topics[:5]]  # Max 5 topics

            resolution_status = analysis.get('resolution_status', 'unresolved')
            if resolution_status not in ['resolved', 'partially_resolved', 'unresolved', 'no_issue']:
                resolution_status = 'unresolved'

            summary = analysis.get('summary', 'Call summary not available')
            if not summary or len(summary) < 10:
                summary = f"Customer service call regarding {call_type.replace('_', ' ')}"

            # Get overall rating
            overall_rating = analysis.get('overall_call_rating', quality_score)
            if not isinstance(overall_rating, (int, float)) or overall_rating < 1 or overall_rating > 10:
                overall_rating = quality_score  # Default to quality score if invalid

            # Get coaching notes
            coaching_notes = analysis.get('coaching_notes', [])
            if not isinstance(coaching_notes, list):
                coaching_notes = []

            # If no coaching notes from AI, generate based on scores
            if not coaching_notes:
                if quality_score >= 8:
                    coaching_notes.append(f"Excellent service delivery with quality score of {quality_score}/10 - continue these practices")
                elif quality_score >= 6:
                    coaching_notes.append(f"Good service quality ({quality_score}/10) with room for improvement in problem resolution")
                else:
                    coaching_notes.append(f"Focus on improving customer engagement and problem-solving skills")

                if sentiment == 'positive':
                    coaching_notes.append("Successfully maintained positive customer engagement throughout the call")
                elif sentiment == 'negative':
                    coaching_notes.append("Consider using more empathy statements and de-escalation techniques")

                if resolution_status == 'resolved':
                    coaching_notes.append("Excellent job achieving first call resolution")
                elif resolution_status == 'unresolved':
                    coaching_notes.append("Ensure proper follow-up procedures are documented and communicated")

            print(f"    🎯 Analysis: Sentiment={sentiment}, Quality={quality_score}, Overall={overall_rating}, Type={call_type}")
            print(f"    💭 Sentiment reason: {sentiment_reasoning[:80]}...")
            print(f"    📊 Quality reason: {quality_reasoning[:80]}...")
            print(f"    📝 Topics: {', '.join(key_topics[:3]) if key_topics else 'None identified'}")
            print(f"    📚 Coaching insights: {len(coaching_notes)} generated")

            return {
                "customer_sentiment": sentiment,
                "sentiment_reasoning": sentiment_reasoning,
                "call_quality_score": float(quality_score),
                "quality_reasoning": quality_reasoning,
                "overall_call_rating": float(overall_rating),
                "call_type": call_type,
                "key_topics": key_topics,
                "resolution_status": resolution_status,
                "first_call_resolution": analysis.get('first_call_resolution', False),
                "follow_up_needed": analysis.get('follow_up_needed', False),
                "escalation_required": analysis.get('escalation_required', False),
                "summary": summary,
                "coaching_notes": coaching_notes,
                "success": True,
                "model_used": model_key
            }

        except json.JSONDecodeError as e:
            print(f"    ⚠️ JSON parse error: {e}")
            return {
                "customer_sentiment": "neutral",
                "sentiment_reasoning": "Unable to parse AI response",
                "call_quality_score": 5.0,
                "quality_reasoning": "Default score due to parsing error",
                "overall_call_rating": 5.0,
                "call_type": "general_inquiry",
                "key_topics": [],
                "resolution_status": "unresolved",
                "summary": "Analysis failed - JSON parse error",
                "coaching_notes": [],
                "success": False,
                "error": "JSON parse failed"
            }
    else:
        # Try fallback model if primary fails
        if model_key != 'mistral-7b' and 'credits' in response.get('details', '').lower():
            print(f"    🔄 Trying fallback model due to credits issue...")
            return analyze_sentiment(transcript_text, customer_name, employee_name, 'mistral-7b')

        return {
            "customer_sentiment": "neutral",
            "sentiment_reasoning": "Analysis unavailable",
            "call_quality_score": 5.0,
            "quality_reasoning": "Analysis unavailable",
            "overall_call_rating": 5.0,
            "call_type": "general_inquiry",
            "key_topics": [],
            "resolution_status": "unresolved",
            "summary": "Analysis unavailable",
            "coaching_notes": [],
            "success": False,
            "error": response.get("error")
        }

def process_layer2_enhanced(model_key: str = 'gemini-flash', limit: int = 10):
    """Process Layer 2 enhanced sentiment analysis updating existing records"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    # Get recordings that need enhanced Layer 2 processing (have insights but no reasoning fields)
    query = """
        SELECT t.recording_id, t.transcript_text, t.customer_name, t.employee_name
        FROM transcripts t
        INNER JOIN transcript_embeddings te ON t.recording_id = te.recording_id
        INNER JOIN insights i ON t.recording_id = i.recording_id
        WHERE t.transcript_text IS NOT NULL
        AND LENGTH(t.transcript_text) > 100
        AND (i.sentiment_reasoning IS NULL
             OR i.quality_reasoning IS NULL
             OR i.overall_call_rating IS NULL)
        ORDER BY t.recording_id
        LIMIT %s
    """

    cursor.execute(query, (limit,))
    records = cursor.fetchall()

    print(f"\n🔍 Layer 2: Enhanced Sentiment Analysis using {model_key}")
    print(f"📊 Found {len(records)} recordings needing enhanced analysis\n")

    if len(records) == 0:
        print("✅ All records already have enhanced fields!")
        cursor.close()
        conn.close()
        return

    success_count = 0
    api_success_count = 0

    for idx, record in enumerate(records, 1):
        rec_id = record['recording_id']
        transcript = record['transcript_text']
        customer = record['customer_name']
        employee = record['employee_name']

        print(f"[{idx}/{len(records)}] Processing {rec_id}")
        print(f"    Names: Customer='{customer}', Employee='{employee}'")

        # Analyze sentiment with enhanced reasoning
        result = analyze_sentiment(transcript, customer, employee, model_key)

        if result["success"]:
            api_success_count += 1

            try:
                # Join coaching notes into text
                coaching_text = " | ".join(result["coaching_notes"]) if result["coaching_notes"] else None

                # Update existing insights record with enhanced fields
                cursor.execute("""
                    UPDATE insights SET
                        customer_sentiment = %s,
                        sentiment_reasoning = %s,
                        call_quality_score = %s,
                        quality_reasoning = %s,
                        overall_call_rating = %s,
                        call_type = %s,
                        key_topics = %s,
                        resolution_status = %s,
                        first_call_resolution = %s,
                        follow_up_needed = %s,
                        escalation_required = %s,
                        summary = %s,
                        coaching_notes = %s,
                        model_version = %s,
                        confidence_score = %s,
                        updated_at = NOW()
                    WHERE recording_id = %s
                """, (
                    result["customer_sentiment"],
                    result["sentiment_reasoning"],
                    result["call_quality_score"],
                    result["quality_reasoning"],
                    result["overall_call_rating"],
                    result["call_type"],
                    result["key_topics"],
                    result["resolution_status"],
                    result.get("first_call_resolution", False),
                    result.get("follow_up_needed", False),
                    result.get("escalation_required", False),
                    result["summary"],
                    coaching_text,
                    f"layer2_enhanced_{model_key}_v3",
                    0.85,  # Confidence score for this model
                    rec_id
                ))

                conn.commit()
                success_count += 1
                print(f"    ✅ Updated database with enhanced fields")

            except Exception as e:
                conn.rollback()
                print(f"    ❌ Database error: {e}")
        else:
            print(f"    ❌ API call failed: {result.get('error')}")

        # Rate limiting
        time.sleep(3)

    cursor.close()
    conn.close()

    print(f"\n📊 Layer 2 Enhanced Summary:")
    print(f"   Model used: {model_key}")
    print(f"   Total processed: {len(records)}")
    print(f"   API calls successful: {api_success_count}/{len(records)}")
    print(f"   Database updates: {success_count}")
    print(f"   Success rate: {(success_count/len(records)*100):.1f}%" if records else "N/A")

def main():
    """Main entry point"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=str, default='gemini-flash', help='Model to use')
    parser.add_argument('--limit', type=int, default=10, help='Number of records to process')
    args = parser.parse_args()

    process_layer2_enhanced(model_key=args.model, limit=args.limit)

if __name__ == "__main__":
    main()