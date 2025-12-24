#!/usr/bin/env python3
"""
Advanced AI-Powered Name Extraction System
Uses Claude-3-Opus with enhanced prompts and company/employee databases
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
    'password': os.getenv('PG_PASSWORD', ''),
    'host': 'localhost',
    'port': 5432
}

# OpenRouter configuration
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '''')
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


def load_company_database() -> List[Dict]:
    """Load known companies database"""
    try:
        with open('/var/www/call-recording-system/config/known_companies.json', 'r') as f:
            data = json.load(f)
            return data.get('companies', [])
    except Exception as e:
        logger.warning(f"Could not load company database: {e}")
        return []


def extract_names_with_ai(transcript: str, employee_list: List[Dict], company_list: List[Dict]) -> Dict[str, str]:
    """
    Use AI to extract customer and employee names from transcript
    Enhanced with employee and company database context
    """

    # Build context for the AI
    employee_names = [emp['name'] for emp in employee_list]
    company_names = [comp['name'] for comp in company_list]

    # Create employee name mapping
    employee_context = ", ".join(employee_names[:15])
    company_context = ", ".join(company_names[:10])

    prompt = f"""You are an expert at extracting names and companies from call transcripts. Analyze this business call transcript carefully.

CONTEXT:
- PC Recruiter and Main Sequence are the VENDORS providing software/support
- ALL employees work for PC Recruiter or Main Sequence
- Everyone calling IN for support are CUSTOMERS (recruiting firms, staffing companies)
- Known employees (work for PCR/Main Sequence): {employee_context}
- Known customer companies (who use our software): {company_context}

EXTRACTION RULES:
1. EMPLOYEE (The Caller/Agent):
   - CRITICAL: ONLY these people are employees: {employee_context}
   - If a name is NOT in this list, they are a CUSTOMER, not an employee
   - Employees are from Main Sequence or PC Recruiter
   - Look for: "This is [NAME]", "Hi, this is [NAME]", "I'm [NAME]"
   - Often says their extension number (e.g., "extension 5466")

2. CUSTOMER (The Client/Recipient):
   - ANYONE whose name is NOT in the employee list above
   - Even if they say "This is [NAME]", if they're not in the employee list, they're a customer
   - Look for: "Hello [NAME]", "Hi [NAME]", "trying to reach [NAME]"
   - In voicemails: "You've reached [NAME]"
   - The person with credit card info or account issues
   - Their name might appear in: "the name on the card is [NAME]"

3. COMPANIES:
   - Employee company: Always Main Sequence or PC Recruiter (the vendors)
   - Customer company: The recruiting/staffing firm calling for support
   - If "$X was charged from PC Recruiter" - this is a billing charge TO the customer
   - Customer companies are firms like Stratos Partners, Cornerstone, Eisner Amper, etc.
   - Check voicemail greetings for customer company names

CRITICAL DISTINCTIONS:
- If someone says "This is Robin with Main Sequence", Robin is the EMPLOYEE
- If the transcript says "Hello, you've reached Dave", Dave is the CUSTOMER
- The person providing credit card info is usually the CUSTOMER
- The person asking about billing/accounts is usually the CUSTOMER

Return ONLY this JSON (no other text):
{{
    "employee_name": "First Last",
    "employee_company": "Company Name",
    "customer_name": "First Last",
    "customer_company": "Company Name"
}}

Use "Unknown" only if you cannot find the information.

Transcript to analyze:
{transcript[:3500]}"""

    try:
        response = requests.post(
            OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "anthropic/claude-3-opus",  # Best model for accuracy
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1,  # Low temperature for consistency
                "max_tokens": 200
            },
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']

            # Parse JSON from response
            try:
                # Extract JSON from the response
                json_match = re.search(r'\{.*?\}', content, re.DOTALL)
                if json_match:
                    names = json.loads(json_match.group())

                    # Post-process: STRICT validation with employee list
                    extracted_employee = names.get('employee_name', '')

                    # CRITICAL: Validate employee name against the list
                    employee_found = False
                    if extracted_employee and extracted_employee != 'Unknown':
                        for emp in employee_list:
                            # Check if extracted name matches a known employee
                            emp_first = emp['name'].split()[0].lower()
                            emp_last = emp['name'].split()[-1].lower() if len(emp['name'].split()) > 1 else ''
                            extracted_lower = extracted_employee.lower()

                            if (emp_first in extracted_lower or
                                (emp_last and emp_last in extracted_lower) or
                                emp['name'].lower() in extracted_lower):
                                names['employee_name'] = emp['name']
                                employee_found = True
                                break

                    # If the extracted "employee" is NOT in our list, they're actually a customer
                    if not employee_found and extracted_employee != 'Unknown':
                        logger.info(f"⚠️ '{extracted_employee}' not in employee list, marking as customer")
                        # Swap the names - this person is actually the customer
                        if names.get('customer_name') == 'Unknown':
                            names['customer_name'] = extracted_employee
                        names['employee_name'] = 'Unknown'

                    # Match company names
                    if names.get('customer_company'):
                        for comp in company_list:
                            if any(alias.lower() in names['customer_company'].lower()
                                   for alias in [comp['name']] + comp.get('aliases', [])):
                                names['customer_company'] = comp['name']
                                break

                    # Default company assignments
                    if names.get('employee_name') != 'Unknown' and names.get('employee_company') == 'Unknown':
                        # If we know the employee but not their company, it's likely Main Sequence or PC Recruiter
                        for emp in employee_list:
                            if emp['name'] == names['employee_name']:
                                names['employee_company'] = 'Main Sequence'
                                break

                    logger.info(f"AI Response: {names}")
                    return names
            except Exception as e:
                logger.error(f"JSON parsing error: {e}, Content: {content}")

        else:
            logger.error(f"AI extraction failed: {response.status_code} - {response.text}")

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
        logger.info(f"✅ Updated {recording_id}: Customer={customer_name}, Employee={employee_name}")

    except Exception as e:
        logger.error(f"Database update failed: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


def process_single_transcript(recording_id: str):
    """Process a single transcript to extract names"""

    # Load databases
    employee_list = load_employee_database()
    company_list = load_company_database()

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
            logger.info(f"\n🔍 Processing {recording_id}")
            logger.info(f"Current: Customer={result['customer_name']}, Employee={result['employee_name']}")

            # Extract names using AI with context
            names = extract_names_with_ai(result['transcript_text'], employee_list, company_list)
            logger.info(f"🎯 Extracted: {names}")

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

    # Load databases
    employee_list = load_employee_database()
    company_list = load_company_database()

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Find transcripts with Unknown names that have actual text
        cursor.execute("""
            SELECT recording_id, transcript_text
            FROM transcripts
            WHERE (customer_name IS NULL OR customer_name = 'Unknown' OR customer_name NOT LIKE %s
                   OR employee_name IS NULL OR employee_name = 'Unknown' OR employee_name NOT LIKE %s)
            AND transcript_text IS NOT NULL
            AND LENGTH(transcript_text) > 100
            ORDER BY call_date DESC
            LIMIT %s
        """, ('%(%%', '%(%%', limit))

        results = cursor.fetchall()
        logger.info(f"📊 Found {len(results)} transcripts to process")

        success_count = 0
        for i, result in enumerate(results, 1):
            logger.info(f"\n--- Processing {i}/{len(results)} ---")
            names = extract_names_with_ai(result['transcript_text'], employee_list, company_list)

            # Count as success if we found at least one name
            if (names['employee_name'] != 'Unknown' or names['customer_name'] != 'Unknown'):
                success_count += 1
                logger.info(f"✓ Successfully extracted names!")

            update_transcript_names(result['recording_id'], names)

        logger.info(f"\n✅ Batch complete: {success_count}/{len(results)} successful ({success_count*100//len(results) if results else 0}%)")

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()


def reprocess_specific_recording(recording_id: str):
    """Force reprocess a specific recording"""
    logger.info(f"🔄 Force reprocessing {recording_id}")
    return process_single_transcript(recording_id)


def main():
    """Main function"""

    if len(sys.argv) > 1:
        if sys.argv[1] == '--reprocess-all':
            # Reprocess all with unknowns
            logger.info("🔄 Reprocessing all transcripts with unknown names...")
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
            process_all_unknowns(limit=limit)
        else:
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
        logger.info("🚀 Processing transcripts with unknown names...")
        process_all_unknowns(limit=50)

        print("\n✅ Batch processing complete!")
        print("Check the logs for details.")


if __name__ == "__main__":
    main()