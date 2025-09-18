#!/usr/bin/env python3
"""
Check Python version compatibility for Call Recording System
"""

import sys
import subprocess
import platform

# Define version requirements
MIN_VERSION = (3, 10)
MAX_VERSION = (3, 12)
RECOMMENDED_VERSION = (3, 11)

def check_version():
    """Check if current Python version is compatible"""
    current = sys.version_info[:2]

    print("=" * 50)
    print("Python Version Compatibility Check")
    print("=" * 50)
    print(f"Current Python: {platform.python_version()}")
    print(f"Location: {sys.executable}")
    print()

    # Check compatibility
    if current < MIN_VERSION:
        print(f"❌ ERROR: Python {current[0]}.{current[1]} is too old")
        print(f"   Minimum required: Python {MIN_VERSION[0]}.{MIN_VERSION[1]}")
        return False

    elif current > MAX_VERSION:
        print(f"⚠️  WARNING: Python {current[0]}.{current[1]} is newer than tested versions")
        print(f"   Maximum tested: Python {MAX_VERSION[0]}.{MAX_VERSION[1]}")
        print("   Some packages may have compatibility issues")
        print("   Consider using Python 3.11 or 3.12")
        return True

    elif current == RECOMMENDED_VERSION:
        print(f"✅ PERFECT: Python {current[0]}.{current[1]} is the recommended version")
        print("   Optimal performance and compatibility")
        return True

    else:
        print(f"✅ OK: Python {current[0]}.{current[1]} is compatible")
        if current < RECOMMENDED_VERSION:
            print(f"   Note: Python {RECOMMENDED_VERSION[0]}.{RECOMMENDED_VERSION[1]} is recommended for better performance")
        return True

def check_packages():
    """Check if critical packages can be imported"""
    print("\nChecking critical package compatibility:")
    print("-" * 40)

    packages = [
        ("whisper", "OpenAI Whisper"),
        ("torch", "PyTorch"),
        ("numpy", "NumPy"),
        ("sqlalchemy", "SQLAlchemy"),
        ("pydantic", "Pydantic"),
        ("librosa", "Librosa"),
        ("psycopg2", "PostgreSQL Driver"),
    ]

    all_ok = True
    for module, name in packages:
        try:
            __import__(module)
            print(f"✅ {name:20} - OK")
        except ImportError:
            print(f"❌ {name:20} - Not installed")
            all_ok = False
        except Exception as e:
            print(f"⚠️  {name:20} - Error: {e}")
            all_ok = False

    return all_ok

def suggest_installation():
    """Suggest installation commands based on OS"""
    print("\n" + "=" * 50)
    print("Installation Recommendations")
    print("=" * 50)

    if sys.platform == "linux":
        print("\nFor Ubuntu/Debian:")
        print("  # Python 3.11 (Recommended)")
        print("  sudo add-apt-repository ppa:deadsnakes/ppa")
        print("  sudo apt update")
        print("  sudo apt install python3.11 python3.11-venv python3.11-dev")
        print()
        print("  # Python 3.10 (Stable)")
        print("  sudo apt install python3.10 python3.10-venv python3.10-dev")

    elif sys.platform == "darwin":
        print("\nFor macOS:")
        print("  # Using Homebrew")
        print("  brew install python@3.11")
        print()
        print("  # Using pyenv")
        print("  pyenv install 3.11.7")
        print("  pyenv local 3.11.7")

    elif sys.platform == "win32":
        print("\nFor Windows:")
        print("  Download from https://www.python.org/downloads/")
        print("  Recommended: Python 3.11.7")

def main():
    """Main execution"""
    # Check Python version
    version_ok = check_version()

    # Try to check packages if in virtual environment
    if 'venv' in sys.executable or 'virtualenv' in sys.executable:
        print("\nVirtual environment detected")
        packages_ok = check_packages()
    else:
        print("\nNo virtual environment detected")
        print("Create one with: python3.11 -m venv venv")
        packages_ok = False

    # Summary
    print("\n" + "=" * 50)
    if version_ok and packages_ok:
        print("✅ System is ready for Call Recording System")
    elif version_ok:
        print("✅ Python version is compatible")
        print("⚠️  Install required packages: pip install -r requirements.txt")
    else:
        suggest_installation()
        sys.exit(1)

if __name__ == "__main__":
    main()