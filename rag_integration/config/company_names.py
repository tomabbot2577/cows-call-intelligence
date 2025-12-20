"""
Company Name Canonicalization

Maps various spellings/variations of company names to their canonical form.
This helps consolidate customer data across different name variations.
"""

# Known company name variations mapped to canonical names
COMPANY_VARIATIONS = {
    # PC Recruiter / Main Sequence (internal - vendor)
    "pc recruiter": "PC Recruiter",
    "pcr": "PC Recruiter",
    "pcrecruiter": "PC Recruiter",
    "pc-recruiter": "PC Recruiter",

    "main sequence": "Main Sequence Technology",
    "main sequence technology": "Main Sequence Technology",
    "main sequence technologies": "Main Sequence Technology",
    "mainsequence": "Main Sequence Technology",
    "mst": "Main Sequence Technology",

    # Customer companies (add as needed)
    "dimensional search": "Dimensional Search",
    "sanford rose": "Sanford Rose Associates",
    "sanford rose it": "Sanford Rose Associates",
    "sanford rose associates": "Sanford Rose Associates",

    "princeton legal": "Princeton Legal Search Group",
    "princeton legal search": "Princeton Legal Search Group",
    "princeton legal search group": "Princeton Legal Search Group",

    "harbinger": "Harbinger Network",
    "harbinger network": "Harbinger Network",

    "hc pursuit": "HC Pursuit",
    "hcpursuit": "HC Pursuit",

    "newport": "Newport Group",
    "newport group": "Newport Group",

    "triumph": "Triumph Staffing",
    "triumph staffing": "Triumph Staffing",

    "maxwell": "Maxwell Management Group",
    "maxwell management": "Maxwell Management Group",
    "maxwell management group": "Maxwell Management Group",

    "united employment": "United Employment Group",
    "united employment group": "United Employment Group",
}

# Companies that are internal/vendor (not customers)
INTERNAL_COMPANIES = [
    "PC Recruiter",
    "Main Sequence Technology",
]


def canonicalize_company_name(name: str) -> str:
    """
    Convert a company name to its canonical form.

    Args:
        name: The raw company name from the database

    Returns:
        The canonical company name, or the original if not found
    """
    if not name:
        return None

    # Clean the name
    name_clean = name.strip()
    name_lower = name_clean.lower()

    # Check exclusions
    if name_lower in ['unknown', 'n/a', '', 'none']:
        return None

    # Look up in variations map
    if name_lower in COMPANY_VARIATIONS:
        return COMPANY_VARIATIONS[name_lower]

    # Check if already canonical (case-insensitive)
    for variation, canonical in COMPANY_VARIATIONS.items():
        if name_lower == canonical.lower():
            return canonical

    # Return original with title case if not found
    return name_clean


def is_internal_company(name: str) -> bool:
    """
    Check if a company is internal (vendor, not customer).

    Args:
        name: The company name to check

    Returns:
        True if the company is internal/vendor
    """
    if not name:
        return False

    canonical = canonicalize_company_name(name)
    return canonical in INTERNAL_COMPANIES


def get_company_search_patterns(company_name: str) -> list:
    """
    Get all variations of a company name for database searching.

    Args:
        company_name: The company name to search for

    Returns:
        List of LIKE patterns for SQL queries
    """
    if not company_name:
        return []

    canonical = canonicalize_company_name(company_name)
    if not canonical:
        return [f"%{company_name}%"]

    # Get all variations that map to this canonical name
    variations = [canonical.lower()]
    for variation, canon in COMPANY_VARIATIONS.items():
        if canon == canonical:
            variations.append(variation)

    # Create LIKE patterns
    patterns = [f"%{v}%" for v in set(variations)]
    return patterns


def get_known_companies() -> list:
    """
    Get list of known customer companies for dropdowns.

    Returns:
        Sorted list of canonical company names (excluding internal)
    """
    companies = set(COMPANY_VARIATIONS.values())
    # Remove internal companies
    companies = companies - set(INTERNAL_COMPANIES)
    return sorted(companies)
