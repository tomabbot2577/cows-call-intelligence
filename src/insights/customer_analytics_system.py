#!/usr/bin/env python3
"""
Customer Analytics System
Comprehensive customer tracking and analytics with phone/person/company lookup
"""

import json
import sqlite3
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import asdict

from .customer_employee_identifier import CustomerEmployeeIdentifier, get_customer_employee_identifier
from .enhanced_call_analyzer import EnhancedCallAnalyzer, get_enhanced_analyzer

logger = logging.getLogger(__name__)


class CustomerAnalyticsSystem:
    """
    Comprehensive customer analytics system that combines:
    1. Customer/Employee identification
    2. Enhanced AI analysis
    3. Searchable database
    4. Journey tracking
    5. Business intelligence
    """

    def __init__(self, db_path: str = None):
        """Initialize customer analytics system"""
        self.db_path = db_path or "/var/www/call-recording-system/data/insights/customer_analytics.db"
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize components
        self.identifier = get_customer_employee_identifier()
        self.analyzer = get_enhanced_analyzer()

        # Initialize database
        self.init_database()

    def init_database(self):
        """Create comprehensive database schema"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Enhanced call records table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS call_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id TEXT UNIQUE NOT NULL,

                    -- Timing
                    call_date TEXT NOT NULL,
                    call_time TEXT,
                    duration_seconds REAL,

                    -- Employee (Agent) Information
                    employee_name TEXT,
                    employee_extension TEXT,
                    employee_phone TEXT,
                    employee_email TEXT,
                    employee_department TEXT,
                    employee_role TEXT,
                    employee_id TEXT,

                    -- Primary Customer Information
                    customer_name TEXT,
                    customer_company TEXT,
                    customer_phone TEXT,
                    customer_email TEXT,
                    customer_role TEXT,
                    customer_source TEXT,  -- metadata, transcript, database

                    -- Call Details
                    call_direction TEXT,  -- inbound, outbound, unknown
                    call_type TEXT,       -- support, sales, billing, etc.
                    call_purpose TEXT,
                    urgency_level TEXT,
                    outcome_status TEXT,

                    -- Scores and Metrics
                    customer_satisfaction_score INTEGER,
                    call_quality_score REAL,
                    relationship_health_score INTEGER,
                    churn_risk_score INTEGER,
                    sales_opportunity_score INTEGER,
                    resolution_time_hours REAL,

                    -- AI Analysis Results
                    support_analysis TEXT,      -- JSON
                    sales_analysis TEXT,        -- JSON
                    customer_profile TEXT,      -- JSON
                    relationship_analysis TEXT, -- JSON

                    -- Flags
                    escalation_required BOOLEAN DEFAULT FALSE,
                    follow_up_needed BOOLEAN DEFAULT FALSE,
                    technical_issue BOOLEAN DEFAULT FALSE,
                    billing_issue BOOLEAN DEFAULT FALSE,
                    sales_opportunity BOOLEAN DEFAULT FALSE,

                    -- Context
                    mentioned_products TEXT,    -- JSON array
                    mentioned_issues TEXT,      -- JSON array
                    key_topics TEXT,           -- JSON array
                    action_items TEXT,         -- JSON array

                    -- Metadata
                    raw_transcript TEXT,
                    raw_insights TEXT,         -- Complete analysis JSON
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Customer master table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_key TEXT UNIQUE,  -- Unique identifier for customer
                    primary_name TEXT,
                    primary_company TEXT,
                    primary_phone TEXT,
                    primary_email TEXT,

                    -- Analytics
                    total_calls INTEGER DEFAULT 0,
                    first_call_date TEXT,
                    last_call_date TEXT,
                    avg_satisfaction REAL,
                    total_escalations INTEGER DEFAULT 0,
                    total_follow_ups INTEGER DEFAULT 0,
                    relationship_status TEXT,  -- active, at_risk, churned

                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Customer contact methods (multiple phones/emails per customer)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS customer_contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_key TEXT,
                    contact_type TEXT,  -- phone, email
                    contact_value TEXT,
                    is_primary BOOLEAN DEFAULT FALSE,
                    first_seen TEXT,
                    last_seen TEXT,
                    FOREIGN KEY (customer_key) REFERENCES customers (customer_key)
                )
            """)

            # Customer companies (multiple companies per customer possible)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS customer_companies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_key TEXT,
                    company_name TEXT,
                    is_primary BOOLEAN DEFAULT FALSE,
                    first_seen TEXT,
                    last_seen TEXT,
                    FOREIGN KEY (customer_key) REFERENCES customers (customer_key)
                )
            """)

            # Call topics for trending analysis
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS call_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id TEXT,
                    topic_category TEXT,
                    topic_name TEXT,
                    sentiment TEXT,
                    confidence REAL,
                    FOREIGN KEY (recording_id) REFERENCES call_records (recording_id)
                )
            """)

            # Action items tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS action_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id TEXT,
                    customer_key TEXT,
                    action_type TEXT,
                    description TEXT,
                    assigned_to TEXT,
                    priority TEXT,
                    due_date TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    FOREIGN KEY (recording_id) REFERENCES call_records (recording_id),
                    FOREIGN KEY (customer_key) REFERENCES customers (customer_key)
                )
            """)

            # Create indexes for fast searching
            self._create_indexes(cursor)
            conn.commit()

            logger.info("Customer analytics database initialized successfully")

    def _create_indexes(self, cursor):
        """Create performance indexes"""
        indexes = [
            # Call records indexes
            "CREATE INDEX IF NOT EXISTS idx_call_records_recording_id ON call_records(recording_id)",
            "CREATE INDEX IF NOT EXISTS idx_call_records_date ON call_records(call_date)",
            "CREATE INDEX IF NOT EXISTS idx_call_records_customer_name ON call_records(customer_name)",
            "CREATE INDEX IF NOT EXISTS idx_call_records_customer_company ON call_records(customer_company)",
            "CREATE INDEX IF NOT EXISTS idx_call_records_customer_phone ON call_records(customer_phone)",
            "CREATE INDEX IF NOT EXISTS idx_call_records_customer_email ON call_records(customer_email)",
            "CREATE INDEX IF NOT EXISTS idx_call_records_employee_name ON call_records(employee_name)",
            "CREATE INDEX IF NOT EXISTS idx_call_records_employee_ext ON call_records(employee_extension)",
            "CREATE INDEX IF NOT EXISTS idx_call_records_call_type ON call_records(call_type)",

            # Customer indexes
            "CREATE INDEX IF NOT EXISTS idx_customers_key ON customers(customer_key)",
            "CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(primary_name)",
            "CREATE INDEX IF NOT EXISTS idx_customers_company ON customers(primary_company)",
            "CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(primary_phone)",
            "CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(primary_email)",

            # Contact indexes
            "CREATE INDEX IF NOT EXISTS idx_customer_contacts_key ON customer_contacts(customer_key)",
            "CREATE INDEX IF NOT EXISTS idx_customer_contacts_value ON customer_contacts(contact_value)",
            "CREATE INDEX IF NOT EXISTS idx_customer_contacts_type ON customer_contacts(contact_type)",
        ]

        for index_sql in indexes:
            cursor.execute(index_sql)

    def process_call_recording(self, transcript_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a call recording through the complete analytics pipeline
        1. Identify participants (customer & employee)
        2. Generate AI insights
        3. Store in database
        4. Update customer records
        """
        recording_id = transcript_data.get("recording_id")
        logger.info(f"🔍 Processing call {recording_id} for customer analytics")

        try:
            # Step 1: Identify participants
            participants = self.identifier.analyze_call_participants(transcript_data)

            # Step 2: Generate comprehensive AI insights
            ai_insights = self.analyzer.generate_comprehensive_insights(transcript_data)

            # Step 3: Combine participant data with AI insights
            comprehensive_analysis = {
                "recording_id": recording_id,
                "participants": participants,
                "ai_insights": ai_insights,
                "processed_at": datetime.now().isoformat()
            }

            # Step 4: Store in database
            self._store_call_analysis(comprehensive_analysis, transcript_data)

            # Step 5: Update customer master records
            self._update_customer_records(comprehensive_analysis)

            logger.info(f"✅ Completed customer analytics for {recording_id}")
            return comprehensive_analysis

        except Exception as e:
            logger.error(f"Failed to process call {recording_id}: {e}")
            return {}

    def _store_call_analysis(self, analysis: Dict[str, Any], transcript_data: Dict[str, Any]):
        """Store comprehensive call analysis in database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            recording_id = analysis["recording_id"]
            participants = analysis["participants"]
            ai_insights = analysis["ai_insights"]

            # Extract data
            employee = participants["primary_employee"]
            customer = participants["primary_customer"]
            metadata = participants["call_metadata"]
            context = participants["call_context"]

            # Extract AI metrics
            ai_metrics = ai_insights.get("key_metrics", {})
            ai_classification = ai_insights.get("call_classification", {})

            # Store main call record
            cursor.execute("""
                INSERT OR REPLACE INTO call_records (
                    recording_id, call_date, call_time, duration_seconds,
                    employee_name, employee_extension, employee_phone, employee_email,
                    employee_department, employee_role, employee_id,
                    customer_name, customer_company, customer_phone, customer_email,
                    customer_role, customer_source,
                    call_direction, call_type, call_purpose, urgency_level, outcome_status,
                    customer_satisfaction_score, call_quality_score,
                    relationship_health_score, churn_risk_score, sales_opportunity_score,
                    escalation_required, follow_up_needed, technical_issue, billing_issue,
                    sales_opportunity, mentioned_products, mentioned_issues, key_topics,
                    action_items, raw_transcript, raw_insights, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                recording_id,
                metadata.get("date"),
                None,  # call_time - can be parsed from metadata
                metadata.get("duration"),
                employee.get("name"),
                employee.get("extension"),
                employee.get("phone"),
                employee.get("email"),
                employee.get("department"),
                employee.get("role"),
                employee.get("employee_id"),
                customer.get("name"),
                customer.get("company"),
                customer.get("phone"),
                customer.get("email"),
                customer.get("role"),
                customer.get("source"),
                metadata.get("direction"),
                ai_classification.get("call_type"),
                ", ".join(ai_classification.get("call_purpose", [])),
                ai_classification.get("urgency_level"),
                ai_classification.get("outcome_status"),
                ai_metrics.get("customer_satisfaction_score"),
                ai_metrics.get("call_quality_score"),
                ai_metrics.get("relationship_health_score"),
                ai_metrics.get("churn_risk_score"),
                ai_metrics.get("sales_opportunity_score"),
                ai_metrics.get("escalation_risk") == "high",
                "follow_up" in ai_classification.get("outcome_status", ""),
                "technical" in context.get("mentioned_issues", []),
                "billing" in context.get("mentioned_products", []),
                ai_metrics.get("upsell_opportunity") != "low",
                json.dumps(context.get("mentioned_products", [])),
                json.dumps(context.get("mentioned_issues", [])),
                json.dumps(self._extract_key_topics(ai_insights)),
                json.dumps(ai_insights.get("action_items", [])),
                transcript_data.get("transcription", {}).get("text", ""),
                json.dumps(analysis),
                datetime.now().isoformat()
            ))

            conn.commit()

    def _update_customer_records(self, analysis: Dict[str, Any]):
        """Update customer master records"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            customer = analysis["participants"]["primary_customer"]
            recording_id = analysis["recording_id"]
            call_date = analysis["participants"]["call_metadata"].get("date")

            if not customer.get("name") and not customer.get("phone") and not customer.get("email"):
                return  # Skip if no customer info

            # Generate customer key (unique identifier)
            customer_key = self._generate_customer_key(customer)

            # Check if customer exists
            cursor.execute("SELECT * FROM customers WHERE customer_key = ?", (customer_key,))
            existing = cursor.fetchone()

            if existing:
                # Update existing customer
                cursor.execute("""
                    UPDATE customers SET
                        primary_name = COALESCE(NULLIF(?, ''), primary_name),
                        primary_company = COALESCE(NULLIF(?, ''), primary_company),
                        primary_phone = COALESCE(NULLIF(?, ''), primary_phone),
                        primary_email = COALESCE(NULLIF(?, ''), primary_email),
                        total_calls = total_calls + 1,
                        last_call_date = ?,
                        updated_at = ?
                    WHERE customer_key = ?
                """, (
                    customer.get("name"),
                    customer.get("company"),
                    customer.get("phone"),
                    customer.get("email"),
                    call_date,
                    datetime.now().isoformat(),
                    customer_key
                ))
            else:
                # Create new customer
                cursor.execute("""
                    INSERT INTO customers (
                        customer_key, primary_name, primary_company,
                        primary_phone, primary_email, total_calls,
                        first_call_date, last_call_date, relationship_status
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, 'active')
                """, (
                    customer_key,
                    customer.get("name"),
                    customer.get("company"),
                    customer.get("phone"),
                    customer.get("email"),
                    call_date,
                    call_date
                ))

            # Store contact methods
            self._store_customer_contacts(cursor, customer_key, customer, call_date)

            conn.commit()

    def _generate_customer_key(self, customer: Dict[str, Any]) -> str:
        """Generate unique customer key from available data"""
        # Priority: phone > email > name+company
        phone = customer.get("phone", "").strip()
        email = customer.get("email", "").strip()
        name = customer.get("name", "").strip()
        company = customer.get("company", "").strip()

        if phone:
            return f"phone_{self._normalize_phone(phone)}"
        elif email:
            return f"email_{email.lower()}"
        elif name and company:
            return f"name_{name.lower().replace(' ', '_')}_{company.lower().replace(' ', '_')}"
        elif name:
            return f"name_{name.lower().replace(' ', '_')}"
        else:
            return f"unknown_{datetime.now().timestamp()}"

    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number"""
        import re
        return re.sub(r'[^\d]', '', str(phone))

    def _store_customer_contacts(self, cursor, customer_key: str, customer: Dict[str, Any], call_date: str):
        """Store customer contact methods"""
        phone = customer.get("phone", "").strip()
        email = customer.get("email", "").strip()

        if phone:
            cursor.execute("""
                INSERT OR REPLACE INTO customer_contacts
                (customer_key, contact_type, contact_value, is_primary, first_seen, last_seen)
                VALUES (?, 'phone', ?, TRUE,
                    COALESCE((SELECT first_seen FROM customer_contacts
                             WHERE customer_key = ? AND contact_value = ?), ?),
                    ?)
            """, (customer_key, phone, customer_key, phone, call_date, call_date))

        if email:
            cursor.execute("""
                INSERT OR REPLACE INTO customer_contacts
                (customer_key, contact_type, contact_value, is_primary, first_seen, last_seen)
                VALUES (?, 'email', ?, TRUE,
                    COALESCE((SELECT first_seen FROM customer_contacts
                             WHERE customer_key = ? AND contact_value = ?), ?),
                    ?)
            """, (customer_key, email, customer_key, email, call_date, call_date))

    def _extract_key_topics(self, ai_insights: Dict[str, Any]) -> List[str]:
        """Extract key topics from AI insights"""
        topics = []

        # Extract from different analysis sections
        support_analysis = ai_insights.get("support_analysis", {})
        sales_analysis = ai_insights.get("sales_analysis", {})
        customer_profile = ai_insights.get("customer_profile", {})

        # Add support topics
        if support_analysis.get("issue_category"):
            topics.append(f"support_{support_analysis['issue_category']}")

        # Add sales topics
        if sales_analysis.get("opportunity_stage"):
            topics.append(f"sales_{sales_analysis['opportunity_stage']}")

        # Add customer topics
        if customer_profile.get("business_type"):
            topics.append(f"industry_{customer_profile['business_type']}")

        return topics

    def search_customer_calls(self, search_term: str, search_type: str = "any") -> List[Dict[str, Any]]:
        """
        Search for customer calls by various criteria
        search_type: 'name', 'phone', 'email', 'company', 'any'
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if search_type == "any":
                # Search across all fields
                cursor.execute("""
                    SELECT * FROM call_records
                    WHERE customer_name LIKE ?
                       OR customer_company LIKE ?
                       OR customer_phone LIKE ?
                       OR customer_email LIKE ?
                       OR employee_name LIKE ?
                    ORDER BY call_date DESC
                    LIMIT 100
                """, (f"%{search_term}%", f"%{search_term}%", f"%{search_term}%",
                      f"%{search_term}%", f"%{search_term}%"))

            elif search_type == "phone":
                normalized_search = self._normalize_phone(search_term)
                cursor.execute("""
                    SELECT cr.* FROM call_records cr
                    LEFT JOIN customer_contacts cc ON cc.customer_key =
                        (SELECT customer_key FROM customers WHERE
                         primary_phone LIKE ? OR primary_name = cr.customer_name)
                    WHERE cr.customer_phone LIKE ?
                       OR cc.contact_value LIKE ?
                    ORDER BY cr.call_date DESC
                    LIMIT 100
                """, (f"%{normalized_search}%", f"%{search_term}%", f"%{normalized_search}%"))

            elif search_type == "email":
                cursor.execute("""
                    SELECT cr.* FROM call_records cr
                    LEFT JOIN customer_contacts cc ON cc.customer_key =
                        (SELECT customer_key FROM customers WHERE
                         primary_email LIKE ? OR primary_name = cr.customer_name)
                    WHERE cr.customer_email LIKE ?
                       OR cc.contact_value LIKE ?
                    ORDER BY cr.call_date DESC
                    LIMIT 100
                """, (f"%{search_term}%", f"%{search_term}%", f"%{search_term}%"))

            elif search_type == "name":
                cursor.execute("""
                    SELECT * FROM call_records
                    WHERE customer_name LIKE ?
                    ORDER BY call_date DESC
                    LIMIT 100
                """, (f"%{search_term}%",))

            elif search_type == "company":
                cursor.execute("""
                    SELECT * FROM call_records
                    WHERE customer_company LIKE ?
                    ORDER BY call_date DESC
                    LIMIT 100
                """, (f"%{search_term}%",))

            results = [dict(row) for row in cursor.fetchall()]
            return results

    def get_customer_analytics(self, customer_identifier: str) -> Dict[str, Any]:
        """Get comprehensive analytics for a customer"""
        calls = self.search_customer_calls(customer_identifier)

        if not calls:
            return {"error": "No calls found for customer"}

        # Calculate analytics
        total_calls = len(calls)

        # Satisfaction scores
        satisfaction_scores = [c["customer_satisfaction_score"] for c in calls if c["customer_satisfaction_score"]]
        avg_satisfaction = sum(satisfaction_scores) / len(satisfaction_scores) if satisfaction_scores else 0

        # Call types breakdown
        call_types = {}
        departments = {}
        employees = {}

        for call in calls:
            # Call types
            call_type = call["call_type"] or "unknown"
            call_types[call_type] = call_types.get(call_type, 0) + 1

            # Departments
            dept = call["employee_department"] or "unknown"
            departments[dept] = departments.get(dept, 0) + 1

            # Employees
            emp = call["employee_name"] or "unknown"
            employees[emp] = employees.get(emp, 0) + 1

        # Timeline analysis
        first_call = min(calls, key=lambda x: x["call_date"])
        last_call = max(calls, key=lambda x: x["call_date"])

        # Issues and escalations
        escalations = sum(1 for c in calls if c["escalation_required"])
        follow_ups = sum(1 for c in calls if c["follow_up_needed"])
        technical_issues = sum(1 for c in calls if c["technical_issue"])
        billing_issues = sum(1 for c in calls if c["billing_issue"])

        return {
            "customer_identifier": customer_identifier,
            "summary": {
                "total_calls": total_calls,
                "average_satisfaction": round(avg_satisfaction, 2),
                "first_call_date": first_call["call_date"],
                "last_call_date": last_call["call_date"],
                "total_escalations": escalations,
                "total_follow_ups": follow_ups
            },
            "breakdown": {
                "call_types": call_types,
                "departments_contacted": departments,
                "employees_spoken_with": employees
            },
            "issues": {
                "technical_issues": technical_issues,
                "billing_issues": billing_issues,
                "escalation_rate": round(escalations / total_calls * 100, 1) if total_calls > 0 else 0
            },
            "recent_calls": calls[:10],  # Last 10 calls
            "trend_analysis": self._analyze_customer_trends(calls)
        }

    def _analyze_customer_trends(self, calls: List[Dict]) -> Dict[str, Any]:
        """Analyze customer trends over time"""
        # Sort by date
        calls_sorted = sorted(calls, key=lambda x: x["call_date"])

        trends = {
            "satisfaction_trend": "stable",
            "call_frequency_trend": "stable",
            "issue_complexity_trend": "stable",
            "relationship_health": "good"
        }

        if len(calls_sorted) >= 3:
            # Analyze last 3 calls vs previous calls
            recent_calls = calls_sorted[-3:]
            older_calls = calls_sorted[:-3] if len(calls_sorted) > 3 else []

            # Satisfaction trend
            if older_calls:
                recent_satisfaction = [c["customer_satisfaction_score"] for c in recent_calls if c["customer_satisfaction_score"]]
                older_satisfaction = [c["customer_satisfaction_score"] for c in older_calls if c["customer_satisfaction_score"]]

                if recent_satisfaction and older_satisfaction:
                    recent_avg = sum(recent_satisfaction) / len(recent_satisfaction)
                    older_avg = sum(older_satisfaction) / len(older_satisfaction)

                    if recent_avg > older_avg + 1:
                        trends["satisfaction_trend"] = "improving"
                    elif recent_avg < older_avg - 1:
                        trends["satisfaction_trend"] = "declining"

            # Recent escalations indicate relationship risk
            recent_escalations = sum(1 for c in recent_calls if c["escalation_required"])
            if recent_escalations >= 2:
                trends["relationship_health"] = "at_risk"

        return trends

    def get_employee_analytics(self, employee_identifier: str) -> Dict[str, Any]:
        """Get analytics for specific employee performance"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM call_records
                WHERE employee_name LIKE ? OR employee_extension = ?
                ORDER BY call_date DESC
                LIMIT 200
            """, (f"%{employee_identifier}%", employee_identifier))

            calls = [dict(row) for row in cursor.fetchall()]

        if not calls:
            return {"error": "No calls found for employee"}

        # Calculate employee metrics
        total_calls = len(calls)
        satisfaction_scores = [c["customer_satisfaction_score"] for c in calls if c["customer_satisfaction_score"]]
        avg_satisfaction = sum(satisfaction_scores) / len(satisfaction_scores) if satisfaction_scores else 0

        escalations = sum(1 for c in calls if c["escalation_required"])
        resolutions = sum(1 for c in calls if c["outcome_status"] in ["resolved", "completed"])

        return {
            "employee": calls[0]["employee_name"] if calls else employee_identifier,
            "department": calls[0]["employee_department"] if calls else "",
            "metrics": {
                "total_calls": total_calls,
                "average_satisfaction": round(avg_satisfaction, 2),
                "escalation_rate": round(escalations / total_calls * 100, 1) if total_calls > 0 else 0,
                "resolution_rate": round(resolutions / total_calls * 100, 1) if total_calls > 0 else 0
            },
            "recent_calls": calls[:10]
        }


def get_customer_analytics_system() -> CustomerAnalyticsSystem:
    """Factory function to get analytics system instance"""
    return CustomerAnalyticsSystem()


if __name__ == "__main__":
    # Test the system
    system = get_customer_analytics_system()
    logger.info("Customer Analytics System initialized successfully")