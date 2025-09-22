#!/usr/bin/env python3
"""
Layer 2: Sentiment & Quality Analysis - Optimized for Cost and Accuracy
Uses the cheapest effective models for sentiment analysis
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
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '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')
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# Database configuration
DB_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': 'call_insights_pass',
    'host': 'localhost',
    'port': 5432
}

# CHEAPEST MODELS FOR SENTIMENT ANALYSIS (tested and effective)
MODELS = {
    'gemini-flash': 'google/gemini-flash-1.5',  # Best for sentiment (often free)
    'gemini-flash-8b': 'google/gemini-flash-1.5-8b',  # Even cheaper backup
    'mistral-7b': 'mistralai/mistral-7b-instruct',  # Good quality, cheap
    'llama-3.2-3b': 'meta-llama/llama-3.2-3b-instruct',  # Smallest, cheapest
}

def call_model(model_key: str, prompt: str, max_tokens: int = 500) -> dict:
    """Call the specified model through OpenRouter"""
    model = MODELS.get(model_key, MODELS['gemini-flash'])

    try:
        print(f"    📡 Calling {model_key} for sentiment analysis...")
        response = requests.post(
            OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a call center analyst expert. Analyze customer service calls for sentiment, quality, and key insights. Return structured JSON data only."},
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

def analyze_sentiment(transcript_text: str, customer_name: str = None, employee_name: str = None, model_key: str = 'gemini-flash') -> dict:
    """Analyze sentiment and quality with improved prompting"""

    # Take first 4000 chars for analysis (longer = better context but more cost)
    transcript_sample = transcript_text[:4000] if len(transcript_text) > 4000 else transcript_text

    # Include names if available for better context
    context_info = []
    if customer_name and customer_name != 'Unknown':
        context_info.append(f"Customer: {customer_name}")
    if employee_name and employee_name != 'Unknown':
        context_info.append(f"Employee: {employee_name}")

    context = " | ".join(context_info) if context_info else "Names not identified"

    # Enhanced prompt for better insights
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
  "summary": "Clear 1-2 sentence summary"
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

            print(f"    🎯 Analysis: Sentiment={sentiment}, Quality={quality_score}, Type={call_type}")
            print(f"    💭 Sentiment reason: {sentiment_reasoning[:80]}...")
            print(f"    📊 Quality reason: {quality_reasoning[:80]}...")
            print(f"    📝 Topics: {', '.join(key_topics[:3]) if key_topics else 'None identified'}")

            # Get overall rating
            overall_rating = analysis.get('overall_call_rating', quality_score)
            if not isinstance(overall_rating, (int, float)) or overall_rating < 1 or overall_rating > 10:
                overall_rating = quality_score  # Default to quality score if invalid

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
                "success": True,
                "model_used": model_key
            }

        except json.JSONDecodeError as e:
            print(f"    ⚠️ JSON parse error: {e}")
            return {
                "customer_sentiment": "neutral",
                "call_quality_score": 5.0,
                "call_type": "general_inquiry",
                "key_topics": [],
                "resolution_status": "unresolved",
                "summary": "Analysis failed - JSON parse error",
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
            "call_quality_score": 5.0,
            "call_type": "general_inquiry",
            "key_topics": [],
            "resolution_status": "unresolved",
            "summary": "Analysis unavailable",
            "success": False,
            "error": response.get("error")
        }

def test_models_on_sample():
    """Test different models to find the best one for sentiment"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    # Get a sample transcript with names
    cursor.execute("""
        SELECT recording_id, transcript_text, customer_name, employee_name
        FROM transcripts
        WHERE transcript_text IS NOT NULL
        AND LENGTH(transcript_text) > 1000
        AND customer_name IS NOT NULL AND customer_name != 'Unknown'
        LIMIT 1
    """)

    sample = cursor.fetchone()
    cursor.close()
    conn.close()

    if not sample:
        print("❌ No sample transcript found")
        return None

    print(f"\n🧪 Testing sentiment models on recording {sample['recording_id']}")
    print(f"   Customer: {sample['customer_name']}, Employee: {sample['employee_name']}")
    print("\n" + "="*60)

    results = {}
    for model_key in MODELS.keys():
        print(f"\n📝 Testing {model_key}...")
        result = analyze_sentiment(
            sample['transcript_text'],
            sample['customer_name'],
            sample['employee_name'],
            model_key
        )
        results[model_key] = result

        if result['success']:
            print(f"   ✅ Success!")
        else:
            print(f"   ❌ Failed: {result.get('error')}")

        time.sleep(2)  # Rate limiting

    # Find best working model
    working_models = [k for k, v in results.items() if v['success']]

    print("\n" + "="*60)
    print("📊 RESULTS SUMMARY:")
    for model, result in results.items():
        status = "✅" if result['success'] else "❌"
        if result['success']:
            print(f"{status} {model}:")
            print(f"   - Sentiment: {result['customer_sentiment']}")
            print(f"   - Quality: {result['call_quality_score']}")
            print(f"   - Type: {result['call_type']}")
            print(f"   - Topics: {', '.join(result['key_topics'][:3]) if result['key_topics'] else 'None'}")
        else:
            print(f"{status} {model}: {result.get('error')}")

    if working_models:
        best_model = working_models[0]  # First working model is cheapest
        print(f"\n🏆 BEST MODEL: {best_model}")
        return best_model
    else:
        print("\n❌ No working models found!")
        return None

def process_layer2_batch(model_key: str = None, limit: int = 10):
    """Process Layer 2 sentiment analysis for a batch of recordings"""

    if not model_key:
        print("🔍 Finding best model first...")
        model_key = test_models_on_sample()
        if not model_key:
            print("❌ No working model found. Please check API credits.")
            return

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    # Get recordings needing Layer 2 analysis
    cursor.execute("""
        SELECT t.recording_id, t.transcript_text, t.customer_name, t.employee_name
        FROM transcripts t
        WHERE t.transcript_text IS NOT NULL
        AND LENGTH(t.transcript_text) > 100
        AND NOT EXISTS (
            SELECT 1 FROM insights i
            WHERE i.recording_id = t.recording_id
        )
        ORDER BY t.recording_id
        LIMIT %s
    """, (limit,))

    records = cursor.fetchall()
    print(f"\n🔍 Layer 2: Sentiment Analysis using {model_key}")
    print(f"📊 Found {len(records)} recordings needing analysis\n")

    success_count = 0
    api_success_count = 0

    for idx, record in enumerate(records, 1):
        rec_id = record['recording_id']
        transcript = record['transcript_text']
        customer = record['customer_name']
        employee = record['employee_name']

        print(f"[{idx}/{len(records)}] Processing {rec_id}")
        print(f"    Names: Customer='{customer}', Employee='{employee}'")

        # Analyze sentiment using selected model
        result = analyze_sentiment(transcript, customer, employee, model_key)

        if result["success"]:
            api_success_count += 1

            # Insert into insights table with reasoning
            try:
                # Generate coaching notes based on the analysis
                coaching_notes = []

                # Add coaching based on quality score
                quality_score = result.get('call_quality_score', 5)
                if quality_score >= 8:
                    coaching_notes.append(f"Excellent service delivery with quality score of {quality_score}/10")
                elif quality_score >= 6:
                    coaching_notes.append(f"Good service with room for improvement (quality: {quality_score}/10)")
                else:
                    coaching_notes.append(f"Service needs improvement (quality: {quality_score}/10)")

                # Add sentiment-based coaching
                sentiment = result.get('customer_sentiment', 'neutral')
                if sentiment == 'positive':
                    coaching_notes.append("Successfully maintained positive customer engagement")
                elif sentiment == 'negative':
                    coaching_notes.append("Focus on de-escalation and empathy techniques")
                else:
                    coaching_notes.append("Customer remained neutral - opportunity to create positive experience")

                # Add resolution-based coaching
                resolution = result.get('resolution_status', 'unresolved')
                if resolution == 'resolved':
                    coaching_notes.append("Great job resolving the issue completely")
                elif resolution == 'partially_resolved':
                    coaching_notes.append("Consider additional follow-up to fully resolve issues")
                elif resolution == 'unresolved':
                    coaching_notes.append("Work on problem-solving skills and resource utilization")

                # Add specific insights from reasoning
                if result.get('sentiment_reasoning'):
                    coaching_notes.append(f"Key insight: {result['sentiment_reasoning']}")

                # Add overall rating guidance
                overall_rating = result.get('overall_call_rating', quality_score)
                if overall_rating >= 9:
                    coaching_notes.append("Outstanding call performance - share as training example")
                elif overall_rating <= 4:
                    coaching_notes.append("Priority coaching needed on customer service fundamentals")

                # Combine into coaching text
                coaching_text = " | ".join(coaching_notes)

                cursor.execute("""
                    INSERT INTO insights (
                        recording_id,
                        customer_sentiment,
                        call_quality_score,
                        call_type,
                        key_topics,
                        resolution_status,
                        first_call_resolution,
                        follow_up_needed,
                        escalation_required,
                        summary,
                        coaching_notes,
                        model_version,
                        confidence_score,
                        created_at,
                        updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                    )
                    ON CONFLICT (recording_id) DO UPDATE SET
                        customer_sentiment = EXCLUDED.customer_sentiment,
                        call_quality_score = EXCLUDED.call_quality_score,
                        call_type = EXCLUDED.call_type,
                        key_topics = EXCLUDED.key_topics,
                        resolution_status = EXCLUDED.resolution_status,
                        first_call_resolution = EXCLUDED.first_call_resolution,
                        follow_up_needed = EXCLUDED.follow_up_needed,
                        escalation_required = EXCLUDED.escalation_required,
                        summary = EXCLUDED.summary,
                        coaching_notes = EXCLUDED.coaching_notes,
                        model_version = EXCLUDED.model_version,
                        updated_at = NOW()
                """, (
                    rec_id,
                    result["customer_sentiment"],
                    result["call_quality_score"],
                    result["call_type"],
                    result["key_topics"],
                    result["resolution_status"],
                    result.get("first_call_resolution", False),
                    result.get("follow_up_needed", False),
                    result.get("escalation_required", False),
                    result["summary"],
                    coaching_text,  # Fixed: use coaching_text instead of reasoning_text
                    f"layer2_{model_key}_v2",
                    0.85,  # Confidence score for this model
                ))

                conn.commit()
                success_count += 1
                print(f"    ✅ Saved to database")

            except Exception as e:
                conn.rollback()
                print(f"    ❌ Database error: {e}")
        else:
            print(f"    ❌ API call failed")

        # Rate limiting
        time.sleep(3)

    cursor.close()
    conn.close()

    print(f"\n📊 Layer 2 Summary:")
    print(f"   Model used: {model_key}")
    print(f"   Total processed: {len(records)}")
    print(f"   API calls successful: {api_success_count}/{len(records)}")
    print(f"   Database updates: {success_count}")
    print(f"   Success rate: {(success_count/len(records)*100):.1f}%" if records else "N/A")

def main():
    """Main entry point"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Test all models to find best one')
    parser.add_argument('--model', type=str, help='Specific model to use')
    parser.add_argument('--limit', type=int, default=10, help='Number of records to process')
    args = parser.parse_args()

    if args.test:
        test_models_on_sample()
    else:
        process_layer2_batch(model_key=args.model, limit=args.limit)

if __name__ == "__main__":
    main()