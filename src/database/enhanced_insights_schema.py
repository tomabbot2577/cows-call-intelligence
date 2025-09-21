#!/usr/bin/env python3
"""
Enhanced Database Schema for Customer/Phone/Person Tracking
Comprehensive data model for call insights with relationship mapping
"""

import sqlite3
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class EnhancedInsightsDatabase:
    """
    Enhanced database for comprehensive call insights with customer tracking
    Supports lookup by customer, phone number, person, and company
    """

    def __init__(self, db_path: str = None):
        """Initialize enhanced insights database"""
        self.db_path = db_path or "/var/www/call-recording-system/data/insights/enhanced_insights.db"
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_database()

    def init_database(self):
        """Create enhanced database schema"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Core insights table (enhanced)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS call_insights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id TEXT UNIQUE NOT NULL,
                    call_date TEXT NOT NULL,
                    call_time TEXT,
                    duration_seconds REAL,

                    -- Call classification
                    call_type TEXT,
                    call_purpose TEXT,
                    urgency_level TEXT,
                    outcome_status TEXT,

                    -- Contact information
                    primary_customer_name TEXT,
                    primary_customer_role TEXT,
                    primary_customer_company TEXT,
                    primary_phone_number TEXT,
                    primary_email TEXT,

                    -- Agent information
                    agent_name TEXT,
                    agent_id TEXT,
                    agent_department TEXT,

                    -- Scores and metrics
                    customer_satisfaction_score INTEGER,
                    call_quality_score REAL,
                    resolution_time_hours REAL,
                    sales_opportunity_score INTEGER,
                    relationship_health_score INTEGER,
                    churn_risk_score INTEGER,

                    -- Flags
                    escalation_required BOOLEAN DEFAULT FALSE,
                    follow_up_needed BOOLEAN DEFAULT FALSE,
                    technical_issue BOOLEAN DEFAULT FALSE,
                    billing_issue BOOLEAN DEFAULT FALSE,
                    sales_opportunity BOOLEAN DEFAULT FALSE,

                    -- Analysis results
                    raw_insights TEXT,  -- JSON of full analysis
                    summary TEXT,
                    key_topics TEXT,    -- JSON array of topics
                    action_items TEXT,  -- JSON array of actions

                    -- Timestamps
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Companies/Organizations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS companies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT UNIQUE NOT NULL,
                    company_domain TEXT,
                    industry TEXT,
                    company_size TEXT,
                    account_status TEXT,
                    primary_contact_id INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (primary_contact_id) REFERENCES contacts (id)
                )
            """)

            # Contacts/People table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    first_name TEXT,
                    last_name TEXT,
                    title TEXT,
                    role TEXT,
                    company_id INTEGER,
                    primary_phone TEXT,
                    primary_email TEXT,
                    decision_maker BOOLEAN DEFAULT FALSE,
                    influencer BOOLEAN DEFAULT FALSE,
                    contact_status TEXT DEFAULT 'active',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (company_id) REFERENCES companies (id)
                )
            """)

            # Phone numbers table (for tracking multiple numbers per contact)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS phone_numbers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone_number TEXT NOT NULL,
                    formatted_number TEXT,
                    contact_id INTEGER,
                    company_id INTEGER,
                    phone_type TEXT,  -- mobile, office, direct, main
                    is_primary BOOLEAN DEFAULT FALSE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (contact_id) REFERENCES contacts (id),
                    FOREIGN KEY (company_id) REFERENCES companies (id)
                )
            """)

            # Email addresses table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS email_addresses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email_address TEXT NOT NULL,
                    contact_id INTEGER,
                    company_id INTEGER,
                    email_type TEXT,  -- work, personal, billing
                    is_primary BOOLEAN DEFAULT FALSE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (contact_id) REFERENCES contacts (id),
                    FOREIGN KEY (company_id) REFERENCES companies (id)
                )
            """)

            # Call participants table (many-to-many)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS call_participants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id TEXT NOT NULL,
                    contact_id INTEGER,
                    participant_role TEXT,  -- primary, secondary, mentioned
                    participation_type TEXT,  -- speaker, listener, mentioned
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (contact_id) REFERENCES contacts (id),
                    FOREIGN KEY (recording_id) REFERENCES call_insights (recording_id)
                )
            """)

            # Topics and categories
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS call_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id TEXT NOT NULL,
                    topic_category TEXT,  -- billing, technical, sales, support
                    topic_name TEXT,
                    topic_sentiment TEXT,  -- positive, neutral, negative
                    confidence_score REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (recording_id) REFERENCES call_insights (recording_id)
                )
            """)

            # Action items table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS action_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id TEXT NOT NULL,
                    action_type TEXT,  -- follow_up, technical, billing, sales
                    action_description TEXT,
                    assigned_to TEXT,
                    priority TEXT,
                    due_date TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    FOREIGN KEY (recording_id) REFERENCES call_insights (recording_id)
                )
            """)

            # Customer journey tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS customer_journey (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contact_id INTEGER,
                    company_id INTEGER,
                    journey_stage TEXT,  -- prospect, trial, customer, at_risk, churned
                    stage_date TEXT,
                    previous_stage TEXT,
                    trigger_event TEXT,
                    confidence_score REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (contact_id) REFERENCES contacts (id),
                    FOREIGN KEY (company_id) REFERENCES companies (id)
                )
            """)

            # Support tickets correlation
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS support_tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id TEXT UNIQUE,
                    recording_id TEXT,
                    contact_id INTEGER,
                    company_id INTEGER,
                    issue_category TEXT,
                    issue_severity TEXT,
                    ticket_status TEXT,
                    resolution_time_hours REAL,
                    satisfaction_rating INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TEXT,
                    FOREIGN KEY (recording_id) REFERENCES call_insights (recording_id),
                    FOREIGN KEY (contact_id) REFERENCES contacts (id),
                    FOREIGN KEY (company_id) REFERENCES companies (id)
                )
            """)

            # Create comprehensive indexes
            self._create_indexes(cursor)

            conn.commit()
            logger.info("Enhanced insights database schema created successfully")

    def _create_indexes(self, cursor):
        """Create performance indexes"""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_call_insights_recording_id ON call_insights(recording_id)",
            "CREATE INDEX IF NOT EXISTS idx_call_insights_call_date ON call_insights(call_date)",
            "CREATE INDEX IF NOT EXISTS idx_call_insights_customer_name ON call_insights(primary_customer_name)",
            "CREATE INDEX IF NOT EXISTS idx_call_insights_company ON call_insights(primary_customer_company)",
            "CREATE INDEX IF NOT EXISTS idx_call_insights_phone ON call_insights(primary_phone_number)",
            "CREATE INDEX IF NOT EXISTS idx_call_insights_email ON call_insights(primary_email)",
            "CREATE INDEX IF NOT EXISTS idx_call_insights_call_type ON call_insights(call_type)",
            "CREATE INDEX IF NOT EXISTS idx_call_insights_urgency ON call_insights(urgency_level)",

            "CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(full_name)",
            "CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company_id)",
            "CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(primary_phone)",
            "CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(primary_email)",

            "CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(company_name)",
            "CREATE INDEX IF NOT EXISTS idx_companies_domain ON companies(company_domain)",

            "CREATE INDEX IF NOT EXISTS idx_phone_numbers_number ON phone_numbers(phone_number)",
            "CREATE INDEX IF NOT EXISTS idx_phone_numbers_contact ON phone_numbers(contact_id)",

            "CREATE INDEX IF NOT EXISTS idx_email_addresses_email ON email_addresses(email_address)",
            "CREATE INDEX IF NOT EXISTS idx_email_addresses_contact ON email_addresses(contact_id)",

            "CREATE INDEX IF NOT EXISTS idx_call_participants_recording ON call_participants(recording_id)",
            "CREATE INDEX IF NOT EXISTS idx_call_participants_contact ON call_participants(contact_id)",

            "CREATE INDEX IF NOT EXISTS idx_call_topics_recording ON call_topics(recording_id)",
            "CREATE INDEX IF NOT EXISTS idx_call_topics_category ON call_topics(topic_category)",

            "CREATE INDEX IF NOT EXISTS idx_action_items_recording ON action_items(recording_id)",
            "CREATE INDEX IF NOT EXISTS idx_action_items_status ON action_items(status)",
            "CREATE INDEX IF NOT EXISTS idx_action_items_due_date ON action_items(due_date)",
        ]

        for index_sql in indexes:
            cursor.execute(index_sql)

    def store_comprehensive_insights(self, insights: Dict[str, Any]) -> bool:
        """Store comprehensive insights with relationship mapping"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Extract core data
                recording_id = insights.get("recording_id")
                contact_info = insights.get("contact_information", {})
                classification = insights.get("call_classification", {})
                metrics = insights.get("key_metrics", {})

                # Get or create company
                company_id = self._get_or_create_company(
                    cursor, contact_info.get("participants", [])
                )

                # Get or create primary contact
                primary_contact_id = self._get_or_create_contact(
                    cursor, contact_info.get("participants", []), company_id
                )

                # Store main insights record
                cursor.execute("""
                    INSERT OR REPLACE INTO call_insights (
                        recording_id, call_date, call_time, duration_seconds,
                        call_type, call_purpose, urgency_level, outcome_status,
                        primary_customer_name, primary_customer_role, primary_customer_company,
                        primary_phone_number, primary_email,
                        customer_satisfaction_score, call_quality_score,
                        sales_opportunity_score, relationship_health_score, churn_risk_score,
                        escalation_required, follow_up_needed,
                        raw_insights, summary, key_topics, action_items,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    recording_id,
                    contact_info.get("recording_metadata", {}).get("call_date"),
                    None,  # call_time - can be extracted later
                    contact_info.get("recording_metadata", {}).get("call_duration"),
                    classification.get("call_type"),
                    ", ".join(classification.get("call_purpose", [])),
                    classification.get("urgency_level"),
                    classification.get("outcome_status"),
                    self._extract_primary_customer_name(contact_info),
                    self._extract_primary_customer_role(contact_info),
                    self._extract_primary_company(contact_info),
                    self._extract_primary_phone(contact_info),
                    self._extract_primary_email(contact_info),
                    metrics.get("customer_satisfaction_score"),
                    metrics.get("call_quality_score"),
                    metrics.get("sales_opportunity_score"),
                    metrics.get("relationship_health_score"),
                    metrics.get("churn_risk_score"),
                    metrics.get("escalation_risk") == "high",
                    "follow_up" in classification.get("outcome_status", ""),
                    json.dumps(insights),
                    insights.get("summary", ""),
                    json.dumps(self._extract_topics(insights)),
                    json.dumps(insights.get("action_items", [])),
                    datetime.now().isoformat()
                ))

                # Store phone numbers
                self._store_phone_numbers(cursor, recording_id, contact_info, primary_contact_id, company_id)

                # Store email addresses
                self._store_email_addresses(cursor, recording_id, contact_info, primary_contact_id, company_id)

                # Store call participants
                self._store_call_participants(cursor, recording_id, contact_info)

                # Store action items
                self._store_action_items(cursor, recording_id, insights.get("action_items", []))

                conn.commit()
                logger.info(f"✅ Stored comprehensive insights for {recording_id}")
                return True

        except Exception as e:
            logger.error(f"Failed to store comprehensive insights: {e}")
            return False

    def search_by_customer(self, search_term: str, limit: int = 50) -> List[Dict]:
        """Search insights by customer name, company, or role"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM call_insights
                WHERE primary_customer_name LIKE ?
                   OR primary_customer_company LIKE ?
                   OR primary_customer_role LIKE ?
                ORDER BY call_date DESC
                LIMIT ?
            """, (f"%{search_term}%", f"%{search_term}%", f"%{search_term}%", limit))

            return [dict(row) for row in cursor.fetchall()]

    def search_by_phone_number(self, phone_number: str) -> List[Dict]:
        """Search insights by phone number"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Clean phone number for search
            clean_phone = re.sub(r'[^\d]', '', phone_number)

            cursor.execute("""
                SELECT ci.* FROM call_insights ci
                LEFT JOIN phone_numbers pn ON pn.phone_number LIKE ?
                LEFT JOIN call_participants cp ON cp.recording_id = ci.recording_id
                LEFT JOIN contacts c ON c.id = cp.contact_id
                WHERE ci.primary_phone_number LIKE ?
                   OR pn.phone_number LIKE ?
                   OR c.primary_phone LIKE ?
                ORDER BY ci.call_date DESC
            """, (f"%{clean_phone}%", f"%{phone_number}%", f"%{clean_phone}%", f"%{phone_number}%"))

            return [dict(row) for row in cursor.fetchall()]

    def search_by_email(self, email: str) -> List[Dict]:
        """Search insights by email address"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT ci.* FROM call_insights ci
                LEFT JOIN email_addresses ea ON ea.email_address LIKE ?
                LEFT JOIN call_participants cp ON cp.recording_id = ci.recording_id
                LEFT JOIN contacts c ON c.id = cp.contact_id
                WHERE ci.primary_email LIKE ?
                   OR ea.email_address LIKE ?
                   OR c.primary_email LIKE ?
                ORDER BY ci.call_date DESC
            """, (f"%{email}%", f"%{email}%", f"%{email}%", f"%{email}%"))

            return [dict(row) for row in cursor.fetchall()]

    def get_customer_journey(self, customer_identifier: str) -> List[Dict]:
        """Get complete customer journey by name, phone, or email"""
        results = []

        # Search by different identifiers
        results.extend(self.search_by_customer(customer_identifier))
        results.extend(self.search_by_phone_number(customer_identifier))
        results.extend(self.search_by_email(customer_identifier))

        # Deduplicate by recording_id
        seen = set()
        unique_results = []
        for result in results:
            if result['recording_id'] not in seen:
                seen.add(result['recording_id'])
                unique_results.append(result)

        # Sort by date
        unique_results.sort(key=lambda x: x['call_date'], reverse=True)
        return unique_results

    def get_analytics_by_customer(self, customer_identifier: str) -> Dict[str, Any]:
        """Get comprehensive analytics for a specific customer"""
        journey = self.get_customer_journey(customer_identifier)

        if not journey:
            return {}

        # Calculate analytics
        total_calls = len(journey)
        avg_satisfaction = sum(r.get('customer_satisfaction_score', 0) for r in journey if r.get('customer_satisfaction_score')) / max(1, len([r for r in journey if r.get('customer_satisfaction_score')]))
        escalations = sum(1 for r in journey if r.get('escalation_required'))
        follow_ups = sum(1 for r in journey if r.get('follow_up_needed'))

        call_types = {}
        for call in journey:
            call_type = call.get('call_type', 'unknown')
            call_types[call_type] = call_types.get(call_type, 0) + 1

        return {
            "customer_identifier": customer_identifier,
            "total_calls": total_calls,
            "average_satisfaction": round(avg_satisfaction, 2),
            "total_escalations": escalations,
            "total_follow_ups": follow_ups,
            "call_types_breakdown": call_types,
            "first_call_date": journey[-1].get('call_date') if journey else None,
            "last_call_date": journey[0].get('call_date') if journey else None,
            "recent_calls": journey[:5]  # Last 5 calls
        }

    # Helper methods for data extraction and storage
    def _get_or_create_company(self, cursor, participants: List[Dict]) -> Optional[int]:
        """Get or create company record"""
        # Implementation for company management
        return None  # Placeholder

    def _get_or_create_contact(self, cursor, participants: List[Dict], company_id: int) -> Optional[int]:
        """Get or create contact record"""
        # Implementation for contact management
        return None  # Placeholder

    def _extract_primary_customer_name(self, contact_info: Dict) -> str:
        """Extract primary customer name from contact info"""
        participants = contact_info.get("participants", [])
        for p in participants:
            if p.get("role") == "customer":
                return p.get("name", "")
        return ""

    def _extract_primary_customer_role(self, contact_info: Dict) -> str:
        """Extract primary customer role"""
        # Implementation
        return ""

    def _extract_primary_company(self, contact_info: Dict) -> str:
        """Extract primary company name"""
        # Implementation
        return ""

    def _extract_primary_phone(self, contact_info: Dict) -> str:
        """Extract primary phone number"""
        phones = contact_info.get("phone_numbers", [])
        return phones[0] if phones else ""

    def _extract_primary_email(self, contact_info: Dict) -> str:
        """Extract primary email address"""
        emails = contact_info.get("email_addresses", [])
        return emails[0] if emails else ""

    def _extract_topics(self, insights: Dict) -> List[str]:
        """Extract key topics from insights"""
        # Implementation to extract topics
        return []

    def _store_phone_numbers(self, cursor, recording_id: str, contact_info: Dict, contact_id: int, company_id: int):
        """Store phone numbers"""
        # Implementation
        pass

    def _store_email_addresses(self, cursor, recording_id: str, contact_info: Dict, contact_id: int, company_id: int):
        """Store email addresses"""
        # Implementation
        pass

    def _store_call_participants(self, cursor, recording_id: str, contact_info: Dict):
        """Store call participants"""
        # Implementation
        pass

    def _store_action_items(self, cursor, recording_id: str, action_items: List[Dict]):
        """Store action items"""
        # Implementation
        pass


def get_enhanced_database() -> EnhancedInsightsDatabase:
    """Factory function to get enhanced database instance"""
    return EnhancedInsightsDatabase()


if __name__ == "__main__":
    # Test the database
    db = get_enhanced_database()
    logger.info("Enhanced insights database initialized successfully")