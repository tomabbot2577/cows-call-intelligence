#!/usr/bin/env python3
"""
Validate Vertex AI RAG Migration

Validates that data was migrated correctly from PostgreSQL to Vertex AI RAG.

Usage:
    python src/migration/validate_migration.py
    python src/migration/validate_migration.py --test-search "billing issue"
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime
from typing import Dict, Any

import psycopg2
from psycopg2.extras import RealDictCursor

# Add project root to path
sys.path.insert(0, '/var/www/call-recording-system')

from src.vertex_ai.config import default_config
from src.vertex_ai.corpus_manager import VertexAICorpusManager
from src.vertex_ai.search_client import VertexSearchClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': os.getenv('PG_PASSWORD', ''),
    'host': 'localhost',
    'port': 5432
}


class MigrationValidator:
    """Validates the migration from PostgreSQL to Vertex AI RAG"""

    def __init__(self):
        """Initialize validator"""
        # Set credentials
        if default_config.credentials_path:
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = default_config.credentials_path

        self.corpus_manager = VertexAICorpusManager()
        self.search_client = None
        self.validation_results = {
            'timestamp': datetime.utcnow().isoformat(),
            'checks': {}
        }

    def check_postgresql_count(self) -> int:
        """Get count of transcripts in PostgreSQL"""
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) as count
            FROM transcripts
            WHERE transcript_text IS NOT NULL
            AND LENGTH(transcript_text) > 100
        """)

        result = cursor.fetchone()
        count = result[0]

        cursor.close()
        conn.close()

        return count

    def check_gcs_count(self) -> int:
        """Get count of documents in GCS"""
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(default_config.gcs_bucket)

        # Count files in transcripts folder
        blobs = list(bucket.list_blobs(prefix='transcripts/'))
        json_files = [b for b in blobs if b.name.endswith('.json')]

        return len(json_files)

    def check_corpus_exists(self) -> Dict[str, Any]:
        """Check if RAG corpus exists and get stats"""
        try:
            corpus = self.corpus_manager.get_corpus()
            if corpus:
                stats = self.corpus_manager.get_corpus_stats()
                return {
                    'exists': True,
                    'name': corpus.name,
                    'display_name': corpus.display_name,
                    'file_count': stats.get('file_count', 0)
                }
            return {'exists': False}
        except Exception as e:
            return {'exists': False, 'error': str(e)}

    def test_semantic_search(self, query: str) -> Dict[str, Any]:
        """Test semantic search functionality"""
        try:
            if not self.search_client:
                self.search_client = VertexSearchClient()

            results = self.search_client.semantic_search(query, limit=5)

            return {
                'query': query,
                'results_count': len(results),
                'results': results[:3] if results else []  # First 3 results
            }
        except Exception as e:
            return {'query': query, 'error': str(e)}

    def run_validation(self, test_queries: list = None) -> Dict[str, Any]:
        """
        Run all validation checks

        Args:
            test_queries: Optional list of queries to test search

        Returns:
            Validation results
        """
        logger.info("Starting migration validation...")

        # Check 1: PostgreSQL count
        logger.info("Checking PostgreSQL transcript count...")
        try:
            pg_count = self.check_postgresql_count()
            self.validation_results['checks']['postgresql'] = {
                'status': 'pass',
                'transcript_count': pg_count
            }
            logger.info(f"  PostgreSQL: {pg_count} transcripts")
        except Exception as e:
            self.validation_results['checks']['postgresql'] = {
                'status': 'fail',
                'error': str(e)
            }
            logger.error(f"  PostgreSQL check failed: {e}")

        # Check 2: GCS document count
        logger.info("Checking GCS document count...")
        try:
            gcs_count = self.check_gcs_count()
            self.validation_results['checks']['gcs'] = {
                'status': 'pass',
                'document_count': gcs_count
            }
            logger.info(f"  GCS: {gcs_count} documents")
        except Exception as e:
            self.validation_results['checks']['gcs'] = {
                'status': 'fail',
                'error': str(e)
            }
            logger.error(f"  GCS check failed: {e}")

        # Check 3: Corpus exists
        logger.info("Checking RAG corpus...")
        corpus_info = self.check_corpus_exists()
        if corpus_info.get('exists'):
            self.validation_results['checks']['corpus'] = {
                'status': 'pass',
                **corpus_info
            }
            logger.info(f"  Corpus: {corpus_info.get('display_name')}")
            logger.info(f"  Files in corpus: {corpus_info.get('file_count', 'unknown')}")
        else:
            self.validation_results['checks']['corpus'] = {
                'status': 'fail',
                **corpus_info
            }
            logger.error(f"  Corpus check failed: {corpus_info.get('error', 'not found')}")

        # Check 4: Semantic search
        test_queries = test_queries or [
            "billing issue",
            "angry customer",
            "technical support"
        ]

        logger.info("Testing semantic search...")
        search_results = []
        for query in test_queries:
            result = self.test_semantic_search(query)
            search_results.append(result)
            if 'error' in result:
                logger.warning(f"  Query '{query}': FAILED - {result['error']}")
            else:
                logger.info(f"  Query '{query}': {result['results_count']} results")

        self.validation_results['checks']['search'] = {
            'status': 'pass' if all('error' not in r for r in search_results) else 'partial',
            'test_results': search_results
        }

        # Summary
        self.validation_results['summary'] = self._generate_summary()

        return self.validation_results

    def _generate_summary(self) -> Dict[str, Any]:
        """Generate validation summary"""
        checks = self.validation_results['checks']

        pg_count = checks.get('postgresql', {}).get('transcript_count', 0)
        gcs_count = checks.get('gcs', {}).get('document_count', 0)
        corpus_exists = checks.get('corpus', {}).get('exists', False)

        # Calculate match percentage
        match_pct = 0
        if pg_count > 0:
            match_pct = (gcs_count / pg_count) * 100

        all_pass = all(
            c.get('status') == 'pass'
            for c in checks.values()
        )

        return {
            'overall_status': 'pass' if all_pass else 'fail',
            'postgresql_count': pg_count,
            'gcs_count': gcs_count,
            'match_percentage': round(match_pct, 1),
            'corpus_ready': corpus_exists,
            'search_functional': checks.get('search', {}).get('status') != 'fail'
        }


def main():
    parser = argparse.ArgumentParser(description='Validate Vertex AI RAG migration')
    parser.add_argument('--test-search', '-t', nargs='+',
                       help='Test queries for semantic search')
    parser.add_argument('--output', '-o',
                       default='/var/www/call-recording-system/data/validation_results.json',
                       help='Output file for validation results')

    args = parser.parse_args()

    validator = MigrationValidator()

    test_queries = args.test_search if args.test_search else None
    results = validator.run_validation(test_queries)

    # Print summary
    summary = results['summary']
    logger.info(f"\n{'='*50}")
    logger.info("VALIDATION SUMMARY")
    logger.info(f"{'='*50}")
    logger.info(f"Overall Status: {summary['overall_status'].upper()}")
    logger.info(f"PostgreSQL Transcripts: {summary['postgresql_count']}")
    logger.info(f"GCS Documents: {summary['gcs_count']}")
    logger.info(f"Match Percentage: {summary['match_percentage']}%")
    logger.info(f"Corpus Ready: {summary['corpus_ready']}")
    logger.info(f"Search Functional: {summary['search_functional']}")

    # Save results
    with open(args.output, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"\nDetailed results saved to: {args.output}")

    # Return exit code based on status
    return 0 if summary['overall_status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
