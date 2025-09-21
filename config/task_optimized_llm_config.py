#!/usr/bin/env python3
"""
Task-Optimized LLM Configuration
Different LLMs optimized for specific tasks based on performance, cost, and accuracy
"""

import os
from typing import Dict, Any, Optional

class TaskOptimizedLLMConfig:
    """Task-specific LLM configuration for optimal performance"""

    # Task-specific LLM mappings based on capabilities
    TASK_MODELS = {
        # Customer name extraction - needs high accuracy with context understanding
        'customer_extraction': {
            'provider': 'openrouter',
            'model': 'anthropic/claude-3-haiku',  # Better at structured extraction
            'api_key_env': 'OPENROUTER_API_KEY',
            'base_url': 'https://openrouter.ai/api/v1',
            'reason': 'Claude excellent at structured data extraction and name recognition'
        },

        # Sentiment analysis - DeepSeek is cost-effective and good at analysis
        'sentiment_analysis': {
            'provider': 'openrouter',
            'model': 'deepseek/deepseek-chat',
            'api_key_env': 'OPENROUTER_API_KEY',
            'base_url': 'https://openrouter.ai/api/v1',
            'reason': 'DeepSeek cost-effective with good emotional understanding'
        },

        # Business intelligence & insights - GPT-4 for complex reasoning
        'business_insights': {
            'provider': 'openrouter',
            'model': 'openai/gpt-4-turbo',
            'api_key_env': 'OPENROUTER_API_KEY',
            'base_url': 'https://openrouter.ai/api/v1',
            'reason': 'GPT-4 superior for complex business analysis and strategic insights'
        },

        # Technical support analysis - Llama good at technical content
        'support_analysis': {
            'provider': 'openrouter',
            'model': 'meta-llama/llama-3.1-70b-instruct',
            'api_key_env': 'OPENROUTER_API_KEY',
            'base_url': 'https://openrouter.ai/api/v1',
            'reason': 'Llama 3.1 excellent at technical problem classification'
        },

        # Sales opportunity detection - Claude good at sales context
        'sales_analysis': {
            'provider': 'openrouter',
            'model': 'anthropic/claude-3-sonnet-20240229',
            'api_key_env': 'OPENROUTER_API_KEY',
            'base_url': 'https://openrouter.ai/api/v1',
            'reason': 'Claude Sonnet balances cost and sales insight quality'
        },

        # Summarization - DeepSeek cost-effective for summaries
        'summarization': {
            'provider': 'openrouter',
            'model': 'deepseek/deepseek-chat',
            'api_key_env': 'OPENROUTER_API_KEY',
            'base_url': 'https://openrouter.ai/api/v1',
            'reason': 'DeepSeek provides good summaries at low cost'
        },

        # Employee identification - Fast and simple, use lightweight model
        'employee_identification': {
            'provider': 'openrouter',
            'model': 'deepseek/deepseek-chat',
            'api_key_env': 'OPENROUTER_API_KEY',
            'base_url': 'https://openrouter.ai/api/v1',
            'reason': 'Simple pattern matching, DeepSeek sufficient and fast'
        },

        # Call classification - GPT-3.5 good balance for classification
        'call_classification': {
            'provider': 'openrouter',
            'model': 'openai/gpt-3.5-turbo',
            'api_key_env': 'OPENROUTER_API_KEY',
            'base_url': 'https://openrouter.ai/api/v1',
            'reason': 'GPT-3.5 reliable for classification tasks at reasonable cost'
        }
    }

    # Fallback configuration
    DEFAULT_CONFIG = {
        'provider': 'openrouter',
        'model': 'deepseek/deepseek-chat',
        'api_key_env': 'OPENROUTER_API_KEY',
        'base_url': 'https://openrouter.ai/api/v1'
    }

    @classmethod
    def get_config_for_task(cls, task: str) -> Dict[str, Any]:
        """Get optimal LLM configuration for specific task"""
        config = cls.TASK_MODELS.get(task, cls.DEFAULT_CONFIG).copy()

        # Add API key
        config['api_key'] = os.getenv(config['api_key_env'])

        return config

    @classmethod
    def get_client_config_for_task(cls, task: str) -> Dict[str, Any]:
        """Get OpenAI-compatible client config for task with OpenRouter best practices"""
        config = cls.get_config_for_task(task)

        client_config = {
            'api_key': config['api_key']
        }

        if config.get('base_url'):
            client_config['base_url'] = config['base_url']
            # Add OpenRouter best practice headers
            client_config['default_headers'] = {
                "HTTP-Referer": "https://mainsequence.net",
                "X-Title": "Main Sequence Call Recording System"
            }

        return client_config

    @classmethod
    def get_model_for_task(cls, task: str) -> str:
        """Get model name for specific task"""
        return cls.TASK_MODELS.get(task, cls.DEFAULT_CONFIG)['model']

    @classmethod
    def get_task_description(cls, task: str) -> str:
        """Get description of why this model was chosen for the task"""
        return cls.TASK_MODELS.get(task, cls.DEFAULT_CONFIG).get('reason', 'Default model')

    @classmethod
    def list_all_tasks(cls) -> Dict[str, str]:
        """List all available tasks and their models"""
        return {
            task: f"{config['model']} - {config.get('reason', 'No description')}"
            for task, config in cls.TASK_MODELS.items()
        }

    @classmethod
    def estimate_cost_per_task(cls) -> Dict[str, str]:
        """Rough cost estimates per task (relative)"""
        cost_mapping = {
            'openai/gpt-4-turbo': 'High',
            'anthropic/claude-3-sonnet-20240229': 'Medium-High',
            'anthropic/claude-3-haiku': 'Medium',
            'meta-llama/llama-3.1-70b-instruct': 'Medium',
            'openai/gpt-3.5-turbo': 'Low-Medium',
            'deepseek/deepseek-chat': 'Very Low'
        }

        return {
            task: cost_mapping.get(config['model'], 'Unknown')
            for task, config in cls.TASK_MODELS.items()
        }