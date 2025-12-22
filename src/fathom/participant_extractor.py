"""
Fathom Participant Extractor

Extracts and normalizes participant information from Fathom meeting data.
Handles calendar invitees, action item assignees, and CRM matches.
"""

import re
import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Participant:
    """Represents a meeting participant."""
    name: str
    email: Optional[str] = None
    email_domain: Optional[str] = None
    is_external: bool = False
    is_host: bool = False
    is_invitee: bool = False
    phone_business: Optional[str] = None
    phone_mobile: Optional[str] = None
    crm_contact_name: Optional[str] = None
    crm_company_name: Optional[str] = None
    roles: Set[str] = field(default_factory=set)

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'name': self.name,
            'email': self.email,
            'email_domain': self.email_domain,
            'is_external': self.is_external,
            'is_host': self.is_host,
            'is_invitee': self.is_invitee,
            'phone_business': self.phone_business,
            'phone_mobile': self.phone_mobile,
            'crm_contact_name': self.crm_contact_name,
            'crm_company_name': self.crm_company_name,
            'roles': list(self.roles)
        }


class ParticipantExtractor:
    """
    Extracts and consolidates participant information from various sources.

    Sources:
    - Meeting participants (from Fathom)
    - Calendar invitees
    - Action item assignees
    - CRM contact matches
    """

    # Internal email domains
    INTERNAL_DOMAINS = {
        'mainsequence.net',
        'mainsequencetechnology.com',
        'pcrecruiter.net'
    }

    def __init__(self, internal_domains: Set[str] = None):
        """
        Initialize the extractor.

        Args:
            internal_domains: Set of internal email domains
        """
        self.internal_domains = internal_domains or self.INTERNAL_DOMAINS

    def _normalize_email(self, email: str) -> Optional[str]:
        """Normalize email address."""
        if not email:
            return None

        email = email.strip().lower()

        # Basic email validation
        if '@' not in email or '.' not in email:
            return None

        return email

    def _extract_domain(self, email: str) -> Optional[str]:
        """Extract domain from email address."""
        if not email or '@' not in email:
            return None
        return email.split('@')[-1].lower()

    def _is_external(self, email: str) -> bool:
        """Determine if email is from external domain."""
        domain = self._extract_domain(email)
        if not domain:
            return True  # Unknown emails treated as external
        return domain not in self.internal_domains

    def _normalize_name(self, name: str) -> str:
        """Normalize participant name."""
        if not name:
            return "Unknown"

        # Clean up whitespace
        name = ' '.join(name.split())

        # Remove common prefixes/suffixes
        name = re.sub(r'^\s*Mr\.?\s*', '', name, flags=re.IGNORECASE)
        name = re.sub(r'^\s*Mrs\.?\s*', '', name, flags=re.IGNORECASE)
        name = re.sub(r'^\s*Ms\.?\s*', '', name, flags=re.IGNORECASE)
        name = re.sub(r'^\s*Dr\.?\s*', '', name, flags=re.IGNORECASE)

        return name.strip() or "Unknown"

    def extract_participants(self, meeting_data: Dict) -> List[Participant]:
        """
        Extract all participants from meeting data.

        Args:
            meeting_data: Raw Fathom meeting data

        Returns:
            List of consolidated Participant objects
        """
        participants_map = {}  # email -> Participant

        # Extract from main participants list
        for p in meeting_data.get('participants', []):
            participant = self._create_participant(p)
            participant.roles.add('attendee')

            key = participant.email or participant.name
            if key in participants_map:
                self._merge_participant(participants_map[key], participant)
            else:
                participants_map[key] = participant

        # Extract from calendar invitees
        for p in meeting_data.get('calendar_invitees', []):
            participant = self._create_participant(p)
            participant.is_invitee = True
            participant.roles.add('invitee')

            key = participant.email or participant.name
            if key in participants_map:
                self._merge_participant(participants_map[key], participant)
            else:
                participants_map[key] = participant

        # Extract from action item assignees
        for item in meeting_data.get('action_items', []):
            assignee = item.get('assignee', {})
            if assignee:
                participant = self._create_participant(assignee)
                participant.roles.add('assignee')

                key = participant.email or participant.name
                if key in participants_map:
                    self._merge_participant(participants_map[key], participant)
                else:
                    participants_map[key] = participant

        # Enrich with CRM data
        self._enrich_with_crm(participants_map, meeting_data.get('crm_matches', {}))

        return list(participants_map.values())

    def _create_participant(self, data: Dict) -> Participant:
        """Create a Participant from raw data."""
        email = self._normalize_email(data.get('email'))

        return Participant(
            name=self._normalize_name(data.get('name', '')),
            email=email,
            email_domain=self._extract_domain(email) if email else None,
            is_external=self._is_external(email) if email else True,
            is_host=data.get('is_host', False)
        )

    def _merge_participant(self, existing: Participant, new: Participant):
        """Merge new participant data into existing."""
        # Update email if missing
        if not existing.email and new.email:
            existing.email = new.email
            existing.email_domain = new.email_domain
            existing.is_external = new.is_external

        # Update name if current is Unknown
        if existing.name == "Unknown" and new.name != "Unknown":
            existing.name = new.name

        # Merge flags
        existing.is_host = existing.is_host or new.is_host
        existing.is_invitee = existing.is_invitee or new.is_invitee

        # Merge roles
        existing.roles.update(new.roles)

    def _enrich_with_crm(self, participants_map: Dict[str, Participant],
                         crm_matches: Dict):
        """Enrich participants with CRM contact data."""
        contacts = crm_matches.get('contacts', [])

        for contact in contacts:
            email = self._normalize_email(contact.get('email'))

            if email and email in participants_map:
                participant = participants_map[email]
                participant.crm_contact_name = contact.get('name')
                participant.crm_company_name = contact.get('company')
                participant.roles.add('crm_contact')

    def extract_companies(self, participants: List[Participant]) -> List[Dict]:
        """
        Extract unique companies from participants.

        Args:
            participants: List of Participant objects

        Returns:
            List of company info dicts
        """
        companies = {}

        for p in participants:
            if p.crm_company_name:
                company_key = p.crm_company_name.lower()
                if company_key not in companies:
                    companies[company_key] = {
                        'name': p.crm_company_name,
                        'domain': p.email_domain,
                        'participants': []
                    }
                companies[company_key]['participants'].append(p.name)

            elif p.email_domain and p.is_external:
                # Use email domain as company fallback
                if p.email_domain not in companies:
                    companies[p.email_domain] = {
                        'name': p.email_domain,
                        'domain': p.email_domain,
                        'participants': []
                    }
                companies[p.email_domain]['participants'].append(p.name)

        return list(companies.values())

    def get_external_participants(self, participants: List[Participant]) -> List[Participant]:
        """Get only external participants."""
        return [p for p in participants if p.is_external]

    def get_internal_participants(self, participants: List[Participant]) -> List[Participant]:
        """Get only internal participants."""
        return [p for p in participants if not p.is_external]

    def summary(self, participants: List[Participant]) -> Dict:
        """
        Generate a summary of participant breakdown.

        Returns:
            Summary dict with counts and lists
        """
        internal = self.get_internal_participants(participants)
        external = self.get_external_participants(participants)
        companies = self.extract_companies(participants)

        return {
            'total_participants': len(participants),
            'internal_count': len(internal),
            'external_count': len(external),
            'companies_count': len(companies),
            'internal_names': [p.name for p in internal],
            'external_names': [p.name for p in external],
            'companies': [c['name'] for c in companies],
            'has_crm_matches': any(p.crm_contact_name for p in participants)
        }
