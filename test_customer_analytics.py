#!/usr/bin/env python3
"""
Test script for customer analytics system
Tests customer and employee identification with real call data
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, '/var/www/call-recording-system')

from src.insights.customer_employee_identifier import get_customer_employee_identifier

def test_customer_identification():
    """Test customer identification on sample files"""
    print("🔍 Testing Customer Analytics System")
    print("=" * 50)

    # Initialize identifier
    identifier = get_customer_employee_identifier()

    # Test files
    test_files = [
        "/var/www/call-recording-system/data/transcriptions/json/2025/09/21/2990260522036.json",
        "/var/www/call-recording-system/data/transcriptions/json/2025/09/21/2991023820036.json"
    ]

    for file_path in test_files:
        try:
            print(f"\n📁 Processing: {Path(file_path).name}")

            with open(file_path, 'r') as f:
                transcript_data = json.load(f)

            # Analyze participants
            participants = identifier.analyze_call_participants(transcript_data)

            # Display results
            print("\n👥 PARTICIPANTS IDENTIFIED:")

            # Employee info
            employee = participants.get('primary_employee', {})
            print(f"  Employee: {employee.get('name', 'Unknown')}")
            print(f"  Extension: {employee.get('extension', 'Unknown')}")
            print(f"  Department: {employee.get('department', 'Unknown')}")

            # Customer info
            customer = participants.get('primary_customer', {})
            print(f"  Customer: {customer.get('name', 'Unknown')}")
            print(f"  Phone: {customer.get('phone', 'Unknown')}")
            print(f"  Company: {customer.get('company', 'Unknown')}")

            # Call metadata
            metadata = participants.get('call_metadata', {})
            print(f"  Call Date: {metadata.get('date', 'Unknown')}")
            print(f"  Duration: {metadata.get('duration', 'Unknown')} seconds")

            # Call context
            context = participants.get('call_context', {})
            print(f"  Issues Mentioned: {context.get('mentioned_issues', [])}")
            print(f"  Products: {context.get('mentioned_products', [])}")

            print("-" * 40)

        except Exception as e:
            print(f"❌ Error processing {file_path}: {e}")

    # Test customer search
    print("\n🔍 TESTING CUSTOMER SEARCH:")

    # Load all transcription files for searching
    transcription_files = []
    transcriptions_dir = Path('/var/www/call-recording-system/data/transcriptions/json')

    for json_file in list(transcriptions_dir.rglob('*.json'))[:5]:  # Limit to 5 files for testing
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
                transcription_files.append(data)
        except Exception as e:
            print(f"Error loading {json_file}: {e}")

    print(f"📊 Loaded {len(transcription_files)} transcription files for search testing")

    # Test searches
    search_terms = ["Robin", "5466", "customer service", "technical"]

    for term in search_terms:
        print(f"\n🔍 Searching for: '{term}'")
        try:
            matching_calls = identifier.search_calls_by_customer(term, transcription_files)
            print(f"  Found {len(matching_calls)} matching calls")

            for i, call in enumerate(matching_calls[:2]):  # Show first 2 results
                participants = call.get('participants', {})
                employee = participants.get('primary_employee', {})
                customer = participants.get('primary_customer', {})
                print(f"    {i+1}. Employee: {employee.get('name', 'Unknown')} | Customer: {customer.get('name', 'Unknown')}")

        except Exception as e:
            print(f"  ❌ Search error: {e}")

if __name__ == "__main__":
    test_customer_identification()