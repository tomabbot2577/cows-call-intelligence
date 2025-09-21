#!/usr/bin/env python3
"""
LLM Configuration Manager
Centralized configuration for switching between different LLM providers
"""

import os
from typing import Dict, Any, Optional

class LLMConfig:
    """Centralized LLM configuration"""

    # Available LLM configurations
    PROVIDERS = {
        'openai': {
            'api_key_env': 'OPENAI_API_KEY',
            'base_url': None,
            'models': {
                'chat': 'gpt-3.5-turbo',
                'completion': 'gpt-3.5-turbo-instruct'
            }
        },
        'openrouter': {
            'api_key_env': 'OPENROUTER_API_KEY',
            'base_url': 'https://openrouter.ai/api/v1',
            'models': {
                'deepseek': 'deepseek/deepseek-chat',
                'claude': 'anthropic/claude-3-haiku',
                'gpt4': 'openai/gpt-4-turbo',
                'llama': 'meta-llama/llama-3.1-70b-instruct'
            }
        }
    }

    # Current active configuration
    CURRENT_PROVIDER = 'openrouter'
    CURRENT_MODEL = 'deepseek'

    @classmethod
    def get_client_config(cls) -> Dict[str, Any]:
        """Get configuration for OpenAI-compatible client"""
        provider = cls.PROVIDERS[cls.CURRENT_PROVIDER]

        config = {
            'api_key': os.getenv(provider['api_key_env']),
        }

        if provider['base_url']:
            config['base_url'] = provider['base_url']

        return config

    @classmethod
    def get_model_name(cls) -> str:
        """Get current model name"""
        provider = cls.PROVIDERS[cls.CURRENT_PROVIDER]

        if cls.CURRENT_PROVIDER == 'openrouter':
            return provider['models'][cls.CURRENT_MODEL]
        else:
            return provider['models']['chat']

    @classmethod
    def switch_provider(cls, provider: str, model: Optional[str] = None):
        """Switch to a different LLM provider"""
        if provider not in cls.PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")

        cls.CURRENT_PROVIDER = provider

        if model:
            if provider == 'openrouter':
                if model not in cls.PROVIDERS[provider]['models']:
                    raise ValueError(f"Unknown model for {provider}: {model}")
                cls.CURRENT_MODEL = model

    @classmethod
    def get_api_key(cls) -> Optional[str]:
        """Get current API key"""
        provider = cls.PROVIDERS[cls.CURRENT_PROVIDER]
        return os.getenv(provider['api_key_env'])