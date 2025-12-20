#!/usr/bin/env python3
"""
AI Insights Manager - Centralized system for storing, organizing, and accessing call insights
Designed for optimal access by both humans and LLMs
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict
# import pandas as pd  # Optional dependency for advanced analytics
import sqlite3

logger = logging.getLogger(__name__)


class InsightsManager:
    """
    Manages AI insights with multiple storage formats and access patterns:
    1. JSON for programmatic access
    2. SQLite for querying and relationships
    3. Markdown for human readability
    4. CSV for data analysis
    5. API endpoints for integration
    """

    def __init__(self, base_path: Path = None):
        """Initialize the insights manager with organized storage structure"""
        self.base_path = base_path or Path('/var/www/call-recording-system/data/insights')

        # Create organized directory structure
        self.dirs = {
            'raw': self.base_path / 'raw',  # Original insights
            'processed': self.base_path / 'processed',  # Enhanced insights
            'by_date': self.base_path / 'by_date',  # Date-based organization
            'by_category': self.base_path / 'by_category',  # Category organization
            'by_agent': self.base_path / 'by_agent',  # Agent-based views
            'by_customer': self.base_path / 'by_customer',  # Customer views
            'summaries': self.base_path / 'summaries',  # Aggregated summaries
            'reports': self.base_path / 'reports',  # Generated reports
            'exports': self.base_path / 'exports',  # Export formats
            'api': self.base_path / 'api',  # API response cache
        }

        # Create all directories
        for dir_path in self.dirs.values():
            dir_path.mkdir(parents=True, exist_ok=True)

        # Initialize SQLite database for structured queries
        self.db_path = self.base_path / 'insights.db'
        self._initialize_database()

        # Initialize master index
        self.master_index_path = self.base_path / 'master_index.json'
        self.master_index = self._load_or_create_master_index()

    def _initialize_database(self):
        """Create SQLite database with optimized schema for insights"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Main insights table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS insights (
                recording_id TEXT PRIMARY KEY,
                timestamp TIMESTAMP,
                call_date DATE,
                duration_seconds INTEGER,

                -- Quality metrics
                call_quality_score REAL,
                customer_satisfaction_score REAL,
                agent_performance_score REAL,
                first_call_resolution BOOLEAN,

                -- Sentiment analysis
                customer_sentiment TEXT,
                agent_sentiment TEXT,
                sentiment_trend TEXT,
                emotional_tone TEXT,

                -- Categories
                call_type TEXT,
                issue_category TEXT,
                resolution_status TEXT,
                escalation_required BOOLEAN,
                follow_up_needed BOOLEAN,

                -- Agent info
                agent_name TEXT,
                agent_id TEXT,
                department TEXT,

                -- Customer info
                customer_name TEXT,
                customer_id TEXT,
                customer_phone TEXT,
                company TEXT,

                -- Business metrics
                potential_revenue REAL,
                churn_risk_score REAL,
                upsell_opportunity BOOLEAN,

                -- Content
                summary TEXT,
                key_topics TEXT,
                action_items TEXT,
                coaching_notes TEXT,
                compliance_issues TEXT,

                -- Metadata
                processing_time REAL,
                model_version TEXT,
                confidence_score REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Quick wins table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS quick_wins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id TEXT,
                win_type TEXT,
                description TEXT,
                impact_score REAL,
                implementation_effort TEXT,
                priority INTEGER,
                status TEXT DEFAULT 'pending',
                FOREIGN KEY (recording_id) REFERENCES insights(recording_id)
            )
        ''')

        # Training needs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS training_needs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT,
                skill_area TEXT,
                current_level INTEGER,
                target_level INTEGER,
                training_type TEXT,
                resources TEXT,
                deadline DATE
            )
        ''')

        # Patterns table for trend analysis
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT,
                description TEXT,
                frequency INTEGER,
                first_seen DATE,
                last_seen DATE,
                affected_recordings TEXT,
                recommended_action TEXT
            )
        ''')

        # Create indexes for fast queries
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_call_date ON insights(call_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_agent ON insights(agent_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_customer ON insights(customer_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_quality ON insights(call_quality_score)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sentiment ON insights(customer_sentiment)')

        conn.commit()
        conn.close()

    def _load_or_create_master_index(self) -> Dict:
        """Load or create the master index for all insights"""
        if self.master_index_path.exists():
            with open(self.master_index_path, 'r') as f:
                return json.load(f)

        return {
            'version': '2.0',
            'created_at': datetime.now().isoformat(),
            'total_insights': 0,
            'recordings': {},
            'categories': defaultdict(list),
            'agents': defaultdict(list),
            'customers': defaultdict(list),
            'dates': defaultdict(list),
            'patterns': [],
            'statistics': {
                'avg_quality_score': 0,
                'avg_satisfaction': 0,
                'total_escalations': 0,
                'total_follow_ups': 0
            }
        }

    def store_insight(self, recording_id: str, insight_data: Dict[str, Any]) -> bool:
        """
        Store insight in multiple formats for optimal access

        Args:
            recording_id: Unique recording identifier
            insight_data: Complete insight data from AI analysis

        Returns:
            Success status
        """
        try:
            timestamp = datetime.now()

            # 1. Store raw JSON
            raw_path = self.dirs['raw'] / f"{recording_id}.json"
            with open(raw_path, 'w') as f:
                json.dump(insight_data, f, indent=2, default=str)

            # 2. Process and enhance the insight
            processed = self._process_insight(insight_data)

            # 3. Store in SQLite
            self._store_in_database(recording_id, processed)

            # 4. Create organized views
            self._create_date_view(recording_id, processed, timestamp)
            self._create_category_view(recording_id, processed)
            self._create_agent_view(recording_id, processed)
            self._create_customer_view(recording_id, processed)

            # 5. Generate human-readable markdown
            self._generate_markdown_report(recording_id, processed)

            # 6. Update master index
            self._update_master_index(recording_id, processed)

            # 7. Check for patterns and trends
            self._analyze_patterns(recording_id, processed)

            logger.info(f"✅ Stored insight for {recording_id} in all formats")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to store insight: {e}")
            return False

    def _process_insight(self, raw_insight: Dict) -> Dict:
        """Enhance raw insight with calculated metrics and categories"""
        processed = raw_insight.copy()

        # Extract key metrics
        if 'support_analysis' in raw_insight:
            support = raw_insight['support_analysis']
            processed['call_quality_score'] = support.get('call_quality_score', 0)
            processed['resolution_status'] = support.get('resolution', 'unknown')
            processed['escalation_required'] = support.get('escalation_needed', False)

        if 'sentiment_analysis' in raw_insight:
            sentiment = raw_insight['sentiment_analysis']
            processed['customer_sentiment'] = sentiment.get('customer', 'neutral')
            processed['sentiment_trend'] = sentiment.get('trend', 'stable')

        # Calculate composite scores
        processed['overall_score'] = self._calculate_overall_score(processed)
        processed['priority_level'] = self._determine_priority(processed)

        # Add metadata
        processed['processed_at'] = datetime.now().isoformat()
        processed['version'] = '2.0'

        return processed

    def _calculate_overall_score(self, data: Dict) -> float:
        """Calculate weighted overall score from multiple metrics"""
        weights = {
            'call_quality_score': 0.3,
            'customer_satisfaction_score': 0.3,
            'agent_performance_score': 0.2,
            'sentiment_score': 0.2
        }

        score = 0
        total_weight = 0

        for metric, weight in weights.items():
            if metric in data and data[metric] is not None:
                score += float(data[metric]) * weight
                total_weight += weight

        return score / total_weight if total_weight > 0 else 0

    def _determine_priority(self, data: Dict) -> str:
        """Determine priority level based on multiple factors"""
        if data.get('escalation_required'):
            return 'critical'
        elif data.get('customer_sentiment') == 'negative':
            return 'high'
        elif data.get('follow_up_needed'):
            return 'medium'
        else:
            return 'low'

    def _store_in_database(self, recording_id: str, data: Dict):
        """Store processed insight in SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Prepare data for insertion
        values = (
            recording_id,
            data.get('timestamp'),
            data.get('call_date'),
            data.get('duration_seconds'),
            data.get('call_quality_score'),
            data.get('customer_satisfaction_score'),
            data.get('agent_performance_score'),
            data.get('first_call_resolution'),
            data.get('customer_sentiment'),
            data.get('agent_sentiment'),
            data.get('sentiment_trend'),
            data.get('emotional_tone'),
            data.get('call_type'),
            data.get('issue_category'),
            data.get('resolution_status'),
            data.get('escalation_required'),
            data.get('follow_up_needed'),
            data.get('agent_name'),
            data.get('agent_id'),
            data.get('department'),
            data.get('customer_name'),
            data.get('customer_id'),
            data.get('customer_phone'),
            data.get('company'),
            data.get('potential_revenue'),
            data.get('churn_risk_score'),
            data.get('upsell_opportunity'),
            data.get('summary'),
            json.dumps(data.get('key_topics', [])),
            json.dumps(data.get('action_items', [])),
            data.get('coaching_notes'),
            data.get('compliance_issues'),
            data.get('processing_time'),
            data.get('model_version'),
            data.get('confidence_score')
        )

        cursor.execute('''
            INSERT OR REPLACE INTO insights VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        ''', values)

        # Store quick wins if present
        if 'quick_wins' in data:
            for win in data['quick_wins']:
                cursor.execute('''
                    INSERT INTO quick_wins (recording_id, win_type, description, impact_score, implementation_effort, priority)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (recording_id, win.get('type'), win.get('description'),
                     win.get('impact_score'), win.get('effort'), win.get('priority')))

        conn.commit()
        conn.close()

    def _create_date_view(self, recording_id: str, data: Dict, timestamp: datetime):
        """Create date-based organization"""
        date_str = timestamp.strftime('%Y/%m/%d')
        date_dir = self.dirs['by_date'] / date_str
        date_dir.mkdir(parents=True, exist_ok=True)

        # Create symlink to raw file
        link_path = date_dir / f"{recording_id}.json"
        if not link_path.exists():
            link_path.symlink_to(self.dirs['raw'] / f"{recording_id}.json")

        # Update daily summary
        summary_path = date_dir / 'daily_summary.json'
        self._update_daily_summary(summary_path, recording_id, data)

    def _create_category_view(self, recording_id: str, data: Dict):
        """Organize by category"""
        category = data.get('issue_category', 'uncategorized')
        category_dir = self.dirs['by_category'] / category
        category_dir.mkdir(parents=True, exist_ok=True)

        link_path = category_dir / f"{recording_id}.json"
        if not link_path.exists():
            link_path.symlink_to(self.dirs['raw'] / f"{recording_id}.json")

    def _create_agent_view(self, recording_id: str, data: Dict):
        """Organize by agent"""
        agent = data.get('agent_id', 'unknown')
        agent_dir = self.dirs['by_agent'] / agent
        agent_dir.mkdir(parents=True, exist_ok=True)

        link_path = agent_dir / f"{recording_id}.json"
        if not link_path.exists():
            link_path.symlink_to(self.dirs['raw'] / f"{recording_id}.json")

        # Update agent performance summary
        self._update_agent_summary(agent_dir, recording_id, data)

    def _create_customer_view(self, recording_id: str, data: Dict):
        """Organize by customer"""
        customer = data.get('customer_id', 'unknown')
        customer_dir = self.dirs['by_customer'] / customer
        customer_dir.mkdir(parents=True, exist_ok=True)

        link_path = customer_dir / f"{recording_id}.json"
        if not link_path.exists():
            link_path.symlink_to(self.dirs['raw'] / f"{recording_id}.json")

    def _generate_markdown_report(self, recording_id: str, data: Dict):
        """Generate human-readable markdown report"""
        report_path = self.dirs['reports'] / f"{recording_id}.md"

        markdown = f"""# Call Insights Report
## Recording ID: {recording_id}
**Date:** {data.get('call_date', 'N/A')}
**Duration:** {data.get('duration_seconds', 0)} seconds
**Priority:** {data.get('priority_level', 'N/A')}

---

## Executive Summary
{data.get('summary', 'No summary available')}

## Quality Metrics
- **Call Quality Score:** {data.get('call_quality_score', 'N/A')}/10
- **Customer Satisfaction:** {data.get('customer_satisfaction_score', 'N/A')}/10
- **Agent Performance:** {data.get('agent_performance_score', 'N/A')}/10
- **Overall Score:** {data.get('overall_score', 0):.2f}

## Sentiment Analysis
- **Customer Sentiment:** {data.get('customer_sentiment', 'N/A')}
- **Sentiment Trend:** {data.get('sentiment_trend', 'N/A')}
- **Emotional Tone:** {data.get('emotional_tone', 'N/A')}

## Key Topics
{self._format_list(data.get('key_topics', []))}

## Action Items
{self._format_list(data.get('action_items', []))}

## Quick Wins
{self._format_quick_wins(data.get('quick_wins', []))}

## Coaching Notes
{data.get('coaching_notes', 'No coaching notes available')}

## Follow-up Required
- **Escalation Needed:** {data.get('escalation_required', False)}
- **Follow-up Needed:** {data.get('follow_up_needed', False)}

---
*Generated: {datetime.now().isoformat()}*
"""

        with open(report_path, 'w') as f:
            f.write(markdown)

    def _format_list(self, items: List) -> str:
        """Format list for markdown"""
        if not items:
            return "- None"
        return '\n'.join([f"- {item}" for item in items])

    def _format_quick_wins(self, wins: List[Dict]) -> str:
        """Format quick wins for markdown"""
        if not wins:
            return "- None identified"

        formatted = []
        for win in wins:
            formatted.append(f"- **{win.get('type', 'General')}:** {win.get('description', 'N/A')}")
            formatted.append(f"  - Impact: {win.get('impact_score', 'N/A')}/10")
            formatted.append(f"  - Effort: {win.get('effort', 'N/A')}")

        return '\n'.join(formatted)

    def _update_master_index(self, recording_id: str, data: Dict):
        """Update the master index with new insight"""
        self.master_index['total_insights'] += 1
        self.master_index['recordings'][recording_id] = {
            'timestamp': datetime.now().isoformat(),
            'quality_score': data.get('call_quality_score'),
            'sentiment': data.get('customer_sentiment'),
            'priority': data.get('priority_level'),
            'category': data.get('issue_category')
        }

        # Update category index
        category = data.get('issue_category', 'uncategorized')
        self.master_index['categories'][category].append(recording_id)

        # Update agent index
        agent = data.get('agent_id')
        if agent:
            self.master_index['agents'][agent].append(recording_id)

        # Update customer index
        customer = data.get('customer_id')
        if customer:
            self.master_index['customers'][customer].append(recording_id)

        # Update date index
        date = data.get('call_date', datetime.now().strftime('%Y-%m-%d'))
        self.master_index['dates'][date].append(recording_id)

        # Save updated index
        with open(self.master_index_path, 'w') as f:
            json.dump(self.master_index, f, indent=2, default=str)

    def _update_daily_summary(self, summary_path: Path, recording_id: str, data: Dict):
        """Update daily summary file"""
        if summary_path.exists():
            with open(summary_path, 'r') as f:
                summary = json.load(f)
        else:
            summary = {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'total_calls': 0,
                'recordings': [],
                'avg_quality': 0,
                'escalations': 0,
                'follow_ups': 0
            }

        summary['total_calls'] += 1
        summary['recordings'].append(recording_id)

        if data.get('escalation_required'):
            summary['escalations'] += 1
        if data.get('follow_up_needed'):
            summary['follow_ups'] += 1

        # Recalculate average quality
        if data.get('call_quality_score'):
            current_sum = summary['avg_quality'] * (summary['total_calls'] - 1)
            summary['avg_quality'] = (current_sum + data['call_quality_score']) / summary['total_calls']

        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)

    def _update_agent_summary(self, agent_dir: Path, recording_id: str, data: Dict):
        """Update agent performance summary"""
        summary_path = agent_dir / 'performance_summary.json'

        if summary_path.exists():
            with open(summary_path, 'r') as f:
                summary = json.load(f)
        else:
            summary = {
                'agent_id': data.get('agent_id'),
                'agent_name': data.get('agent_name'),
                'total_calls': 0,
                'avg_quality': 0,
                'avg_satisfaction': 0,
                'recordings': []
            }

        summary['total_calls'] += 1
        summary['recordings'].append(recording_id)

        # Update averages
        for metric in ['quality', 'satisfaction']:
            value = data.get(f'call_{metric}_score')
            if value:
                current_sum = summary[f'avg_{metric}'] * (summary['total_calls'] - 1)
                summary[f'avg_{metric}'] = (current_sum + value) / summary['total_calls']

        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)

    def _analyze_patterns(self, recording_id: str, data: Dict):
        """Analyze for patterns and trends"""
        # This would typically involve more sophisticated pattern detection
        # For now, we'll track basic patterns

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check for recurring issues
        if data.get('issue_category'):
            cursor.execute('''
                SELECT COUNT(*) FROM insights
                WHERE issue_category = ? AND call_date >= date('now', '-7 days')
            ''', (data['issue_category'],))

            count = cursor.fetchone()[0]
            if count >= 5:  # Threshold for pattern detection
                cursor.execute('''
                    INSERT OR REPLACE INTO patterns (pattern_type, description, frequency, last_seen)
                    VALUES ('recurring_issue', ?, ?, date('now'))
                ''', (f"Frequent {data['issue_category']} issues", count))

        conn.commit()
        conn.close()

    def query_insights(self,
                       start_date: Optional[str] = None,
                       end_date: Optional[str] = None,
                       agent_id: Optional[str] = None,
                       agent_name: Optional[str] = None,  # NEW: Search by agent name
                       customer_id: Optional[str] = None,
                       customer_name: Optional[str] = None,  # NEW: Search by customer name
                       customer_phone: Optional[str] = None,  # NEW: Search by phone
                       search_term: Optional[str] = None,  # NEW: Open text search
                       min_quality_score: Optional[float] = None,
                       sentiment: Optional[str] = None,
                       category: Optional[str] = None,
                       sort_by: Optional[str] = None,  # NEW: Sorting option
                       sort_order: str = 'DESC',  # NEW: ASC or DESC
                       limit: int = 100) -> List[Dict]:
        """
        Query insights with flexible filters and enhanced search

        Args:
            start_date: Filter by start date
            end_date: Filter by end date
            agent_id: Filter by agent ID
            agent_name: Filter by agent name (partial match)
            customer_id: Filter by customer ID
            customer_name: Filter by customer name (partial match)
            customer_phone: Filter by phone number
            search_term: Open text search in summary and key topics
            min_quality_score: Filter by minimum quality score
            sentiment: Filter by sentiment
            category: Filter by category
            sort_by: Sort by field (date, quality, sentiment, agent, customer)
            sort_order: ASC or DESC
            limit: Maximum number of results

        Returns:
            List of matching insights
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM insights WHERE 1=1"
        params = []

        if start_date:
            query += " AND call_date >= ?"
            params.append(start_date)

        if end_date:
            query += " AND call_date <= ?"
            params.append(end_date)

        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)

        # NEW: Agent name search (partial match)
        if agent_name:
            query += " AND agent_name LIKE ?"
            params.append(f"%{agent_name}%")

        if customer_id:
            query += " AND customer_id = ?"
            params.append(customer_id)

        # NEW: Customer name search (partial match)
        if customer_name:
            query += " AND customer_name LIKE ?"
            params.append(f"%{customer_name}%")

        # NEW: Phone number search
        if customer_phone:
            # Remove non-digit characters for flexible matching
            phone_digits = ''.join(filter(str.isdigit, customer_phone))
            query += " AND REPLACE(REPLACE(REPLACE(customer_phone, '-', ''), '(', ''), ')', '') LIKE ?"
            params.append(f"%{phone_digits}%")

        # NEW: Open text search in summary and key topics
        if search_term:
            query += " AND (summary LIKE ? OR key_topics LIKE ? OR action_items LIKE ?)"
            params.append(f"%{search_term}%")
            params.append(f"%{search_term}%")
            params.append(f"%{search_term}%")

        if min_quality_score:
            query += " AND call_quality_score >= ?"
            params.append(min_quality_score)

        if sentiment:
            query += " AND customer_sentiment = ?"
            params.append(sentiment)

        if category:
            query += " AND issue_category = ?"
            params.append(category)

        # NEW: Flexible sorting
        sort_column = "created_at"  # default
        if sort_by:
            sort_map = {
                'date': 'call_date',
                'quality': 'call_quality_score',
                'satisfaction': 'customer_satisfaction_score',
                'sentiment': 'customer_sentiment',
                'agent': 'agent_name',
                'customer': 'customer_name',
                'duration': 'duration_seconds'
            }
            sort_column = sort_map.get(sort_by, 'created_at')

        # Validate sort order
        if sort_order.upper() not in ['ASC', 'DESC']:
            sort_order = 'DESC'

        query += f" ORDER BY {sort_column} {sort_order.upper()} LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        results = [dict(row) for row in cursor.fetchall()]

        conn.close()
        return results

    def analyze_date_range(self,
                           entity_type: str,
                           entity_value: str,
                           start_date: str,
                           end_date: str,
                           analysis_type: str = 'comprehensive') -> Dict:
        """
        Analyze all calls for a specific customer or employee within a date range

        Args:
            entity_type: 'customer' or 'employee'
            entity_value: Customer name/phone or Employee name/id
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            analysis_type: Type of analysis ('comprehensive', 'sentiment', 'quality', 'patterns')

        Returns:
            Comprehensive analysis across all calls in the range
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Build query based on entity type
        if entity_type == 'customer':
            # Search by customer name or phone
            if entity_value.replace('-', '').replace('(', '').replace(')', '').isdigit():
                # Phone number search
                phone_digits = ''.join(filter(str.isdigit, entity_value))
                query = """
                    SELECT * FROM insights
                    WHERE REPLACE(REPLACE(REPLACE(customer_phone, '-', ''), '(', ''), ')', '') LIKE ?
                    AND call_date BETWEEN ? AND ?
                    ORDER BY call_date ASC
                """
                params = [f"%{phone_digits}%", start_date, end_date]
            else:
                # Customer name search
                query = """
                    SELECT * FROM insights
                    WHERE customer_name LIKE ?
                    AND call_date BETWEEN ? AND ?
                    ORDER BY call_date ASC
                """
                params = [f"%{entity_value}%", start_date, end_date]

        elif entity_type == 'employee':
            # Search by employee name or ID
            query = """
                SELECT * FROM insights
                WHERE (agent_name LIKE ? OR agent_id = ?)
                AND call_date BETWEEN ? AND ?
                ORDER BY call_date ASC
            """
            params = [f"%{entity_value}%", entity_value, start_date, end_date]

        else:
            conn.close()
            return {"error": "Invalid entity type. Use 'customer' or 'employee'"}

        cursor.execute(query, params)
        insights = [dict(row) for row in cursor.fetchall()]

        if not insights:
            conn.close()
            return {
                "entity_type": entity_type,
                "entity_value": entity_value,
                "date_range": f"{start_date} to {end_date}",
                "total_calls": 0,
                "message": "No calls found for this entity in the specified date range"
            }

        # Perform comprehensive analysis
        analysis = {
            "entity_type": entity_type,
            "entity_value": entity_value,
            "date_range": f"{start_date} to {end_date}",
            "total_calls": len(insights),
            "timeline": [],
            "metrics": {},
            "patterns": {},
            "recommendations": []
        }

        # Calculate aggregate metrics
        total_duration = sum(i.get('duration_seconds', 0) for i in insights)
        avg_quality = sum(i.get('call_quality_score', 0) for i in insights) / len(insights) if insights else 0
        avg_satisfaction = sum(i.get('customer_satisfaction_score', 0) for i in insights) / len(insights) if insights else 0

        # Sentiment analysis over time
        sentiment_counts = {'positive': 0, 'neutral': 0, 'negative': 0}
        for insight in insights:
            sentiment = insight.get('customer_sentiment', 'neutral')
            sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1

        # Issue categories
        issue_categories = {}
        for insight in insights:
            category = insight.get('issue_category', 'other')
            issue_categories[category] = issue_categories.get(category, 0) + 1

        # Build timeline
        for insight in insights:
            analysis['timeline'].append({
                'date': insight.get('call_date'),
                'recording_id': insight.get('recording_id'),
                'summary': insight.get('summary'),
                'sentiment': insight.get('customer_sentiment'),
                'quality_score': insight.get('call_quality_score'),
                'duration': insight.get('duration_seconds')
            })

        # Aggregate metrics
        analysis['metrics'] = {
            'average_quality_score': round(avg_quality, 2),
            'average_satisfaction_score': round(avg_satisfaction, 2),
            'total_duration_minutes': round(total_duration / 60, 2),
            'average_call_duration_minutes': round(total_duration / 60 / len(insights), 2) if insights else 0,
            'sentiment_distribution': sentiment_counts,
            'sentiment_trend': self._calculate_sentiment_trend(insights),
            'issue_categories': issue_categories,
            'escalation_rate': sum(1 for i in insights if i.get('escalation_required')) / len(insights) * 100,
            'resolution_rate': sum(1 for i in insights if i.get('first_call_resolution')) / len(insights) * 100
        }

        # Identify patterns
        analysis['patterns'] = {
            'most_common_issues': sorted(issue_categories.items(), key=lambda x: x[1], reverse=True)[:3],
            'peak_call_days': self._identify_peak_days(insights),
            'recurring_topics': self._extract_recurring_topics(insights),
            'quality_trend': self._calculate_quality_trend(insights)
        }

        # Generate recommendations based on analysis
        analysis['recommendations'] = self._generate_recommendations(analysis)

        conn.close()
        return analysis

    def _calculate_sentiment_trend(self, insights: List[Dict]) -> str:
        """Calculate sentiment trend over time"""
        if len(insights) < 2:
            return "insufficient_data"

        # Compare first half to second half
        mid = len(insights) // 2
        first_half = insights[:mid]
        second_half = insights[mid:]

        sentiment_scores = {'positive': 1, 'neutral': 0, 'negative': -1}

        first_avg = sum(sentiment_scores.get(i.get('customer_sentiment', 'neutral'), 0)
                       for i in first_half) / len(first_half)
        second_avg = sum(sentiment_scores.get(i.get('customer_sentiment', 'neutral'), 0)
                        for i in second_half) / len(second_half)

        if second_avg > first_avg + 0.2:
            return "improving"
        elif second_avg < first_avg - 0.2:
            return "declining"
        else:
            return "stable"

    def _calculate_quality_trend(self, insights: List[Dict]) -> str:
        """Calculate quality score trend over time"""
        if len(insights) < 2:
            return "insufficient_data"

        mid = len(insights) // 2
        first_half = insights[:mid]
        second_half = insights[mid:]

        first_avg = sum(i.get('call_quality_score', 0) for i in first_half) / len(first_half)
        second_avg = sum(i.get('call_quality_score', 0) for i in second_half) / len(second_half)

        if second_avg > first_avg + 0.5:
            return "improving"
        elif second_avg < first_avg - 0.5:
            return "declining"
        else:
            return "stable"

    def _identify_peak_days(self, insights: List[Dict]) -> List[str]:
        """Identify days with most calls"""
        day_counts = {}
        for insight in insights:
            date = insight.get('call_date', '')
            day_counts[date] = day_counts.get(date, 0) + 1

        sorted_days = sorted(day_counts.items(), key=lambda x: x[1], reverse=True)
        return [day for day, count in sorted_days[:3] if count > 1]

    def _extract_recurring_topics(self, insights: List[Dict]) -> List[str]:
        """Extract recurring topics from summaries and key topics"""
        topic_counts = {}
        for insight in insights:
            topics = insight.get('key_topics', '').split(',') if insight.get('key_topics') else []
            for topic in topics:
                topic = topic.strip()
                if topic:
                    topic_counts[topic] = topic_counts.get(topic, 0) + 1

        sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
        return [topic for topic, count in sorted_topics[:5] if count > 1]

    def _generate_recommendations(self, analysis: Dict) -> List[str]:
        """Generate actionable recommendations based on analysis"""
        recommendations = []

        # Sentiment-based recommendations
        sentiment_dist = analysis['metrics']['sentiment_distribution']
        if sentiment_dist.get('negative', 0) > sentiment_dist.get('positive', 0):
            recommendations.append("High negative sentiment detected. Consider proactive outreach or service improvement.")

        # Quality-based recommendations
        if analysis['metrics']['average_quality_score'] < 6:
            recommendations.append("Low average quality score. Review call handling procedures and provide additional training.")

        # Escalation rate recommendations
        if analysis['metrics']['escalation_rate'] > 20:
            recommendations.append("High escalation rate. Empower front-line agents to resolve more issues independently.")

        # Resolution rate recommendations
        if analysis['metrics']['resolution_rate'] < 70:
            recommendations.append("Low first-call resolution rate. Improve knowledge base and agent training.")

        # Trend-based recommendations
        if analysis['metrics']['sentiment_trend'] == "declining":
            recommendations.append("Sentiment trend is declining. Investigate recent changes and address customer concerns.")

        if analysis['patterns']['quality_trend'] == "declining":
            recommendations.append("Call quality is declining. Schedule refresher training and review recent process changes.")

        # Pattern-based recommendations
        if analysis['patterns']['most_common_issues']:
            top_issue = analysis['patterns']['most_common_issues'][0][0]
            recommendations.append(f"Most common issue: {top_issue}. Create targeted solutions or FAQ for this issue.")

        if not recommendations:
            recommendations.append("Performance is stable. Continue current practices and monitor for changes.")

        return recommendations

    def generate_analytics_report(self, period: str = 'daily') -> Dict:
        """
        Generate analytics report for specified period

        Args:
            period: 'daily', 'weekly', or 'monthly'

        Returns:
            Analytics report dictionary
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Determine date range
        if period == 'daily':
            date_filter = "date('now')"
        elif period == 'weekly':
            date_filter = "date('now', '-7 days')"
        else:  # monthly
            date_filter = "date('now', '-30 days')"

        # Get summary statistics
        cursor.execute(f'''
            SELECT
                COUNT(*) as total_calls,
                AVG(call_quality_score) as avg_quality,
                AVG(customer_satisfaction_score) as avg_satisfaction,
                SUM(escalation_required) as total_escalations,
                SUM(follow_up_needed) as total_follow_ups
            FROM insights
            WHERE call_date >= {date_filter}
        ''')

        row = cursor.fetchone()
        if row:
            stats = {
                'total_calls': row[0] or 0,
                'avg_quality': row[1] or 0,
                'avg_satisfaction': row[2] or 0,
                'total_escalations': row[3] or 0,
                'total_follow_ups': row[4] or 0
            }
        else:
            stats = {
                'total_calls': 0,
                'avg_quality': 0,
                'avg_satisfaction': 0,
                'total_escalations': 0,
                'total_follow_ups': 0
            }

        # Get sentiment breakdown
        cursor.execute(f'''
            SELECT customer_sentiment, COUNT(*) as count
            FROM insights
            WHERE call_date >= {date_filter}
            GROUP BY customer_sentiment
        ''')

        sentiment_breakdown = {row[0]: row[1] for row in cursor.fetchall()}

        # Get top issues
        cursor.execute(f'''
            SELECT issue_category, COUNT(*) as count
            FROM insights
            WHERE call_date >= {date_filter}
            GROUP BY issue_category
            ORDER BY count DESC
            LIMIT 5
        ''')

        top_issues = [{'category': row[0], 'count': row[1]} for row in cursor.fetchall()]

        # Get agent leaderboard
        cursor.execute(f'''
            SELECT agent_name, agent_id,
                   AVG(agent_performance_score) as avg_score,
                   COUNT(*) as total_calls
            FROM insights
            WHERE call_date >= {date_filter} AND agent_id IS NOT NULL
            GROUP BY agent_id
            ORDER BY avg_score DESC
            LIMIT 10
        ''')

        leaderboard = [dict(row) for row in cursor.fetchall()]

        conn.close()

        report = {
            'period': period,
            'generated_at': datetime.now().isoformat(),
            'statistics': stats,
            'sentiment_breakdown': sentiment_breakdown,
            'top_issues': top_issues,
            'agent_leaderboard': leaderboard
        }

        # Save report
        report_path = self.dirs['reports'] / f"{period}_report_{datetime.now().strftime('%Y%m%d')}.json"
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)

        return report

    def export_for_llm(self, format: str = 'jsonl') -> Path:
        """
        Export insights in LLM-friendly format

        Args:
            format: 'jsonl' for training, 'context' for RAG

        Returns:
            Path to exported file
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        if format == 'jsonl':
            # Export for fine-tuning
            export_path = self.dirs['exports'] / f"insights_training_{timestamp}.jsonl"

            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM insights ORDER BY created_at DESC')

            with open(export_path, 'w') as f:
                for row in cursor:
                    record = dict(row)
                    # Format for training
                    training_record = {
                        'prompt': f"Analyze this call: Duration {record['duration_seconds']}s, Category: {record['issue_category']}",
                        'completion': {
                            'quality_score': record['call_quality_score'],
                            'sentiment': record['customer_sentiment'],
                            'summary': record['summary'],
                            'action_items': json.loads(record['action_items'] or '[]')
                        }
                    }
                    f.write(json.dumps(training_record) + '\n')

            conn.close()

        else:  # context format for RAG
            export_path = self.dirs['exports'] / f"insights_context_{timestamp}.json"

            # Create structured context for LLM consumption
            context = {
                'version': '2.0',
                'generated_at': datetime.now().isoformat(),
                'total_insights': self.master_index['total_insights'],
                'categories': dict(self.master_index['categories']),
                'recent_insights': self.query_insights(limit=100),
                'patterns': self._get_patterns(),
                'statistics': self.generate_analytics_report('weekly')
            }

            with open(export_path, 'w') as f:
                json.dump(context, f, indent=2, default=str)

        logger.info(f"📤 Exported insights to {export_path}")
        return export_path

    def _get_patterns(self) -> List[Dict]:
        """Get detected patterns"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM patterns ORDER BY frequency DESC LIMIT 20')
        patterns = [dict(row) for row in cursor.fetchall()]

        conn.close()
        return patterns

    def get_api_response(self, endpoint: str, params: Dict = None) -> Dict:
        """
        Generate API-ready response for various endpoints

        Args:
            endpoint: API endpoint name
            params: Query parameters

        Returns:
            API response dictionary
        """
        params = params or {}

        if endpoint == 'insights/list':
            return {
                'status': 'success',
                'data': self.query_insights(**params),
                'count': len(self.query_insights(**params))
            }

        elif endpoint == 'insights/summary':
            return {
                'status': 'success',
                'data': self.generate_analytics_report(params.get('period', 'daily'))
            }

        elif endpoint == 'insights/agent':
            agent_id = params.get('agent_id')
            if not agent_id:
                return {'status': 'error', 'message': 'agent_id required'}

            insights = self.query_insights(agent_id=agent_id, limit=params.get('limit', 50))
            return {
                'status': 'success',
                'agent_id': agent_id,
                'total_calls': len(insights),
                'insights': insights
            }

        elif endpoint == 'insights/patterns':
            return {
                'status': 'success',
                'patterns': self._get_patterns()
            }

        else:
            return {
                'status': 'error',
                'message': f'Unknown endpoint: {endpoint}'
            }


# Singleton instance
insights_manager = None

def get_insights_manager() -> InsightsManager:
    """Get or create the insights manager instance"""
    global insights_manager
    if insights_manager is None:
        insights_manager = InsightsManager()
    return insights_manager