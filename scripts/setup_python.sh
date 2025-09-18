#!/bin/bash

# Python Setup Script for Call Recording System
# This script helps install the correct Python version on your VPS

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "========================================="
echo "Python Setup for Call Recording System"
echo "========================================="
echo ""

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VERSION=$VERSION_ID
else
    echo -e "${RED}Cannot detect OS version${NC}"
    exit 1
fi

echo "Detected OS: $OS $VERSION"
echo ""

# Function to check Python version
check_python() {
    local py_cmd=$1
    if command -v $py_cmd > /dev/null 2>&1; then
        local version=$($py_cmd --version 2>&1 | awk '{print $2}')
        echo -e "${GREEN}✓${NC} Found $py_cmd (version $version)"
        return 0
    else
        return 1
    fi
}

# Check existing Python installations
echo "Checking existing Python installations..."
echo "-----------------------------------------"

PYTHON_FOUND=false
RECOMMENDED_PYTHON=""

# Check for Python versions (best to worst)
for py_version in python3.11 python3.10 python3.12 python3; do
    if check_python $py_version; then
        PYTHON_FOUND=true
        if [ -z "$RECOMMENDED_PYTHON" ]; then
            RECOMMENDED_PYTHON=$py_version
        fi
    fi
done

echo ""

# If Python 3.11 not found, offer to install it
if ! command -v python3.11 > /dev/null 2>&1; then
    echo -e "${YELLOW}Python 3.11 (recommended) is not installed${NC}"
    read -p "Would you like to install Python 3.11? (y/n) " -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Installing Python 3.11..."

        if [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
            # Ubuntu/Debian installation
            apt-get update
            apt-get install -y software-properties-common
            add-apt-repository -y ppa:deadsnakes/ppa
            apt-get update
            apt-get install -y python3.11 python3.11-venv python3.11-dev python3.11-distutils

            echo -e "${GREEN}✓${NC} Python 3.11 installed successfully"
            RECOMMENDED_PYTHON="python3.11"

        elif [ "$OS" = "centos" ] || [ "$OS" = "rhel" ] || [ "$OS" = "fedora" ]; then
            # RHEL/CentOS/Fedora installation
            yum install -y gcc openssl-devel bzip2-devel libffi-devel zlib-devel

            cd /tmp
            wget https://www.python.org/ftp/python/3.11.7/Python-3.11.7.tgz
            tar -xzf Python-3.11.7.tgz
            cd Python-3.11.7
            ./configure --enable-optimizations
            make altinstall

            echo -e "${GREEN}✓${NC} Python 3.11 installed successfully"
            RECOMMENDED_PYTHON="python3.11"

        else
            echo -e "${RED}Unsupported OS for automatic Python installation${NC}"
            echo "Please install Python 3.11 manually"
        fi
    fi
elif command -v python3.11 > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Python 3.11 is already installed (recommended version)"
    RECOMMENDED_PYTHON="python3.11"
fi

echo ""
echo "========================================="
echo "Setup Virtual Environment"
echo "========================================="
echo ""

# Check if we're in the right directory
if [ ! -f "requirements.txt" ]; then
    echo -e "${YELLOW}Warning: requirements.txt not found${NC}"
    echo "Please run this script from the project root directory"
    echo "Example: cd /opt/call_recording_system && ./scripts/setup_python.sh"
    exit 1
fi

# Check if venv already exists
if [ -d "venv" ]; then
    echo -e "${YELLOW}Virtual environment already exists${NC}"
    read -p "Would you like to recreate it? (y/n) " -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Removing old virtual environment..."
        rm -rf venv
    else
        echo "Keeping existing virtual environment"
        echo "Activate it with: source venv/bin/activate"
        exit 0
    fi
fi

# Create virtual environment
if [ -n "$RECOMMENDED_PYTHON" ]; then
    echo "Creating virtual environment with $RECOMMENDED_PYTHON..."
    $RECOMMENDED_PYTHON -m venv venv

    # Activate and verify
    source venv/bin/activate

    echo -e "${GREEN}✓${NC} Virtual environment created"
    echo "Python version in venv: $(python --version)"

    # Upgrade pip
    echo "Upgrading pip..."
    pip install --upgrade pip > /dev/null 2>&1
    echo -e "${GREEN}✓${NC} Pip upgraded"

    # Offer to install requirements
    read -p "Install requirements.txt now? (y/n) " -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Installing requirements..."
        echo "(This may take several minutes)"

        # Check available memory
        AVAILABLE_MEM=$(free -m | awk 'NR==2{print $7}')
        if [ "$AVAILABLE_MEM" -lt 2000 ]; then
            echo -e "${YELLOW}Low memory detected ($AVAILABLE_MEM MB)${NC}"
            echo "Using --no-cache-dir to save memory..."
            pip install --no-cache-dir -r requirements.txt
        else
            pip install -r requirements.txt
        fi

        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓${NC} Requirements installed successfully"
        else
            echo -e "${RED}Failed to install some requirements${NC}"
            echo "You may need to install them manually"
        fi
    fi

    echo ""
    echo "========================================="
    echo -e "${GREEN}Setup Complete!${NC}"
    echo "========================================="
    echo ""
    echo "Virtual environment location: ./venv"
    echo "Python version: $($RECOMMENDED_PYTHON --version)"
    echo ""
    echo "To activate the virtual environment:"
    echo -e "${BLUE}source venv/bin/activate${NC}"
    echo ""
    echo "To test the installation:"
    echo -e "${BLUE}python scripts/check_python_version.py${NC}"
    echo -e "${BLUE}python scripts/test_connections.py${NC}"

else
    echo -e "${RED}No suitable Python version found${NC}"
    echo "Please install Python 3.10, 3.11, or 3.12 manually"
    exit 1
fi