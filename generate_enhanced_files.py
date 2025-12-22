#!/usr/bin/env python3
"""
Generate enhanced JSON files with all AI insights and upload to Google Drive
"""

import json
import os
import sys
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from datetime import datetime

sys.path.insert(0, '/var/www/call-recording-system')

# Try to import Google Drive uploader, fallback if not available
try:
    from src.storage.google_drive import GoogleDriveUploader
    GDRIVE_AVAILABLE = True
except ImportError:
    print("⚠️ Google Drive uploader not available, will skip uploads")
    GoogleDriveUploader = None
    GDRIVE_AVAILABLE = False

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': os.getenv('PG_PASSWORD', ''),
    'host': 'localhost',
    'port': 5432
}

def get_complete_transcript_data(recording_id):
    """Get complete transcript data with all insights"""
    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT
                t.*,
                i.call_quality_score,
                i.customer_sentiment,
                i.call_type,
                i.key_topics,
                i.summary,
                i.follow_up_needed,
                i.escalation_required,
                r.process_improvements,
                r.employee_strengths,
                r.employee_improvements,
                r.suggested_phrases,
                r.follow_up_actions,
                r.knowledge_base_updates,
                r.escalation_required as rec_escalation_required,
                r.risk_level,
                r.escalation_reason,
                r.efficiency_score,
                r.training_priority,
                cr.problem_statement,
                cr.resolution_status,
                cr.resolution_details,
                cr.follow_up_type,
                cr.follow_up_details,
                cr.follow_up_timeline,
                cr.solution_summarized,
                cr.understanding_confirmed,
                cr.asked_if_anything_else,
                cr.next_steps_provided,
                cr.timeline_given,
                cr.contact_info_provided,
                cr.closure_score,
                cr.missed_best_practices,
                cr.improvement_suggestions,
                cr.customer_satisfaction_likely,
                cr.call_back_risk,
                cr.escalation_probability
            FROM transcripts t
            LEFT JOIN insights i ON t.recording_id = i.recording_id
            LEFT JOIN call_recommendations r ON t.recording_id = r.recording_id
            LEFT JOIN call_resolutions cr ON t.recording_id = cr.recording_id
            WHERE t.recording_id = %s
            AND t.transcript_text IS NOT NULL
            AND LENGTH(t.transcript_text) > 100
        """, (recording_id,))

        return cursor.fetchone()

    finally:
        cursor.close()
        conn.close()

def create_enhanced_json(transcript_data):
    """Create enhanced JSON with all insights"""

    # Convert psycopg2 record to dict and handle None values
    data = dict(transcript_data)

    # Build enhanced structure
    enhanced = {
        "recording_id": data['recording_id'],
        "version": "3.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "processing_complete": True,

        "call_metadata": {
            "date": str(data.get('call_date', ''))[:10] if data.get('call_date') else '',
            "duration_seconds": data.get('duration_seconds', 0),
            "word_count": data.get('word_count', 0),
            "customer": {
                "name": data.get('customer_name', 'Unknown'),
                "phone": data.get('customer_phone', ''),
                "company": data.get('customer_company', '')
            },
            "employee": {
                "name": data.get('employee_name', 'Unknown'),
                "extension": data.get('employee_extension', ''),
                "department": data.get('employee_department', '')
            }
        },

        "transcript_text": data.get('transcript_text', ''),

        "ai_insights": {
            "sentiment_analysis": {
                "customer_sentiment": data.get('customer_sentiment', 'unknown'),
                "call_quality_score": float(data.get('call_quality_score', 0)) if data.get('call_quality_score') else 0,
                "call_type": data.get('call_type', 'unknown'),
                "key_topics": data.get('key_topics', []) or [],
                "summary": data.get('summary', ''),
                "follow_up_needed": data.get('follow_up_needed', False),
                "escalation_required": data.get('escalation_required', False)
            },

            "process_recommendations": {
                "process_improvements": data.get('process_improvements', []) or [],
                "employee_coaching": {
                    "strengths": data.get('employee_strengths', []) or [],
                    "improvements": data.get('employee_improvements', []) or [],
                    "suggested_phrases": data.get('suggested_phrases', []) or []
                },
                "follow_up_actions": data.get('follow_up_actions', []) or [],
                "knowledge_base_updates": data.get('knowledge_base_updates', []) or [],
                "escalation": {
                    "required": data.get('rec_escalation_required', False),
                    "risk_level": data.get('risk_level', 'low'),
                    "reason": data.get('escalation_reason', '')
                },
                "performance_metrics": {
                    "efficiency_score": float(data.get('efficiency_score', 0)) if data.get('efficiency_score') else 0,
                    "training_priority": data.get('training_priority', 'low')
                }
            },

            "call_resolution": {
                "problem_statement": data.get('problem_statement', ''),
                "resolution_status": data.get('resolution_status', 'unknown'),
                "resolution_details": data.get('resolution_details', ''),
                "follow_up": {
                    "type": data.get('follow_up_type', 'none'),
                    "details": data.get('follow_up_details', ''),
                    "timeline": data.get('follow_up_timeline', '')
                },
                "loop_closure": {
                    "solution_summarized": data.get('solution_summarized', False),
                    "understanding_confirmed": data.get('understanding_confirmed', False),
                    "asked_if_anything_else": data.get('asked_if_anything_else', False),
                    "next_steps_provided": data.get('next_steps_provided', False),
                    "timeline_given": data.get('timeline_given', False),
                    "contact_info_provided": data.get('contact_info_provided', False),
                    "closure_score": float(data.get('closure_score', 0)) if data.get('closure_score') else 0
                },
                "quality_assessment": {
                    "missed_best_practices": data.get('missed_best_practices', []) or [],
                    "improvement_suggestions": data.get('improvement_suggestions', []) or [],
                    "customer_satisfaction_likely": data.get('customer_satisfaction_likely', 'unknown'),
                    "call_back_risk": data.get('call_back_risk', 'unknown'),
                    "escalation_probability": data.get('escalation_probability', 'unknown')
                }
            }
        },

        "pipeline_metadata": {
            "ai_model_versions": {
                "sentiment": "deepseek/deepseek-r1",
                "recommendations": "deepseek/deepseek-r1",
                "name_extraction": "anthropic/claude-3-opus",
                "embeddings": "openai/text-embedding-ada-002"
            },
            "processing_date": datetime.utcnow().isoformat() + "Z",
            "version": "3.0"
        }
    }

    return enhanced

def generate_enhanced_files_batch(limit=100):
    """Generate enhanced files for transcripts with complete insights"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Find transcripts with complete insights (all 3 tables)
        cursor.execute("""
            SELECT t.recording_id
            FROM transcripts t
            INNER JOIN insights i ON t.recording_id = i.recording_id
            INNER JOIN call_recommendations r ON t.recording_id = r.recording_id
            INNER JOIN call_resolutions cr ON t.recording_id = cr.recording_id
            WHERE t.transcript_text IS NOT NULL
            AND LENGTH(t.transcript_text) > 100
            ORDER BY t.call_date DESC
            LIMIT %s
        """, (limit,))

        recording_ids = [row['recording_id'] for row in cursor.fetchall()]
        logger.info(f"📊 Found {len(recording_ids)} transcripts with complete insights")

        if not recording_ids:
            logger.info("No transcripts ready for enhanced file generation")
            return

        # Initialize Google Drive uploader
        gdrive = None
        if GDRIVE_AVAILABLE:
            try:
                gdrive = GoogleDriveUploader()
            except Exception as e:
                logger.warning(f"Google Drive initialization failed: {e}")
                gdrive = None

        enhanced_dir = Path('/var/www/call-recording-system/data/transcriptions/enhanced')
        enhanced_dir.mkdir(parents=True, exist_ok=True)

        generated_count = 0
        uploaded_count = 0

        for recording_id in recording_ids:
            try:
                # Get complete data
                transcript_data = get_complete_transcript_data(recording_id)

                if not transcript_data:
                    continue

                # Create enhanced JSON
                enhanced_json = create_enhanced_json(transcript_data)

                # Save enhanced file
                enhanced_file = enhanced_dir / f"{recording_id}.enhanced.json"
                with open(enhanced_file, 'w') as f:
                    json.dump(enhanced_json, f, indent=2, default=str)

                generated_count += 1

                # Upload to Google Drive
                if gdrive:
                    try:
                        gdrive.upload_insights_file(str(enhanced_file), recording_id)
                        uploaded_count += 1
                    except Exception as e:
                        logger.warning(f"Upload failed for {recording_id}: {e}")

                if generated_count % 10 == 0:
                    logger.info(f"  ✅ Generated {generated_count} enhanced files...")

            except Exception as e:
                logger.error(f"Error processing {recording_id}: {e}")

        logger.info(f"\n✅ Enhanced file generation complete!")
        logger.info(f"  📊 Generated: {generated_count} files")
        logger.info(f"  ☁️ Uploaded to Google Drive: {uploaded_count} files")

    finally:
        cursor.close()
        conn.close()

def main():
    """Main function"""

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 100

    logger.info(f"🚀 Starting enhanced file generation for {limit} transcripts...")
    generate_enhanced_files_batch(limit=limit)

if __name__ == "__main__":
    main()