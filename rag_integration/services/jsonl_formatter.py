"""JSONL Formatter - Converts database records to RAG-ready format."""

import json
from datetime import datetime, date
from typing import Dict, Any, Optional, List
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class JSONLFormatter:
    """Formats call data into JSONL for RAG systems."""

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
        """Build formatted text with embedded metadata for semantic search."""
        call_date = data.get("call_date", "Unknown")
        if isinstance(call_date, (datetime, date)):
            call_date = call_date.strftime("%Y-%m-%d")

        call_time = data.get("call_time", "")
        if call_time:
            call_time = str(call_time)[:8]  # HH:MM:SS

        duration = data.get("duration_seconds", 0) or 0
        duration_min, duration_sec = divmod(int(duration), 60)

        # Build key topics string
        key_topics = data.get("key_topics", [])
        if isinstance(key_topics, list):
            topics_str = ", ".join(key_topics) if key_topics else "N/A"
        else:
            topics_str = str(key_topics) if key_topics else "N/A"

        # Build arrays from Layer 3/4 data
        frustration_points = self._format_array(data.get("frustration_points"))
        delight_moments = self._format_array(data.get("delight_moments"))
        process_gaps = self._format_array(data.get("process_gaps"))
        strengths = self._format_array(data.get("employee_strengths"))
        improvements = self._format_array(data.get("employee_improvements"))
        followup_actions = self._format_array(data.get("followup_actions"))

        return f"""[CALL METADATA]
Call ID: {data.get('recording_id', 'Unknown')}
Date: {call_date} {call_time}
Duration: {duration_min}:{duration_sec:02d}
Direction: {data.get('direction', 'Unknown')}

[PARTICIPANTS]
Employee: {data.get('employee_name', 'Unknown')}
Department: {data.get('employee_department', 'N/A')}
Customer: {data.get('customer_name', 'Unknown')}
Company: {data.get('customer_company', 'N/A')}
Phone: {data.get('customer_phone') or data.get('from_number', 'N/A')}

[LAYER 2 - SENTIMENT & QUALITY]
Customer Sentiment: {data.get('customer_sentiment', 'N/A')}
Sentiment Reasoning: {data.get('sentiment_reasoning', 'N/A')}
Call Quality Score: {data.get('call_quality_score', 'N/A')}/10
Quality Reasoning: {data.get('quality_reasoning', 'N/A')}
Overall Rating: {data.get('overall_call_rating', 'N/A')}/10
Call Type: {data.get('call_type', 'N/A')}
Issue Category: {data.get('issue_category', 'N/A')}
Key Topics: {topics_str}
Summary: {data.get('summary', 'N/A')}

[LAYER 3 - RESOLUTION & PERFORMANCE]
Problem Complexity: {data.get('problem_complexity', 'N/A')}
Resolution Effectiveness: {data.get('resolution_effectiveness', 'N/A')}/10
First Call Resolution: {data.get('first_call_resolution', 'N/A')}
Empathy Score: {data.get('empathy_score', 'N/A')}/10
Communication Clarity: {data.get('communication_clarity', 'N/A')}/10
Active Listening: {data.get('active_listening_score', 'N/A')}/10
Employee Knowledge: {data.get('employee_knowledge_level', 'N/A')}/10
Customer Effort Score: {data.get('customer_effort_score', 'N/A')}/10 (lower is better)
Churn Risk: {data.get('churn_risk_score') or data.get('resolution_churn_risk', 'N/A')}
Revenue Impact: {data.get('revenue_impact', 'N/A')}

[LOOP CLOSURE METRICS]
Solution Summarized: {self._bool_to_yesno(data.get('solution_summarized'))}
Understanding Confirmed: {self._bool_to_yesno(data.get('understanding_confirmed'))}
Asked If Anything Else: {self._bool_to_yesno(data.get('asked_if_anything_else'))}
Next Steps Provided: {self._bool_to_yesno(data.get('next_steps_provided'))}
Timeline Given: {self._bool_to_yesno(data.get('timeline_given'))}
Contact Info Provided: {self._bool_to_yesno(data.get('contact_info_provided'))}
Thanked Customer: {self._bool_to_yesno(data.get('thanked_customer'))}
Confirmed Satisfaction: {self._bool_to_yesno(data.get('confirmed_satisfaction'))}

[CUSTOMER EXPERIENCE]
Frustration Points: {frustration_points}
Delight Moments: {delight_moments}

[PROCESS INSIGHTS]
Process Gaps: {process_gaps}
Automation Opportunities: {self._format_array(data.get('automation_opportunities'))}
Knowledge Base Gaps: {self._format_array(data.get('knowledge_base_gaps'))}

[LAYER 4 - RECOMMENDATIONS]
Employee Strengths: {strengths}
Areas for Improvement: {improvements}
Suggested Phrases: {self._format_array(data.get('suggested_phrases'))}
Follow-up Actions: {followup_actions}
Escalation Required: {self._bool_to_yesno(data.get('escalation_required') or data.get('rec_escalation_needed'))}
Risk Level: {data.get('risk_level', 'N/A')}
Training Priority: {data.get('training_priority', 'N/A')}
Coaching Notes: {data.get('coaching_notes', 'N/A')}

[TRANSCRIPT]
{data.get('transcript_text', 'No transcript available')}
"""

    def _build_struct_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Build structured data for filtered queries in Vertex AI."""
        call_date = data.get("call_date")
        if isinstance(call_date, (datetime, date)):
            call_date_str = call_date.strftime("%Y-%m-%d")
        else:
            call_date_str = str(call_date) if call_date else None

        return {
            # Identifiers
            "call_id": str(data.get("recording_id")),
            "call_date": call_date_str,

            # Participants
            "employee_name": data.get("employee_name"),
            "employee_department": data.get("employee_department"),
            "customer_name": data.get("customer_name"),
            "customer_company": data.get("customer_company"),
            "customer_phone": data.get("customer_phone") or data.get("from_number"),

            # Call metadata
            "duration_seconds": self._safe_int(data.get("duration_seconds")),
            "direction": data.get("direction"),
            "word_count": self._safe_int(data.get("word_count")),

            # Sentiment & Quality (Layer 2)
            "customer_sentiment": data.get("customer_sentiment"),
            "call_quality_score": self._safe_float(data.get("call_quality_score")),
            "customer_satisfaction_score": self._safe_float(data.get("customer_satisfaction_score")),
            "overall_call_rating": self._safe_float(data.get("overall_call_rating")),
            "call_type": data.get("call_type"),
            "issue_category": data.get("issue_category"),
            "churn_risk_score": self._safe_float(data.get("churn_risk_score")),

            # Resolution (Layer 3)
            "problem_complexity": data.get("problem_complexity"),
            "resolution_effectiveness": self._safe_float(data.get("resolution_effectiveness")),
            "empathy_score": self._safe_float(data.get("empathy_score")),
            "communication_clarity": self._safe_float(data.get("communication_clarity")),
            "active_listening_score": self._safe_float(data.get("active_listening_score")),
            "customer_effort_score": self._safe_float(data.get("customer_effort_score")),
            "first_call_resolution": data.get("first_call_resolution"),

            # Flags
            "follow_up_needed": data.get("follow_up_needed"),
            "escalation_required": data.get("escalation_required") or data.get("rec_escalation_needed"),
            "risk_level": data.get("risk_level"),

            # Loop closure (for filtering)
            "solution_summarized": data.get("solution_summarized"),
            "understanding_confirmed": data.get("understanding_confirmed"),
        }

    def _format_array(self, value: Any) -> str:
        """Format array or JSON value as string."""
        if value is None:
            return "N/A"
        if isinstance(value, list):
            return ", ".join(str(v) for v in value) if value else "N/A"
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return ", ".join(str(v) for v in parsed) if parsed else "N/A"
            except:
                pass
            return value if value else "N/A"
        return str(value)

    def _bool_to_yesno(self, value: Any) -> str:
        """Convert boolean to Yes/No string."""
        if value is None:
            return "N/A"
        return "Yes" if value else "No"

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
            return float(value)
        except:
            return None


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
        "transcript_text": "Hello, this is a test transcript...",
    }

    formatter = JSONLFormatter()
    result = formatter.format_call(test_data)

    print("Formatted document:")
    print(json.dumps(result, indent=2, default=str))
