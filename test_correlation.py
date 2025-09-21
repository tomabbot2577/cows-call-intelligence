#!/usr/bin/env python3
"""
Test Customer-Employee Correlation System
Shows how DeepSeek correlates customer names with phone numbers and employees with extensions
"""

import os
import sys
import json

sys.path.insert(0, '/var/www/call-recording-system')

# Set API key for DeepSeek
os.environ['OPENROUTER_API_KEY'] = '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'

from src.insights.customer_employee_identifier import get_customer_employee_identifier

def test_correlation():
    print("🔍 Testing Customer-Employee Correlation System")
    print("=" * 60)

    # Initialize identifier
    identifier = get_customer_employee_identifier()

    print(f"📊 Loaded {len(identifier.employees)} employees:")
    for emp in identifier.employees[:5]:  # Show first 5
        print(f"  • {emp.name} (ext: {emp.extension}, dept: {emp.department})")
    print()

    # Test with real call data
    print("📞 Testing with Real Call Data:")
    print("-" * 40)

    # Load a recent transcription
    test_file = "/var/www/call-recording-system/data/transcriptions/json/2025/09/21/2991080665036.json"

    try:
        with open(test_file, 'r') as f:
            call_data = json.load(f)

        print(f"📁 Analyzing call: {call_data.get('recording_id', 'Unknown')}")

        # Show original metadata
        print("\n📋 Original Call Metadata:")
        metadata = call_data.get('call_metadata', {})
        print(f"  From: {metadata.get('from')}")
        print(f"  To: {metadata.get('to')}")
        print(f"  Duration: {metadata.get('duration_seconds')} seconds")

        # Analyze participants
        participants = identifier.analyze_call_participants(call_data)

        print("\n👤 EMPLOYEE IDENTIFICATION:")
        employee = participants.get('primary_employee', {})
        print(f"  Name: {employee.get('name')}")
        print(f"  Extension: {employee.get('extension')}")
        print(f"  Department: {employee.get('department')}")
        print(f"  Phone: {employee.get('phone')}")
        print(f"  How identified: {'Metadata match' if employee.get('extension') else 'Transcript analysis'}")

        print("\n👥 CUSTOMER IDENTIFICATION:")
        customer = participants.get('primary_customer', {})
        print(f"  Name: {customer.get('name')}")
        print(f"  Company: {customer.get('company')}")
        print(f"  Phone: {customer.get('phone')}")
        print(f"  Source: {customer.get('source')}")

        print("\n🔗 CORRELATION DETAILS:")
        call_meta = participants.get('call_metadata', {})
        print(f"  Call Direction: {call_meta.get('direction')}")
        print(f"  From Number: {call_meta.get('from_number')}")
        print(f"  To Number: {call_meta.get('to_number')}")
        print(f"  From Extension: {call_meta.get('from_extension')}")
        print(f"  To Extension: {call_meta.get('to_extension')}")

        # Show all customers found
        all_customers = participants.get('all_customers_identified', [])
        if len(all_customers) > 1:
            print(f"\n📋 All Customers Found ({len(all_customers)}):")
            for i, cust in enumerate(all_customers):
                print(f"  {i+1}. {cust.get('name')} ({cust.get('source')})")

        print("\n🔍 CONTEXT ANALYSIS:")
        context = participants.get('call_context', {})
        print(f"  Products Mentioned: {context.get('mentioned_products', [])}")
        print(f"  Issues Mentioned: {context.get('mentioned_issues', [])}")

    except Exception as e:
        print(f"❌ Error analyzing call: {e}")

    print("\n" + "=" * 60)
    print("🧠 HOW THE CORRELATION WORKS:")
    print("=" * 60)

    print("\n1. EMPLOYEE IDENTIFICATION:")
    print("   • First checks call metadata for extensions")
    print("   • Matches against employee database by extension")
    print("   • Falls back to phone number matching")
    print("   • Uses transcript analysis for employee names")
    print("   • Priority: Extension > Phone > Name mention")

    print("\n2. CUSTOMER IDENTIFICATION:")
    print("   • Extracts names from transcript using patterns:")
    print("     - 'This is [Name]', 'My name is [Name]'")
    print("     - '[Name] speaking', '[Name] from [Company]'")
    print("   • Finds phone numbers in transcript text")
    print("   • Extracts company names (Inc, LLC, Corp, etc.)")
    print("   • Gets phone numbers from call metadata")
    print("   • Correlates all data into customer profiles")

    print("\n3. DEEPSEEK ENHANCEMENT:")
    print("   • Uses AI to improve name extraction")
    print("   • Analyzes conversation context")
    print("   • Identifies customer sentiment and intent")
    print("   • Generates business insights and action items")

    print("\n4. CORRELATION LOGIC:")
    print("   • Links customer names with their phone numbers")
    print("   • Associates employees with call extensions")
    print("   • Determines call direction (inbound/outbound)")
    print("   • Builds customer journey history")

if __name__ == "__main__":
    test_correlation()