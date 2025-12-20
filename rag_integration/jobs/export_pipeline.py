"""Export Pipeline - Orchestrates full export process."""

import os
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pathlib import Path
import logging
import json

# Add parent directory to path
sys.path.insert(0, '/var/www/call-recording-system')

from rag_integration.services.db_reader import DatabaseReader
from rag_integration.services.jsonl_formatter import JSONLFormatter, JSONLWriter
from rag_integration.services.gcs_uploader import GCSUploader
from rag_integration.services.gemini_file_search import GeminiFileSearchService
from rag_integration.services.vertex_rag import VertexRAGService
from rag_integration.config.settings import get_config

logger = logging.getLogger(__name__)


class ExportPipeline:
    """Orchestrates export from PostgreSQL to RAG systems."""

    def __init__(self):
        self.config = get_config()
        self.db_reader = DatabaseReader()
        self.formatter = JSONLFormatter()
        self.writer = JSONLWriter(self.config.export_dir)
        self.gcs = GCSUploader(self.config.gcs_bucket)

        # Initialize RAG services (lazy)
        self._gemini = None
        self._vertex = None

    @property
    def gemini(self):
        if self._gemini is None:
            self._gemini = GeminiFileSearchService(self.config.gemini_api_key)
        return self._gemini

    @property
    def vertex(self):
        if self._vertex is None:
            self._vertex = VertexRAGService(
                project_id=self.config.gcp_project,
                location=self.config.vertex_location
            )
        return self._vertex

    def run_full_export(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        batch_size: int = 100,
        skip_gcs: bool = False,
        skip_gemini: bool = False,
        skip_vertex: bool = False
    ) -> Dict[str, Any]:
        """
        Run a full export pipeline.

        Args:
            since: Export calls since this date
            until: Export calls until this date
            batch_size: Number of records per JSONL file
            skip_gcs: Skip GCS upload
            skip_gemini: Skip Gemini import
            skip_vertex: Skip Vertex AI import

        Returns:
            Result dict with statistics
        """
        results = {
            "started_at": datetime.now().isoformat(),
            "calls_exported": 0,
            "files_created": [],
            "gcs_uris": [],
            "errors": [],
            "status": "running"
        }

        try:
            logger.info(f"Starting export pipeline (since={since}, batch_size={batch_size})")

            # Step 1: Read from database
            calls = list(self.db_reader.get_calls_for_export(since=since, until=until))
            total = len(calls)
            logger.info(f"Found {total} calls to export")

            if total == 0:
                results["status"] = "success"
                results["message"] = "No calls to export"
                results["completed_at"] = datetime.now().isoformat()
                return results

            # Step 2: Format and write to JSONL
            for i in range(0, total, batch_size):
                batch = calls[i:i + batch_size]
                documents = []

                for call in batch:
                    try:
                        doc = self.formatter.format_call(call)
                        documents.append(doc)
                    except Exception as e:
                        error_msg = f"Format error for {call.get('recording_id')}: {e}"
                        logger.warning(error_msg)
                        results["errors"].append(error_msg)

                if documents:
                    batch_num = (i // batch_size) + 1
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"calls_batch_{batch_num:04d}_{timestamp}.jsonl"

                    filepath = self.writer.write_batch(documents, filename)
                    results["files_created"].append(str(filepath))
                    results["calls_exported"] += len(documents)

                    logger.info(f"Wrote batch {batch_num}: {len(documents)} documents")

            # Step 3: Upload to GCS
            if not skip_gcs:
                logger.info("Uploading to GCS...")
                for filepath in results["files_created"]:
                    try:
                        gcs_uri = self.gcs.upload_file(Path(filepath))
                        results["gcs_uris"].append(gcs_uri)
                    except Exception as e:
                        error_msg = f"GCS upload error for {filepath}: {e}"
                        logger.error(error_msg)
                        results["errors"].append(error_msg)

                results["gcs_upload"] = "success" if results["gcs_uris"] else "failed"

            # Step 4: Import to Gemini
            if not skip_gemini and results.get("gcs_uris"):
                logger.info("Importing to Gemini File Search...")
                try:
                    for filepath in results["files_created"]:
                        self.gemini.upload_file(filepath)
                    results["gemini_import"] = "success"
                except Exception as e:
                    error_msg = f"Gemini import error: {e}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)
                    results["gemini_import"] = "failed"

            # Step 5: Import to Vertex AI
            if not skip_vertex and results.get("gcs_uris"):
                logger.info("Importing to Vertex AI RAG...")
                try:
                    self.vertex.initialize_corpus()
                    for gcs_uri in results["gcs_uris"]:
                        self.vertex.import_from_gcs(gcs_uri)
                    results["vertex_import"] = "success"
                except Exception as e:
                    error_msg = f"Vertex import error: {e}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)
                    results["vertex_import"] = "failed"

            # Complete
            results["completed_at"] = datetime.now().isoformat()
            results["status"] = "success" if not results["errors"] else "partial"

            # Calculate duration
            start = datetime.fromisoformat(results["started_at"])
            end = datetime.fromisoformat(results["completed_at"])
            results["duration_seconds"] = (end - start).total_seconds()

            logger.info(f"Export complete: {results['calls_exported']} calls, {len(results['errors'])} errors")

        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            results["status"] = "error"
            results["error"] = str(e)
            results["completed_at"] = datetime.now().isoformat()

        return results

    def run_incremental(self, days: int = 1) -> Dict[str, Any]:
        """
        Run incremental export (last N days).

        Args:
            days: Number of days to look back

        Returns:
            Result dict
        """
        since = datetime.now() - timedelta(days=days)
        return self.run_full_export(since=since)

    def run_daily(self) -> Dict[str, Any]:
        """Run daily export (last 24 hours) - for cron job."""
        return self.run_incremental(days=1)

    def get_status(self) -> Dict[str, Any]:
        """Get pipeline status and statistics."""
        try:
            db_stats = self.db_reader.get_statistics()

            # Count exported files
            export_dir = Path(self.config.export_dir)
            exported_files = list(export_dir.glob("*.jsonl"))

            return {
                "status": "ready",
                "database": {
                    "total_transcripts": db_stats.get("total_transcripts", 0),
                    "layer1_names": db_stats.get("with_names", 0),
                    "layer2_insights": db_stats.get("with_insights", 0),
                    "layer3_resolutions": db_stats.get("with_resolutions", 0),
                    "layer4_recommendations": db_stats.get("with_recommendations", 0),
                    "layer5_advanced_metrics": db_stats.get("with_advanced_metrics", 0),
                    "all_5_layers_complete": db_stats.get("ready_for_export", 0),
                    "date_range": f"{db_stats.get('earliest_date')} to {db_stats.get('latest_date')}"
                },
                "exports": {
                    "directory": str(self.config.export_dir),
                    "files_count": len(exported_files),
                    "latest_files": [f.name for f in sorted(exported_files, key=lambda x: x.stat().st_mtime, reverse=True)[:5]]
                },
                "gcs": {
                    "bucket": self.config.gcs_bucket,
                    "prefix": "transcripts/"
                }
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def cleanup_old_exports(self, days: int = 7) -> int:
        """
        Remove export files older than N days.

        Args:
            days: Keep files newer than this many days

        Returns:
            Number of files deleted
        """
        export_dir = Path(self.config.export_dir)
        cutoff = datetime.now() - timedelta(days=days)
        deleted = 0

        for filepath in export_dir.glob("*.jsonl"):
            if datetime.fromtimestamp(filepath.stat().st_mtime) < cutoff:
                try:
                    filepath.unlink()
                    deleted += 1
                except Exception as e:
                    logger.warning(f"Failed to delete {filepath}: {e}")

        logger.info(f"Cleaned up {deleted} old export files")
        return deleted


def run_daily_export():
    """Entry point for daily cron job."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info("Starting daily RAG export...")

    pipeline = ExportPipeline()
    result = pipeline.run_daily()

    # Log result
    logger.info(f"Daily export result: {json.dumps(result, indent=2)}")

    # Save result to file
    result_file = Path(pipeline.config.export_dir) / f"export_result_{datetime.now().strftime('%Y%m%d')}.json"
    with open(result_file, 'w') as f:
        json.dump(result, f, indent=2)

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='RAG Export Pipeline')
    parser.add_argument('--full', action='store_true', help='Run full export')
    parser.add_argument('--incremental', type=int, metavar='DAYS', help='Run incremental export for N days')
    parser.add_argument('--status', action='store_true', help='Show pipeline status')
    parser.add_argument('--cleanup', type=int, metavar='DAYS', help='Clean up exports older than N days')
    parser.add_argument('--batch-size', type=int, default=100, help='Batch size for export')
    parser.add_argument('--skip-gcs', action='store_true', help='Skip GCS upload')
    parser.add_argument('--skip-gemini', action='store_true', help='Skip Gemini import')
    parser.add_argument('--skip-vertex', action='store_true', help='Skip Vertex AI import')

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    pipeline = ExportPipeline()

    if args.status:
        status = pipeline.get_status()
        print(json.dumps(status, indent=2))

    elif args.cleanup:
        deleted = pipeline.cleanup_old_exports(args.cleanup)
        print(f"Deleted {deleted} old export files")

    elif args.full:
        result = pipeline.run_full_export(
            batch_size=args.batch_size,
            skip_gcs=args.skip_gcs,
            skip_gemini=args.skip_gemini,
            skip_vertex=args.skip_vertex
        )
        print(json.dumps(result, indent=2))

    elif args.incremental:
        result = pipeline.run_incremental(days=args.incremental)
        print(json.dumps(result, indent=2))

    else:
        # Default: run daily
        result = run_daily_export()
        print(json.dumps(result, indent=2))
