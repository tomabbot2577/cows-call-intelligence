#!/usr/bin/env python3
"""
Enhanced AI-Powered Name Extraction System
Uses Claude-3-Opus and employee database for accurate name matching
"""

import os
import sys
import json
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from typing import Dict, Optional, Tuple, List
import re

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


def load_employee_database() -> List[Dict]:
    """Load employee database from config file"""
    try:
        with open('/var/www/call-recording-system/config/employees.json', 'r') as f:
            data = json.load(f)
            return data.get('employees', [])
    except Exception as e:
        logger.warning(f"Could not load employee database: {e}")
        return []


def extract_names_with_ai(transcript: str, employee_list: List[Dict]) -> Dict[str, str]:
    """
    Use AI to extract customer and employee names from transcript
    Enhanced with employee database context
    """

    # Build employee context for the AI
    employee_names = [emp['name'] for emp in employee_list]
    employee_context = "Known employees: " + ", ".join(employee_names[:20])  # First 20 names as context

    prompt = f"""Analyze this call transcript and extract the following information:

1. EMPLOYEE NAME: The person making the call (usually introduces themselves)
   - This is typically someone from PC Recruiter or Main Sequence
   - {employee_context}
   - Look for names like "This is [NAME]" or "I'm [NAME]"

2. EMPLOYEE COMPANY: The company the caller works for
   - Usually PC Recruiter, Main Sequence, or related companies

3. CUSTOMER NAME: The person being called (who they're trying to reach)
   - The person who answers or who left a voicemail
   - Look for full names when mentioned

4. CUSTOMER COMPANY: The company the customer works for
   - May be mentioned in conversation or context clues

Important context clues:
- "$72.91 was charged from PC Recruiter" indicates PC Recruiter is the employee's company
- "Main Sequence" references indicate Main Sequence employees
- Look for credit card names like "Carl V. Richards" which would be the customer
- Employees often say "This is [NAME]" at the beginning

Return in JSON format:
{{
    "employee_name": "full name or Unknown",
    "employee_company": "company name or Unknown",
    "customer_name": "full name or Unknown",
    "customer_company": "company name or Unknown"
}}

Transcript:
""" + transcript[:3000]  # Use first 3000 chars to stay within limits

    try:
        response = requests.post(
            OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "anthropic/claude-3-opus",  # Using Opus for better accuracy
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1,
                "max_tokens": 200
            }
        )

        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']

            # Parse JSON from response
            try:
                # Extract JSON from the response (might have extra text)
                json_match = re.search(r'\{[^}]+\}', content, re.DOTALL)
                if json_match:
                    names = json.loads(json_match.group())

                    # Try to match employee name with database
                    extracted_employee = names.get('employee_name', '')
                    if extracted_employee and extracted_employee != 'Unknown':
                        # Check for partial matches in employee database
                        for emp in employee_list:
                            if extracted_employee.lower() in emp['name'].lower() or emp['name'].lower() in extracted_employee.lower():
                                names['employee_name'] = emp['name']  # Use full name from database
                                if names.get('employee_company') == 'Unknown':
                                    names['employee_company'] = 'Main Sequence'
                                break

                    # If Robin is detected, it's Robin Montoni
                    if 'robin' in extracted_employee.lower() and names['employee_name'] == 'Robin':
                        names['employee_name'] = 'Robin Montoni'
                        if names.get('employee_company') == 'Unknown':
                            names['employee_company'] = 'PC Recruiter'

                    return names
            except:
                pass

        logger.error(f"AI extraction failed: {response.status_code}")

    except Exception as e:
        logger.error(f"Error calling AI: {e}")

    return {
        "employee_name": "Unknown",
        "employee_company": "Unknown",
        "customer_name": "Unknown",
        "customer_company": "Unknown"
    }


def update_transcript_names(recording_id: str, names: Dict[str, str]):
    """Update the database with extracted names"""

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        # Format names for database
        customer_name = names.get('customer_name', 'Unknown')
        if names.get('customer_company') and names['customer_company'] != 'Unknown':
            customer_name = f"{customer_name} ({names['customer_company']})"

        employee_name = names.get('employee_name', 'Unknown')
        if names.get('employee_company') and names['employee_company'] != 'Unknown':
            employee_name = f"{employee_name} ({names['employee_company']})"

        # Update transcripts table
        cursor.execute("""
            UPDATE transcripts
            SET customer_name = %s, employee_name = %s
            WHERE recording_id = %s
        """, (customer_name, employee_name, recording_id))

        # Update embeddings table if exists
        cursor.execute("""
            UPDATE transcript_embeddings
            SET customer_name = %s, employee_name = %s
            WHERE recording_id = %s
        """, (customer_name, employee_name, recording_id))

        conn.commit()
        logger.info(f"Updated {recording_id}: Customer={customer_name}, Employee={employee_name}")

    except Exception as e:
        logger.error(f"Database update failed: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


def process_single_transcript(recording_id: str):
    """Process a single transcript to extract names"""

    # Load employee database
    employee_list = load_employee_database()

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Get transcript
        cursor.execute("""
            SELECT recording_id, transcript_text, customer_name, employee_name
            FROM transcripts
            WHERE recording_id = %s
        """, (recording_id,))

        result = cursor.fetchone()

        if result and result['transcript_text']:
            logger.info(f"\nProcessing {recording_id}")
            logger.info(f"Current: Customer={result['customer_name']}, Employee={result['employee_name']}")

            # Extract names using AI with employee context
            names = extract_names_with_ai(result['transcript_text'], employee_list)
            logger.info(f"Extracted: {names}")

            # Update database
            update_transcript_names(recording_id, names)

            return names
        else:
            logger.warning(f"No transcript found for {recording_id}")

    except Exception as e:
        logger.error(f"Error processing {recording_id}: {e}")
    finally:
        cursor.close()
        conn.close()

    return None


def process_all_unknowns(limit: int = 10):
    """Process all transcripts with Unknown names"""

    # Load employee database
    employee_list = load_employee_database()

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Find transcripts with Unknown names that have actual text
        cursor.execute("""
            SELECT recording_id, transcript_text
            FROM transcripts
            WHERE (customer_name IS NULL OR customer_name = 'Unknown'
                   OR employee_name IS NULL OR employee_name = 'Unknown')
            AND transcript_text IS NOT NULL
            AND LENGTH(transcript_text) > 100
            LIMIT %s
        """, (limit,))

        results = cursor.fetchall()
        logger.info(f"Found {len(results)} transcripts with unknown names and actual text")

        success_count = 0
        for i, result in enumerate(results, 1):
            logger.info(f"\n--- Processing {i}/{len(results)} ---")
            names = extract_names_with_ai(result['transcript_text'], employee_list)
            logger.info(f"Recording {result['recording_id']}: {names}")

            # Count as success if we found at least one name
            if (names['employee_name'] != 'Unknown' or names['customer_name'] != 'Unknown'):
                success_count += 1
                logger.info(f"✓ Successfully extracted names!")

            update_transcript_names(result['recording_id'], names)

        logger.info(f"\n✅ Processed {len(results)} transcripts")
        logger.info(f"📊 Success rate: {success_count}/{len(results)} ({success_count*100//len(results) if results else 0}%)")

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()


def main():
    """Main function"""

    if len(sys.argv) > 1:
        # Process specific recording
        recording_id = sys.argv[1]
        logger.info(f"Processing single recording: {recording_id}")
        result = process_single_transcript(recording_id)

        if result:
            print("\n✅ Name Extraction Complete:")
            print(f"  Employee: {result['employee_name']} from {result['employee_company']}")
            print(f"  Customer: {result['customer_name']} from {result['customer_company']}")
    else:
        # Process all unknowns with actual transcript text
        logger.info("Processing all transcripts with unknown names...")
        process_all_unknowns(limit=50)

        print("\n✅ Batch processing complete!")
        print("Check the logs for details.")


if __name__ == "__main__":
    main()