#!/usr/bin/env python3
"""
API Key Auto-Provisioning Manager
Manages and validates API keys for different LLM providers with auto-detection
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

class APIKeyManager:
    """
    Manages API keys with auto-detection, validation, and provisioning guidance
    """

    def __init__(self, config_file: str = "/var/www/call-recording-system/config/api_keys.json"):
        self.config_file = Path(config_file)
        self.api_keys = self._load_api_keys()

        # Required API keys for different providers
        self.required_keys = {
            'openrouter': {
                'env_var': 'OPENROUTER_API_KEY',
                'description': 'OpenRouter unified LLM access',
                'signup_url': 'https://openrouter.ai/keys',
                'validation_model': 'deepseek/deepseek-chat',
                'tasks': ['customer_extraction', 'sentiment_analysis', 'business_insights',
                         'support_analysis', 'sales_analysis', 'summarization',
                         'employee_identification', 'call_classification']
            },
            'anthropic': {
                'env_var': 'ANTHROPIC_API_KEY',
                'description': 'Direct Anthropic API access (optional)',
                'signup_url': 'https://console.anthropic.com/',
                'validation_model': 'claude-3-haiku-20240307',
                'tasks': ['customer_extraction']
            },
            'openai': {
                'env_var': 'OPENAI_API_KEY',
                'description': 'Direct OpenAI API access (optional)',
                'signup_url': 'https://platform.openai.com/api-keys',
                'validation_model': 'gpt-3.5-turbo',
                'tasks': ['call_classification']
            }
        }

    def _load_api_keys(self) -> Dict[str, Any]:
        """Load API keys from config file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load API keys config: {e}")

        return {
            'keys': {},
            'validation_history': {},
            'last_updated': datetime.now().isoformat()
        }

    def _save_api_keys(self):
        """Save API keys to config file"""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            self.api_keys['last_updated'] = datetime.now().isoformat()

            with open(self.config_file, 'w') as f:
                json.dump(self.api_keys, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save API keys config: {e}")

    def detect_available_keys(self) -> Dict[str, str]:
        """Detect API keys from environment variables"""
        detected = {}

        for provider, info in self.required_keys.items():
            env_var = info['env_var']
            key = os.getenv(env_var)

            if key:
                detected[provider] = key
                # Update our config
                self.api_keys['keys'][provider] = {
                    'key': key[:8] + '...' + key[-4:],  # Store masked version
                    'env_var': env_var,
                    'detected_at': datetime.now().isoformat(),
                    'status': 'detected'
                }

        if detected:
            self._save_api_keys()

        return detected

    def validate_api_key(self, provider: str, key: str = None) -> bool:
        """Validate an API key by making a test request"""
        if not key:
            key = os.getenv(self.required_keys[provider]['env_var'])

        if not key:
            return False

        try:
            # Import here to avoid circular dependencies
            from openai import OpenAI

            if provider == 'openrouter':
                client = OpenAI(
                    api_key=key,
                    base_url="https://openrouter.ai/api/v1"
                )
                model = self.required_keys[provider]['validation_model']
            elif provider == 'openai':
                client = OpenAI(api_key=key)
                model = self.required_keys[provider]['validation_model']
            elif provider == 'anthropic':
                # Would need anthropic SDK
                return True  # Skip validation for now
            else:
                return False

            # Test with minimal request
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Test"}],
                max_tokens=1
            )

            # Update validation history
            self.api_keys['validation_history'][provider] = {
                'last_validated': datetime.now().isoformat(),
                'status': 'valid',
                'model_tested': model
            }
            self._save_api_keys()

            return True

        except Exception as e:
            logger.error(f"API key validation failed for {provider}: {e}")
            self.api_keys['validation_history'][provider] = {
                'last_validated': datetime.now().isoformat(),
                'status': 'invalid',
                'error': str(e)
            }
            self._save_api_keys()
            return False

    def get_provisioning_instructions(self, task: str = None) -> Dict[str, Any]:
        """Get instructions for provisioning required API keys"""
        detected = self.detect_available_keys()

        instructions = {
            'detected_keys': detected,
            'missing_keys': [],
            'provisioning_steps': {},
            'priority_recommendations': []
        }

        # Determine required providers for task
        required_providers = ['openrouter']  # OpenRouter is primary

        if task:
            # Find which providers support this task
            for provider, info in self.required_keys.items():
                if task in info.get('tasks', []):
                    required_providers.append(provider)

        # Check what's missing
        for provider in required_providers:
            if provider not in detected:
                instructions['missing_keys'].append(provider)
                instructions['provisioning_steps'][provider] = {
                    'step': 1,
                    'description': self.required_keys[provider]['description'],
                    'signup_url': self.required_keys[provider]['signup_url'],
                    'env_var': self.required_keys[provider]['env_var'],
                    'setup_command': f"export {self.required_keys[provider]['env_var']}='your-api-key-here'"
                }

        # Priority recommendations
        if 'openrouter' not in detected:
            instructions['priority_recommendations'].append({
                'priority': 'HIGH',
                'provider': 'openrouter',
                'reason': 'Provides unified access to all models with single API key',
                'cost_benefit': 'Most cost-effective option'
            })

        return instructions

    def auto_configure_for_task(self, task: str) -> Dict[str, Any]:
        """Auto-configure API keys for a specific task"""
        logger.info(f"Auto-configuring API keys for task: {task}")

        # Detect available keys
        detected = self.detect_available_keys()

        # Get provisioning instructions
        instructions = self.get_provisioning_instructions(task)

        # Validate detected keys
        validation_results = {}
        for provider, key in detected.items():
            is_valid = self.validate_api_key(provider)
            validation_results[provider] = is_valid
            logger.info(f"API key validation for {provider}: {'✓' if is_valid else '✗'}")

        return {
            'task': task,
            'detected_keys': detected,
            'validation_results': validation_results,
            'missing_keys': instructions['missing_keys'],
            'provisioning_needed': len(instructions['missing_keys']) > 0,
            'instructions': instructions
        }

    def get_best_provider_for_task(self, task: str) -> Optional[str]:
        """Get the best available provider for a specific task"""
        detected = self.detect_available_keys()

        # Priority order based on capabilities and cost
        provider_priority = {
            'customer_extraction': ['openrouter', 'anthropic'],
            'support_analysis': ['openrouter'],
            'business_insights': ['openrouter', 'openai'],
            'sentiment_analysis': ['openrouter'],
            'sales_analysis': ['openrouter', 'anthropic'],
            'summarization': ['openrouter'],
            'employee_identification': ['openrouter'],
            'call_classification': ['openrouter', 'openai']
        }

        preferred_providers = provider_priority.get(task, ['openrouter'])

        for provider in preferred_providers:
            if provider in detected and self.validate_api_key(provider):
                return provider

        return None

    def generate_setup_script(self) -> str:
        """Generate a setup script for API key configuration"""
        instructions = self.get_provisioning_instructions()

        script = """#!/bin/bash
# API Key Setup Script for Call Recording System
# Generated automatically by API Key Manager

echo "🔑 Setting up API Keys for Call Recording System"
echo "================================================"

"""

        for provider, steps in instructions['provisioning_steps'].items():
            env_var = steps['env_var']
            script += f"""
# {provider.upper()} API Key Setup
echo "Setting up {provider.upper()} API key..."
echo "1. Sign up at: {steps['signup_url']}"
echo "2. Generate an API key"
echo "3. Set environment variable:"
echo "   {steps['setup_command']}"
echo "4. Add to .env file:"
echo "   echo '{env_var}=your-actual-key' >> /var/www/call-recording-system/.env"
echo ""
"""

        script += """
echo "After setting up API keys, test with:"
echo "python /var/www/call-recording-system/test_optimized_llms.py"
echo ""
echo "✅ Setup complete!"
"""

        return script

# Global instance
api_key_manager = APIKeyManager()

def get_api_key_manager() -> APIKeyManager:
    """Get the global API key manager instance"""
    return api_key_manager