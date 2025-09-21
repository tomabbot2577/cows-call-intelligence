#!/usr/bin/env python3
"""
Enhanced Call Insights Analyzer
Comprehensive AI analysis for support and sales calls with customer/phone/person tracking
"""

import json
import re
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from openai import OpenAI
import os
import sys

# Add config path
sys.path.insert(0, '/var/www/call-recording-system')
from config.task_optimized_llm_config import TaskOptimizedLLMConfig

logger = logging.getLogger(__name__)


class EnhancedCallAnalyzer:
    """
    Advanced AI-powered call analyzer with task-optimized LLMs
    Uses different models for different tasks to optimize performance and cost
    """

    def __init__(self, api_key: str = None):
        """Initialize with task-optimized LLM configuration"""
        self.api_key = api_key or os.getenv('OPENROUTER_API_KEY')
        self.task_config = TaskOptimizedLLMConfig()

        logger.info(f"EnhancedCallAnalyzer initialized with task-optimized LLMs")
        logger.info(f"Available tasks: {list(self.task_config.TASK_MODELS.keys())}")
        self.__init_prompts__()

    def _safe_json_parse(self, response_content: str, fallback_data: dict = None) -> dict:
        """Safely parse JSON response with fallback handling"""
        if fallback_data is None:
            fallback_data = {}

        try:
            # Clean the response content
            content = response_content.strip()

            # Remove markdown code blocks if present
            if content.startswith('```'):
                lines = content.split('\n')
                # Find start and end of JSON
                start_idx = 0
                end_idx = len(lines)
                for i, line in enumerate(lines):
                    if line.strip().startswith('{'):
                        start_idx = i
                        break
                for i in range(len(lines) - 1, -1, -1):
                    if line.strip().endswith('}'):
                        end_idx = i + 1
                        break
                content = '\n'.join(lines[start_idx:end_idx])

            # Try to parse JSON
            return json.loads(content)

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parsing failed: {e}")
            logger.debug(f"Raw content: {response_content[:200]}...")

            # Try to extract JSON from text using regex
            try:
                import re
                json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except:
                pass

            return fallback_data
        except Exception as e:
            logger.error(f"Unexpected error parsing JSON: {e}")
            return fallback_data

    def _get_client_for_task(self, task: str) -> OpenAI:
        """Get OpenAI client configured for specific task"""
        client_config = self.task_config.get_client_config_for_task(task)
        if self.api_key:
            client_config['api_key'] = self.api_key

        return OpenAI(**client_config)

    def __init_prompts__(self):
        """Initialize enhanced prompts for deeper analysis"""
        self.customer_profile_prompt = """
        Analyze this call transcript and extract comprehensive customer profile information:

        CUSTOMER IDENTIFICATION:
        - Primary contact name and role
        - Company/organization name
        - Phone numbers mentioned
        - Email addresses mentioned
        - Key decision makers referenced
        - Team members and their roles

        BUSINESS CONTEXT:
        - Industry or business type
        - Company size indicators
        - Technology stack mentions
        - Current challenges/pain points
        - Growth stage indicators

        RELATIONSHIP MAPPING:
        - Previous interactions referenced
        - Existing service usage
        - Account history mentions
        - Relationship duration indicators
        - Trust level indicators

        IMPORTANT: Return ONLY valid JSON format. No additional text or explanations.

        Return structured JSON with extracted information.
        """

        self.support_analysis_prompt = """
        Perform deep support call analysis focusing on:

        ISSUE CLASSIFICATION:
        - Primary issue category (billing, technical, feature request, etc.)
        - Issue severity (critical, high, medium, low)
        - Technical complexity level
        - Time sensitivity

        RESOLUTION TRACKING:
        - Issue status (resolved, pending, escalated, follow-up needed)
        - Resolution steps taken
        - Outstanding action items
        - Next steps required

        CUSTOMER EFFORT:
        - Call complexity for customer
        - Number of contacts required
        - Self-service opportunities missed
        - Knowledge base gaps identified

        AGENT PERFORMANCE:
        - Problem-solving approach
        - Communication clarity
        - Technical knowledge demonstrated
        - Empathy and rapport building

        IMPORTANT: Return ONLY valid JSON format. No additional text or explanations.

        Return detailed JSON analysis.
        """

        self.sales_analysis_prompt = """
        Analyze this call for sales and business intelligence:

        OPPORTUNITY ASSESSMENT:
        - Deal stage/pipeline position
        - Revenue potential indicators
        - Decision timeline
        - Budget discussions
        - Competitive mentions

        PRODUCT ENGAGEMENT:
        - Features discussed
        - Use case scenarios
        - Implementation requirements
        - Integration needs
        - Training requirements

        BUYING SIGNALS:
        - Purchase intent indicators
        - Urgency signals
        - Decision criteria mentioned
        - Stakeholder involvement
        - Approval process insights

        OBJECTION HANDLING:
        - Concerns raised
        - Objections and responses
        - Unresolved hesitations
        - Competitive comparisons

        IMPORTANT: Return ONLY valid JSON format. No additional text or explanations.

        Return comprehensive sales intelligence JSON.
        """

        self.relationship_analysis_prompt = """
        Analyze the relationship dynamics and customer journey:

        RELATIONSHIP HEALTH:
        - Overall satisfaction indicators
        - Trust level signals
        - Communication style
        - Rapport quality

        CUSTOMER JOURNEY STAGE:
        - Onboarding status
        - Product adoption level
        - Feature utilization
        - Expansion opportunities

        RETENTION FACTORS:
        - Satisfaction drivers
        - Risk indicators
        - Loyalty signals
        - Advocacy potential

        COMMUNICATION PREFERENCES:
        - Preferred contact methods
        - Response time expectations
        - Information style preferences
        - Decision-making patterns

        IMPORTANT: Return ONLY valid JSON format. No additional text or explanations.

        Return relationship intelligence JSON.
        """

    def extract_contact_information(self, transcript: str, metadata: Dict) -> Dict[str, Any]:
        """Extract comprehensive contact information using Claude Haiku (optimized for extraction)"""

        # Extract using regex patterns
        phone_pattern = r'(\d{3}[-.]?\d{3}[-.]?\d{4}|\(\d{3}\)\s?\d{3}[-.]?\d{4})'
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

        phones = list(set(re.findall(phone_pattern, transcript)))
        emails = list(set(re.findall(email_pattern, transcript)))

        # Extract names using Claude Haiku (optimized for customer extraction)
        name_prompt = f"""
        Extract all person names mentioned in this call transcript.
        Identify their roles and relationships:

        {transcript[:2000]}...

        IMPORTANT: Return ONLY valid JSON format. No additional text or explanations.

        Return JSON format:
        {{
            "participants": [
                {{"name": "John Smith", "role": "customer", "company": "ABC Corp"}},
                {{"name": "Jane Doe", "role": "agent", "company": "Main Sequence"}}
            ],
            "mentioned_contacts": [
                {{"name": "Bob Johnson", "role": "decision_maker", "context": "needs approval"}}
            ]
        }}
        """

        try:
            client = self._get_client_for_task('customer_extraction')
            model = self.task_config.get_model_for_task('customer_extraction')
            logger.info(f"Using {model} for contact extraction")

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": name_prompt}],
                temperature=0.1
            )
            name_analysis = self._safe_json_parse(
                response.choices[0].message.content,
                {"participants": [], "mentioned_contacts": []}
            )
        except Exception as e:
            logger.error(f"Name extraction failed: {e}")
            name_analysis = {"participants": [], "mentioned_contacts": []}

        # Validate extracted names to reduce false positives
        validated_participants = self._validate_customer_names(
            name_analysis.get("participants", []), transcript, metadata
        )

        return {
            "phone_numbers": phones,
            "email_addresses": emails,
            "participants": validated_participants,
            "mentioned_contacts": name_analysis.get("mentioned_contacts", []),
            "recording_metadata": {
                "from_number": metadata.get("call_metadata", {}).get("from", {}).get("number"),
                "to_number": metadata.get("call_metadata", {}).get("to", {}).get("number"),
                "call_duration": metadata.get("call_metadata", {}).get("duration_seconds"),
                "call_date": metadata.get("call_metadata", {}).get("date")
            }
        }

    def _validate_customer_names(self, participants: List[Dict], transcript: str, metadata: Dict) -> List[Dict]:
        """AI-powered validation to filter false positive customer names using Claude Haiku"""
        if not participants:
            return []

        # Get employee database for filtering
        try:
            from src.insights.customer_employee_identifier import CustomerEmployeeIdentifier
            identifier = CustomerEmployeeIdentifier()
            employee_names = set(emp.get('name', '').lower() for emp in identifier.employee_database)
        except Exception:
            employee_names = set()

        validation_prompt = f"""
        Review these extracted participant names and validate which are likely REAL CUSTOMERS vs false positives.

        CONTEXT:
        - Call from: {metadata.get("call_metadata", {}).get("from", {}).get("number", "unknown")}
        - Call to: {metadata.get("call_metadata", {}).get("to", {}).get("number", "unknown")}
        - Duration: {metadata.get("call_metadata", {}).get("duration_seconds", 0)} seconds

        EXTRACTED PARTICIPANTS:
        {json.dumps(participants, indent=2)}

        VALIDATION CRITERIA:
        - Real customer names are mentioned as the caller, account holder, or primary contact
        - Exclude: company names, product names, system names, department names
        - Exclude: words that sound like names but are actually business terms
        - Exclude: names mentioned casually or as examples
        - Exclude: employee names from Main Sequence staff

        IMPORTANT: Return ONLY valid JSON format. No additional text or explanations.

        Return JSON with validated participants and confidence scores:
        {{
            "validated_participants": [
                {{
                    "name": "John Smith",
                    "role": "customer",
                    "company": "ABC Corp",
                    "confidence_score": 0.95,
                    "validation_reason": "Clearly identified as account holder"
                }}
            ],
            "excluded_participants": [
                {{
                    "name": "Billing Department",
                    "reason": "Department name, not a person"
                }}
            ]
        }}
        """

        try:
            client = self._get_client_for_task('customer_extraction')
            model = self.task_config.get_model_for_task('customer_extraction')
            logger.info(f"Using {model} for customer name validation")

            response = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "system",
                    "content": "You are an expert at identifying real customer names vs false positives in business call transcripts."
                }, {
                    "role": "user",
                    "content": validation_prompt
                }],
                temperature=0.1
            )

            fallback_validation = {
                "validated_participants": participants,
                "excluded_participants": []
            }
            validation_result = self._safe_json_parse(
                response.choices[0].message.content, fallback_validation
            )
            validated = validation_result.get("validated_participants", [])
            excluded = validation_result.get("excluded_participants", [])

            logger.info(f"Customer name validation: {len(validated)} valid, {len(excluded)} excluded")
            for exc in excluded[:3]:  # Log first 3 exclusions
                logger.info(f"  Excluded: {exc.get('name')} - {exc.get('reason')}")

            return validated

        except Exception as e:
            logger.error(f"Customer name validation failed: {e}")
            # Fallback: basic filtering
            return self._basic_name_filter(participants, employee_names)

    def _basic_name_filter(self, participants: List[Dict], employee_names: set) -> List[Dict]:
        """Basic fallback filtering for customer names"""
        filtered = []

        # Common false positive patterns
        false_positive_patterns = [
            'billing', 'department', 'support', 'team', 'company', 'corp', 'inc', 'llc',
            'system', 'service', 'account', 'manager', 'representative', 'admin'
        ]

        for participant in participants:
            name = participant.get('name', '').lower()

            # Skip if matches employee name
            if name in employee_names:
                continue

            # Skip if contains false positive patterns
            if any(pattern in name for pattern in false_positive_patterns):
                continue

            # Skip single words that aren't likely names
            if len(name.split()) == 1 and len(name) < 3:
                continue

            filtered.append(participant)

        return filtered

    def analyze_customer_profile(self, transcript: str) -> Dict[str, Any]:
        """Generate comprehensive customer profile analysis using Claude Haiku (optimized for extraction)"""
        try:
            client = self._get_client_for_task('customer_extraction')
            model = self.task_config.get_model_for_task('customer_extraction')
            logger.info(f"Using {model} for customer profile analysis")

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are an expert business analyst specializing in customer profiling."},
                    {"role": "user", "content": f"{self.customer_profile_prompt}\n\nTranscript:\n{transcript}"}
                ],
                temperature=0.2
            )
            return self._safe_json_parse(response.choices[0].message.content, {})
        except Exception as e:
            logger.error(f"Customer profile analysis failed: {e}")
            return {}

    def analyze_support_call(self, transcript: str) -> Dict[str, Any]:
        """Deep support call analysis using Llama (optimized for technical analysis)"""
        try:
            client = self._get_client_for_task('support_analysis')
            model = self.task_config.get_model_for_task('support_analysis')
            logger.info(f"Using {model} for support analysis")

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are an expert support analyst with deep knowledge of customer service operations."},
                    {"role": "user", "content": f"{self.support_analysis_prompt}\n\nTranscript:\n{transcript}"}
                ],
                temperature=0.2
            )
            return self._safe_json_parse(response.choices[0].message.content, {})
        except Exception as e:
            logger.error(f"Support analysis failed: {e}")
            return {}

    def analyze_sales_call(self, transcript: str) -> Dict[str, Any]:
        """Comprehensive sales call analysis using Claude Sonnet (optimized for sales insights)"""
        try:
            client = self._get_client_for_task('sales_analysis')
            model = self.task_config.get_model_for_task('sales_analysis')
            logger.info(f"Using {model} for sales analysis")

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are an expert sales analyst with deep understanding of B2B sales processes."},
                    {"role": "user", "content": f"{self.sales_analysis_prompt}\n\nTranscript:\n{transcript}"}
                ],
                temperature=0.2
            )
            return self._safe_json_parse(response.choices[0].message.content, {})
        except Exception as e:
            logger.error(f"Sales analysis failed: {e}")
            return {}

    def analyze_relationship_dynamics(self, transcript: str) -> Dict[str, Any]:
        """Analyze relationship health and customer journey using GPT-4 (optimized for business insights)"""
        try:
            client = self._get_client_for_task('business_insights')
            model = self.task_config.get_model_for_task('business_insights')
            logger.info(f"Using {model} for relationship analysis")

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are an expert relationship analyst specializing in customer success and retention."},
                    {"role": "user", "content": f"{self.relationship_analysis_prompt}\n\nTranscript:\n{transcript}"}
                ],
                temperature=0.2
            )
            return self._safe_json_parse(response.choices[0].message.content, {})
        except Exception as e:
            logger.error(f"Relationship analysis failed: {e}")
            return {}

    def classify_call_type(self, transcript: str) -> Dict[str, Any]:
        """Classify the call type and purpose using GPT-3.5 (optimized for classification)"""
        classification_prompt = f"""
        Classify this call transcript:

        CALL TYPE:
        - support_technical
        - support_billing
        - support_feature_request
        - sales_discovery
        - sales_demo
        - sales_negotiation
        - account_management
        - onboarding
        - training
        - escalation
        - other

        CALL PURPOSE (primary objectives):
        - List 2-3 main purposes

        URGENCY LEVEL:
        - critical
        - high
        - medium
        - low

        OUTCOME STATUS:
        - resolved
        - partially_resolved
        - pending
        - escalated
        - follow_up_required

        IMPORTANT: Return ONLY valid JSON format. No additional text or explanations.

        Return JSON with classifications.

        Transcript: {transcript[:1500]}...
        """

        try:
            client = self._get_client_for_task('call_classification')
            model = self.task_config.get_model_for_task('call_classification')
            logger.info(f"Using {model} for call classification")

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": classification_prompt}],
                temperature=0.1
            )
            fallback_classification = {
                "call_type": "other",
                "call_purpose": ["general_inquiry"],
                "urgency_level": "medium",
                "outcome_status": "pending"
            }
            return self._safe_json_parse(response.choices[0].message.content, fallback_classification)
        except Exception as e:
            logger.error(f"Call classification failed: {e}")
            return {
                "call_type": "other",
                "call_purpose": ["general_inquiry"],
                "urgency_level": "medium",
                "outcome_status": "pending"
            }

    def generate_comprehensive_insights(self, transcript_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate comprehensive insights combining all analysis types"""
        transcript = transcript_data.get("transcription", {}).get("text", "")
        metadata = transcript_data

        if not transcript:
            logger.error("No transcript text found")
            return {}

        logger.info("🧠 Generating comprehensive call insights...")

        # Extract contact information
        contact_info = self.extract_contact_information(transcript, metadata)

        # Classify call
        call_classification = self.classify_call_type(transcript)

        # Generate analyses
        customer_profile = self.analyze_customer_profile(transcript)
        support_analysis = self.analyze_support_call(transcript)
        sales_analysis = self.analyze_sales_call(transcript)
        relationship_analysis = self.analyze_relationship_dynamics(transcript)

        # Combine all insights
        comprehensive_insights = {
            "recording_id": transcript_data.get("recording_id"),
            "analysis_timestamp": datetime.now().isoformat(),
            "analysis_version": "2.0",

            # Contact and identification
            "contact_information": contact_info,

            # Call classification
            "call_classification": call_classification,

            # Deep analyses
            "customer_profile": customer_profile,
            "support_analysis": support_analysis,
            "sales_analysis": sales_analysis,
            "relationship_analysis": relationship_analysis,

            # Summary metrics (extracted from analyses)
            "key_metrics": self._extract_key_metrics(
                call_classification, customer_profile, support_analysis,
                sales_analysis, relationship_analysis
            ),

            # Action items and next steps
            "action_items": self._extract_action_items(
                support_analysis, sales_analysis, relationship_analysis
            )
        }

        logger.info("✅ Comprehensive insights generated successfully")
        return comprehensive_insights

    def _extract_key_metrics(self, classification: Dict, customer: Dict,
                           support: Dict, sales: Dict, relationship: Dict) -> Dict[str, Any]:
        """Extract key metrics for dashboard and reporting"""
        return {
            "call_type": classification.get("call_type", "other"),
            "urgency_level": classification.get("urgency_level", "medium"),
            "outcome_status": classification.get("outcome_status", "pending"),
            "customer_satisfaction_score": self._extract_satisfaction_score(relationship),
            "resolution_time": self._extract_resolution_time(support),
            "sales_opportunity_score": self._extract_opportunity_score(sales),
            "relationship_health_score": self._extract_relationship_score(relationship),
            "escalation_risk": self._extract_escalation_risk(support, relationship),
            "churn_risk_score": self._extract_churn_risk(customer, relationship),
            "upsell_opportunity": self._extract_upsell_potential(sales, customer)
        }

    def _extract_action_items(self, support: Dict, sales: Dict, relationship: Dict) -> List[Dict]:
        """Extract actionable items from all analyses"""
        actions = []

        # Support actions
        if support.get("outstanding_action_items"):
            for item in support["outstanding_action_items"]:
                actions.append({
                    "type": "support",
                    "action": item,
                    "priority": "high" if "urgent" in item.lower() else "medium",
                    "category": "technical_resolution"
                })

        # Sales actions
        if sales.get("next_steps"):
            for step in sales["next_steps"]:
                actions.append({
                    "type": "sales",
                    "action": step,
                    "priority": "high" if "demo" in step.lower() or "proposal" in step.lower() else "medium",
                    "category": "sales_progression"
                })

        # Relationship actions
        if relationship.get("recommended_actions"):
            for action in relationship["recommended_actions"]:
                actions.append({
                    "type": "relationship",
                    "action": action,
                    "priority": "medium",
                    "category": "customer_success"
                })

        return actions

    def _extract_satisfaction_score(self, relationship: Dict) -> int:
        """Extract satisfaction score from relationship analysis"""
        # Implementation to parse satisfaction indicators
        return relationship.get("satisfaction_score", 7)  # Default neutral

    def _extract_resolution_time(self, support: Dict) -> Optional[str]:
        """Extract resolution timeframe"""
        return support.get("estimated_resolution_time")

    def _extract_opportunity_score(self, sales: Dict) -> int:
        """Extract sales opportunity score 1-10"""
        return sales.get("opportunity_score", 5)  # Default neutral

    def _extract_relationship_score(self, relationship: Dict) -> int:
        """Extract relationship health score 1-10"""
        return relationship.get("relationship_health_score", 7)  # Default good

    def _extract_escalation_risk(self, support: Dict, relationship: Dict) -> str:
        """Determine escalation risk level"""
        if support.get("issue_severity") == "critical":
            return "high"
        if relationship.get("satisfaction_level", 7) < 5:
            return "high"
        return "low"

    def _extract_churn_risk(self, customer: Dict, relationship: Dict) -> int:
        """Calculate churn risk score 1-10"""
        return relationship.get("churn_risk_score", 3)  # Default low risk

    def _extract_upsell_potential(self, sales: Dict, customer: Dict) -> str:
        """Assess upsell/expansion potential"""
        return sales.get("expansion_potential", "medium")


def get_enhanced_analyzer() -> EnhancedCallAnalyzer:
    """Factory function to get analyzer instance"""
    return EnhancedCallAnalyzer()


if __name__ == "__main__":
    # Test the analyzer
    analyzer = get_enhanced_analyzer()
    logger.info("Enhanced Call Analyzer initialized successfully")