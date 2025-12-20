#!/usr/bin/env python3

import psycopg2
from openai import OpenAI
import os
import json
import sys
import time

# Set up OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

def get_db_connection():
    return psycopg2.connect(
        dbname='call_insights',
        user='call_insights_user',
        password='call_insights_pass',
        host='localhost',
        port=5432
    )

def extract_names_with_ai(transcript_text, recording_id):
    """Extract names using GPT-3.5-turbo with new API"""

    prompt = f"""
    Analyze this call transcript and extract the participant names.

    TRANSCRIPT:
    {transcript_text[:3000]}...

    Extract:
    1. CUSTOMER name (the person calling for help/service)
    2. EMPLOYEE/AGENT name (the company representative helping)

    Return ONLY a JSON object with this exact format:
    {{"customer_name": "extracted name or Unknown", "employee_name": "extracted name or Unknown"}}

    If no clear name is found, use "Unknown" for that field.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a name extraction specialist. Extract customer and employee names from call transcripts. Return JSON only."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.1,
            timeout=30
        )

        result_text = response.choices[0].message.content.strip()
        print(f"  AI Response: {result_text}")

        # Parse JSON response
        try:
            names = json.loads(result_text)
            customer = names.get('customer_name', 'Unknown')
            employee = names.get('employee_name', 'Unknown')

            # Don't use "null" or None as names
            if customer == "null" or customer is None:
                customer = "Unknown"
            if employee == "null" or employee is None:
                employee = "Unknown"

            return customer, employee
        except json.JSONDecodeError:
            print(f"  Failed to parse JSON: {result_text}")
            return "Unknown", "Unknown"

    except Exception as e:
        print(f"  Error extracting names: {e}")
        return "Unknown", "Unknown"

def fix_missing_names():
    """Fix transcripts with missing customer/employee names"""

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get transcripts with missing names
    cursor.execute("""
        SELECT recording_id, transcript_text
        FROM transcripts
        WHERE (customer_name IS NULL OR customer_name = '' OR
               employee_name IS NULL OR employee_name = '')
        AND transcript_text IS NOT NULL
        AND LENGTH(transcript_text) > 100
        ORDER BY recording_id
    """)

    records = cursor.fetchall()
    print(f"🎯 Found {len(records)} recordings with missing names\n")

    success_count = 0
    error_count = 0

    for idx, (recording_id, transcript_text) in enumerate(records, 1):
        print(f"[{idx}/{len(records)}] Processing {recording_id}...")

        # Extract names with AI
        customer_name, employee_name = extract_names_with_ai(transcript_text, recording_id)

        # Always update with at least "Unknown" if blank
        update_fields = []
        update_values = []

        # Get current values
        cursor.execute("""
            SELECT customer_name, employee_name
            FROM transcripts
            WHERE recording_id = %s
        """, (recording_id,))
        current = cursor.fetchone()
        current_customer = current[0] if current else None
        current_employee = current[1] if current else None

        # Update customer name if blank
        if not current_customer or current_customer == '':
            update_fields.append("customer_name = %s")
            update_values.append(customer_name)

        # Update employee name if blank
        if not current_employee or current_employee == '':
            update_fields.append("employee_name = %s")
            update_values.append(employee_name)

        if update_fields:
            update_values.append(recording_id)
            update_sql = f"UPDATE transcripts SET {', '.join(update_fields)} WHERE recording_id = %s"

            try:
                cursor.execute(update_sql, update_values)
                conn.commit()
                success_count += 1
                print(f"  ✅ Updated: customer='{customer_name}', employee='{employee_name}'")
            except Exception as e:
                conn.rollback()
                error_count += 1
                print(f"  ❌ Database error: {e}")
        else:
            print(f"  ⏭️ Skipped - already has names")

        # Rate limiting to avoid API throttling
        if idx % 10 == 0:
            time.sleep(2)  # Pause every 10 requests

    cursor.close()
    conn.close()

    print(f"\n🎯 Completed!")
    print(f"   ✅ Successfully updated: {success_count}")
    print(f"   ❌ Errors: {error_count}")
    print(f"   📊 Total processed: {len(records)}")

if __name__ == "__main__":
    fix_missing_names()