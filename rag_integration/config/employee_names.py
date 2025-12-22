"""
Employee Name Canonicalization

Maps various spellings/variations of employee names to their canonical form.
The called party (to_number) is typically the employee.
The caller (from_number) is typically the customer.

Updated: 2024-12-20 with verified employee list from user.
"""

# Canonical employee names at PC Recruiter / Main Sequence
# Format: "First Last" for display in dropdowns
CANONICAL_EMPLOYEES = [
    "Bill Kubicek",
    "Dylan Bello",
    "James Blair",
    "Nicholas Bradach",
    "Brian Coverstone",
    "Brian Eaton",
    "Joshua Fresenko",
    "Wayne Geissinger",
    "Jacob Gooden",
    "Thomas James",
    "Garrett Komyati",
    "James Lombardo",
    "Sean McLaughlin",
    "Robin Montoni",
    "Matthew Mueller",
    "Andrew Rothman",
    "Jason Salamon",
    "Christian Salem",
    "Mackenzie Scalise",
    "Davisha",
    "Lisa Rogers",
    "Samuel Barnes",
    "Tyler Trautman",
]

# Map variations to canonical names (case-insensitive lookup)
NAME_VARIATIONS = {
    # Bill Kubicek
    "bill": "Bill Kubicek",
    "bill kubicek": "Bill Kubicek",
    "kubicek, bill": "Bill Kubicek",

    # Dylan Bello
    "dylan": "Dylan Bello",
    "dylan bello": "Dylan Bello",
    "bello, dylan": "Dylan Bello",

    # James Blair
    "james blair": "James Blair",
    "blair, james": "James Blair",

    # Nicholas Bradach
    "nicholas": "Nicholas Bradach",
    "nick": "Nicholas Bradach",
    "nicholas bradach": "Nicholas Bradach",
    "nicholas j bradach": "Nicholas Bradach",
    "bradach, nicholas": "Nicholas Bradach",
    "bradach, nicholas j": "Nicholas Bradach",

    # Brian Coverstone
    "brian coverstone": "Brian Coverstone",
    "brian d coverstone": "Brian Coverstone",
    "coverstone, brian": "Brian Coverstone",
    "coverstone, brian d": "Brian Coverstone",

    # Brian Eaton
    "brian eaton": "Brian Eaton",
    "brian r eaton": "Brian Eaton",
    "eaton, brian": "Brian Eaton",
    "eaton, brian r": "Brian Eaton",

    # Joshua Fresenko
    "joshua": "Joshua Fresenko",
    "josh": "Joshua Fresenko",
    "joshua fresenko": "Joshua Fresenko",
    "fresenko, joshua": "Joshua Fresenko",

    # Wayne Geissinger
    "wayne": "Wayne Geissinger",
    "wayne geissinger": "Wayne Geissinger",
    "geissinger, wayne": "Wayne Geissinger",

    # Jacob Gooden
    "jacob": "Jacob Gooden",
    "jacob gooden": "Jacob Gooden",
    "gooden, jacob": "Jacob Gooden",

    # Thomas James
    "thomas": "Thomas James",
    "thomas james": "Thomas James",
    "thomas r james": "Thomas James",
    "james, thomas": "Thomas James",
    "james, thomas r": "Thomas James",

    # Garrett Komyati
    "garrett": "Garrett Komyati",
    "garrett komyati": "Garrett Komyati",
    "garrett m komyati": "Garrett Komyati",
    "komyati, garrett": "Garrett Komyati",
    "komyati, garrett m": "Garrett Komyati",

    # James Lombardo (Jim)
    "jim": "James Lombardo",
    "jim lombardo": "James Lombardo",
    "james lombardo": "James Lombardo",
    "james r lombardo": "James Lombardo",
    "lombardo, james": "James Lombardo",
    "lombardo, james r": "James Lombardo",

    # Sean McLaughlin
    "sean": "Sean McLaughlin",
    "sean mclaughlin": "Sean McLaughlin",
    "mclaughlin, sean": "Sean McLaughlin",

    # Robin Montoni (many transcription variations)
    "robin": "Robin Montoni",
    "robin montoni": "Robin Montoni",
    "robin mantoni": "Robin Montoni",
    "robin mancini": "Robin Montoni",
    "robin mantone": "Robin Montoni",
    "robin mentoni": "Robin Montoni",
    "robin martoni": "Robin Montoni",
    "robin montali": "Robin Montoni",
    "miss robin": "Robin Montoni",
    "montoni, robin": "Robin Montoni",

    # Matthew Mueller
    "matthew": "Matthew Mueller",
    "matt": "Matthew Mueller",
    "matthew mueller": "Matthew Mueller",
    "mueller, matthew": "Matthew Mueller",

    # Andrew Rothman
    "andrew": "Andrew Rothman",
    "andrew rothman": "Andrew Rothman",
    "andrew b rothman": "Andrew Rothman",
    "rothman, andrew": "Andrew Rothman",
    "rothman, andrew b": "Andrew Rothman",
    "drew": "Andrew Rothman",

    # Jason Salamon
    "jason": "Jason Salamon",
    "jason salamon": "Jason Salamon",
    "jason a salamon": "Jason Salamon",
    "salamon, jason": "Jason Salamon",
    "salamon, jason a": "Jason Salamon",

    # Christian Salem
    "christian": "Christian Salem",
    "christian salem": "Christian Salem",
    "christian d salem": "Christian Salem",
    "salem, christian": "Christian Salem",
    "salem, christian d": "Christian Salem",

    # Mackenzie Scalise
    "mackenzie": "Mackenzie Scalise",
    "mckenzie": "Mackenzie Scalise",
    "mackenzie scalise": "Mackenzie Scalise",
    "scalise, mackenzie": "Mackenzie Scalise",

    # Davisha (single name)
    "davisha": "Davisha",

    # Lisa Rogers
    "lisa": "Lisa Rogers",
    "lisa rogers": "Lisa Rogers",
    "rogers, lisa": "Lisa Rogers",

    # Samuel Barnes
    "samuel": "Samuel Barnes",
    "sam": "Samuel Barnes",
    "samuel barnes": "Samuel Barnes",
    "barnes, samuel": "Samuel Barnes",

    # Tyler Trautman
    "tyler": "Tyler Trautman",
    "tyler trautman": "Tyler Trautman",
    "trautman, tyler": "Tyler Trautman",
}

# Names that are NOT employees (customers, etc.)
# These should be excluded from the employee dropdown
EXCLUDE_FROM_EMPLOYEES = [
    "Unknown",
    "unknown",
    "N/A",
    "Customer",
    "Client",
    "Caller",
    "Guest",
]


def canonicalize_employee_name(name: str) -> str:
    """
    Convert an employee name to its canonical form.

    Args:
        name: The raw employee name from the database

    Returns:
        The canonical employee name, or the original if not found
    """
    if not name:
        return None

    # Clean the name
    name_lower = name.strip().lower()

    # Check exclusions
    if name_lower in [e.lower() for e in EXCLUDE_FROM_EMPLOYEES]:
        return None

    # Handle multi-person entries (e.g., "Jim, Robin Montoni, Zach")
    if "," in name and not any(name_lower.startswith(p) for p in ["bello,", "blair,", "bradach,", "coverstone,", "eaton,", "fresenko,", "geissinger,", "gooden,", "james,", "komyati,", "kubicek,", "lombardo,", "mclaughlin,", "montoni,", "mueller,", "rothman,", "salamon,", "salem,", "scalise,", "rogers,", "barnes,"]):
        # Take the first recognized employee name
        parts = [p.strip() for p in name.split(",")]
        for part in parts:
            canonical = NAME_VARIATIONS.get(part.lower())
            if canonical:
                return canonical
        return parts[0]  # Return first part if no match

    # Look up in variations map
    if name_lower in NAME_VARIATIONS:
        return NAME_VARIATIONS[name_lower]

    # Check if it's already a canonical name
    for canonical in CANONICAL_EMPLOYEES:
        if name_lower == canonical.lower():
            return canonical

    # If it's a known first name, try to match
    first_name = name_lower.split()[0] if " " in name_lower else name_lower
    if first_name in NAME_VARIATIONS:
        return NAME_VARIATIONS[first_name]

    # Return as-is if not found (might be a customer misidentified as employee)
    return name


def get_canonical_employee_list() -> list:
    """
    Get the list of canonical employee names for dropdowns.

    Returns:
        Sorted list of canonical employee names
    """
    return sorted(CANONICAL_EMPLOYEES)


def is_employee(name: str) -> bool:
    """
    Check if a name is a known employee.

    Args:
        name: The name to check

    Returns:
        True if the name is a known employee or variation
    """
    if not name:
        return False

    name_lower = name.strip().lower()

    # Check exclusions
    if name_lower in [e.lower() for e in EXCLUDE_FROM_EMPLOYEES]:
        return False

    # Check if it's in the variations map
    if name_lower in NAME_VARIATIONS:
        return True

    # Check if it's a canonical name
    if name_lower in [e.lower() for e in CANONICAL_EMPLOYEES]:
        return True

    # Check first name only
    first_name = name_lower.split()[0] if " " in name_lower else name_lower
    if first_name in NAME_VARIATIONS:
        return True

    return False


def get_employee_first_names() -> list:
    """
    Get list of first names that match employees.
    Useful for quick lookups in transcripts.
    """
    first_names = set()
    for name in CANONICAL_EMPLOYEES:
        parts = name.split()
        if parts:
            first_names.add(parts[0].lower())
    return list(first_names)


def get_employee_name_variations(canonical_name: str) -> list:
    """
    Get all name variations that map to a canonical employee name.
    Used for database queries to match all possible spellings.

    Args:
        canonical_name: The canonical employee name (e.g., "James Lombardo")

    Returns:
        List of all variations including the canonical name
        e.g., ["James Lombardo", "jim", "jim lombardo", "james lombardo", ...]
    """
    if not canonical_name:
        return []

    variations = set()
    variations.add(canonical_name)  # Include canonical name

    # Find all variations that map to this canonical name
    for variation, canon in NAME_VARIATIONS.items():
        if canon == canonical_name:
            variations.add(variation)

    # Also add first name only (common in transcripts)
    parts = canonical_name.split()
    if parts:
        variations.add(parts[0].lower())  # First name lowercase
        variations.add(parts[0])  # First name as-is

    return list(variations)
