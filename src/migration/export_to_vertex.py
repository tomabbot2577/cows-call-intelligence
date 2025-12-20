#!/usr/bin/env python3
"""
Export PostgreSQL Data to Vertex AI Format

Exports all transcripts with insights from PostgreSQL to JSONL format
compatible with Vertex AI RAG Engine.

Usage:
    python src/migration/export_to_vertex.py --output /path/to/output/
    python src/migration/export_to_vertex.py --output gs://bucket/path/ --upload
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

# Add project root to path
sys.path.insert(0, '/var/www/call-recording-system')

from src.vertex_ai.config import default_config

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
    'password': 'call_insights_pass',
    'host': 'localhost',
    'port': 5432
}


class PostgreSQLExporter:
    """Exports PostgreSQL data to Vertex AI compatible format"""

    def __init__(self, db_config: Dict[str, Any] = None):
        """Initialize exporter with database config"""
        self.db_config = db_config or DB_CONFIG
        self.conn = None
        self.stats = {
            'total_exported': 0,
            'skipped': 0,
            'errors': []
        }

    def connect(self):
        """Connect to PostgreSQL"""
        self.conn = psycopg2.connect(**self.db_config, cursor_factory=RealDictCursor)
        logger.info("Connected to PostgreSQL")

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Disconnected from PostgreSQL")

    def get_transcript_count(self) -> int:
        """Get total count of transcripts with text"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM transcripts
            WHERE transcript_text IS NOT NULL
            AND LENGTH(transcript_text) > 100
        """)
        result = cursor.fetchone()
        cursor.close()
        return result['count']

    def fetch_transcripts_batch(self, offset: int, limit: int) -> List[Dict[str, Any]]:
        """
        Fetch a batch of transcripts with all related data

        Args:
            offset: Starting offset
            limit: Number of records to fetch

        Returns:
            List of transcript records with insights
        """
        cursor = self.conn.cursor()

        # Query to join all relevant tables
        query = """
            SELECT
                t.recording_id,
                t.transcript_text,
                t.call_date,
                t.call_time,
                t.duration_seconds,
                t.direction,
                t.from_number,
                t.to_number,
                t.customer_name,
                t.customer_phone,
                t.customer_company,
                t.employee_name,
                t.employee_extension,
                t.word_count,
                t.confidence_score,

                -- Insights
                i.customer_sentiment,
                i.call_quality_score,
                i.customer_satisfaction_score,
                i.call_type,
                i.issue_category,
                i.summary,
                i.key_topics,
                i.follow_up_needed,
                i.escalation_required,
                i.coaching_notes,

                -- Resolutions (if exists)
                cr.resolution_status,
                cr.problem_statement,
                cr.resolution_details,
                cr.follow_up_type,
                cr.follow_up_details,
                cr.solution_summarized,
                cr.understanding_confirmed,
                cr.asked_if_anything_else,
                cr.next_steps_provided,
                cr.timeline_given,
                cr.contact_info_provided,
                cr.closure_score,
                cr.empathy_score,
                cr.active_listening_score,
                cr.employee_knowledge_level,
                cr.customer_satisfaction_likely,
                cr.call_back_risk,
                cr.churn_risk,

                -- Recommendations (if exists)
                rec.process_improvements,
                rec.employee_strengths,
                rec.employee_improvements,
                rec.suggested_phrases,
                rec.follow_up_actions,
                rec.knowledge_base_updates,
                rec.escalation_required as rec_escalation_required,
                rec.risk_level,
                rec.efficiency_score,
                rec.training_priority

            FROM transcripts t
            LEFT JOIN insights i ON t.recording_id = i.recording_id
            LEFT JOIN call_resolutions cr ON t.recording_id = cr.recording_id
            LEFT JOIN call_recommendations rec ON t.recording_id = rec.recording_id
            WHERE t.transcript_text IS NOT NULL
            AND LENGTH(t.transcript_text) > 100
            ORDER BY t.call_date DESC, t.recording_id
            OFFSET %s LIMIT %s
        """

        cursor.execute(query, (offset, limit))
        records = cursor.fetchall()
        cursor.close()

        return [dict(r) for r in records]

    def build_vertex_document(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a Vertex AI compatible document from a database record.

        Embeds ALL metadata directly into the content field for semantic search,
        while also storing structured data for filtering.

        Args:
            record: Database record with all fields

        Returns:
            Vertex AI document structure with rich searchable content
        """
        recording_id = record['recording_id']
        transcript_text = record['transcript_text'] or ''

        # Extract all metadata fields
        call_date = str(record.get('call_date', '')) if record.get('call_date') else 'Unknown'
        call_time = str(record.get('call_time', '')) if record.get('call_time') else ''
        duration_seconds = record.get('duration_seconds') or 0
        duration_mins = round(duration_seconds / 60, 1) if duration_seconds else 0
        direction = record.get('direction') or 'Unknown'
        from_number = record.get('from_number') or ''
        to_number = record.get('to_number') or ''

        # Participants
        customer_name = record.get('customer_name') or 'Unknown Customer'
        customer_phone = record.get('customer_phone') or ''
        customer_company = record.get('customer_company') or ''
        employee_name = record.get('employee_name') or 'Unknown Employee'
        employee_extension = record.get('employee_extension') or ''

        # Sentiment & Quality
        customer_sentiment = record.get('customer_sentiment') or ''
        call_quality_score = record.get('call_quality_score') or 0
        customer_satisfaction_score = record.get('customer_satisfaction_score') or 0
        call_type = record.get('call_type') or ''
        issue_category = record.get('issue_category') or ''
        summary = record.get('summary') or ''
        key_topics = record.get('key_topics') or []
        follow_up_needed = bool(record.get('follow_up_needed'))
        escalation_required = bool(record.get('escalation_required'))
        coaching_notes = record.get('coaching_notes') or ''

        # Resolution
        resolution_status = record.get('resolution_status') or ''
        problem_statement = record.get('problem_statement') or ''
        resolution_details = record.get('resolution_details') or ''
        follow_up_type = record.get('follow_up_type') or ''
        follow_up_details = record.get('follow_up_details') or ''

        # Loop closure metrics
        closure_score = record.get('closure_score') or 0
        empathy_score = record.get('empathy_score') or 0
        active_listening_score = record.get('active_listening_score') or 0
        employee_knowledge_level = record.get('employee_knowledge_level') or ''

        # Risk assessment
        customer_satisfaction_likely = record.get('customer_satisfaction_likely') or ''
        call_back_risk = record.get('call_back_risk') or ''
        churn_risk = record.get('churn_risk') or ''

        # Recommendations
        process_improvements = record.get('process_improvements') or []
        employee_strengths = record.get('employee_strengths') or []
        employee_improvements = record.get('employee_improvements') or []
        suggested_phrases = record.get('suggested_phrases') or []
        follow_up_actions = record.get('follow_up_actions') or []
        knowledge_base_updates = record.get('knowledge_base_updates') or []
        risk_level = record.get('risk_level') or ''
        efficiency_score = record.get('efficiency_score') or 0
        training_priority = record.get('training_priority') or ''

        # Build rich searchable content with ALL metadata embedded
        content_parts = []

        # Header with call info
        content_parts.append(f"=== CALL RECORDING: {recording_id} ===")
        content_parts.append(f"Date: {call_date} {call_time}")
        content_parts.append(f"Duration: {duration_mins} minutes ({duration_seconds} seconds)")
        content_parts.append(f"Direction: {direction}")
        if from_number:
            content_parts.append(f"From: {from_number}")
        if to_number:
            content_parts.append(f"To: {to_number}")
        content_parts.append("")

        # Participants section
        content_parts.append("=== PARTICIPANTS ===")
        content_parts.append(f"Customer Name: {customer_name}")
        if customer_company:
            content_parts.append(f"Customer Company: {customer_company}")
        if customer_phone:
            content_parts.append(f"Customer Phone: {customer_phone}")
        content_parts.append(f"Employee Name: {employee_name}")
        if employee_extension:
            content_parts.append(f"Employee Extension: {employee_extension}")
        content_parts.append("")

        # Summary and Analysis section
        content_parts.append("=== CALL SUMMARY & ANALYSIS ===")
        if summary:
            content_parts.append(f"Summary: {summary}")
        content_parts.append(f"Call Type: {call_type}")
        if issue_category:
            content_parts.append(f"Issue Category: {issue_category}")
        if key_topics:
            topics_str = ', '.join(key_topics) if isinstance(key_topics, list) else str(key_topics)
            content_parts.append(f"Key Topics: {topics_str}")
        content_parts.append(f"Customer Sentiment: {customer_sentiment}")
        content_parts.append(f"Call Quality Score: {call_quality_score}/10")
        if customer_satisfaction_score:
            content_parts.append(f"Customer Satisfaction Score: {customer_satisfaction_score}/10")
        content_parts.append("")

        # Resolution section
        content_parts.append("=== RESOLUTION STATUS ===")
        content_parts.append(f"Resolution Status: {resolution_status}")
        if problem_statement:
            content_parts.append(f"Problem Statement: {problem_statement}")
        if resolution_details:
            content_parts.append(f"Resolution Details: {resolution_details}")
        content_parts.append(f"Follow-up Needed: {'Yes' if follow_up_needed else 'No'}")
        if follow_up_type:
            content_parts.append(f"Follow-up Type: {follow_up_type}")
        if follow_up_details:
            content_parts.append(f"Follow-up Details: {follow_up_details}")
        content_parts.append(f"Escalation Required: {'Yes' if escalation_required else 'No'}")
        content_parts.append("")

        # Performance Scores section
        content_parts.append("=== PERFORMANCE SCORES ===")
        content_parts.append(f"Closure Score: {closure_score}/10")
        content_parts.append(f"Empathy Score: {empathy_score}/10")
        content_parts.append(f"Active Listening Score: {active_listening_score}/10")
        if employee_knowledge_level:
            content_parts.append(f"Employee Knowledge Level: {employee_knowledge_level}")
        content_parts.append(f"Efficiency Score: {efficiency_score}/10")
        content_parts.append("")

        # Risk Assessment section
        content_parts.append("=== RISK ASSESSMENT ===")
        content_parts.append(f"Customer Satisfaction Likely: {customer_satisfaction_likely}")
        content_parts.append(f"Call Back Risk: {call_back_risk}")
        content_parts.append(f"Churn Risk: {churn_risk}")
        if risk_level:
            content_parts.append(f"Overall Risk Level: {risk_level}")
        content_parts.append("")

        # Coaching & Recommendations section
        content_parts.append("=== COACHING & RECOMMENDATIONS ===")
        if coaching_notes:
            content_parts.append(f"Coaching Notes: {coaching_notes}")
        if employee_strengths:
            strengths_str = ', '.join(employee_strengths) if isinstance(employee_strengths, list) else str(employee_strengths)
            content_parts.append(f"Employee Strengths: {strengths_str}")
        if employee_improvements:
            improvements_str = ', '.join(employee_improvements) if isinstance(employee_improvements, list) else str(employee_improvements)
            content_parts.append(f"Areas for Improvement: {improvements_str}")
        if training_priority:
            content_parts.append(f"Training Priority: {training_priority}")
        content_parts.append("")

        # Process Improvements section
        if process_improvements:
            content_parts.append("=== PROCESS IMPROVEMENTS ===")
            for i, improvement in enumerate(process_improvements, 1):
                content_parts.append(f"{i}. {improvement}")
            content_parts.append("")

        # Follow-up Actions section
        if follow_up_actions:
            content_parts.append("=== FOLLOW-UP ACTIONS ===")
            for i, action in enumerate(follow_up_actions, 1):
                content_parts.append(f"{i}. {action}")
            content_parts.append("")

        # Suggested Phrases section
        if suggested_phrases:
            content_parts.append("=== SUGGESTED PHRASES ===")
            for phrase in suggested_phrases:
                content_parts.append(f"- {phrase}")
            content_parts.append("")

        # Knowledge Base Updates section
        if knowledge_base_updates:
            content_parts.append("=== KNOWLEDGE BASE UPDATES NEEDED ===")
            for update in knowledge_base_updates:
                content_parts.append(f"- {update}")
            content_parts.append("")

        # Full Transcript section
        content_parts.append("=== FULL TRANSCRIPT ===")
        content_parts.append(transcript_text)

        # Combine all parts into searchable content
        full_content = '\n'.join(content_parts)

        # Build structured metadata for filtering
        struct_data = {
            'recording_id': recording_id,
            'indexed_at': datetime.utcnow().isoformat(),
            'call_date': str(record.get('call_date', '')) if record.get('call_date') else '',
            'call_time': str(record.get('call_time', '')) if record.get('call_time') else '',
            'duration_seconds': duration_seconds,
            'direction': direction,
            'from_number': from_number,
            'to_number': to_number,
            'word_count': record.get('word_count') or 0,
            'customer_name': customer_name,
            'customer_phone': customer_phone,
            'customer_company': customer_company,
            'employee_name': employee_name,
            'employee_extension': employee_extension or '',
            'customer_sentiment': customer_sentiment,
            'call_quality_score': call_quality_score,
            'customer_satisfaction_score': customer_satisfaction_score,
            'call_type': call_type,
            'issue_category': issue_category or '',
            'summary': summary,
            'key_topics': key_topics,
            'follow_up_needed': follow_up_needed,
            'escalation_required': escalation_required,
            'resolution_status': resolution_status,
            'closure_score': closure_score,
            'empathy_score': empathy_score,
            'active_listening_score': active_listening_score,
            'churn_risk': churn_risk,
            'call_back_risk': call_back_risk,
            'risk_level': risk_level,
            'efficiency_score': efficiency_score,
            'training_priority': training_priority,
        }

        return {
            'id': recording_id,
            'structData': struct_data,
            'content': full_content
        }

    def export_to_jsonl(
        self,
        output_path: str,
        batch_size: int = 500
    ) -> Dict[str, Any]:
        """
        Export all transcripts to JSONL files

        Args:
            output_path: Directory or GCS path for output
            batch_size: Number of records per file

        Returns:
            Export statistics
        """
        self.connect()

        try:
            total_count = self.get_transcript_count()
            logger.info(f"Found {total_count} transcripts to export")

            output_dir = Path(output_path)
            output_dir.mkdir(parents=True, exist_ok=True)

            file_num = 0
            offset = 0
            exported_files = []

            while offset < total_count:
                # Fetch batch
                records = self.fetch_transcripts_batch(offset, batch_size)
                if not records:
                    break

                # Convert to Vertex AI documents
                documents = []
                for record in records:
                    try:
                        doc = self.build_vertex_document(record)
                        documents.append(doc)
                        self.stats['total_exported'] += 1
                    except Exception as e:
                        logger.error(f"Error processing {record.get('recording_id')}: {e}")
                        self.stats['errors'].append({
                            'recording_id': record.get('recording_id'),
                            'error': str(e)
                        })
                        self.stats['skipped'] += 1

                # Write to JSONL file
                file_name = f"transcripts_{file_num:04d}.jsonl"
                file_path = output_dir / file_name

                with open(file_path, 'w', encoding='utf-8') as f:
                    for doc in documents:
                        f.write(json.dumps(doc, ensure_ascii=False) + '\n')

                exported_files.append(str(file_path))
                logger.info(f"Exported {file_name}: {len(documents)} documents")

                offset += batch_size
                file_num += 1

            self.stats['files'] = exported_files
            self.stats['total_count'] = total_count

            return self.stats

        finally:
            self.close()


def upload_to_gcs(local_files: List[str], gcs_bucket: str, gcs_prefix: str = 'exports/'):
    """
    Upload local files to GCS

    Args:
        local_files: List of local file paths
        gcs_bucket: GCS bucket name
        gcs_prefix: Prefix for GCS paths
    """
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(gcs_bucket)

    uploaded = []
    for local_path in local_files:
        blob_name = f"{gcs_prefix}{Path(local_path).name}"
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(local_path)
        gcs_uri = f"gs://{gcs_bucket}/{blob_name}"
        uploaded.append(gcs_uri)
        logger.info(f"Uploaded {local_path} to {gcs_uri}")

    return uploaded


def main():
    parser = argparse.ArgumentParser(description='Export PostgreSQL data to Vertex AI format')
    parser.add_argument('--output', '-o', default='/var/www/call-recording-system/data/vertex_exports',
                       help='Output directory for JSONL files')
    parser.add_argument('--batch-size', '-b', type=int, default=500,
                       help='Number of records per JSONL file')
    parser.add_argument('--upload', '-u', action='store_true',
                       help='Upload to GCS after export')
    parser.add_argument('--gcs-bucket', default=default_config.gcs_bucket,
                       help='GCS bucket for upload')

    args = parser.parse_args()

    # Set credentials
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = default_config.credentials_path

    logger.info("Starting PostgreSQL to Vertex AI export")
    logger.info(f"Output: {args.output}")
    logger.info(f"Batch size: {args.batch_size}")

    exporter = PostgreSQLExporter()
    stats = exporter.export_to_jsonl(args.output, args.batch_size)

    logger.info(f"\n{'='*50}")
    logger.info(f"Export Complete!")
    logger.info(f"Total exported: {stats['total_exported']}")
    logger.info(f"Skipped: {stats['skipped']}")
    logger.info(f"Files created: {len(stats.get('files', []))}")

    if stats.get('errors'):
        logger.warning(f"Errors: {len(stats['errors'])}")

    # Upload to GCS if requested
    if args.upload and stats.get('files'):
        logger.info(f"\nUploading to GCS: gs://{args.gcs_bucket}/")
        uploaded = upload_to_gcs(stats['files'], args.gcs_bucket)
        logger.info(f"Uploaded {len(uploaded)} files to GCS")
        stats['gcs_uris'] = uploaded

    # Save stats
    stats_file = Path(args.output) / 'export_stats.json'
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=2, default=str)
    logger.info(f"Stats saved to {stats_file}")

    return stats


if __name__ == '__main__':
    main()
