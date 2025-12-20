#!/usr/bin/env python3
"""
Layer 5: Advanced Call Metrics
Extracts additional insights for sales, quality monitoring, and RAG optimization.

Metrics:
1. Buying signals - Identify sales opportunities
2. Competitor mentions - Competitive intelligence
3. Hold time / dead air - Quality monitoring (from audio analysis)
4. Talk-to-listen ratio - Agent effectiveness
5. Compliance score - Risk management
6. Key quotes extraction - Better RAG retrieval
7. Question-answer pairs - Training data
8. Urgency classification - Prioritization
"""

import os
import sys
import json
import logging
import time
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

load_dotenv('/var/www/call-recording-system/.env')
sys.path.insert(0, '/var/www/call-recording-system')

import psycopg2
from psycopg2.extras import Json
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'/var/www/call-recording-system/logs/layer5_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)
logger = logging.getLogger(__name__)

DB_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': 'REDACTED_DB_PASSWORD',
    'host': 'localhost',
    'port': 5432
}

OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# MODEL CONFIGURATION - Updated 2025-12-20
# Primary: FREE model with best quality
# Secondary: Low-cost backup
PRIMARY_MODEL = "google/gemma-3-12b-it:free"
SECONDARY_MODEL = "meta-llama/llama-3.1-8b-instruct"

# Known competitors for competitive intelligence
COMPETITORS = [
    "Bullhorn", "JobDiva", "Crelate", "Avionte", "CEIPAL", "Vincere",
    "Zoho Recruit", "Greenhouse", "Lever", "Workday", "iCIMS", "Jobvite",
    "SmartRecruiters", "Breezy", "JazzHR", "BambooHR", "Namely", "Paylocity"
]


class Layer5Processor:
    """Process Layer 5 advanced metrics"""

    def __init__(self):
        self.model = "google/gemma-3-12b-it:free"  # FREE - Best quality, reliable JSON
        self.headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://call-insights.local",
            "X-Title": "Call Insights Layer 5"
        }

    def _call_llm(self, prompt: str, max_tokens: int = 2000) -> Optional[str]:
        """Call OpenRouter LLM"""
        try:
            response = requests.post(
                OPENROUTER_URL,
                headers=self.headers,
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.3
                },
                timeout=60
            )
            response.raise_for_status()
            return response.json()['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return None

    def extract_buying_signals(self, transcript: str) -> Dict:
        """Extract buying signals from transcript"""
        prompt = f"""Analyze this call transcript for BUYING SIGNALS.

TRANSCRIPT:
{transcript[:8000]}

Identify:
1. Explicit interest statements ("I want to buy", "We're looking for", "Send me a quote")
2. Timeline mentions ("Need this by", "Looking to implement in Q1")
3. Budget discussions ("Our budget is", "How much does it cost")
4. Decision maker indicators ("I'll need to check with my boss", "I have authority to sign")
5. Pain points they want solved
6. Comparison shopping signals ("We're also looking at", "How do you compare to")

Return JSON:
{{
    "buying_signals_detected": true/false,
    "signal_strength": "strong/medium/weak/none",
    "explicit_interest": ["list of interest statements"],
    "timeline_mentioned": "description or null",
    "budget_discussed": true/false,
    "budget_range": "range if mentioned or null",
    "decision_maker_present": true/false,
    "decision_maker_title": "title if mentioned or null",
    "pain_points": ["list of pain points"],
    "comparison_shopping": true/false,
    "competitors_mentioned": ["list"],
    "next_steps_requested": true/false,
    "demo_requested": true/false,
    "quote_requested": true/false,
    "sales_opportunity_score": 1-10
}}

Return ONLY valid JSON."""

        result = self._call_llm(prompt)
        try:
            return json.loads(result) if result else {}
        except:
            return {"buying_signals_detected": False, "sales_opportunity_score": 0}

    def extract_competitor_mentions(self, transcript: str) -> Dict:
        """Extract competitor mentions and context"""
        # First, do keyword search
        mentioned = []
        transcript_lower = transcript.lower()
        for comp in COMPETITORS:
            if comp.lower() in transcript_lower:
                mentioned.append(comp)

        prompt = f"""Analyze this call transcript for COMPETITOR MENTIONS and competitive intelligence.

TRANSCRIPT:
{transcript[:8000]}

Known competitors to look for: {', '.join(COMPETITORS)}

Identify:
1. Direct competitor mentions by name
2. Indirect references ("your competitor", "another system we use")
3. Feature comparisons
4. Pricing comparisons
5. Switching intent or barriers
6. Reasons for considering alternatives

Return JSON:
{{
    "competitors_mentioned": ["list of competitor names"],
    "competitor_context": [
        {{"name": "CompetitorX", "context": "how they were mentioned", "sentiment": "positive/negative/neutral"}}
    ],
    "feature_comparisons": ["list of features compared"],
    "pricing_mentioned": true/false,
    "switching_from": "competitor name or null",
    "switching_to": "competitor name or null",
    "switching_barriers": ["list of barriers mentioned"],
    "competitive_advantage_opportunities": ["what we do better"],
    "competitive_disadvantages_mentioned": ["what competitor does better"],
    "win_probability_impact": "positive/negative/neutral"
}}

Return ONLY valid JSON."""

        result = self._call_llm(prompt)
        try:
            data = json.loads(result) if result else {}
            # Add keyword-detected competitors
            if mentioned and 'competitors_mentioned' in data:
                data['competitors_mentioned'] = list(set(data['competitors_mentioned'] + mentioned))
            return data
        except:
            return {"competitors_mentioned": mentioned}

    def analyze_talk_listen_ratio(self, transcript: str, segments: List = None) -> Dict:
        """Analyze talk-to-listen ratio from transcript or segments"""
        # If we have diarization segments, calculate precisely
        if segments:
            speaker_words = {}
            for seg in segments:
                speaker = seg.get('speaker', 'unknown')
                words = len(seg.get('text', '').split())
                speaker_words[speaker] = speaker_words.get(speaker, 0) + words

            total_words = sum(speaker_words.values())
            ratios = {s: round(w/total_words*100, 1) for s, w in speaker_words.items()}
            
            # Identify agent vs customer (agent usually talks less in good calls)
            return {
                "speaker_word_counts": speaker_words,
                "speaker_percentages": ratios,
                "total_words": total_words,
                "dominant_speaker": max(speaker_words, key=speaker_words.get) if speaker_words else None,
                "balance_score": 10 - abs(50 - min(ratios.values())) / 5 if ratios else 5
            }

        # Estimate from transcript patterns
        prompt = f"""Analyze this call transcript for TALK-TO-LISTEN RATIO.

TRANSCRIPT:
{transcript[:6000]}

Estimate:
1. Who talked more - agent or customer?
2. Approximate percentage split
3. Was the agent a good listener?
4. Did agent interrupt customer?

Return JSON:
{{
    "agent_talk_percentage": 40,
    "customer_talk_percentage": 60,
    "agent_listening_quality": "excellent/good/fair/poor",
    "interruptions_detected": true/false,
    "interruption_count_estimate": 0,
    "monologue_detected": true/false,
    "balance_score": 1-10,
    "recommendation": "brief recommendation"
}}

Return ONLY valid JSON."""

        result = self._call_llm(prompt)
        try:
            return json.loads(result) if result else {}
        except:
            return {"balance_score": 5}

    def calculate_compliance_score(self, transcript: str) -> Dict:
        """Calculate compliance score for risk management"""
        prompt = f"""Analyze this call transcript for COMPLIANCE and RISK factors.

TRANSCRIPT:
{transcript[:8000]}

Check for:
1. Proper greeting and identification
2. Privacy/GDPR compliance (asking permission to record, data handling)
3. Accurate information provided (no false promises)
4. Proper disclosure of terms/conditions
5. No discriminatory language
6. Professional conduct
7. Proper call closure
8. Required disclosures made

Return JSON:
{{
    "compliance_score": 1-100,
    "risk_level": "low/medium/high/critical",
    "proper_greeting": true/false,
    "identified_self": true/false,
    "identified_company": true/false,
    "recording_disclosure": true/false,
    "privacy_compliant": true/false,
    "accurate_information": true/false,
    "no_false_promises": true/false,
    "professional_language": true/false,
    "no_discrimination": true/false,
    "proper_closure": true/false,
    "compliance_issues": ["list of specific issues"],
    "compliance_recommendations": ["list of recommendations"],
    "legal_risk_phrases": ["any risky statements made"]
}}

Return ONLY valid JSON."""

        result = self._call_llm(prompt)
        try:
            return json.loads(result) if result else {}
        except:
            return {"compliance_score": 50, "risk_level": "medium"}

    def extract_key_quotes(self, transcript: str) -> Dict:
        """Extract key quotes for better RAG retrieval"""
        prompt = f"""Extract KEY QUOTES from this call transcript for knowledge base indexing.

TRANSCRIPT:
{transcript[:8000]}

Extract:
1. Customer pain points (verbatim quotes)
2. Product feedback (positive and negative)
3. Feature requests
4. Objections raised
5. Success stories / testimonials
6. Memorable statements
7. Questions that need documentation

Return JSON:
{{
    "pain_point_quotes": [
        {{"quote": "exact quote", "context": "brief context", "speaker": "customer/agent"}}
    ],
    "positive_feedback": [
        {{"quote": "exact quote", "feature": "related feature"}}
    ],
    "negative_feedback": [
        {{"quote": "exact quote", "issue": "related issue"}}
    ],
    "feature_requests": [
        {{"quote": "exact quote", "feature_requested": "description"}}
    ],
    "objections": [
        {{"quote": "exact quote", "objection_type": "price/timing/competition/other"}}
    ],
    "testimonial_quotes": ["list of positive testimonials"],
    "key_questions_asked": ["important questions from customer"],
    "quotable_moments": ["other memorable quotes"],
    "rag_keywords": ["key terms for search indexing"]
}}

Return ONLY valid JSON."""

        result = self._call_llm(prompt)
        try:
            return json.loads(result) if result else {}
        except:
            return {"key_quotes": [], "rag_keywords": []}

    def extract_qa_pairs(self, transcript: str) -> Dict:
        """Extract question-answer pairs for training data"""
        prompt = f"""Extract QUESTION-ANSWER PAIRS from this call transcript for training data.

TRANSCRIPT:
{transcript[:8000]}

Find all questions asked and their answers. Focus on:
1. Product/feature questions
2. Pricing questions
3. Technical questions
4. Process questions
5. Policy questions

Return JSON:
{{
    "qa_pairs": [
        {{
            "question": "exact question asked",
            "answer": "answer provided",
            "category": "product/pricing/technical/process/policy/other",
            "answer_quality": "complete/partial/incorrect/unanswered",
            "could_be_faq": true/false
        }}
    ],
    "unanswered_questions": ["questions that weren't answered"],
    "questions_needing_followup": ["questions that need more info"],
    "potential_kb_articles": ["topics that should be documented"],
    "training_value_score": 1-10
}}

Return ONLY valid JSON."""

        result = self._call_llm(prompt)
        try:
            return json.loads(result) if result else {}
        except:
            return {"qa_pairs": [], "training_value_score": 0}

    def classify_urgency(self, transcript: str) -> Dict:
        """Classify call urgency for prioritization"""
        prompt = f"""Classify the URGENCY of this call for prioritization.

TRANSCRIPT:
{transcript[:6000]}

Analyze:
1. Time-sensitive language ("urgent", "ASAP", "deadline")
2. Business impact mentioned
3. Escalation requests
4. Emotional intensity
5. Repeat caller indicators
6. SLA implications

Return JSON:
{{
    "urgency_level": "critical/high/medium/low",
    "urgency_score": 1-10,
    "time_sensitive": true/false,
    "deadline_mentioned": "date/time or null",
    "business_impact": "high/medium/low/unknown",
    "impact_description": "brief description",
    "escalation_requested": true/false,
    "repeat_issue": true/false,
    "emotional_urgency": "high/medium/low",
    "sla_risk": true/false,
    "priority_keywords": ["urgent words used"],
    "recommended_response_time": "immediate/same-day/24h/48h/standard",
    "requires_immediate_action": true/false,
    "action_items": ["immediate actions needed"]
}}

Return ONLY valid JSON."""

        result = self._call_llm(prompt)
        try:
            return json.loads(result) if result else {}
        except:
            return {"urgency_level": "medium", "urgency_score": 5}

    def process_transcript(self, recording_id: str, transcript: str, segments: List = None) -> Dict:
        """Process all Layer 5 metrics for a transcript"""
        logger.info(f"Processing Layer 5 metrics for {recording_id}")

        results = {
            "recording_id": recording_id,
            "processed_at": datetime.now().isoformat(),
            "layer": 5
        }

        # Process each metric
        logger.info(f"  Extracting buying signals...")
        results["buying_signals"] = self.extract_buying_signals(transcript)
        time.sleep(1)

        logger.info(f"  Analyzing competitor mentions...")
        results["competitor_intelligence"] = self.extract_competitor_mentions(transcript)
        time.sleep(1)

        logger.info(f"  Calculating talk-listen ratio...")
        results["talk_listen_ratio"] = self.analyze_talk_listen_ratio(transcript, segments)
        time.sleep(1)

        logger.info(f"  Evaluating compliance...")
        results["compliance"] = self.calculate_compliance_score(transcript)
        time.sleep(1)

        logger.info(f"  Extracting key quotes...")
        results["key_quotes"] = self.extract_key_quotes(transcript)
        time.sleep(1)

        logger.info(f"  Extracting Q&A pairs...")
        results["qa_pairs"] = self.extract_qa_pairs(transcript)
        time.sleep(1)

        logger.info(f"  Classifying urgency...")
        results["urgency"] = self.classify_urgency(transcript)

        return results

    def save_to_database(self, results: Dict) -> bool:
        """Save Layer 5 results to database"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()

            # Check if table exists, create if not
            cur.execute("""
                CREATE TABLE IF NOT EXISTS call_advanced_metrics (
                    recording_id TEXT PRIMARY KEY,
                    buying_signals JSONB,
                    competitor_intelligence JSONB,
                    talk_listen_ratio JSONB,
                    compliance JSONB,
                    key_quotes JSONB,
                    qa_pairs JSONB,
                    urgency JSONB,
                    sales_opportunity_score INTEGER,
                    compliance_score INTEGER,
                    urgency_score INTEGER,
                    processed_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # Upsert results
            cur.execute("""
                INSERT INTO call_advanced_metrics 
                (recording_id, buying_signals, competitor_intelligence, talk_listen_ratio,
                 compliance, key_quotes, qa_pairs, urgency, 
                 sales_opportunity_score, compliance_score, urgency_score, processed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (recording_id) DO UPDATE SET
                    buying_signals = EXCLUDED.buying_signals,
                    competitor_intelligence = EXCLUDED.competitor_intelligence,
                    talk_listen_ratio = EXCLUDED.talk_listen_ratio,
                    compliance = EXCLUDED.compliance,
                    key_quotes = EXCLUDED.key_quotes,
                    qa_pairs = EXCLUDED.qa_pairs,
                    urgency = EXCLUDED.urgency,
                    sales_opportunity_score = EXCLUDED.sales_opportunity_score,
                    compliance_score = EXCLUDED.compliance_score,
                    urgency_score = EXCLUDED.urgency_score,
                    processed_at = NOW()
            """, (
                results["recording_id"],
                Json(results.get("buying_signals", {})),
                Json(results.get("competitor_intelligence", {})),
                Json(results.get("talk_listen_ratio", {})),
                Json(results.get("compliance", {})),
                Json(results.get("key_quotes", {})),
                Json(results.get("qa_pairs", {})),
                Json(results.get("urgency", {})),
                results.get("buying_signals", {}).get("sales_opportunity_score", 0),
                results.get("compliance", {}).get("compliance_score", 0),
                results.get("urgency", {}).get("urgency_score", 0)
            ))

            conn.commit()
            cur.close()
            conn.close()
            return True

        except Exception as e:
            logger.error(f"Database error: {e}")
            return False


def process_batch(limit: int = 50):
    """Process batch of transcripts through Layer 5"""
    processor = Layer5Processor()

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        # Get transcripts that need Layer 5 processing
        cur.execute("""
            SELECT t.recording_id, t.transcript_text, t.transcript_segments
            FROM transcripts t
            LEFT JOIN call_advanced_metrics m ON t.recording_id = m.recording_id
            WHERE t.transcript_text IS NOT NULL 
            AND t.transcript_text != ''
            AND m.recording_id IS NULL
            LIMIT %s
        """, (limit,))

        transcripts = cur.fetchall()
        cur.close()
        conn.close()

        logger.info(f"Found {len(transcripts)} transcripts for Layer 5 processing")

        processed = 0
        for recording_id, transcript, segments in transcripts:
            try:
                results = processor.process_transcript(recording_id, transcript, segments)
                if processor.save_to_database(results):
                    processed += 1
                    logger.info(f"  Saved Layer 5 for {recording_id}")
                time.sleep(2)  # Rate limit
            except Exception as e:
                logger.error(f"Error processing {recording_id}: {e}")

        logger.info(f"\nProcessed {processed}/{len(transcripts)} transcripts")

    except Exception as e:
        logger.error(f"Batch processing error: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Layer 5 Advanced Metrics')
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--recording-id', type=str, help='Process single recording')
    args = parser.parse_args()

    if args.recording_id:
        # Process single recording
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT transcript_text, transcript_segments FROM transcripts WHERE recording_id = %s", 
                    (args.recording_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()

        if result:
            processor = Layer5Processor()
            results = processor.process_transcript(args.recording_id, result[0], result[1])
            processor.save_to_database(results)
            print(json.dumps(results, indent=2, default=str))
        else:
            print(f"Recording {args.recording_id} not found")
    else:
        process_batch(limit=args.limit)


if __name__ == '__main__':
    main()
