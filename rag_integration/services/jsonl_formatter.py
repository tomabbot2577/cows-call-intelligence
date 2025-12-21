"""JSONL Formatter - Converts database records to RAG-ready format for Vertex AI."""

import json
from datetime import datetime, date
from typing import Dict, Any, Optional, List
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class JSONLFormatter:
    """
    Formats call data into JSONL for Vertex AI RAG systems.

    Structure:
    - content.text: Formatted with clear [LAYER X] headers for semantic search chunking
    - struct_data: Flattened for Vertex AI Search filtering with booleans, numerics, arrays
    """

    def format_call(self, call_data: Dict[str, Any]) -> Dict[str, Any]:
        """Format a single call record for RAG ingestion."""
        call_id = call_data.get("recording_id", "unknown")
        content_text = self._build_content_text(call_data)
        struct_data = self._build_struct_data(call_data)

        return {
            "id": f"call_{call_id}",
            "content": {"mime_type": "text/plain", "text": content_text},
            "struct_data": struct_data
        }

    def _build_content_text(self, data: Dict[str, Any]) -> str:
        """
        Build formatted text with clear [LAYER X] headers for semantic search.
        Headers allow semantic search to find relevant chunks even if metadata gets split.
        """
        call_date = data.get("call_date", "Unknown")
        if isinstance(call_date, (datetime, date)):
            call_date = call_date.strftime("%Y-%m-%d")

        call_time = data.get("call_time", "")
        if call_time:
            call_time = str(call_time)[:8]

        duration = data.get("duration_seconds", 0) or 0
        duration_min, duration_sec = divmod(int(duration), 60)

        # Build key topics array
        key_topics = self._parse_array(data.get("key_topics"))
        topics_str = ", ".join(key_topics) if key_topics else "N/A"

        # Build arrays from Layer 3/4 data
        frustration_points = self._format_array_display(data.get("frustration_points"))
        delight_moments = self._format_array_display(data.get("delight_moments"))
        process_gaps = self._format_array_display(data.get("process_gaps"))
        strengths = self._format_array_display(data.get("employee_strengths"))
        improvements = self._format_array_display(data.get("employee_improvements"))
        followup_actions = self._format_array_display(data.get("followup_actions"))

        return f"""[LAYER 1 - CALL METADATA & PARTICIPANTS]
Call ID: {data.get('recording_id', 'Unknown')}
Date: {call_date} {call_time}
Duration: {duration_min}:{duration_sec:02d}
Direction: {data.get('direction', 'Unknown')}
Employee: {data.get('employee_name', 'Unknown')}
Department: {data.get('employee_department', 'N/A')}
Customer: {data.get('customer_name', 'Unknown')}
Company: {data.get('customer_company', 'N/A')}
Phone: {data.get('customer_phone') or data.get('from_number', 'N/A')}

[LAYER 2 - SENTIMENT & QUALITY ANALYSIS]
Customer Sentiment: {data.get('customer_sentiment', 'N/A')}
Sentiment Reasoning: {data.get('sentiment_reasoning', 'N/A')}
Call Quality Score: {data.get('call_quality_score', 'N/A')}/10
Quality Reasoning: {data.get('quality_reasoning', 'N/A')}
Overall Rating: {data.get('overall_call_rating', 'N/A')}/10
Call Type: {data.get('call_type', 'N/A')}
Issue Category: {data.get('issue_category', 'N/A')}
Key Topics: {topics_str}
Summary: {data.get('summary', 'N/A')}

[LAYER 3 - RESOLUTION & PERFORMANCE METRICS]
Problem Complexity: {data.get('problem_complexity', 'N/A')}
Resolution Effectiveness: {data.get('resolution_effectiveness', 'N/A')}/10
First Call Resolution: {self._bool_to_yesno(data.get('first_call_resolution'))}
Empathy Score: {data.get('empathy_score', 'N/A')}/10
Communication Clarity: {data.get('communication_clarity', 'N/A')}/10
Active Listening Score: {data.get('active_listening_score', 'N/A')}/10
Employee Knowledge Level: {data.get('employee_knowledge_level', 'N/A')}/10
Customer Effort Score: {data.get('customer_effort_score', 'N/A')}/10 (lower is better)
Churn Risk: {data.get('churn_risk_score') or data.get('resolution_churn_risk', 'N/A')}
Revenue Impact: {data.get('revenue_impact', 'N/A')}
Frustration Points: {frustration_points}
Delight Moments: {delight_moments}

[LAYER 3 - LOOP CLOSURE QUALITY]
Solution Summarized: {self._bool_to_yesno(data.get('solution_summarized'))}
Understanding Confirmed: {self._bool_to_yesno(data.get('understanding_confirmed'))}
Asked If Anything Else: {self._bool_to_yesno(data.get('asked_if_anything_else'))}
Next Steps Provided: {self._bool_to_yesno(data.get('next_steps_provided'))}
Timeline Given: {self._bool_to_yesno(data.get('timeline_given'))}
Contact Info Provided: {self._bool_to_yesno(data.get('contact_info_provided'))}
Thanked Customer: {self._bool_to_yesno(data.get('thanked_customer'))}
Confirmed Satisfaction: {self._bool_to_yesno(data.get('confirmed_satisfaction'))}

[LAYER 4 - RECOMMENDATIONS & COACHING]
Employee Strengths: {strengths}
Areas for Improvement: {improvements}
Suggested Phrases: {self._format_array_display(data.get('suggested_phrases'))}
Follow-up Actions: {followup_actions}
Process Gaps: {process_gaps}
Automation Opportunities: {self._format_array_display(data.get('automation_opportunities'))}
Knowledge Base Gaps: {self._format_array_display(data.get('knowledge_base_gaps'))}
Escalation Required: {self._bool_to_yesno(data.get('escalation_required') or data.get('rec_escalation_needed'))}
Risk Level: {data.get('risk_level', 'N/A')}
Training Priority: {data.get('training_priority', 'N/A')}
Coaching Notes: {data.get('coaching_notes', 'N/A')}

[LAYER 5 - ADVANCED METRICS & INTELLIGENCE]
Buying Signals Detected: {self._bool_to_yesno(self._extract_buying_signals(data.get('buying_signals')))}
Sales Opportunity Score: {data.get('sales_opportunity_score', 'N/A')}/10
Competitors Mentioned: {self._format_competitors_display(data.get('competitor_intelligence'))}
Talk/Listen Ratio Balance: {self._format_jsonb(data.get('talk_listen_ratio'), 'balance_score')}/10
Compliance Score: {data.get('compliance_score', 'N/A')}/100
Urgency Level: {self._format_jsonb(data.get('urgency'), 'level')} (Score: {data.get('urgency_score', 'N/A')}/10)
Key Quotes: {self._format_key_quotes(data.get('key_quotes'))}
Q&A Pairs Extracted: {self._count_qa_pairs(data.get('qa_pairs'))}
{self._format_qa_pairs(data.get('qa_pairs'))}

[TRANSCRIPT]
{data.get('transcript_text', 'No transcript available')}
"""

    def _build_struct_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build flattened structured data for Vertex AI Search filtering.

        - Boolean fields for quick filtering (competitor_mentioned: true)
        - Numeric scores for range queries (churn_risk_score >= 7)
        - Arrays for multi-value fields (topics, competitor_names)
        """
        call_date = data.get("call_date")
        if isinstance(call_date, (datetime, date)):
            call_date_str = call_date.strftime("%Y-%m-%d")
        else:
            call_date_str = str(call_date) if call_date else None

        # Parse arrays
        key_topics = self._parse_array(data.get("key_topics"))
        competitor_names = self._extract_competitors(data.get("competitor_intelligence"))

        return {
            # === IDENTIFIERS ===
            "call_id": str(data.get("recording_id")),
            "call_date": call_date_str,

            # === PARTICIPANTS (strings) ===
            "employee_name": data.get("employee_name"),
            "employee_department": data.get("employee_department"),
            "customer_name": data.get("customer_name"),
            "customer_company": data.get("customer_company"),
            "customer_phone": data.get("customer_phone") or data.get("from_number"),

            # === CALL METADATA (numerics) ===
            "duration_seconds": self._safe_int(data.get("duration_seconds")),
            "duration_minutes": self._safe_int(data.get("duration_seconds")) // 60 if data.get("duration_seconds") else None,
            "word_count": self._safe_int(data.get("word_count")),
            "direction": data.get("direction"),

            # === LAYER 2: SENTIMENT & QUALITY (mixed) ===
            "customer_sentiment": data.get("customer_sentiment"),  # string: positive/negative/neutral
            "call_quality_score": self._safe_float(data.get("call_quality_score")),  # 0-10
            "customer_satisfaction_score": self._safe_float(data.get("customer_satisfaction_score")),  # 0-10
            "overall_call_rating": self._safe_float(data.get("overall_call_rating")),  # 0-10
            "call_type": data.get("call_type"),  # string
            "issue_category": data.get("issue_category"),  # string
            "topics": key_topics,  # array of strings

            # === LAYER 3: RESOLUTION METRICS (numerics) ===
            "problem_complexity": data.get("problem_complexity"),  # string: simple/medium/complex
            "resolution_effectiveness": self._safe_float(data.get("resolution_effectiveness")),  # 0-10
            "empathy_score": self._safe_float(data.get("empathy_score")),  # 0-10
            "communication_clarity": self._safe_float(data.get("communication_clarity")),  # 0-10
            "active_listening_score": self._safe_float(data.get("active_listening_score")),  # 0-10
            "employee_knowledge_level": self._safe_float(data.get("employee_knowledge_level")),  # 0-10
            "customer_effort_score": self._safe_float(data.get("customer_effort_score")),  # 1-10 (lower better)
            "churn_risk_score": self._safe_float(data.get("churn_risk_score")),  # 0-10

            # === LAYER 3: BOOLEAN FLAGS (for quick filtering) ===
            "first_call_resolution": self._safe_bool(data.get("first_call_resolution")),
            "follow_up_needed": self._safe_bool(data.get("follow_up_needed")),
            "escalation_required": self._safe_bool(data.get("escalation_required") or data.get("rec_escalation_needed")),
            "solution_summarized": self._safe_bool(data.get("solution_summarized")),
            "understanding_confirmed": self._safe_bool(data.get("understanding_confirmed")),
            "next_steps_provided": self._safe_bool(data.get("next_steps_provided")),

            # === LAYER 4: RISK & PRIORITY ===
            "risk_level": data.get("risk_level"),  # string: low/medium/high
            "training_priority": data.get("training_priority"),  # string

            # === LAYER 5: ADVANCED METRICS ===
            "has_layer5": data.get("has_layer5") is not None,
            "sales_opportunity_score": self._safe_int(data.get("sales_opportunity_score")),  # 0-10
            "compliance_score": self._safe_int(data.get("compliance_score")),  # 0-100
            "urgency_score": self._safe_int(data.get("urgency_score")),  # 0-10

            # === LAYER 5: BOOLEAN FLAGS (for quick filtering) ===
            "buying_signals_detected": self._extract_buying_signals(data.get("buying_signals")),  # boolean
            "competitor_mentioned": len(competitor_names) > 0,  # boolean for quick filter
            "has_qa_pairs": self._count_qa_pairs(data.get("qa_pairs")) > 0,  # boolean

            # === LAYER 5: ARRAYS (for multi-value queries) ===
            "competitor_names": competitor_names,  # array of strings
            "qa_pairs_count": self._count_qa_pairs(data.get("qa_pairs")),  # int

            # === COMPUTED FLAGS (for common queries) ===
            "is_high_risk": self._is_high_risk(data),  # churn_risk >= 7 or escalation_required
            "is_low_quality": self._safe_float(data.get("call_quality_score")) is not None and self._safe_float(data.get("call_quality_score")) < 5,
            "is_negative_sentiment": data.get("customer_sentiment") == "negative",
            "has_sales_opportunity": self._safe_int(data.get("sales_opportunity_score")) is not None and self._safe_int(data.get("sales_opportunity_score")) >= 7,
        }

    # === HELPER METHODS ===

    def _parse_array(self, value: Any) -> List[str]:
        """Parse value into a list of strings."""
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value if v]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed if v]
            except:
                # Maybe comma-separated string
                if ',' in value:
                    return [v.strip() for v in value.split(',') if v.strip()]
                return [value] if value else []
        return []

    def _format_array_display(self, value: Any) -> str:
        """Format array for display in content text."""
        arr = self._parse_array(value)
        return ", ".join(arr) if arr else "N/A"

    def _bool_to_yesno(self, value: Any) -> str:
        """Convert boolean to Yes/No string for display."""
        if value is None:
            return "N/A"
        return "Yes" if value else "No"

    def _safe_bool(self, value: Any) -> Optional[bool]:
        """Safely convert to boolean."""
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', 'yes', '1')
        return bool(value)

    def _safe_int(self, value: Any) -> Optional[int]:
        """Safely convert to int."""
        if value is None:
            return None
        try:
            return int(value)
        except:
            return None

    def _safe_float(self, value: Any) -> Optional[float]:
        """Safely convert to float."""
        if value is None:
            return None
        try:
            return round(float(value), 2)
        except:
            return None

    def _format_jsonb(self, value: Any, key: str) -> str:
        """Extract a value from JSONB field for display."""
        if value is None:
            return "N/A"
        data = value if isinstance(value, dict) else {}
        if isinstance(value, str):
            try:
                data = json.loads(value)
            except:
                return "N/A"
        return str(data.get(key, "N/A")) if isinstance(data, dict) else "N/A"

    def _format_competitors_display(self, value: Any) -> str:
        """Format competitor names for display."""
        competitors = self._extract_competitors(value)
        return ", ".join(competitors) if competitors else "None"

    def _format_key_quotes(self, value: Any) -> str:
        """Format key quotes for display."""
        if value is None:
            return "N/A"
        data = value if isinstance(value, dict) else {}
        if isinstance(value, str):
            try:
                data = json.loads(value)
            except:
                return "N/A"
        quotes = data.get("quotes", []) if isinstance(data, dict) else []
        if not quotes:
            return "N/A"
        return "; ".join(f'"{q}"' for q in quotes[:3])

    def _format_qa_pairs(self, value: Any) -> str:
        """Format Q&A pairs for display in content."""
        if value is None:
            return ""
        data = value if isinstance(value, dict) else {}
        if isinstance(value, str):
            try:
                data = json.loads(value)
            except:
                return ""
        pairs = data.get("pairs", []) if isinstance(data, dict) else []
        if not pairs:
            return ""
        formatted = []
        for pair in pairs[:5]:
            q = pair.get("question", "")
            a = pair.get("answer", "")
            if q and a:
                formatted.append(f"  Q: {q}\n  A: {a}")
        return "\n".join(formatted) if formatted else ""

    def _count_qa_pairs(self, value: Any) -> int:
        """Count Q&A pairs."""
        if value is None:
            return 0
        data = value if isinstance(value, dict) else {}
        if isinstance(value, str):
            try:
                data = json.loads(value)
            except:
                return 0
        pairs = data.get("pairs", []) if isinstance(data, dict) else []
        return len(pairs)

    def _extract_buying_signals(self, value: Any) -> bool:
        """Extract buying signals detected boolean."""
        if value is None:
            return False
        data = value if isinstance(value, dict) else {}
        if isinstance(value, str):
            try:
                data = json.loads(value)
            except:
                return False
        if isinstance(data, dict):
            return bool(data.get("buying_signals_detected", False))
        return False

    def _extract_competitors(self, value: Any) -> List[str]:
        """Extract competitor names as array."""
        if value is None:
            return []
        data = value if isinstance(value, dict) else {}
        if isinstance(value, str):
            try:
                data = json.loads(value)
            except:
                return []
        if isinstance(data, dict):
            competitors = data.get("competitors_mentioned", []) or data.get("competitors", [])
            return [str(c) for c in competitors] if competitors else []
        return []

    def _is_high_risk(self, data: Dict[str, Any]) -> bool:
        """Check if call is high risk (churn_risk >= 7 or escalation required)."""
        churn = self._safe_float(data.get("churn_risk_score"))
        escalation = self._safe_bool(data.get("escalation_required") or data.get("rec_escalation_needed"))
        return (churn is not None and churn >= 7) or (escalation is True)

    # === FRESHDESK Q&A FORMATTING ===

    def format_freshdesk_qa(self, qa_data: Dict[str, Any]) -> Dict[str, Any]:
        """Format a Freshdesk Q&A record for RAG ingestion."""
        qa_id = qa_data.get("qa_id", "unknown")
        content_text = self._build_freshdesk_content(qa_data)
        struct_data = self._build_freshdesk_struct_data(qa_data)

        return {
            "id": qa_id,  # Already prefixed with fd_
            "content": {"mime_type": "text/plain", "text": content_text},
            "struct_data": struct_data
        }

    def _build_freshdesk_content(self, data: Dict[str, Any]) -> str:
        """Build formatted text for Freshdesk Q&A."""
        resolved_at = data.get("resolved_at", "Unknown")
        if isinstance(resolved_at, (datetime, date)):
            resolved_at = resolved_at.strftime("%Y-%m-%d %H:%M")

        created_at = data.get("created_at", "Unknown")
        if isinstance(created_at, (datetime, date)):
            created_at = created_at.strftime("%Y-%m-%d %H:%M")

        tags = data.get("tags", [])
        tags_str = ", ".join(tags) if tags else "None"

        priority_map = {1: "Low", 2: "Medium", 3: "High", 4: "Urgent"}
        priority = priority_map.get(data.get("priority"), "Unknown")

        # AI-enriched fields
        ai_topics = data.get("ai_topics", [])
        ai_topics_str = ", ".join(ai_topics) if ai_topics else "N/A"
        ai_summary = data.get("ai_summary", "")

        content = f"""[SOURCE: FRESHDESK SUPPORT TICKET]
Ticket ID: #{data.get('ticket_id', 'Unknown')}
Category: {data.get('category', 'General')}
Tags: {tags_str}
Priority: {priority}
Created: {created_at}
Resolved: {resolved_at}

[SUPPORT AGENT]
Agent Name: {data.get('agent_name', 'Unknown')}

[CUSTOMER/REQUESTER]
Requester Email: {data.get('requester_email', 'Unknown')}

[QUESTION/PROBLEM]
{data.get('question', 'No question available')}

[ANSWER/SOLUTION]
{data.get('answer', 'No answer available')}
"""

        # Add AI analysis section if enriched
        if data.get('enriched_at'):
            content += f"""
[AI ANALYSIS]
Summary: {ai_summary or 'N/A'}
Key Topics: {ai_topics_str}
Problem Type: {data.get('ai_problem_type', 'N/A')}
Product Area: {data.get('ai_product_area', 'N/A')}
Customer Sentiment: {data.get('ai_sentiment', 'N/A')}
Problem Complexity: {data.get('ai_complexity', 'N/A')}
Resolution Quality: {data.get('ai_resolution_quality', 'N/A')}/10
Resolution Complete: {self._bool_to_yesno(data.get('ai_resolution_complete'))}
Follow-up Needed: {self._bool_to_yesno(data.get('ai_follow_up_needed'))}
"""
            if data.get('ai_knowledge_gap'):
                content += f"Knowledge Gap: {data.get('ai_knowledge_gap')}\n"
            if data.get('ai_suggested_article'):
                content += f"Suggested KB Article: {data.get('ai_suggested_article')}\n"

        content += f"""
[METADATA]
Source: Freshdesk Support Ticket
Q&A ID: {data.get('qa_id', 'Unknown')}
"""
        return content

    def _build_freshdesk_struct_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Build structured data for Freshdesk Q&A for filtering."""
        resolved_at = data.get("resolved_at")
        if isinstance(resolved_at, (datetime, date)):
            resolved_at_str = resolved_at.strftime("%Y-%m-%d")
        else:
            resolved_at_str = str(resolved_at)[:10] if resolved_at else None

        created_at = data.get("created_at")
        if isinstance(created_at, (datetime, date)):
            created_at_str = created_at.strftime("%Y-%m-%d")
        else:
            created_at_str = str(created_at)[:10] if created_at else None

        tags = data.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except:
                tags = [tags] if tags else []

        return {
            # === IDENTIFIERS ===
            "qa_id": data.get("qa_id"),
            "ticket_id": self._safe_int(data.get("ticket_id")),
            "source_type": "freshdesk",

            # === DATES ===
            "created_date": created_at_str,
            "resolved_date": resolved_at_str,

            # === PARTICIPANTS ===
            "agent_name": data.get("agent_name"),
            "requester_email": data.get("requester_email"),

            # === CATEGORIZATION ===
            "category": data.get("category"),
            "tags": tags if isinstance(tags, list) else [],
            "priority": self._safe_int(data.get("priority")),

            # === CONTENT FLAGS ===
            "has_question": bool(data.get("question")),
            "has_answer": bool(data.get("answer")),
            "question_length": len(data.get("question", "")) if data.get("question") else 0,
            "answer_length": len(data.get("answer", "")) if data.get("answer") else 0,

            # === COMPUTED FLAGS ===
            "is_freshdesk": True,
            "is_call_recording": False,
        }


class JSONLWriter:
    """Writes documents to JSONL files."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_batch(self, documents: List[Dict], filename: Optional[str] = None) -> Path:
        """Write a batch of documents to a JSONL file."""
        if filename is None:
            filename = f"calls_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

        filepath = self.output_dir / filename
        with open(filepath, 'w') as f:
            for doc in documents:
                f.write(json.dumps(doc, default=str) + '\n')

        logger.info(f"Wrote {len(documents)} documents to {filepath}")
        return filepath

    def write_single(self, document: Dict, filename: str) -> Path:
        """Write a single document to a JSONL file."""
        filepath = self.output_dir / filename
        with open(filepath, 'a') as f:
            f.write(json.dumps(document, default=str) + '\n')
        return filepath


if __name__ == "__main__":
    # Test the formatter
    test_data = {
        "recording_id": "test123",
        "call_date": datetime.now(),
        "duration_seconds": 300,
        "employee_name": "John Smith",
        "customer_name": "Jane Doe",
        "customer_sentiment": "positive",
        "call_quality_score": 8.5,
        "churn_risk_score": 3,
        "key_topics": ["billing", "upgrade", "support"],
        "transcript_text": "Hello, this is a test transcript...",
        "competitor_intelligence": {"competitors_mentioned": ["Bullhorn", "Crelate"]},
        "buying_signals": {"buying_signals_detected": True},
        "qa_pairs": {"pairs": [{"question": "How much?", "answer": "$99/month"}]},
    }

    formatter = JSONLFormatter()
    result = formatter.format_call(test_data)

    print("=" * 60)
    print("FORMATTED DOCUMENT")
    print("=" * 60)
    print("\n--- struct_data (for filtering) ---")
    print(json.dumps(result["struct_data"], indent=2, default=str))
    print("\n--- content.text (first 1000 chars) ---")
    print(result["content"]["text"][:1000])
