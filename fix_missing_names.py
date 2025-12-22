#!/usr/bin/env python3

import psycopg2
import openai
import os
import json
import sys

# Set up OpenAI
openai.api_key = os.getenv('OPENAI_API_KEY')

def get_db_connection():
    return psycopg2.connect(
        dbname='call_insights',
        user='call_insights_user',
        password=os.getenv('PG_PASSWORD', ''),
        host='localhost',
        port=5432
    )

def extract_names_with_ai(transcript_text, recording_id):
    """Extract names using GPT-3.5-turbo"""

    prompt = f"""
    Analyze this call transcript and extract the participant names.

    TRANSCRIPT:
    {transcript_text[:3000]}...

    Extract:
    1. CUSTOMER name (the person calling for help/service)
    2. EMPLOYEE/AGENT name (the company representative helping)

    Return ONLY a JSON object with this exact format:
    {{"customer_name": "extracted name or null", "employee_name": "extracted name or null"}}
    """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a name extraction specialist. Extract customer and employee names from call transcripts."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.1,
            timeout=30
        )

        result_text = response.choices[0].message.content.strip()
        print(f"AI Response for {recording_id}: {result_text}")

        # Parse JSON response
        try:
            names = json.loads(result_text)
            return names.get('customer_name'), names.get('employee_name')
        except json.JSONDecodeError:
            print(f"Failed to parse JSON for {recording_id}: {result_text}")
            return None, None

    except Exception as e:
        print(f"Error extracting names for {recording_id}: {e}")
        return None, None

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
    print(f"Found {len(records)} recordings with missing names")

    for recording_id, transcript_text in records:
        print(f"\nProcessing {recording_id}...")

        # Extract names with AI
        customer_name, employee_name = extract_names_with_ai(transcript_text, recording_id)

        if customer_name or employee_name:
            # Update the database
            update_fields = []
            update_values = []

            if customer_name and customer_name != "null":
                update_fields.append("customer_name = %s")
                update_values.append(customer_name)

            if employee_name and employee_name != "null":
                update_fields.append("employee_name = %s")
                update_values.append(employee_name)

            if update_fields:
                update_values.append(recording_id)
                update_sql = f"UPDATE transcripts SET {', '.join(update_fields)} WHERE recording_id = %s"

                cursor.execute(update_sql, update_values)
                conn.commit()

                print(f"✅ Updated {recording_id}: customer='{customer_name}', employee='{employee_name}'")
        else:
            print(f"❌ No names extracted for {recording_id}")

    cursor.close()
    conn.close()
    print(f"\n🎯 Completed fixing missing names!")

if __name__ == "__main__":
    fix_missing_names()