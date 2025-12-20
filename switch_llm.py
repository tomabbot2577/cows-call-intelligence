#!/usr/bin/env python3
"""
LLM Switching Utility
Easy command-line tool to switch between different LLM providers
"""

import sys
import os

sys.path.insert(0, '/var/www/call-recording-system')
from config.llm_config import LLMConfig

def main():
    if len(sys.argv) < 2:
        print("Current LLM Configuration:")
        print(f"  Provider: {LLMConfig.CURRENT_PROVIDER}")
        print(f"  Model: {LLMConfig.get_model_name()}")
        print(f"  API Key: {'✓' if LLMConfig.get_api_key() else '✗'}")
        print()
        print("Available providers:")
        for provider, config in LLMConfig.PROVIDERS.items():
            print(f"  {provider}: {list(config['models'].keys()) if 'models' in config else 'N/A'}")
        print()
        print("Usage: python switch_llm.py <provider> [model]")
        print("Examples:")
        print("  python switch_llm.py openrouter deepseek")
        print("  python switch_llm.py openai")
        return

    provider = sys.argv[1]
    model = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        old_provider = LLMConfig.CURRENT_PROVIDER
        old_model = LLMConfig.get_model_name()

        LLMConfig.switch_provider(provider, model)

        print(f"✅ Switched LLM:")
        print(f"  From: {old_provider}/{old_model}")
        print(f"  To: {LLMConfig.CURRENT_PROVIDER}/{LLMConfig.get_model_name()}")
        print(f"  API Key: {'✓' if LLMConfig.get_api_key() else '✗'}")

        # Update the config file
        config_file = '/var/www/call-recording-system/config/llm_config.py'
        with open(config_file, 'r') as f:
            content = f.read()

        # Update current provider and model
        content = content.replace(
            f"CURRENT_PROVIDER = '{old_provider}'",
            f"CURRENT_PROVIDER = '{provider}'"
        )

        if model and provider == 'openrouter':
            old_model_key = old_model.split('/')[-1] if '/' in old_model else 'deepseek'
            content = content.replace(
                f"CURRENT_MODEL = '{old_model_key}'",
                f"CURRENT_MODEL = '{model}'"
            )

        with open(config_file, 'w') as f:
            f.write(content)

        print("✅ Configuration updated")

    except ValueError as e:
        print(f"❌ Error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main() or 0)