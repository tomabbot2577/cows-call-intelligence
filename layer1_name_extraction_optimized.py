#!/usr/bin/env python3
"""
Layer 1: Name Extraction - Optimized for Cost
Uses the cheapest/free models for simple name extraction task
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import requests
import json
import sys
import time
import os

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

def call_model(model_key: str, prompt: str) -> dict:
    """Call the specified model through OpenRouter"""
    model = MODELS.get(model_key, PRIMARY_MODEL)

    try:
        print(f"    📡 Calling {model_key} ({model})...")
        response = requests.post(
            OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a name extraction specialist. Extract names from call transcripts and return ONLY valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 150,  # Names don't need many tokens
                "temperature": 0.1  # Low temperature for consistency
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
        print(f"    ❌ HTTP Error: {e.response.status_code} - {error_text[:200]}")
        return {"success": False, "error": f"HTTP {e.response.status_code}", "details": error_text}
    except Exception as e:
        print(f"    ❌ API Error: {e}")
        return {"success": False, "error": str(e)}

def extract_names_from_transcript(transcript_text: str, model_key: str = 'primary') -> dict:
    """Extract customer and employee names using the specified model"""

    # Take first 2500 chars for context (shorter = cheaper)
    transcript_sample = transcript_text[:2500] if len(transcript_text) > 2500 else transcript_text

    # Simple, clear prompt for name extraction
    prompt = f"""Extract the names from this customer service call transcript.

Look for:
1. EMPLOYEE: The company representative (usually introduces themselves)
2. CUSTOMER: The person calling for help

Rules:
- Extract actual names, not titles or roles
- First names are fine if last names aren't mentioned
- Return "Unknown" ONLY if no name is found

Transcript:
{transcript_sample}

Return ONLY this JSON:
{{"customer_name": "name or Unknown", "employee_name": "name or Unknown"}}"""

    response = call_model(model_key, prompt)

    if response["success"]:
        try:
            content = response["content"]

            # Find JSON in response
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
            names = json.loads(json_str)

            customer = names.get('customer_name', 'Unknown')
            employee = names.get('employee_name', 'Unknown')

            # Clean up common issues
            if not customer or customer.lower() in ['null', 'none', '', 'customer', 'n/a']:
                customer = 'Unknown'
            if not employee or employee.lower() in ['null', 'none', '', 'agent', 'employee', 'n/a']:
                employee = 'Unknown'

            print(f"    🎯 Extracted: Customer='{customer}', Employee='{employee}'")

            return {
                "customer_name": customer,
                "employee_name": employee,
                "success": True,
                "model_used": model_key
            }

        except json.JSONDecodeError as e:
            print(f"    ⚠️ JSON parse error: {e}")
            return {
                "customer_name": "Unknown",
                "employee_name": "Unknown",
                "success": False,
                "error": "JSON parse failed"
            }
    else:
        # If primary model fails, try secondary fallback
        if model_key == 'primary':
            print(f"    🔄 Trying secondary model...")
            return extract_names_from_transcript(transcript_text, 'secondary')

        return {
            "customer_name": "Unknown",
            "employee_name": "Unknown",
            "success": False,
            "error": response.get("error")
        }

def test_models_on_sample():
    """Test different models on a sample to find the cheapest working one"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    # Get a sample transcript
    cursor.execute("""
        SELECT recording_id, transcript_text, customer_name, employee_name
        FROM transcripts
        WHERE transcript_text IS NOT NULL
        AND LENGTH(transcript_text) > 500
        LIMIT 1
    """)

    sample = cursor.fetchone()
    cursor.close()
    conn.close()

    if not sample:
        print("❌ No sample transcript found")
        return None

    print(f"\n🧪 Testing models on recording {sample['recording_id']}")
    print(f"   Current names: Customer='{sample['customer_name']}', Employee='{sample['employee_name']}'")
    print("\n" + "="*60)

    results = {}
    for model_key in MODELS.keys():
        print(f"\n📝 Testing {model_key}...")
        result = extract_names_from_transcript(sample['transcript_text'], model_key)
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
            print(f"{status} {model}: Customer='{result['customer_name']}', Employee='{result['employee_name']}'")
        else:
            print(f"{status} {model}: {result.get('error')}")

    if working_models:
        best_model = working_models[0]  # First working model is cheapest
        print(f"\n🏆 BEST MODEL: {best_model}")
        return best_model
    else:
        print("\n❌ No working models found!")
        return None

def process_layer1_batch(model_key: str = None, limit: int = 10):
    """Process Layer 1 name extraction for a batch of recordings"""

    if not model_key:
        print("🔍 Finding best model first...")
        model_key = test_models_on_sample()
        if not model_key:
            print("❌ No working model found. Please check API credits.")
            return

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    # Get recordings needing name extraction
    cursor.execute("""
        SELECT recording_id, transcript_text, customer_name, employee_name
        FROM transcripts
        WHERE (customer_name IS NULL OR customer_name = '' OR customer_name = 'Unknown'
               OR employee_name IS NULL OR employee_name = '' OR employee_name = 'Unknown')
        AND transcript_text IS NOT NULL
        AND LENGTH(transcript_text) > 100
        ORDER BY recording_id
        LIMIT %s
    """, (limit,))

    records = cursor.fetchall()
    print(f"\n🔍 Layer 1: Name Extraction using {model_key}")
    print(f"📊 Found {len(records)} recordings needing name extraction\n")

    success_count = 0
    api_success_count = 0

    for idx, record in enumerate(records, 1):
        rec_id = record['recording_id']
        transcript = record['transcript_text']
        current_customer = record['customer_name']
        current_employee = record['employee_name']

        print(f"[{idx}/{len(records)}] Processing {rec_id}")
        print(f"    Current: Customer='{current_customer}', Employee='{current_employee}'")

        # Extract names using selected model
        result = extract_names_from_transcript(transcript, model_key)

        if result["success"]:
            api_success_count += 1

            # Update database if we got better names
            if result["customer_name"] != "Unknown" or result["employee_name"] != "Unknown":
                cursor.execute("""
                    UPDATE transcripts
                    SET customer_name = %s,
                        employee_name = %s,
                        updated_at = NOW()
                    WHERE recording_id = %s
                """, (result["customer_name"], result["employee_name"], rec_id))

                conn.commit()
                success_count += 1
                print(f"    ✅ Updated database")
            else:
                print(f"    ⏭️ No clear names found")
        else:
            print(f"    ❌ API call failed")

        # Rate limiting
        time.sleep(3)

    cursor.close()
    conn.close()

    print(f"\n📊 Layer 1 Summary:")
    print(f"   Model used: {model_key}")
    print(f"   Total processed: {len(records)}")
    print(f"   API calls successful: {api_success_count}/{len(records)}")
    print(f"   Names updated: {success_count}")
    print(f"   Success rate: {(success_count/len(records)*100):.1f}%" if records else "N/A")

def main():
    """Main entry point"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Test all models to find cheapest')
    parser.add_argument('--model', type=str, help='Specific model to use')
    parser.add_argument('--limit', type=int, default=10, help='Number of records to process')
    args = parser.parse_args()

    if args.test:
        test_models_on_sample()
    else:
        process_layer1_batch(model_key=args.model, limit=args.limit)

if __name__ == "__main__":
    main()