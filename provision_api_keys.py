#!/usr/bin/env python3
"""
API Key Auto-Provisioning Tool
Automatically detects, validates, and guides API key setup for the call recording system
"""

import sys
import os
import argparse

sys.path.insert(0, '/var/www/call-recording-system')

from config.api_key_manager import get_api_key_manager

def main():
    parser = argparse.ArgumentParser(description='Auto-provision API keys for call recording system')
    parser.add_argument('--task', help='Specific task to provision for (e.g., customer_extraction)')
    parser.add_argument('--validate', action='store_true', help='Validate existing API keys')
    parser.add_argument('--setup-script', action='store_true', help='Generate setup script')
    parser.add_argument('--check-all', action='store_true', help='Check all API key requirements')

    args = parser.parse_args()

    manager = get_api_key_manager()

    if args.setup_script:
        print("📝 Generating API Key Setup Script...")
        script = manager.generate_setup_script()

        script_path = '/var/www/call-recording-system/setup_api_keys.sh'
        with open(script_path, 'w') as f:
            f.write(script)

        os.chmod(script_path, 0o755)
        print(f"✅ Setup script created: {script_path}")
        print("Run: bash setup_api_keys.sh")
        return

    if args.validate:
        print("🔍 Validating API Keys...")
        detected = manager.detect_available_keys()

        if not detected:
            print("❌ No API keys detected")
            return

        for provider in detected:
            is_valid = manager.validate_api_key(provider)
            status = "✅ Valid" if is_valid else "❌ Invalid"
            print(f"  {provider}: {status}")
        return

    if args.task:
        print(f"🎯 Auto-configuring for task: {args.task}")
        result = manager.auto_configure_for_task(args.task)

        print(f"\n📊 Configuration Results:")
        print(f"  Task: {result['task']}")
        print(f"  Detected Keys: {len(result['detected_keys'])}")
        print(f"  Missing Keys: {len(result['missing_keys'])}")

        if result['detected_keys']:
            print(f"\n✅ Available API Keys:")
            for provider, status in result['validation_results'].items():
                status_icon = "✅" if status else "❌"
                print(f"    {provider}: {status_icon}")

        if result['missing_keys']:
            print(f"\n❌ Missing API Keys:")
            for provider in result['missing_keys']:
                info = result['instructions']['provisioning_steps'][provider]
                print(f"    {provider}:")
                print(f"      Description: {info['description']}")
                print(f"      Signup: {info['signup_url']}")
                print(f"      Setup: {info['setup_command']}")

        # Recommend best provider
        best_provider = manager.get_best_provider_for_task(args.task)
        if best_provider:
            print(f"\n🎯 Recommended Provider: {best_provider}")
        else:
            print(f"\n⚠️  No valid providers available for {args.task}")
            print("Please provision API keys using --setup-script")

        return

    if args.check_all:
        print("🔍 Checking All API Key Requirements...")

        tasks = ['customer_extraction', 'sentiment_analysis', 'business_insights',
                'support_analysis', 'sales_analysis', 'summarization',
                'employee_identification', 'call_classification']

        overall_status = {}

        for task in tasks:
            result = manager.auto_configure_for_task(task)
            best_provider = manager.get_best_provider_for_task(task)

            overall_status[task] = {
                'configured': best_provider is not None,
                'provider': best_provider,
                'missing_keys': result['missing_keys']
            }

        print(f"\n📊 Overall System Status:")
        print("=" * 50)

        configured_tasks = sum(1 for status in overall_status.values() if status['configured'])
        total_tasks = len(tasks)

        print(f"Configured Tasks: {configured_tasks}/{total_tasks}")
        print(f"Completion Rate: {configured_tasks/total_tasks*100:.1f}%")

        print(f"\n📋 Task Details:")
        for task, status in overall_status.items():
            status_icon = "✅" if status['configured'] else "❌"
            provider = status['provider'] or 'None'
            print(f"  {status_icon} {task}: {provider}")

        # Show missing keys summary
        all_missing = set()
        for status in overall_status.values():
            all_missing.update(status['missing_keys'])

        if all_missing:
            print(f"\n⚠️  Missing API Keys Required:")
            for provider in all_missing:
                info = manager.required_keys[provider]
                print(f"    {provider}: {info['signup_url']}")

        return

    # Default behavior - show overview
    print("🔑 API Key Auto-Provisioning Tool")
    print("=" * 40)

    detected = manager.detect_available_keys()
    instructions = manager.get_provisioning_instructions()

    if detected:
        print(f"✅ Detected API Keys: {list(detected.keys())}")
    else:
        print("❌ No API keys detected")

    if instructions['missing_keys']:
        print(f"⚠️  Missing API Keys: {instructions['missing_keys']}")

    print(f"\nPriority Recommendations:")
    for rec in instructions['priority_recommendations']:
        print(f"  {rec['priority']}: {rec['provider']} - {rec['reason']}")

    print(f"\nUsage:")
    print(f"  python provision_api_keys.py --task customer_extraction")
    print(f"  python provision_api_keys.py --validate")
    print(f"  python provision_api_keys.py --setup-script")
    print(f"  python provision_api_keys.py --check-all")

if __name__ == "__main__":
    main()