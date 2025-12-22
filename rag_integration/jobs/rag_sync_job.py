#!/usr/bin/env python3
"""
RAG Sync Job - Automated export of analyzed calls to Vertex AI RAG system.

This job runs every 60 minutes to:
1. Find calls with all 5 layers of analysis complete
2. Check which calls haven't been exported yet (using rag_exports table)
3. Export new calls to JSONL format
4. Upload JSONL files to Google Cloud Storage
5. Import files into Vertex AI RAG corpus
6. Track all exports in database to prevent duplicates

Usage:
    python -m rag_integration.jobs.rag_sync_job [OPTIONS]

Options:
    --batch-size N      Number of calls per batch (default: 100)
    --max-batches N     Maximum batches to process (default: 10)
    --dry-run           Show what would be exported without doing it
    --status            Show current export status and exit
    --force-reexport    Re-export failed records
    --skip-vertex       Skip Vertex AI import (just GCS)
    --skip-gemini       Skip Gemini import
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from contextlib import contextmanager
import uuid

# Add project to path
sys.path.insert(0, '/var/www/call-recording-system')

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from rag_integration.config.settings import get_config
from rag_integration.services.db_reader import DatabaseReader
from rag_integration.services.jsonl_formatter import JSONLFormatter, JSONLWriter
from rag_integration.services.gcs_uploader import GCSUploader
from rag_integration.services.vertex_rag import VertexRAGService
from rag_integration.services.gemini_file_search import GeminiFileSearchService

load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/var/www/call-recording-system/logs/rag_sync.log')
    ]
)
logger = logging.getLogger('rag_sync_job')


@dataclass
class SyncResult:
    """Result of a sync operation."""
    batch_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    calls_found: int = 0
    calls_exported: int = 0
    calls_skipped: int = 0
    calls_failed: int = 0
    jsonl_files: List[str] = None
    gcs_uris: List[str] = None
    vertex_imported: bool = False
    gemini_imported: bool = False
    errors: List[str] = None
    status: str = "running"

    def __post_init__(self):
        if self.jsonl_files is None:
            self.jsonl_files = []
        if self.gcs_uris is None:
            self.gcs_uris = []
        if self.errors is None:
            self.errors = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "calls_found": self.calls_found,
            "calls_exported": self.calls_exported,
            "calls_skipped": self.calls_skipped,
            "calls_failed": self.calls_failed,
            "jsonl_files": self.jsonl_files,
            "gcs_uris": self.gcs_uris,
            "vertex_imported": self.vertex_imported,
            "gemini_imported": self.gemini_imported,
            "errors": self.errors,
            "status": self.status,
            "duration_seconds": (self.completed_at - self.started_at).total_seconds() if self.completed_at else None
        }


class RAGExportTracker:
    """Tracks RAG exports in the database to prevent duplicates."""

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or os.getenv(
            "RAG_DATABASE_URL",
            
        )

    @contextmanager
    def get_connection(self):
        """Get a database connection."""
        conn = psycopg2.connect(self.database_url)
        try:
            yield conn
        finally:
            conn.close()

    def get_pending_calls(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get calls that are ready for RAG export (all 5 layers complete, not yet exported).

        Uses the calls_ready_for_rag_export view which joins all required tables
        and excludes already exported calls.
        """
        query = """
            SELECT * FROM calls_ready_for_rag_export
            LIMIT %s
        """

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (limit,))
                return [dict(row) for row in cur.fetchall()]

    def get_failed_exports(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get previously failed exports that should be retried."""
        query = """
            SELECT recording_id, error_message, retry_count
            FROM rag_exports
            WHERE export_status = 'failed'
              AND retry_count < 3
            ORDER BY last_retry_at ASC NULLS FIRST
            LIMIT %s
        """

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (limit,))
                return [dict(row) for row in cur.fetchall()]

    def mark_export_started(
        self,
        recording_id: str,
        batch_id: str,
        batch_sequence: int,
        call_date: Optional[str] = None,
        employee_name: Optional[str] = None,
        customer_name: Optional[str] = None
    ) -> bool:
        """Mark a call as being exported (create or update tracking record)."""
        # Clean up None strings and invalid dates
        if call_date and (call_date == 'None' or call_date == 'null' or call_date == ''):
            call_date = None

        query = """
            INSERT INTO rag_exports (
                recording_id, export_status, batch_id, batch_sequence,
                call_date, employee_name, customer_name,
                layer1_complete, layer2_complete, layer3_complete,
                layer4_complete, layer5_complete
            ) VALUES (
                %s, 'pending', %s, %s,
                %s, %s, %s,
                TRUE, TRUE, TRUE, TRUE, TRUE
            )
            ON CONFLICT (recording_id) DO UPDATE SET
                export_status = 'pending',
                batch_id = EXCLUDED.batch_id,
                batch_sequence = EXCLUDED.batch_sequence,
                retry_count = rag_exports.retry_count + 1,
                last_retry_at = CURRENT_TIMESTAMP,
                error_message = NULL
            RETURNING id
        """

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (
                        recording_id, batch_id, batch_sequence,
                        call_date, employee_name, customer_name
                    ))
                    conn.commit()
                    return True
        except Exception as e:
            logger.error(f"Failed to mark export started for {recording_id}: {e}")
            return False

    def mark_export_success(
        self,
        recording_id: str,
        jsonl_file: str,
        gcs_uri: Optional[str] = None,
        vertex_imported: bool = False,
        gemini_imported: bool = False
    ) -> bool:
        """Mark a call as successfully exported."""
        query = """
            UPDATE rag_exports SET
                export_status = 'exported',
                exported_at = CURRENT_TIMESTAMP,
                jsonl_file = %s,
                gcs_uri = %s,
                vertex_imported = %s,
                gemini_imported = %s,
                error_message = NULL
            WHERE recording_id = %s
        """

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (
                        jsonl_file, gcs_uri, vertex_imported, gemini_imported,
                        recording_id
                    ))
                    conn.commit()
                    return True
        except Exception as e:
            logger.error(f"Failed to mark export success for {recording_id}: {e}")
            return False

    def mark_export_failed(self, recording_id: str, error_message: str) -> bool:
        """Mark a call export as failed."""
        query = """
            UPDATE rag_exports SET
                export_status = 'failed',
                error_message = %s,
                last_retry_at = CURRENT_TIMESTAMP
            WHERE recording_id = %s
        """

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (error_message[:1000], recording_id))
                    conn.commit()
                    return True
        except Exception as e:
            logger.error(f"Failed to mark export failed for {recording_id}: {e}")
            return False

    def is_already_exported(self, recording_id: str) -> bool:
        """Check if a call has already been successfully exported."""
        query = """
            SELECT 1 FROM rag_exports
            WHERE recording_id = %s AND export_status = 'exported'
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (recording_id,))
                return cur.fetchone() is not None

    def get_export_stats(self) -> Dict[str, Any]:
        """Get overall export statistics."""
        query = """
            SELECT
                COUNT(*) as total_tracked,
                SUM(CASE WHEN export_status = 'exported' THEN 1 ELSE 0 END) as exported,
                SUM(CASE WHEN export_status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN export_status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN vertex_imported THEN 1 ELSE 0 END) as vertex_imported,
                SUM(CASE WHEN gemini_imported THEN 1 ELSE 0 END) as gemini_imported,
                MIN(exported_at) as earliest_export,
                MAX(exported_at) as latest_export
            FROM rag_exports
        """

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query)
                row = cur.fetchone()

                # Get count ready for export
                cur.execute("SELECT COUNT(*) as count FROM calls_ready_for_rag_export")
                ready_row = cur.fetchone()
                ready_count = ready_row['count'] if ready_row else 0

                return {
                    **dict(row),
                    "ready_for_export": ready_count
                }


class RAGSyncJob:
    """Main job that syncs analyzed calls to Vertex AI RAG."""

    def __init__(
        self,
        batch_size: int = 100,
        max_batches: int = 10,
        skip_vertex: bool = False,
        skip_gemini: bool = False
    ):
        self.config = get_config()
        self.batch_size = batch_size
        self.max_batches = max_batches
        self.skip_vertex = skip_vertex
        self.skip_gemini = skip_gemini

        # Initialize services
        self.tracker = RAGExportTracker()
        self.db_reader = DatabaseReader()
        self.formatter = JSONLFormatter()
        self.writer = JSONLWriter(self.config.export_dir)
        self.gcs = GCSUploader(self.config.gcs_bucket)

        # Lazy initialize RAG services
        self._vertex = None
        self._gemini = None

    @property
    def vertex(self) -> VertexRAGService:
        if self._vertex is None and not self.skip_vertex:
            self._vertex = VertexRAGService(
                project_id=self.config.gcp_project,
                location=self.config.vertex_location
            )
        return self._vertex

    @property
    def gemini(self) -> GeminiFileSearchService:
        if self._gemini is None and not self.skip_gemini:
            self._gemini = GeminiFileSearchService(self.config.gemini_api_key)
        return self._gemini

    def run(self, dry_run: bool = False, force_reexport: bool = False) -> SyncResult:
        """
        Run the sync job.

        Args:
            dry_run: If True, just show what would be done without doing it
            force_reexport: If True, also retry failed exports

        Returns:
            SyncResult with statistics
        """
        batch_id = f"sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        result = SyncResult(batch_id=batch_id, started_at=datetime.now())

        logger.info(f"Starting RAG sync job (batch_id={batch_id}, dry_run={dry_run})")

        try:
            # Step 1: Get pending calls
            pending_calls = self.tracker.get_pending_calls(limit=self.batch_size * self.max_batches)
            result.calls_found = len(pending_calls)

            if force_reexport:
                failed_calls = self.tracker.get_failed_exports(limit=50)
                logger.info(f"Including {len(failed_calls)} failed exports for retry")
                # Add failed recording_ids to pending list
                failed_ids = {c['recording_id'] for c in failed_calls}
                pending_calls.extend([{'recording_id': rid} for rid in failed_ids
                                     if rid not in {c['recording_id'] for c in pending_calls}])

            logger.info(f"Found {result.calls_found} calls ready for RAG export")

            if result.calls_found == 0:
                result.status = "success"
                result.completed_at = datetime.now()
                logger.info("No calls to export")
                return result

            if dry_run:
                logger.info(f"DRY RUN: Would export {result.calls_found} calls")
                result.status = "dry_run"
                result.completed_at = datetime.now()
                return result

            # Step 2: Process in batches
            batches_processed = 0
            for batch_start in range(0, len(pending_calls), self.batch_size):
                if batches_processed >= self.max_batches:
                    logger.info(f"Reached max batches ({self.max_batches}), stopping")
                    break

                batch = pending_calls[batch_start:batch_start + self.batch_size]
                batch_num = batches_processed + 1

                logger.info(f"Processing batch {batch_num}/{min(self.max_batches, (len(pending_calls) + self.batch_size - 1) // self.batch_size)}: {len(batch)} calls")

                batch_result = self._process_batch(batch, batch_id, batch_num)

                result.calls_exported += batch_result['exported']
                result.calls_failed += batch_result['failed']
                result.calls_skipped += batch_result['skipped']
                if batch_result.get('jsonl_file'):
                    result.jsonl_files.append(batch_result['jsonl_file'])
                if batch_result.get('gcs_uri'):
                    result.gcs_uris.append(batch_result['gcs_uri'])
                result.errors.extend(batch_result.get('errors', []))

                batches_processed += 1

            # Step 3: Import to RAG systems
            if result.gcs_uris:
                if not self.skip_vertex:
                    result.vertex_imported = self._import_to_vertex(result.gcs_uris)
                if not self.skip_gemini:
                    result.gemini_imported = self._import_to_gemini(result.jsonl_files)

            result.status = "success" if not result.errors else "partial"
            result.completed_at = datetime.now()

            logger.info(f"Sync complete: {result.calls_exported} exported, {result.calls_failed} failed, {result.calls_skipped} skipped")

        except Exception as e:
            logger.error(f"Sync job failed: {e}")
            result.status = "error"
            result.errors.append(str(e))
            result.completed_at = datetime.now()

        # Save result to file
        self._save_result(result)

        return result

    def _process_batch(
        self,
        batch: List[Dict[str, Any]],
        batch_id: str,
        batch_num: int
    ) -> Dict[str, Any]:
        """Process a batch of calls."""
        result = {
            'exported': 0,
            'failed': 0,
            'skipped': 0,
            'errors': [],
            'jsonl_file': None,
            'gcs_uri': None
        }

        documents = []
        recording_ids = []

        for seq, call_info in enumerate(batch):
            recording_id = call_info['recording_id']

            try:
                # Double-check not already exported
                if self.tracker.is_already_exported(recording_id):
                    result['skipped'] += 1
                    continue

                # Mark as being processed
                self.tracker.mark_export_started(
                    recording_id=recording_id,
                    batch_id=batch_id,
                    batch_sequence=seq,
                    call_date=str(call_info.get('call_date', '')),
                    employee_name=call_info.get('employee_name'),
                    customer_name=call_info.get('customer_name')
                )

                # Get full call data
                call_data = self._get_full_call_data(recording_id)
                if not call_data:
                    raise ValueError(f"Could not retrieve full data for {recording_id}")

                # Format for JSONL
                doc = self.formatter.format_call(call_data)
                documents.append(doc)
                recording_ids.append(recording_id)

            except Exception as e:
                error_msg = f"Error processing {recording_id}: {e}"
                logger.error(error_msg)
                result['errors'].append(error_msg)
                result['failed'] += 1
                self.tracker.mark_export_failed(recording_id, str(e))

        # Write batch to JSONL
        if documents:
            try:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"rag_sync_{batch_id}_batch{batch_num:03d}_{timestamp}.jsonl"
                filepath = self.writer.write_batch(documents, filename)
                result['jsonl_file'] = str(filepath)

                logger.info(f"Wrote {len(documents)} documents to {filepath}")

                # Upload to GCS
                gcs_uri = self.gcs.upload_file(filepath)
                result['gcs_uri'] = gcs_uri
                logger.info(f"Uploaded to {gcs_uri}")

                # Mark all as exported
                for recording_id in recording_ids:
                    self.tracker.mark_export_success(
                        recording_id=recording_id,
                        jsonl_file=str(filepath),
                        gcs_uri=gcs_uri,
                        vertex_imported=False,  # Will be updated after import
                        gemini_imported=False
                    )
                    result['exported'] += 1

            except Exception as e:
                error_msg = f"Failed to write/upload batch: {e}"
                logger.error(error_msg)
                result['errors'].append(error_msg)
                for recording_id in recording_ids:
                    self.tracker.mark_export_failed(recording_id, str(e))
                    result['failed'] += 1

        return result

    def _get_full_call_data(self, recording_id: str) -> Optional[Dict[str, Any]]:
        """Get full call data with all 5 layers."""
        query = """
            SELECT
                t.recording_id, t.call_date, t.call_time, t.duration_seconds,
                t.direction, t.from_number, t.to_number,
                t.customer_name, t.customer_company, t.customer_phone,
                t.employee_name, t.employee_department, t.transcript_text,
                t.word_count, t.confidence_score as transcript_confidence,

                i.customer_sentiment, i.call_quality_score, i.customer_satisfaction_score,
                i.call_type, i.issue_category, i.summary, i.key_topics,
                i.churn_risk_score, i.coaching_notes, i.follow_up_needed,
                i.escalation_required, i.first_call_resolution,
                i.sentiment_reasoning, i.quality_reasoning, i.overall_call_rating,

                cr.problem_complexity, cr.resolution_status, cr.resolution_details,
                cr.resolution_effectiveness, cr.empathy_score, cr.empathy_demonstrated,
                cr.active_listening_score, cr.employee_knowledge_level,
                cr.confidence_in_solution, cr.training_needed,
                cr.churn_risk as resolution_churn_risk, cr.revenue_impact,
                cr.customer_effort_score, cr.first_contact_resolution, cr.closure_score,
                cr.solution_summarized, cr.understanding_confirmed,
                cr.asked_if_anything_else, cr.next_steps_provided,
                cr.timeline_given, cr.contact_info_provided,
                cr.thanked_customer, cr.confirmed_satisfaction,

                rec.process_improvements, rec.employee_strengths,
                rec.employee_improvements, rec.suggested_phrases,
                rec.follow_up_actions, rec.knowledge_base_updates,
                rec.escalation_required as rec_escalation_required,
                rec.risk_level, rec.efficiency_score, rec.training_priority

            FROM transcripts t
            INNER JOIN insights i ON t.recording_id = i.recording_id
            INNER JOIN call_resolutions cr ON t.recording_id = cr.recording_id
            INNER JOIN call_recommendations rec ON t.recording_id = rec.recording_id
            WHERE t.recording_id = %s
        """

        with self.tracker.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (recording_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def _import_to_vertex(self, gcs_uris: List[str]) -> bool:
        """Import GCS files to Vertex AI RAG corpus."""
        if not gcs_uris or self.skip_vertex:
            return False

        try:
            logger.info(f"Importing {len(gcs_uris)} files to Vertex AI RAG...")

            # Initialize corpus if needed
            self.vertex.initialize_corpus()

            for gcs_uri in gcs_uris:
                result = self.vertex.import_from_gcs(gcs_uri)
                if result.get('error'):
                    logger.warning(f"Vertex import warning for {gcs_uri}: {result['error']}")

            logger.info("Vertex AI RAG import complete")

            # Update tracker to mark vertex_imported = True
            self._update_vertex_imported(gcs_uris)

            return True

        except Exception as e:
            logger.error(f"Vertex AI RAG import failed: {e}")
            return False

    def _import_to_gemini(self, jsonl_files: List[str]) -> bool:
        """Import JSONL files to Gemini."""
        if not jsonl_files or self.skip_gemini:
            return False

        try:
            logger.info(f"Importing {len(jsonl_files)} files to Gemini...")

            for filepath in jsonl_files:
                if Path(filepath).exists():
                    result = self.gemini.upload_file(filepath)
                    logger.info(f"Uploaded to Gemini: {result.get('name')}")

            logger.info("Gemini import complete")

            # Update tracker to mark gemini_imported = True
            self._update_gemini_imported(jsonl_files)

            return True

        except Exception as e:
            logger.error(f"Gemini import failed: {e}")
            return False

    def _update_vertex_imported(self, gcs_uris: List[str]):
        """Update tracker to mark calls as imported to Vertex."""
        query = """
            UPDATE rag_exports SET vertex_imported = TRUE
            WHERE gcs_uri = ANY(%s)
        """
        try:
            with self.tracker.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (gcs_uris,))
                    conn.commit()
        except Exception as e:
            logger.warning(f"Failed to update vertex_imported flag: {e}")

    def _update_gemini_imported(self, jsonl_files: List[str]):
        """Update tracker to mark calls as imported to Gemini."""
        query = """
            UPDATE rag_exports SET gemini_imported = TRUE
            WHERE jsonl_file = ANY(%s)
        """
        try:
            with self.tracker.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (jsonl_files,))
                    conn.commit()
        except Exception as e:
            logger.warning(f"Failed to update gemini_imported flag: {e}")

    def _save_result(self, result: SyncResult):
        """Save sync result to file for audit."""
        results_dir = Path(self.config.export_dir) / 'sync_results'
        results_dir.mkdir(parents=True, exist_ok=True)

        result_file = results_dir / f"sync_result_{result.batch_id}.json"
        with open(result_file, 'w') as f:
            json.dump(result.to_dict(), f, indent=2, default=str)

        logger.info(f"Saved sync result to {result_file}")

    def get_status(self) -> Dict[str, Any]:
        """Get current sync status and statistics."""
        stats = self.tracker.get_export_stats()

        # Get GCS file count
        try:
            gcs_files = self.gcs.list_files()
            gcs_count = len(gcs_files)
        except Exception as e:
            gcs_count = f"Error: {e}"

        # Get Gemini file count
        try:
            if self.gemini:
                gemini_files = self.gemini.list_files()
                gemini_count = len(gemini_files)
            else:
                gemini_count = "Skipped"
        except Exception as e:
            gemini_count = f"Error: {e}"

        return {
            "database": stats,
            "gcs": {
                "bucket": self.config.gcs_bucket,
                "file_count": gcs_count
            },
            "gemini": {
                "file_count": gemini_count
            },
            "config": {
                "batch_size": self.batch_size,
                "max_batches": self.max_batches,
                "skip_vertex": self.skip_vertex,
                "skip_gemini": self.skip_gemini
            },
            "timestamp": datetime.now().isoformat()
        }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='RAG Sync Job - Export analyzed calls to Vertex AI RAG')
    parser.add_argument('--batch-size', type=int, default=100, help='Calls per batch (default: 100)')
    parser.add_argument('--max-batches', type=int, default=10, help='Max batches to process (default: 10)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without doing it')
    parser.add_argument('--status', action='store_true', help='Show status and exit')
    parser.add_argument('--force-reexport', action='store_true', help='Retry failed exports')
    parser.add_argument('--skip-vertex', action='store_true', help='Skip Vertex AI import')
    parser.add_argument('--skip-gemini', action='store_true', help='Skip Gemini import')
    parser.add_argument('--json', action='store_true', help='Output results as JSON')

    args = parser.parse_args()

    job = RAGSyncJob(
        batch_size=args.batch_size,
        max_batches=args.max_batches,
        skip_vertex=args.skip_vertex,
        skip_gemini=args.skip_gemini
    )

    if args.status:
        status = job.get_status()
        if args.json:
            print(json.dumps(status, indent=2, default=str))
        else:
            print("\n=== RAG Sync Status ===")
            print(f"\nDatabase Tracking:")
            print(f"  Total tracked: {status['database']['total_tracked']}")
            print(f"  Exported: {status['database']['exported']}")
            print(f"  Failed: {status['database']['failed']}")
            print(f"  Ready for export: {status['database']['ready_for_export']}")
            print(f"  Vertex imported: {status['database']['vertex_imported']}")
            print(f"  Gemini imported: {status['database']['gemini_imported']}")
            print(f"\nGCS Bucket: {status['gcs']['bucket']}")
            print(f"  Files: {status['gcs']['file_count']}")
            print(f"\nGemini Files: {status['gemini']['file_count']}")
        return

    # Run the sync
    result = job.run(dry_run=args.dry_run, force_reexport=args.force_reexport)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print("\n=== RAG Sync Complete ===")
        print(f"Batch ID: {result.batch_id}")
        print(f"Status: {result.status}")
        print(f"Calls found: {result.calls_found}")
        print(f"Exported: {result.calls_exported}")
        print(f"Failed: {result.calls_failed}")
        print(f"Skipped: {result.calls_skipped}")
        print(f"JSONL files: {len(result.jsonl_files)}")
        print(f"GCS uploads: {len(result.gcs_uris)}")
        print(f"Vertex imported: {result.vertex_imported}")
        print(f"Gemini imported: {result.gemini_imported}")
        if result.errors:
            print(f"\nErrors ({len(result.errors)}):")
            for err in result.errors[:5]:
                print(f"  - {err}")
            if len(result.errors) > 5:
                print(f"  ... and {len(result.errors) - 5} more")


if __name__ == "__main__":
    main()
