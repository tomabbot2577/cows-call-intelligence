"""
Advanced Call Insights Analyzer using OpenAI
Provides comprehensive business intelligence from call transcriptions
"""

import os
import logging
import json
from typing import Optional, Dict, Any, List
from openai import OpenAI
from datetime import datetime

logger = logging.getLogger(__name__)


class CallInsightsAnalyzer:
    """
    Analyzes call transcriptions to provide actionable business insights
    using OpenAI's GPT-3.5-turbo for cost-effective analysis
    """

    def __init__(self):
        """Initialize OpenAI client with cost-optimized settings"""
        self.api_key = os.environ.get('OPENAI_API_KEY')
        self.model = os.environ.get('OPENAI_MODEL', 'gpt-3.5-turbo')

        if self.api_key:
            self.client = OpenAI(api_key=self.api_key)
            logger.info(f"Call Insights Analyzer initialized with {self.model}")
        else:
            self.client = None
            logger.warning("OpenAI API key not found - insights features disabled")

    def analyze_support_call(self, transcription: str) -> Optional[Dict[str, Any]]:
        """
        Comprehensive analysis of support calls

        Returns insights on:
        - Call quality score
        - Customer satisfaction indicators
        - Issue resolution effectiveness
        - Employee performance
        - Improvement suggestions
        """
        if not self.client:
            return None

        try:
            prompt = """Analyze this support call and provide a comprehensive assessment:

1. CALL QUALITY SCORE (1-10)
   - Communication clarity
   - Professionalism
   - Problem-solving approach

2. CUSTOMER SATISFACTION INDICATORS
   - Emotional tone progression
   - Issue resolution status
   - Customer frustration points

3. EMPLOYEE PERFORMANCE
   - Strengths demonstrated
   - Areas needing improvement
   - Specific coaching recommendations

4. BEST PRACTICES ASSESSMENT
   - Which best practices were followed
   - Which were missed
   - Priority improvements needed

5. ACTIONABLE IMPROVEMENTS
   - Top 3 specific suggestions
   - Training needs identified
   - Process improvements recommended

6. EFFICIENCY METRICS
   - Call handling efficiency
   - First call resolution likelihood
   - Follow-up requirements

7. COMPLIANCE & RISK
   - Any compliance issues noted
   - Potential risks identified
   - Escalation needs

Format as JSON with clear, actionable insights.

Transcription:
""" + transcription[:4000]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert call center quality analyst and business consultant. Provide specific, actionable insights."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=800,  # Increased for comprehensive analysis
                temperature=0.3,
                response_format={"type": "json_object"}
            )

            return json.loads(response.choices[0].message.content)

        except Exception as e:
            logger.error(f"Support call analysis failed: {e}")
            return None

    def analyze_sales_call(self, transcription: str) -> Optional[Dict[str, Any]]:
        """
        Analyze sales calls for effectiveness and opportunities
        """
        if not self.client:
            return None

        try:
            prompt = """Analyze this sales call and provide insights:

1. SALES EFFECTIVENESS (1-10)
   - Opening quality
   - Needs discovery
   - Solution presentation
   - Objection handling
   - Closing technique

2. OPPORTUNITY ASSESSMENT
   - Deal likelihood (%)
   - Deal size indicators
   - Timeline mentioned
   - Decision makers identified

3. SALES REP PERFORMANCE
   - Strengths shown
   - Missed opportunities
   - Talk-to-listen ratio
   - Question quality

4. CUSTOMER ENGAGEMENT
   - Interest level (1-10)
   - Pain points identified
   - Budget discussion
   - Next steps clarity

5. IMPROVEMENT RECOMMENDATIONS
   - Top 3 coaching points
   - Sales technique improvements
   - Follow-up strategy

6. COMPETITIVE INTELLIGENCE
   - Competitors mentioned
   - Price sensitivity
   - Key differentiators discussed

Format as JSON with specific insights.

Transcription:
""" + transcription[:4000]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a sales excellence coach and analyst. Focus on actionable improvements."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=700,
                temperature=0.3,
                response_format={"type": "json_object"}
            )

            return json.loads(response.choices[0].message.content)

        except Exception as e:
            logger.error(f"Sales call analysis failed: {e}")
            return None

    def generate_employee_coaching(self, transcription: str, employee_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Generate personalized coaching recommendations for employees
        """
        if not self.client:
            return None

        try:
            prompt = f"""Based on this call, provide personalized coaching for {employee_name or 'the employee'}:

1. COMMUNICATION SKILLS
   - Strengths observed
   - Areas for improvement
   - Specific phrases to use/avoid

2. TECHNICAL KNOWLEDGE
   - Knowledge gaps identified
   - Training recommendations
   - Resources needed

3. SOFT SKILLS ASSESSMENT
   - Empathy demonstration
   - Active listening
   - Patience and composure
   - Problem-solving approach

4. SPECIFIC COACHING ACTIONS
   - Top 3 immediate improvements
   - Practice exercises recommended
   - Role-play scenarios suggested

5. POSITIVE REINFORCEMENT
   - What they did excellently
   - Behaviors to continue
   - Recognition points

6. DEVELOPMENT PLAN
   - 30-day improvement goals
   - Measurable objectives
   - Support needed from management

Format as JSON with encouraging, specific guidance.

Transcription:
""" + transcription[:4000]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a supportive performance coach. Be specific, encouraging, and actionable."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=600,
                temperature=0.4,
                response_format={"type": "json_object"}
            )

            return json.loads(response.choices[0].message.content)

        except Exception as e:
            logger.error(f"Employee coaching generation failed: {e}")
            return None

    def identify_training_needs(self, transcriptions: List[str]) -> Optional[Dict[str, Any]]:
        """
        Analyze multiple calls to identify team-wide training needs
        """
        if not self.client or not transcriptions:
            return None

        try:
            # Combine snippets from multiple calls
            combined = "\n---\n".join([t[:500] for t in transcriptions[:5]])

            prompt = """Analyze these call samples to identify team-wide training needs:

1. COMMON ISSUES PATTERNS
   - Recurring problems
   - Systematic gaps
   - Process breakdowns

2. TRAINING PRIORITIES
   - Top 5 training modules needed
   - Urgency level for each
   - Expected impact

3. TEAM STRENGTHS
   - Consistent strong points
   - Best practices to share
   - Peer learning opportunities

4. RECOMMENDED TRAINING PROGRAM
   - Weekly training topics
   - Workshop suggestions
   - E-learning recommendations
   - Mentoring pairs

5. SUCCESS METRICS
   - KPIs to track
   - Improvement targets
   - Timeline for results

Format as JSON training plan.

Call Samples:
""" + combined

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a training and development specialist. Create actionable training plans."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=600,
                temperature=0.3,
                response_format={"type": "json_object"}
            )

            return json.loads(response.choices[0].message.content)

        except Exception as e:
            logger.error(f"Training needs analysis failed: {e}")
            return None

    def analyze_customer_sentiment(self, transcription: str) -> Optional[Dict[str, Any]]:
        """
        Deep sentiment analysis with customer experience insights
        """
        if not self.client:
            return None

        try:
            prompt = """Perform deep sentiment analysis on this call:

1. EMOTIONAL JOURNEY
   - Starting sentiment
   - Turning points
   - Final sentiment
   - Emotional triggers

2. SATISFACTION INDICATORS
   - Satisfaction level (1-10)
   - Likelihood to recommend (NPS)
   - Repeat business probability
   - Churn risk level

3. PAIN POINTS
   - Main frustrations
   - Unmet expectations
   - Process friction points
   - Communication breakdowns

4. POSITIVE MOMENTS
   - What delighted them
   - Appreciated actions
   - Trust-building moments

5. CUSTOMER NEEDS
   - Stated needs
   - Implied needs
   - Future requirements
   - Upsell opportunities

6. RETENTION STRATEGIES
   - Immediate actions needed
   - Follow-up requirements
   - Relationship repair needs
   - Loyalty building opportunities

Format as JSON with specific insights.

Transcription:
""" + transcription[:4000]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a customer experience specialist. Focus on sentiment and satisfaction drivers."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=600,
                temperature=0.3,
                response_format={"type": "json_object"}
            )

            return json.loads(response.choices[0].message.content)

        except Exception as e:
            logger.error(f"Sentiment analysis failed: {e}")
            return None

    def generate_call_summary_report(self, transcription: str, call_metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Generate comprehensive call report with all insights
        """
        if not self.client:
            return None

        try:
            # Determine call type
            call_type = self._detect_call_type(transcription)

            insights = {
                "call_id": call_metadata.get('recording_id'),
                "date": call_metadata.get('date'),
                "duration": call_metadata.get('duration'),
                "call_type": call_type,
                "timestamp": datetime.now().isoformat()
            }

            # Get appropriate analysis based on call type
            if call_type == "support":
                insights["support_analysis"] = self.analyze_support_call(transcription)
            elif call_type == "sales":
                insights["sales_analysis"] = self.analyze_sales_call(transcription)

            # Always include these analyses
            insights["sentiment_analysis"] = self.analyze_customer_sentiment(transcription)
            insights["coaching_recommendations"] = self.generate_employee_coaching(transcription)

            # Add quick wins
            insights["quick_wins"] = self._identify_quick_wins(transcription)

            # Calculate overall scores
            insights["overall_scores"] = self._calculate_overall_scores(insights)

            return insights

        except Exception as e:
            logger.error(f"Call summary report generation failed: {e}")
            return None

    def _detect_call_type(self, transcription: str) -> str:
        """Detect the type of call from transcription"""
        try:
            prompt = "Classify this call as one of: support, sales, complaint, inquiry, internal. Reply with just the category.\n\n" + transcription[:500]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a call classifier. Reply with only one word."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=10,
                temperature=0
            )

            return response.choices[0].message.content.strip().lower()
        except:
            return "unknown"

    def _identify_quick_wins(self, transcription: str) -> List[str]:
        """Identify quick improvements that can be implemented immediately"""
        try:
            prompt = """List 3 quick wins (immediate improvements) from this call.
Be specific and actionable. Format as JSON array of strings.

Transcription:
""" + transcription[:2000]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a process improvement specialist."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=200,
                temperature=0.3
            )

            return json.loads(response.choices[0].message.content)
        except:
            return []

    def _calculate_overall_scores(self, insights: Dict[str, Any]) -> Dict[str, float]:
        """Calculate aggregate scores from various analyses"""
        scores = {
            "overall_quality": 0,
            "customer_satisfaction": 0,
            "employee_performance": 0,
            "improvement_priority": 0
        }

        # Extract scores from nested analyses
        if insights.get("support_analysis"):
            scores["overall_quality"] = insights["support_analysis"].get("call_quality_score", 0)
        elif insights.get("sales_analysis"):
            scores["overall_quality"] = insights["sales_analysis"].get("sales_effectiveness", 0)

        if insights.get("sentiment_analysis"):
            scores["customer_satisfaction"] = insights["sentiment_analysis"].get("satisfaction_level", 0)

        return scores

    def estimate_analysis_cost(self, transcription_length: int) -> float:
        """Estimate cost for complete analysis"""
        # Rough estimates for all analysis types
        total_tokens = (transcription_length / 4) * 5  # Multiple analyses
        cost_per_1k = 0.002  # GPT-3.5-turbo combined rate
        return (total_tokens / 1000) * cost_per_1k


class InsightsReportGenerator:
    """Generate formatted reports from insights"""

    @staticmethod
    def generate_html_report(insights: Dict[str, Any]) -> str:
        """Generate HTML report from insights"""
        html = f"""
        <html>
        <head>
            <title>Call Insights Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h1 {{ color: #333; }}
                h2 {{ color: #666; border-bottom: 1px solid #ccc; }}
                .score {{ font-size: 24px; font-weight: bold; }}
                .good {{ color: green; }}
                .warning {{ color: orange; }}
                .bad {{ color: red; }}
                .insight-box {{ background: #f5f5f5; padding: 10px; margin: 10px 0; border-radius: 5px; }}
                ul {{ line-height: 1.8; }}
            </style>
        </head>
        <body>
            <h1>Call Analysis Report</h1>
            <p>Call ID: {insights.get('call_id', 'Unknown')}</p>
            <p>Date: {insights.get('date', 'Unknown')}</p>
            <p>Type: {insights.get('call_type', 'Unknown')}</p>

            <h2>Overall Scores</h2>
            <div class="insight-box">
        """

        if insights.get('overall_scores'):
            for metric, score in insights['overall_scores'].items():
                color_class = 'good' if score >= 7 else 'warning' if score >= 5 else 'bad'
                html += f'<p>{metric.replace("_", " ").title()}: <span class="score {color_class}">{score}/10</span></p>'

        html += """
            </div>

            <h2>Key Insights</h2>
            <div class="insight-box">
        """

        # Add quick wins if available
        if insights.get('quick_wins'):
            html += "<h3>Quick Wins</h3><ul>"
            for win in insights['quick_wins']:
                html += f"<li>{win}</li>"
            html += "</ul>"

        html += """
            </div>
        </body>
        </html>
        """

        return html