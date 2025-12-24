#!/usr/bin/env python3
"""
Test OpenRouter embeddings specifically
"""

import os
import sys
import time
import requests
import json
sys.path.insert(0, '/var/www/call-recording-system')

from src.insights.embeddings_manager import EmbeddingsManager
import psycopg2
from psycopg2.extras import RealDictCursor

class OpenRouterEmbeddingsManager(EmbeddingsManager):
    """Custom manager that only uses OpenRouter"""

    def __init__(self):
        super().__init__()
        # Force OpenRouter usage
        self.openai_api_key = None  # Disable OpenAI
        self.use_openai_direct = False

    def generate_embedding(self, text: str):
        """Generate embedding using only OpenRouter"""
        if not self.openrouter_api_key:
            print("OpenRouter API key not set")
            return None

        try:
            # Try different OpenRouter endpoint configurations
            endpoints_to_try = [
                "https://openrouter.ai/api/v1/embeddings",
                "https://api.openrouter.ai/api/v1/embeddings"
            ]

            for endpoint in endpoints_to_try:
                print(f"Trying endpoint: {endpoint}")

                response = requests.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self.openrouter_api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://call-recording-system.local",
                        "X-Title": "Call Recording AI System"
                    },
                    json={
                        "model": "openai/text-embedding-ada-002",
                        "input": text
                    },
                    timeout=20
                )

                print(f"Status: {response.status_code}")
                print(f"Content-Type: {response.headers.get('Content-Type', 'Unknown')}")

                if response.status_code == 200:
                    content_type = response.headers.get('Content-Type', '')
                    if 'application/json' in content_type:
                        try:
                            data = response.json()
                            if 'data' in data and len(data['data']) > 0:
                                print(f"✅ Success with {endpoint}")
                                return data['data'][0]['embedding']
                        except Exception as e:
                            print(f"JSON parse error: {e}")
                    else:
                        print(f"❌ HTML response from {endpoint}")
                else:
                    print(f"❌ HTTP {response.status_code} from {endpoint}")

        except Exception as e:
            print(f"Error: {e}")

        return None

def main():
    print("Testing OpenRouter embedding API...")

    # Set environment variables
    os.environ['OPENROUTER_API_KEY'] = ''''

    mgr = OpenRouterEmbeddingsManager()

    # Test simple embedding
    print("\n🧪 Testing simple text embedding...")
    embedding = mgr.generate_embedding("This is a test embedding via OpenRouter")

    if embedding:
        print(f"✅ Embedding generated successfully! Length: {len(embedding)}")
        print(f"First 5 values: {embedding[:5]}")

        # Test with a transcript
        print("\n🧪 Testing transcript processing...")
        result = mgr.process_transcript('2991023820036')
        print(f"Transcript processing result: {result}")
    else:
        print("❌ Failed to generate embedding")

if __name__ == "__main__":
    main()