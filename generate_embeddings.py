#!/usr/bin/env python3
"""
Generate embeddings for all existing transcripts
Uses OpenRouter API with best embedding model
"""

import sys
import os
sys.path.insert(0, '/var/www/call-recording-system')

from src.insights.embeddings_manager import get_embeddings_manager
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    print("=" * 80)
    print("GENERATING EMBEDDINGS FOR TRANSCRIPTS")
    print("=" * 80)

    # Check for API key
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        print("\n❌ ERROR: OPENROUTER_API_KEY not set")
        print("Please set your OpenRouter API key:")
        print("export OPENROUTER_API_KEY='your-key-here'")
        sys.exit(1)

    print(f"\n✅ OpenRouter API key found")

    # Initialize embeddings manager
    manager = get_embeddings_manager()

    print("\nStarting embedding generation...")
    print("-" * 40)

    # Process all transcripts in batches
    batch_size = 5  # Process 5 at a time to avoid rate limits

    try:
        stats = manager.process_all_transcripts(batch_size=batch_size)

        print("\n" + "=" * 80)
        print("EMBEDDING GENERATION COMPLETE")
        print("=" * 80)
        print(f"✅ Processed: {stats.get('processed', 0)}")
        print(f"❌ Failed: {stats.get('failed', 0)}")
        print(f"📊 Total embeddings in database: {stats.get('total', 0)}")
        print("=" * 80)

    except Exception as e:
        logger.error(f"Error generating embeddings: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()