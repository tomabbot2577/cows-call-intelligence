#!/usr/bin/env python3
"""
Batch 6-Layer AI Analysis for Video Meetings

Runs comprehensive metadata extraction on all transcribed RC Video recordings:
- Enhanced participant identification (all 7+ participants)
- Layer 1-6 analysis (entities, sentiment, outcomes, recommendations, metrics, learning)
- Best practices extraction
- Knowledge Base Q&A pairs
- Key quotes for reports

Usage:
    python scripts/video_processing/batch_layer_analysis.py [--limit N] [--meeting-id ID]
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from google import genai

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Known MainSequence employees for participant identification
MAINSEQUENCE_EMPLOYEES = {
    "Garrett Komyati": {"email": "gkomyati@mainsequence.net", "role": "Training Specialist"},
    "Mike Keys": {"email": "mkeys@mainsequence.net", "role": "Training Specialist"},
    "Jason Salamon": {"email": "jsalamon@mainsequence.net", "role": "Senior Trainer"},
    "Tyler Trautman": {"email": "ttrautman@mainsequence.net", "role": "Product Specialist"},
    "Nick Bradach": {"email": "nbradach@mainsequence.net", "role": "Support Lead"},
    "James Blair": {"email": "jblair@mainsequence.net", "role": "Account Manager"},
    "Bill Kubicek": {"email": "bkubicek@mainsequence.net", "role": "Director"},
    "Dylan Bello": {"email": "dbello@mainsequence.net", "role": "Developer"},
    "Robin Montoni": {"email": "rmontoni@mainsequence.net", "role": "Support"},
}


class BatchLayerAnalyzer:
    """Batch processor for 6-layer AI analysis of video meetings."""

    def __init__(self):
        """Initialize the analyzer with Gemini and database connections."""
        # Gemini client
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")
        self.gemini_client = genai.Client(api_key=api_key)

        # Database connection
        db_url = os.getenv('RAG_DATABASE_URL') or os.getenv('DATABASE_URL')
        if not db_url:
            db_url = "postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights"
        self.engine = create_engine(db_url)
        self.Session = sessionmaker(bind=self.engine)

        # Stats with thread lock
        self.stats = {
            'total': 0,
            'processed': 0,
            'failed': 0,
            'skipped': 0
        }
        self.stats_lock = threading.Lock()

        logger.info("BatchLayerAnalyzer initialized")

    def get_pending_meetings(self, limit: int = 50) -> List[Dict]:
        """Get meetings with transcripts that need layer analysis."""
        with self.Session() as session:
            result = session.execute(
                text("""
                    SELECT id, title, host_name, host_email,
                           SUBSTRING(transcript_text, 1, 25000) as transcript_text,
                           duration_seconds, meeting_type
                    FROM video_meetings
                    WHERE source IN ('ringcentral', 'fathom')
                      AND transcript_text IS NOT NULL
                      AND (layer1_complete IS NULL OR layer1_complete = FALSE)
                    ORDER BY start_time DESC NULLS LAST
                    LIMIT :limit
                """),
                {'limit': limit}
            )
            meetings = []
            for row in result.fetchall():
                meetings.append({
                    'id': row[0],
                    'title': row[1],
                    'host_name': row[2],
                    'host_email': row[3],
                    'transcript': row[4],
                    'duration': row[5],
                    'meeting_type': row[6]
                })
            return meetings

    def build_extraction_prompt(self, meeting: Dict) -> str:
        """Build the comprehensive extraction prompt for a meeting."""
        employees_list = "\n".join([
            f"- {name} ({info['email']}) - {info['role']}"
            for name, info in MAINSEQUENCE_EMPLOYEES.items()
        ])

        prompt = f"""Analyze this PCRecruiter training/meeting transcript and extract comprehensive metadata.

MEETING INFO:
- Title: {meeting['title']}
- Host: {meeting['host_name']} ({meeting['host_email']})
- Duration: {meeting['duration']} seconds

KNOWN MAINSEQUENCE EMPLOYEES (internal):
{employees_list}

TRANSCRIPT:
{meeting['transcript'][:18000]}

Extract ALL of the following in JSON format. Be thorough and identify all participants.

{{
  "participants": [
    {{
      "name": "Full name",
      "name_variations": ["nicknames"],
      "email": "email if known",
      "company": "Company name",
      "role": "Trainer/Primary Trainee/Secondary Trainee/Observer/Mentioned Only",
      "is_internal": true,
      "is_trainer": true,
      "is_trainee": false,
      "speaking_time_percentage": 70,
      "questions_asked": 0,
      "engagement_level": "high/medium/low",
      "evidence": "Quote from transcript"
    }}
  ],
  "participant_summary": {{
    "total_count": 7,
    "internal_count": 1,
    "external_count": 6,
    "trainers": 1,
    "trainees": 3,
    "active_speakers": 4
  }},
  "layer1_entities": {{
    "main_topics": [{{"topic": "Name", "duration_minutes": 15, "depth": "thorough"}}],
    "tools_demonstrated": ["Tool names"],
    "features_explained": ["Feature names"],
    "key_terms_defined": ["Terms"],
    "companies_mentioned": ["Companies"],
    "meeting_classification": {{
      "primary_type": "training/support/sales/internal",
      "training_category": "onboarding/feature_deep_dive/troubleshooting",
      "complexity_level": "beginner/intermediate/advanced"
    }}
  }},
  "layer2_sentiment": {{
    "overall_sentiment": "positive/neutral/negative",
    "sentiment_score": 8.5,
    "trainer_sentiment": {{"tone": "instructive", "patience_level": "high", "enthusiasm": "high"}},
    "trainee_sentiment": {{"engagement": "high", "confidence_level": "medium", "confusion_count": 0}},
    "engagement_metrics": {{"overall_engagement": 8.5, "nps_indicator": 9}},
    "risk_assessment": {{"churn_risk_level": "low", "satisfaction_signals": ["signals"]}}
  }},
  "layer3_outcomes": {{
    "objectives_met": true,
    "objectives_met_score": 8.5,
    "action_items": [{{"description": "Action", "assignee": "Name", "priority": "high", "follow_up_required": true}}],
    "resolution_metrics": {{"first_contact_resolution": true, "follow_up_needed": true, "loop_closure_score": 8.5}},
    "skills_demonstrated": ["Skills learned"]
  }},
  "layer4_recommendations": {{
    "trainer_coaching": {{
      "strengths": ["Strengths"],
      "improvements": ["Areas to improve"],
      "coaching_priorities": [{{"area": "Area", "suggestion": "How", "priority": "high"}}]
    }},
    "process_improvements": [{{"improvement": "What", "impact": "Benefit", "effort": "low/medium/high"}}],
    "knowledge_gaps_identified": ["Gaps"],
    "customer_success_actions": {{"retention_actions": ["Actions"], "expansion_opportunities": ["Opportunities"]}}
  }},
  "layer5_metrics": {{
    "speaking_time": {{"trainer_percentage": 70, "trainee_percentage": 30}},
    "interaction_metrics": {{"total_questions": 12, "questions_by_trainer": 8, "questions_by_trainee": 4}},
    "content_analysis": {{"key_phrases": ["Phrases"], "examples_given": 5}},
    "quality_scores": {{"demo_clarity": 8.5, "explanation_quality": 8.0, "meeting_effectiveness_percentile": 85}}
  }},
  "layer6_learning": {{
    "utl_metrics": {{"learning_score": 7.8, "entropy_delta": 0.72, "coherence_delta": 0.85, "emotional_coefficient": 0.78, "phase_alignment": 0.82}},
    "learning_state": {{"current_state": "building/aha_zone/struggling/overwhelmed/bored", "trajectory": "upward/stable/downward"}},
    "trainee_learning_profile": {{"knowledge_level": "beginner/intermediate/advanced", "learning_style": "visual/auditory/kinesthetic", "comprehension_rate": "fast/moderate/slow"}},
    "trainer_teaching_analysis": {{"teaching_clarity": 8.5, "pacing_score": 7.5, "scaffolding_quality": 8.0, "check_in_frequency": 8}},
    "new_hire_readiness": {{"status": "ready/needs_practice/not_ready", "ready_skills": ["Skills"], "skill_gaps": ["Gaps"], "estimated_sessions_to_proficiency": 2}},
    "coaching_recommendations": {{
      "lambda_adjustments": [{{"parameter": "depth", "adjustment": "increase", "reason": "Why"}}],
      "for_trainer": [{{"recommendation": "What", "priority": "high"}}],
      "for_trainee": [{{"recommendation": "What", "priority": "high"}}]
    }}
  }},
  "best_practices": {{
    "effective_techniques_used": [{{"technique": "Name", "effectiveness": "high", "evidence": "Quote"}}],
    "techniques_to_improve": [{{"area": "Area", "recommendation": "How"}}],
    "training_materials_needed": ["Materials"],
    "curriculum_gaps": [{{"topic": "Topic", "priority": "high"}}]
  }},
  "kb_qa_pairs": [
    {{
      "question": "Question asked in training",
      "answer": "Answer given",
      "category": "Category",
      "tags": ["tags"],
      "quality": "complete/partial"
    }}
  ],
  "key_quotes": [
    {{
      "speaker": "Name",
      "quote": "The quote",
      "type": "satisfaction/objection/insight/question",
      "sentiment": "positive/neutral/negative",
      "usable_for": ["testimonial", "training_material", "documentation"]
    }}
  ]
}}

IMPORTANT: Extract ALL participants (speakers AND mentioned), identify best practices, and capture Q&A pairs for knowledge base.
"""
        return prompt

    def analyze_meeting(self, meeting: Dict) -> Optional[Dict]:
        """Run 6-layer analysis on a single meeting."""
        logger.info(f"[{meeting['id']}] Analyzing: {meeting['title'][:50]}...")

        try:
            prompt = self.build_extraction_prompt(meeting)

            response = self.gemini_client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt
            )
            text = response.text

            # Clean JSON response
            if text.startswith('```'):
                text = text.split('```')[1]
                if text.startswith('json'):
                    text = text[4:]
            text = text.strip()

            result = json.loads(text)
            logger.info(f"[{meeting['id']}] Extraction complete - {len(result.get('participants', []))} participants")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"[{meeting['id']}] JSON parse error: {e}")
            return None
        except Exception as e:
            logger.error(f"[{meeting['id']}] Analysis failed: {e}")
            return None

    def save_analysis(self, meeting_id: int, analysis: Dict) -> bool:
        """Save analysis results to database."""
        try:
            with self.Session() as session:
                # Update video_meetings with layer flags and summary data
                summary = analysis.get('participant_summary', {})
                l2 = analysis.get('layer2_sentiment', {})
                l3 = analysis.get('layer3_outcomes', {})
                l6 = analysis.get('layer6_learning', {})

                session.execute(
                    text("""
                        UPDATE video_meetings
                        SET layer1_complete = TRUE,
                            layer2_complete = TRUE,
                            layer3_complete = TRUE,
                            layer4_complete = TRUE,
                            layer5_complete = TRUE,
                            layer6_complete = TRUE,
                            participant_count = :participant_count,
                            internal_participant_count = :internal_count,
                            external_participant_count = :external_count,
                            overall_sentiment = :sentiment,
                            sentiment_score = :sentiment_score,
                            meeting_quality_score = :quality_score,
                            churn_risk_level = :churn_risk,
                            learning_score = :learning_score,
                            learning_state = :learning_state,
                            ai_analysis_json = :analysis_json,
                            updated_at = NOW()
                        WHERE id = :meeting_id
                    """),
                    {
                        'meeting_id': meeting_id,
                        'participant_count': summary.get('total_count', 0),
                        'internal_count': summary.get('internal_count', 0),
                        'external_count': summary.get('external_count', 0),
                        'sentiment': l2.get('overall_sentiment', 'neutral'),
                        'sentiment_score': l2.get('sentiment_score'),
                        'quality_score': l2.get('engagement_metrics', {}).get('overall_engagement'),
                        'churn_risk': l2.get('risk_assessment', {}).get('churn_risk_level', 'low'),
                        'learning_score': l6.get('utl_metrics', {}).get('learning_score'),
                        'learning_state': l6.get('learning_state', {}).get('current_state'),
                        'analysis_json': json.dumps(analysis)
                    }
                )

                # Insert participants
                for p in analysis.get('participants', []):
                    session.execute(
                        text("""
                            INSERT INTO video_meeting_participants
                            (meeting_id, participant_name, participant_email, company_name,
                             role_type, is_internal, is_trainer, is_trainee,
                             speaking_time_percentage, questions_asked, engagement_level)
                            VALUES (:meeting_id, :name, :email, :company, :role, :internal, :trainer, :trainee,
                                    :speaking, :questions, :engagement)
                            ON CONFLICT (meeting_id, participant_name)
                            DO UPDATE SET
                                speaking_time_percentage = EXCLUDED.speaking_time_percentage,
                                engagement_level = EXCLUDED.engagement_level,
                                updated_at = NOW()
                        """),
                        {
                            'meeting_id': meeting_id,
                            'name': p.get('name'),
                            'email': p.get('email'),
                            'company': p.get('company'),
                            'role': p.get('role'),
                            'internal': p.get('is_internal', False),
                            'trainer': p.get('is_trainer', False),
                            'trainee': p.get('is_trainee', False),
                            'speaking': p.get('speaking_time_percentage'),
                            'questions': p.get('questions_asked'),
                            'engagement': p.get('engagement_level')
                        }
                    )

                # Insert Q&A pairs for KB
                for qa in analysis.get('kb_qa_pairs', []):
                    session.execute(
                        text("""
                            INSERT INTO video_meeting_qa_pairs
                            (video_meeting_id, question, answer, category, tags, quality, created_at)
                            VALUES (:meeting_id, :question, :answer, :category, :tags, :quality, NOW())
                        """),
                        {
                            'meeting_id': meeting_id,
                            'question': qa.get('question'),
                            'answer': qa.get('answer'),
                            'category': qa.get('category'),
                            'tags': json.dumps(qa.get('tags', [])),
                            'quality': qa.get('quality', 'complete')
                        }
                    )

                session.commit()
                logger.info(f"[{meeting_id}] Saved to database")
                return True

        except Exception as e:
            logger.error(f"[{meeting_id}] Database save failed: {e}")
            return False

    def process_single(self, meeting: Dict) -> bool:
        """Process a single meeting (for parallel execution)."""
        try:
            analysis = self.analyze_meeting(meeting)

            if analysis:
                if self.save_analysis(meeting['id'], analysis):
                    with self.stats_lock:
                        self.stats['processed'] += 1
                    return True
                else:
                    with self.stats_lock:
                        self.stats['failed'] += 1
                    return False
            else:
                with self.stats_lock:
                    self.stats['failed'] += 1
                return False

        except Exception as e:
            logger.error(f"[{meeting['id']}] Error: {e}")
            with self.stats_lock:
                self.stats['failed'] += 1
            return False

    def process_batch(self, limit: int = 50, workers: int = 8) -> Dict:
        """Process a batch of meetings in parallel."""
        meetings = self.get_pending_meetings(limit)
        self.stats['total'] = len(meetings)

        if not meetings:
            logger.info("No pending meetings for analysis")
            return self.stats

        logger.info(f"Processing {len(meetings)} meetings with {workers} parallel workers")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self.process_single, m): m for m in meetings}

            for future in as_completed(futures):
                meeting = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"[{meeting['id']}] Worker exception: {e}")

        return self.stats


def main():
    parser = argparse.ArgumentParser(description='Run 6-layer AI analysis on video meetings')
    parser.add_argument('--limit', type=int, default=50,
                        help='Maximum meetings to process (default: 50)')
    parser.add_argument('--workers', type=int, default=8,
                        help='Number of parallel workers (default: 8)')
    parser.add_argument('--meeting-id', type=int,
                        help='Process a specific meeting ID')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be processed')

    args = parser.parse_args()

    print("=" * 60)
    print("6-Layer Video Meeting Analysis")
    print(f"Limit: {args.limit} | Workers: {args.workers}")
    print("=" * 60)

    analyzer = BatchLayerAnalyzer()

    if args.dry_run:
        meetings = analyzer.get_pending_meetings(args.limit)
        print(f"\nWould process {len(meetings)} meetings:")
        for m in meetings[:10]:
            print(f"  [{m['id']}] {m['title'][:50]}...")
        if len(meetings) > 10:
            print(f"  ... and {len(meetings) - 10} more")
        return

    if args.meeting_id:
        # Process single meeting
        with analyzer.Session() as session:
            result = session.execute(
                text("""
                    SELECT id, title, host_name, host_email,
                           SUBSTRING(transcript_text, 1, 25000) as transcript_text,
                           duration_seconds, meeting_type
                    FROM video_meetings WHERE id = :id
                """),
                {'id': args.meeting_id}
            ).fetchone()

            if result:
                meeting = {
                    'id': result[0], 'title': result[1],
                    'host_name': result[2], 'host_email': result[3],
                    'transcript': result[4], 'duration': result[5],
                    'meeting_type': result[6]
                }
                analysis = analyzer.analyze_meeting(meeting)
                if analysis:
                    analyzer.save_analysis(args.meeting_id, analysis)
                    print(f"\nAnalysis complete for meeting {args.meeting_id}")
                    print(f"Participants: {len(analysis.get('participants', []))}")
                    print(f"Q&A pairs: {len(analysis.get('kb_qa_pairs', []))}")
            else:
                print(f"Meeting {args.meeting_id} not found")
        return

    # Process batch
    import time
    start_time = time.time()
    stats = analyzer.process_batch(limit=args.limit, workers=args.workers)
    elapsed = time.time() - start_time

    print("\n" + "=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)
    print(f"Total: {stats['total']}")
    print(f"Processed: {stats['processed']}")
    print(f"Failed: {stats['failed']}")
    print(f"Time: {elapsed:.1f} seconds")
    print("=" * 60)


if __name__ == '__main__':
    main()
