#!/usr/bin/env python3
"""
Layer 1: Name Extraction using DeepSeek R1
Properly extracts customer and employee names from transcripts
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import requests
import json
import sys
import time
import os

# OpenRouter configuration for DeepSeek R1
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

def call_deepseek_r1(prompt: str) -> dict:
    """Call DeepSeek R1 through OpenRouter API"""
    try:
        print("    📡 Calling DeepSeek R1 for name extraction...")
        response = requests.post(
            OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek/deepseek-r1",
                "messages": [
                    {"role": "system", "content": "You are a name extraction specialist for customer service calls. Extract customer and employee names accurately from transcripts. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 300,
                "temperature": 0.1
            },
            timeout=30
        )

        response.raise_for_status()
        result = response.json()

        if 'choices' in result and result['choices']:
            content = result['choices'][0]['message']['content']
            print(f"    ✅ DeepSeek R1 responded: {len(content)} chars")
            return {"success": True, "content": content}
        else:
            print(f"    ❌ Unexpected response structure: {result}")
            return {"success": False, "error": "Invalid response structure"}

    except requests.exceptions.HTTPError as e:
        print(f"    ❌ HTTP Error: {e.response.status_code} - {e.response.text[:200]}")
        return {"success": False, "error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        print(f"    ❌ API Error: {e}")
        return {"success": False, "error": str(e)}

def extract_names_from_transcript(transcript_text: str) -> dict:
    """Extract customer and employee names using DeepSeek R1"""

    # Take first 3000 chars for context
    transcript_sample = transcript_text[:3000] if len(transcript_text) > 3000 else transcript_text

    prompt = f"""Analyze this customer service call transcript and extract the names of the participants.

Look for:
1. EMPLOYEE/AGENT: The company representative (often introduces themselves at the start)
   - Look for phrases like "Hi, this is [name]", "My name is [name]", "I'm [name]"
   - Often from Main Sequence, PC Recruiter, or similar companies

2. CUSTOMER: The person calling for help/service
   - May introduce themselves or be addressed by name
   - Look for "Hi [name]", "Thank you [name]", "Is this [name]?"

IMPORTANT:
- Extract actual names from the transcript, not generic labels
- If a name appears multiple times, that confirms it
- First names are acceptable if last names aren't mentioned
- Return "Unknown" ONLY if no name is found after careful analysis

Transcript:
{transcript_sample}

Return ONLY valid JSON in this exact format:
{{
    "customer_name": "actual name or Unknown",
    "employee_name": "actual name or Unknown",
    "confidence": "high|medium|low"
}}"""

    response = call_deepseek_r1(prompt)

    if response["success"]:
        try:
            # Extract JSON from response
            content = response["content"]

            # Try to find JSON in the response
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

            # Validate and clean results
            customer = names.get('customer_name', 'Unknown')
            employee = names.get('employee_name', 'Unknown')
            confidence = names.get('confidence', 'low')

            # Don't accept null, empty, or generic values
            if not customer or customer.lower() in ['null', 'none', '', 'customer']:
                customer = 'Unknown'
            if not employee or employee.lower() in ['null', 'none', '', 'agent', 'employee']:
                employee = 'Unknown'

            print(f"    🎯 Extracted: Customer='{customer}', Employee='{employee}' (confidence: {confidence})")

            return {
                "customer_name": customer,
                "employee_name": employee,
                "confidence": confidence,
                "success": True
            }

        except json.JSONDecodeError as e:
            print(f"    ⚠️ JSON parse error: {e}")
            print(f"       Raw content: {response['content'][:200]}")
            return {
                "customer_name": "Unknown",
                "employee_name": "Unknown",
                "confidence": "failed",
                "success": False
            }
    else:
        return {
            "customer_name": "Unknown",
            "employee_name": "Unknown",
            "confidence": "failed",
            "success": False,
            "error": response.get("error")
        }

def process_layer1(recording_id: str = None, limit: int = 10):
    """Process Layer 1 name extraction for recordings"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Get recordings needing name extraction
        if recording_id:
            cursor.execute("""
                SELECT recording_id, transcript_text, customer_name, employee_name
                FROM transcripts
                WHERE recording_id = %s
                AND transcript_text IS NOT NULL
                AND LENGTH(transcript_text) > 100
            """, (recording_id,))
        else:
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
        print(f"\n🔍 Layer 1: Name Extraction using DeepSeek R1")
        print(f"📊 Found {len(records)} recordings to process\n")

        success_count = 0
        api_success_count = 0

        for idx, record in enumerate(records, 1):
            rec_id = record['recording_id']
            transcript = record['transcript_text']
            current_customer = record['customer_name']
            current_employee = record['employee_name']

            print(f"[{idx}/{len(records)}] Processing {rec_id}")
            print(f"    Current: Customer='{current_customer}', Employee='{current_employee}'")

            # Extract names using DeepSeek R1
            result = extract_names_from_transcript(transcript)

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
                print(f"    ✅ Updated database with new names")
            else:
                print(f"    ⏭️ No names extracted")

            # Rate limiting
            time.sleep(2)  # Be respectful to the API

        print(f"\n📊 Layer 1 Summary:")
        print(f"   Total processed: {len(records)}")
        print(f"   API calls successful: {api_success_count}/{len(records)}")
        print(f"   Names updated: {success_count}")
        print(f"   Success rate: {(success_count/len(records)*100):.1f}%" if records else "N/A")

    except Exception as e:
        print(f"❌ Database error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def main():
    """Main entry point"""
    if len(sys.argv) > 1:
        # Process specific recording
        recording_id = sys.argv[1]
        print(f"Processing specific recording: {recording_id}")
        process_layer1(recording_id=recording_id)
    else:
        # Process batch
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        process_layer1(limit=limit)

if __name__ == "__main__":
    main()