#!/usr/bin/env python3
"""
Test DeepSeek Integration
Quick test to verify the LLM switch worked
"""

import os
import sys

sys.path.insert(0, '/var/www/call-recording-system')

# Set API key
os.environ['OPENROUTER_API_KEY'] = 'os.getenv('OPENROUTER_API_KEY', '')'

from src.insights.enhanced_call_analyzer import EnhancedCallAnalyzer

def test_deepseek():
    print("🧠 Testing DeepSeek Integration...")

    try:
        # Initialize analyzer
        analyzer = EnhancedCallAnalyzer()
        print(f"✅ Analyzer initialized with {analyzer.model}")

        # Test with simple call content
        test_transcript = """
        Hello, this is Robin from Main Sequence Technologies. I'm calling regarding your recent support ticket.
        Customer said they're having issues with their billing system integration.
        The customer name is John Smith from ABC Corp, phone number 614-555-1234.
        They need help configuring the API endpoints for their accounting software.
        This seems like a technical support case that may require escalation to our development team.
        """

        # Test contact information extraction
        print("📞 Testing contact extraction...")
        contact_info = analyzer.extract_contact_information(test_transcript, {})

        print("Contact Info Found:")
        for key, value in contact_info.items():
            if value:
                print(f"  {key}: {value}")

        print("\n✅ DeepSeek integration test completed successfully!")

    except Exception as e:
        print(f"❌ Error testing DeepSeek: {e}")
        return False

    return True

if __name__ == "__main__":
    test_deepseek()