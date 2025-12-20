#!/usr/bin/env python3
"""
Test Optimized LLM Configuration
Tests task-specific model assignments and OpenRouter best practices
"""

import os
import sys

sys.path.insert(0, '/var/www/call-recording-system')

# Set API key
os.environ['OPENROUTER_API_KEY'] = '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'

from config.task_optimized_llm_config import TaskOptimizedLLMConfig

def test_task_assignments():
    print("🧠 Testing Task-Optimized LLM Configuration")
    print("=" * 60)

    config = TaskOptimizedLLMConfig()

    print("📊 Task-Model Assignments:")
    print("-" * 40)
    for task, description in config.list_all_tasks().items():
        model = config.get_model_for_task(task)
        cost = config.estimate_cost_per_task().get(task, 'Unknown')
        print(f"  • {task}:")
        print(f"    Model: {model}")
        print(f"    Cost: {cost}")
        print(f"    Reason: {config.get_task_description(task)}")
        print()

    print("💰 Cost Analysis:")
    print("-" * 40)
    costs = config.estimate_cost_per_task()
    cost_summary = {}
    for cost_level in costs.values():
        cost_summary[cost_level] = cost_summary.get(cost_level, 0) + 1

    for cost_level, count in cost_summary.items():
        print(f"  {cost_level} Cost: {count} tasks")

    print("\n🔧 OpenRouter Configuration Test:")
    print("-" * 40)

    # Test configuration for a specific task
    task = 'customer_extraction'
    client_config = config.get_client_config_for_task(task)

    print(f"Task: {task}")
    print(f"Model: {config.get_model_for_task(task)}")
    print(f"Base URL: {client_config.get('base_url', 'N/A')}")
    print(f"API Key: {'✓' if client_config.get('api_key') else '✗'}")
    print(f"Headers: {client_config.get('default_headers', {})}")

    print("\n✅ Configuration Test Complete!")
    print("\nRecommendations:")
    print("  • Use Claude Haiku for customer extraction (high accuracy)")
    print("  • Use Llama 3.1 70B for technical support analysis")
    print("  • Use GPT-4 Turbo for complex business insights")
    print("  • Use DeepSeek for cost-sensitive tasks (sentiment, summaries)")

if __name__ == "__main__":
    test_task_assignments()