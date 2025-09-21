#!/usr/bin/env python3
"""
Customer & Employee Identification System
Comprehensive identification from call metadata, transcripts, and employee database
"""

import json
import re
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Employee:
    """Employee data structure"""
    name: str
    extension: str
    phone: str
    email: str
    department: str
    role: str
    employee_id: str


@dataclass
class Customer:
    """Customer data structure"""
    name: str
    company: str
    phone: str
    email: str
    role: str
    source: str  # transcript, metadata, database


class CustomerEmployeeIdentifier:
    """
    Identifies customers and employees from call data using multiple sources:
    1. Call metadata (phone numbers, extensions)
    2. Transcript content (names, companies mentioned)
    3. Employee database (extensions, names)
    4. Historical call data
    """

    def __init__(self, employee_data_file: str = None):
        """Initialize with employee data"""
        self.employee_data_file = employee_data_file or "/var/www/call-recording-system/config/employees.json"
        self.employees = self._load_employee_data()

        # Create lookup dictionaries for fast searching
        self.employee_by_extension = {emp.extension: emp for emp in self.employees}
        self.employee_by_phone = {self._normalize_phone(emp.phone): emp for emp in self.employees}
        self.employee_by_name = {emp.name.lower(): emp for emp in self.employees}

    def _load_employee_data(self) -> List[Employee]:
        """Load employee data from JSON file"""
        try:
            if Path(self.employee_data_file).exists():
                with open(self.employee_data_file, 'r') as f:
                    data = json.load(f)
                    return [Employee(**emp) for emp in data.get('employees', [])]
            else:
                logger.warning(f"Employee data file not found: {self.employee_data_file}")
                return self._create_default_employees()
        except Exception as e:
            logger.error(f"Failed to load employee data: {e}")
            return self._create_default_employees()

    def _create_default_employees(self) -> List[Employee]:
        """Create default employee list (placeholder for your actual employees)"""
        return [
            Employee(
                name="Robin Montoni",
                extension="2001",
                phone="6145551234",
                email="robin@mainsequence.net",
                department="Sales",
                role="Account Manager",
                employee_id="EMP001"
            ),
            Employee(
                name="Robert Smith",
                extension="2002",
                phone="6145551235",
                email="robert@mainsequence.net",
                department="Support",
                role="Technical Support",
                employee_id="EMP002"
            )
        ]

    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number for comparison"""
        if not phone:
            return ""
        # Remove all non-digits
        return re.sub(r'[^\d]', '', str(phone))

    def identify_employee_from_metadata(self, call_metadata: Dict) -> Optional[Employee]:
        """Identify employee from call metadata (extension, phone numbers)"""

        # Check 'from' field for extension
        from_info = call_metadata.get("from", {})
        from_ext = from_info.get("extension", "")
        from_phone = from_info.get("number", "")

        # Check 'to' field for extension
        to_info = call_metadata.get("to", {})
        to_ext = to_info.get("extension", "")
        to_phone = to_info.get("number", "")

        # Try to match by extension first
        for ext in [from_ext, to_ext]:
            if ext and ext in self.employee_by_extension:
                return self.employee_by_extension[ext]

        # Try to match by phone number
        for phone in [from_phone, to_phone]:
            normalized = self._normalize_phone(phone)
            if normalized and normalized in self.employee_by_phone:
                return self.employee_by_phone[normalized]

        return None

    def identify_employee_from_transcript(self, transcript: str) -> List[Employee]:
        """Identify employees mentioned in transcript"""
        identified = []
        transcript_lower = transcript.lower()

        for employee in self.employees:
            # Check for full name
            if employee.name.lower() in transcript_lower:
                identified.append(employee)
                continue

            # Check for first name (if unique enough)
            first_name = employee.name.split()[0].lower()
            if len(first_name) > 3 and first_name in transcript_lower:
                identified.append(employee)

        return identified

    def identify_customers_from_transcript(self, transcript: str) -> List[Customer]:
        """Extract customer information from transcript using AI and patterns"""
        customers = []

        # Extract names using patterns and context
        customer_patterns = [
            r"(?:this is|i'm|my name is|speaking with)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:speaking|here|from)",
            r"(?:mr|ms|mrs|dr)\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)"
        ]

        names_found = set()
        for pattern in customer_patterns:
            matches = re.findall(pattern, transcript, re.IGNORECASE)
            names_found.update(matches)

        # Extract company names
        company_patterns = [
            r"(?:from|with|at)\s+([A-Z][a-zA-Z\s&.,]+(?:Inc|LLC|Corp|Company|Ltd))",
            r"([A-Z][a-zA-Z\s&.,]+(?:Inc|LLC|Corp|Company|Ltd))",
            r"(?:work for|employed by|represent)\s+([A-Z][a-zA-Z\s&.,]+)"
        ]

        companies_found = set()
        for pattern in company_patterns:
            matches = re.findall(pattern, transcript, re.IGNORECASE)
            companies_found.update(matches)

        # Extract phone numbers from transcript
        phone_pattern = r'(\d{3}[-.]?\d{3}[-.]?\d{4}|\(\d{3}\)\s?\d{3}[-.]?\d{4})'
        phones_found = re.findall(phone_pattern, transcript)

        # Extract email addresses
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails_found = re.findall(email_pattern, transcript)

        # Create customer objects
        for name in names_found:
            # Skip if it's an employee name
            if name.lower() not in [emp.name.lower() for emp in self.employees]:
                customer = Customer(
                    name=name.strip(),
                    company=list(companies_found)[0] if companies_found else "",
                    phone=phones_found[0] if phones_found else "",
                    email=emails_found[0] if emails_found else "",
                    role="",
                    source="transcript"
                )
                customers.append(customer)

        return customers

    def identify_customers_from_metadata(self, call_metadata: Dict) -> List[Customer]:
        """Extract customer information from call metadata"""
        customers = []

        # Check 'from' and 'to' fields for customer info
        from_info = call_metadata.get("from", {})
        to_info = call_metadata.get("to", {})

        # If 'from' is not an employee, it's likely a customer
        employee = self.identify_employee_from_metadata(call_metadata)

        for info_source, label in [(from_info, "from"), (to_info, "to")]:
            name = info_source.get("name", "").strip()
            number = info_source.get("number", "").strip()
            company = info_source.get("company", "").strip()

            # Skip if it's an employee
            if employee and (number == employee.phone or name.lower() == employee.name.lower()):
                continue

            # Create customer if we have meaningful info
            if name or (number and number != "unknown"):
                customer = Customer(
                    name=name if name != "unknown" else "",
                    company=company if company != "unknown" else "",
                    phone=number if number != "unknown" else "",
                    email="",
                    role="",
                    source=f"metadata_{label}"
                )
                customers.append(customer)

        return customers

    def analyze_call_participants(self, transcript_data: Dict) -> Dict[str, Any]:
        """
        Comprehensive analysis of call participants (customers and employees)
        """
        transcript = transcript_data.get("transcription", {}).get("text", "")
        call_metadata = transcript_data.get("call_metadata", {})

        # Identify employee
        employee_from_metadata = self.identify_employee_from_metadata(call_metadata)
        employees_from_transcript = self.identify_employee_from_transcript(transcript)

        # Identify customers
        customers_from_transcript = self.identify_customers_from_transcript(transcript)
        customers_from_metadata = self.identify_customers_from_metadata(call_metadata)

        # Determine primary employee (agent)
        primary_employee = employee_from_metadata
        if not primary_employee and employees_from_transcript:
            primary_employee = employees_from_transcript[0]

        # Determine primary customer
        all_customers = customers_from_transcript + customers_from_metadata
        primary_customer = None
        if all_customers:
            # Prefer customers with names from transcript
            named_customers = [c for c in all_customers if c.name]
            primary_customer = named_customers[0] if named_customers else all_customers[0]

        # Extract additional context
        call_direction = self._determine_call_direction(call_metadata, primary_employee)
        call_context = self._extract_call_context(transcript)

        return {
            "primary_employee": {
                "name": primary_employee.name if primary_employee else "Unknown",
                "extension": primary_employee.extension if primary_employee else "",
                "phone": primary_employee.phone if primary_employee else "",
                "email": primary_employee.email if primary_employee else "",
                "department": primary_employee.department if primary_employee else "",
                "role": primary_employee.role if primary_employee else "",
                "employee_id": primary_employee.employee_id if primary_employee else ""
            },
            "primary_customer": {
                "name": primary_customer.name if primary_customer else "Unknown",
                "company": primary_customer.company if primary_customer else "",
                "phone": primary_customer.phone if primary_customer else "",
                "email": primary_customer.email if primary_customer else "",
                "role": primary_customer.role if primary_customer else "",
                "source": primary_customer.source if primary_customer else ""
            },
            "all_customers_identified": [
                {
                    "name": c.name,
                    "company": c.company,
                    "phone": c.phone,
                    "email": c.email,
                    "role": c.role,
                    "source": c.source
                } for c in all_customers
            ],
            "all_employees_mentioned": [
                {
                    "name": e.name,
                    "extension": e.extension,
                    "department": e.department,
                    "role": e.role
                } for e in employees_from_transcript
            ],
            "call_metadata": {
                "direction": call_direction,
                "from_number": call_metadata.get("from", {}).get("number"),
                "to_number": call_metadata.get("to", {}).get("number"),
                "from_extension": call_metadata.get("from", {}).get("extension"),
                "to_extension": call_metadata.get("to", {}).get("extension"),
                "duration": call_metadata.get("duration_seconds"),
                "date": call_metadata.get("date")
            },
            "call_context": call_context
        }

    def _determine_call_direction(self, call_metadata: Dict, primary_employee: Employee) -> str:
        """Determine if call is inbound or outbound"""
        from_info = call_metadata.get("from", {})
        to_info = call_metadata.get("to", {})

        if primary_employee:
            # Check if employee is in 'to' field (inbound) or 'from' field (outbound)
            if (from_info.get("extension") == primary_employee.extension or
                self._normalize_phone(from_info.get("number")) == self._normalize_phone(primary_employee.phone)):
                return "outbound"
            elif (to_info.get("extension") == primary_employee.extension or
                  self._normalize_phone(to_info.get("number")) == self._normalize_phone(primary_employee.phone)):
                return "inbound"

        return "unknown"

    def _extract_call_context(self, transcript: str) -> Dict[str, Any]:
        """Extract additional context from transcript"""
        context = {
            "mentioned_products": [],
            "mentioned_issues": [],
            "urgency_indicators": [],
            "follow_up_mentions": []
        }

        # Product mentions
        product_keywords = ["billing", "invoice", "upgrade", "training", "features", "service", "account"]
        for keyword in product_keywords:
            if keyword in transcript.lower():
                context["mentioned_products"].append(keyword)

        # Issue indicators
        issue_keywords = ["problem", "issue", "error", "trouble", "not working", "failed"]
        for keyword in issue_keywords:
            if keyword in transcript.lower():
                context["mentioned_issues"].append(keyword)

        # Urgency indicators
        urgency_keywords = ["urgent", "asap", "immediately", "critical", "emergency"]
        for keyword in urgency_keywords:
            if keyword in transcript.lower():
                context["urgency_indicators"].append(keyword)

        # Follow-up mentions
        followup_keywords = ["follow up", "call back", "reach out", "send email", "get back to you"]
        for keyword in followup_keywords:
            if keyword in transcript.lower():
                context["follow_up_mentions"].append(keyword)

        return context

    def search_calls_by_customer(self, customer_identifier: str, call_history: List[Dict]) -> List[Dict]:
        """
        Search for all calls involving a specific customer
        customer_identifier can be: name, phone number, email, or company
        """
        matching_calls = []

        for call_data in call_history:
            participants = self.analyze_call_participants(call_data)

            # Check primary customer
            primary_customer = participants["primary_customer"]

            # Check if identifier matches any customer field
            identifier_lower = customer_identifier.lower()

            matches = [
                identifier_lower in primary_customer["name"].lower(),
                identifier_lower in primary_customer["company"].lower(),
                self._normalize_phone(customer_identifier) == self._normalize_phone(primary_customer["phone"]),
                customer_identifier.lower() == primary_customer["email"].lower()
            ]

            # Also check all identified customers
            for customer in participants["all_customers_identified"]:
                matches.extend([
                    identifier_lower in customer["name"].lower(),
                    identifier_lower in customer["company"].lower(),
                    self._normalize_phone(customer_identifier) == self._normalize_phone(customer["phone"]),
                    customer_identifier.lower() == customer["email"].lower()
                ])

            if any(matches):
                matching_calls.append({
                    "recording_id": call_data.get("recording_id"),
                    "call_date": call_data.get("call_metadata", {}).get("date"),
                    "participants": participants,
                    "transcript_excerpt": call_data.get("transcription", {}).get("text", "")[:200] + "..."
                })

        return matching_calls

    def create_employee_database_file(self, employees_data: List[Dict]):
        """Create/update employee database file"""
        data = {
            "employees": employees_data,
            "last_updated": datetime.now().isoformat(),
            "version": "1.0"
        }

        with open(self.employee_data_file, 'w') as f:
            json.dump(data, f, indent=2)

        logger.info(f"Employee database updated with {len(employees_data)} employees")

        # Reload employee data
        self.employees = self._load_employee_data()
        self.employee_by_extension = {emp.extension: emp for emp in self.employees}
        self.employee_by_phone = {self._normalize_phone(emp.phone): emp for emp in self.employees}
        self.employee_by_name = {emp.name.lower(): emp for emp in self.employees}


def get_customer_employee_identifier() -> CustomerEmployeeIdentifier:
    """Factory function to get identifier instance"""
    return CustomerEmployeeIdentifier()


if __name__ == "__main__":
    # Test the identifier
    identifier = get_customer_employee_identifier()
    logger.info("Customer & Employee Identifier initialized successfully")