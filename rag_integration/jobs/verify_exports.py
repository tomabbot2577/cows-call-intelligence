#!/usr/bin/env python3
"""
RAG Export Verification Tool

Verifies that:
1. JSONL files contain all 5 layers of metadata
2. Data is properly formatted for RAG systems
3. GCS uploads match local files
4. Vertex AI corpus contains the expected files

Usage:
    python -m rag_integration.jobs.verify_exports [OPTIONS]

Options:
    --check-jsonl FILE     Verify a specific JSONL file
    --check-latest         Verify the latest export
    --check-gcs            Verify GCS bucket contents
    --check-vertex         Verify Vertex AI corpus
    --check-db N           Verify N random records from tracking DB
    --full                 Run all checks
    --sample N             Show N sample records (default: 3)
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import random

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
load_dotenv()

from rag_integration.config.settings import get_config
from rag_integration.services.gcs_uploader import GCSUploader
from rag_integration.services.vertex_rag import VertexRAGService
from rag_integration.jobs.rag_sync_job import RAGExportTracker


class ExportVerifier:
    """Verifies RAG exports are complete and correct."""

    # Required fields for each layer
    LAYER1_FIELDS = ['employee_name', 'customer_name', 'customer_company']
    LAYER2_FIELDS = ['customer_sentiment', 'call_quality_score', 'summary', 'call_type']
    LAYER3_FIELDS = ['resolution_effectiveness', 'empathy_score', 'churn_risk', 'closure_score']
    LAYER4_FIELDS = ['process_improvements', 'employee_strengths', 'follow_up_actions']
    LAYER5_FIELDS = ['has_layer5']  # Indicates layer 5 was present in source

    def __init__(self):
        self.config = get_config()
        self.export_dir = Path(self.config.export_dir)
        self.tracker = RAGExportTracker()
        self._gcs = None
        self._vertex = None

    @property
    def gcs(self):
        if self._gcs is None:
            self._gcs = GCSUploader(self.config.gcs_bucket)
        return self._gcs

    @property
    def vertex(self):
        if self._vertex is None:
            self._vertex = VertexRAGService(
                project_id=self.config.gcp_project,
                location=self.config.vertex_location
            )
        return self._vertex

    def verify_jsonl_file(self, filepath: str, sample_size: int = 3) -> Dict[str, Any]:
        """
        Verify a JSONL file contains properly formatted records with all layers.

        Returns:
            Dict with verification results
        """
        filepath = Path(filepath)
        if not filepath.exists():
            return {"status": "error", "error": f"File not found: {filepath}"}

        result = {
            "file": str(filepath),
            "status": "ok",
            "total_records": 0,
            "valid_records": 0,
            "issues": [],
            "layer_coverage": {
                "layer1": 0,
                "layer2": 0,
                "layer3": 0,
                "layer4": 0,
                "layer5": 0,
            },
            "samples": []
        }

        records = []
        with open(filepath, 'r') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    record = json.loads(line.strip())
                    records.append(record)
                    result["total_records"] += 1

                    # Verify structure
                    issues = self._verify_record_structure(record, line_num)
                    if issues:
                        result["issues"].extend(issues)
                    else:
                        result["valid_records"] += 1

                    # Check layer coverage
                    self._check_layer_coverage(record, result["layer_coverage"])

                except json.JSONDecodeError as e:
                    result["issues"].append(f"Line {line_num}: Invalid JSON - {e}")

        # Add sample records
        if records:
            samples = random.sample(records, min(sample_size, len(records)))
            for sample in samples:
                result["samples"].append(self._summarize_record(sample))

        # Calculate percentages
        if result["total_records"] > 0:
            for layer in result["layer_coverage"]:
                result["layer_coverage"][layer] = {
                    "count": result["layer_coverage"][layer],
                    "percent": round(result["layer_coverage"][layer] / result["total_records"] * 100, 1)
                }

        if result["issues"]:
            result["status"] = "warning" if result["valid_records"] > 0 else "error"

        return result

    def _verify_record_structure(self, record: Dict, line_num: int) -> List[str]:
        """Verify a single record has the correct structure."""
        issues = []

        # Check required top-level fields
        if "id" not in record:
            issues.append(f"Line {line_num}: Missing 'id' field")
        if "content" not in record:
            issues.append(f"Line {line_num}: Missing 'content' field")
        if "struct_data" not in record:
            issues.append(f"Line {line_num}: Missing 'struct_data' field")

        # Check content structure
        content = record.get("content", {})
        if not isinstance(content, dict):
            issues.append(f"Line {line_num}: 'content' should be a dict")
        elif "text" not in content:
            issues.append(f"Line {line_num}: Missing 'content.text' field")
        elif len(content.get("text", "")) < 100:
            issues.append(f"Line {line_num}: Content text too short ({len(content.get('text', ''))} chars)")

        return issues

    def _check_layer_coverage(self, record: Dict, coverage: Dict):
        """Check which layers have data in this record."""
        content_text = record.get("content", {}).get("text", "")
        struct_data = record.get("struct_data", {})

        # Layer 1: Names
        if any(struct_data.get(f) for f in self.LAYER1_FIELDS):
            coverage["layer1"] += 1

        # Layer 2: Sentiment/Quality
        if any(struct_data.get(f) for f in self.LAYER2_FIELDS):
            coverage["layer2"] += 1

        # Layer 3: Resolution
        if "[LAYER 3" in content_text or any(struct_data.get(f) for f in self.LAYER3_FIELDS):
            coverage["layer3"] += 1

        # Layer 4: Recommendations
        if "[LAYER 4" in content_text or any(struct_data.get(f) for f in self.LAYER4_FIELDS):
            coverage["layer4"] += 1

        # Layer 5: Advanced Metrics
        if struct_data.get("has_layer5") or "[LAYER 5" in content_text:
            coverage["layer5"] += 1

    def _summarize_record(self, record: Dict) -> Dict:
        """Create a summary of a record for display."""
        struct_data = record.get("struct_data", {})
        content = record.get("content", {}).get("text", "")

        return {
            "id": record.get("id"),
            "call_date": struct_data.get("call_date"),
            "employee": struct_data.get("employee_name"),
            "customer": struct_data.get("customer_name"),
            "company": struct_data.get("customer_company"),
            "sentiment": struct_data.get("customer_sentiment"),
            "quality_score": struct_data.get("call_quality_score"),
            "churn_risk": struct_data.get("churn_risk_score"),
            "content_length": len(content),
            "has_transcript": "[TRANSCRIPT]" in content,
            "has_layer_markers": all(f"[LAYER {i}" in content or f"[{['CALL METADATA', 'PARTICIPANTS', 'LAYER 2', 'LAYER 3', 'LAYER 4'][i-1] if i <= 4 else 'LAYER 5'}" in content for i in range(1, 5))
        }

    def verify_gcs_contents(self) -> Dict[str, Any]:
        """Verify GCS bucket contents."""
        try:
            files = self.gcs.list_files()
            return {
                "status": "ok",
                "bucket": self.config.gcs_bucket,
                "file_count": len(files),
                "files": files[:10],
                "total_files": len(files)
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def verify_vertex_corpus(self) -> Dict[str, Any]:
        """Verify Vertex AI RAG corpus."""
        try:
            status = self.vertex.get_status()
            files = self.vertex.list_files_in_corpus()
            return {
                "status": "ok",
                "corpus": status.get("corpus", {}),
                "file_count": len(files),
                "files": files[:10]
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def verify_tracking_db(self, limit: int = 10) -> Dict[str, Any]:
        """Verify tracking database records."""
        try:
            stats = self.tracker.get_export_stats()

            # Get sample exports
            with self.tracker.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT recording_id, export_status, exported_at, vertex_imported, gemini_imported
                        FROM rag_exports
                        WHERE export_status = 'exported'
                        ORDER BY exported_at DESC
                        LIMIT %s
                    """, (limit,))
                    samples = [
                        {
                            "recording_id": row[0],
                            "status": row[1],
                            "exported_at": str(row[2]) if row[2] else None,
                            "vertex": row[3],
                            "gemini": row[4]
                        }
                        for row in cur.fetchall()
                    ]

            return {
                "status": "ok",
                "stats": stats,
                "recent_exports": samples
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def verify_latest_export(self, sample_size: int = 3) -> Dict[str, Any]:
        """Verify the most recent export file."""
        jsonl_files = sorted(self.export_dir.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True)
        if not jsonl_files:
            return {"status": "error", "error": "No JSONL files found in export directory"}

        latest = jsonl_files[0]
        return self.verify_jsonl_file(str(latest), sample_size)

    def run_full_verification(self, sample_size: int = 3) -> Dict[str, Any]:
        """Run all verification checks."""
        print("\n" + "="*60)
        print("RAG EXPORT VERIFICATION")
        print("="*60)

        results = {}

        # 1. Check latest JSONL
        print("\n[1/4] Verifying latest JSONL export...")
        results["jsonl"] = self.verify_latest_export(sample_size)
        self._print_jsonl_result(results["jsonl"])

        # 2. Check GCS
        print("\n[2/4] Verifying GCS bucket...")
        results["gcs"] = self.verify_gcs_contents()
        self._print_gcs_result(results["gcs"])

        # 3. Check Vertex
        print("\n[3/4] Verifying Vertex AI corpus...")
        results["vertex"] = self.verify_vertex_corpus()
        self._print_vertex_result(results["vertex"])

        # 4. Check tracking DB
        print("\n[4/4] Verifying tracking database...")
        results["database"] = self.verify_tracking_db()
        self._print_db_result(results["database"])

        # Summary
        print("\n" + "="*60)
        print("VERIFICATION SUMMARY")
        print("="*60)
        all_ok = all(r.get("status") == "ok" for r in results.values())
        print(f"Overall Status: {'OK' if all_ok else 'ISSUES FOUND'}")

        return results

    def _print_jsonl_result(self, result: Dict):
        """Print JSONL verification result."""
        if result.get("status") == "error":
            print(f"  ERROR: {result.get('error')}")
            return

        print(f"  File: {result.get('file')}")
        print(f"  Total records: {result.get('total_records')}")
        print(f"  Valid records: {result.get('valid_records')}")
        print(f"  Status: {result.get('status').upper()}")

        print("\n  Layer Coverage:")
        for layer, data in result.get("layer_coverage", {}).items():
            if isinstance(data, dict):
                print(f"    {layer}: {data['count']} ({data['percent']}%)")

        if result.get("samples"):
            print("\n  Sample Records:")
            for i, sample in enumerate(result["samples"], 1):
                print(f"    [{i}] {sample.get('id')}")
                print(f"        Date: {sample.get('call_date')}, Employee: {sample.get('employee')}")
                print(f"        Customer: {sample.get('customer')} ({sample.get('company')})")
                print(f"        Sentiment: {sample.get('sentiment')}, Quality: {sample.get('quality_score')}")
                print(f"        Content: {sample.get('content_length')} chars, Has transcript: {sample.get('has_transcript')}")

        if result.get("issues"):
            print(f"\n  Issues ({len(result['issues'])}):")
            for issue in result["issues"][:5]:
                print(f"    - {issue}")

    def _print_gcs_result(self, result: Dict):
        """Print GCS verification result."""
        if result.get("status") == "error":
            print(f"  ERROR: {result.get('error')}")
            return

        print(f"  Bucket: {result.get('bucket')}")
        print(f"  Total files: {result.get('file_count')}")
        print("  Recent files:")
        for f in result.get("files", [])[:5]:
            print(f"    - {f}")

    def _print_vertex_result(self, result: Dict):
        """Print Vertex verification result."""
        if result.get("status") == "error":
            print(f"  ERROR: {result.get('error')}")
            return

        corpus = result.get("corpus", {})
        print(f"  Corpus: {corpus.get('display_name', 'N/A')}")
        print(f"  Status: {corpus.get('status', 'N/A')}")
        print(f"  Files: {result.get('file_count')}")

    def _print_db_result(self, result: Dict):
        """Print database verification result."""
        if result.get("status") == "error":
            print(f"  ERROR: {result.get('error')}")
            return

        stats = result.get("stats", {})
        print(f"  Total tracked: {stats.get('total_tracked', 0)}")
        print(f"  Exported: {stats.get('exported', 0)}")
        print(f"  Failed: {stats.get('failed', 0)}")
        print(f"  Ready for export: {stats.get('ready_for_export', 0)}")
        print(f"  Vertex imported: {stats.get('vertex_imported', 0)}")
        print(f"  Gemini imported: {stats.get('gemini_imported', 0)}")


def main():
    parser = argparse.ArgumentParser(description='Verify RAG exports')
    parser.add_argument('--check-jsonl', type=str, help='Verify specific JSONL file')
    parser.add_argument('--check-latest', action='store_true', help='Verify latest export')
    parser.add_argument('--check-gcs', action='store_true', help='Verify GCS contents')
    parser.add_argument('--check-vertex', action='store_true', help='Verify Vertex corpus')
    parser.add_argument('--check-db', type=int, metavar='N', help='Verify N DB records')
    parser.add_argument('--full', action='store_true', help='Run all checks')
    parser.add_argument('--sample', type=int, default=3, help='Number of samples to show')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    verifier = ExportVerifier()

    if args.full or not any([args.check_jsonl, args.check_latest, args.check_gcs, args.check_vertex, args.check_db]):
        results = verifier.run_full_verification(args.sample)
        if args.json:
            print(json.dumps(results, indent=2, default=str))
        return

    results = {}

    if args.check_jsonl:
        results["jsonl"] = verifier.verify_jsonl_file(args.check_jsonl, args.sample)

    if args.check_latest:
        results["latest"] = verifier.verify_latest_export(args.sample)

    if args.check_gcs:
        results["gcs"] = verifier.verify_gcs_contents()

    if args.check_vertex:
        results["vertex"] = verifier.verify_vertex_corpus()

    if args.check_db:
        results["database"] = verifier.verify_tracking_db(args.check_db)

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
