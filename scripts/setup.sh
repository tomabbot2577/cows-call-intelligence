#!/bin/bash
# Complete automated setup script for RingCentral Call Recording System
# This script sets up the environment on Ubuntu 22.04 LTS

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[+]${NC} $1"
}

print_error() {
    echo -e "${RED}[!]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[*]${NC} $1"
}

echo "=========================================="
echo "RingCentral Call Recording System Setup"
echo "=========================================="
echo ""

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   print_error "This script should not be run as root!"
   exit 1
fi

# System update
print_status "Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install system dependencies
print_status "Installing system dependencies..."
sudo apt install -y \
    python3.10 python3.10-venv python3.10-dev \
    postgresql postgresql-contrib \
    ffmpeg libsndfile1 sox libsox-fmt-all \
    nginx certbot python3-certbot-nginx \
    git curl wget build-essential \
    libssl-dev libffi-dev \
    htop iotop ncdu

# Create application directory
print_status "Creating application directory structure..."
sudo mkdir -p /opt/call_recordings
sudo chown $USER:$USER /opt/call_recordings

# Check if we're in development or production
if [ -d "/Users" ]; then
    print_warning "Development environment detected (macOS)"
    BASE_DIR="$(pwd)/call_recording_system"
else
    print_status "Production environment detected"
    BASE_DIR="/opt/call_recordings"

    # Copy files to production location
    if [ -d "call_recording_system" ]; then
        cp -r call_recording_system/* $BASE_DIR/
    fi
fi

cd $BASE_DIR

# Setup Python environment
print_status "Setting up Python virtual environment..."
python3.10 -m venv venv
source venv/bin/activate

# Install Python packages
print_status "Installing Python packages..."
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# Download Whisper model
print_status "Downloading Whisper base model..."
python -c "import whisper; whisper.load_model('base')"

# Setup PostgreSQL (only in production)
if [ ! -d "/Users" ]; then
    print_status "Setting up PostgreSQL database..."

    # Generate secure password
    DB_PASSWORD=$(openssl rand -base64 32)

    sudo -u postgres psql <<EOF
CREATE DATABASE call_recordings;
CREATE USER recording_user WITH PASSWORD '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE call_recordings TO recording_user;
EOF

    print_warning "Database password: $DB_PASSWORD"
    print_warning "Please save this password in your .env file"
fi

# Create necessary directories
print_status "Creating necessary directories..."
mkdir -p logs temp archive credentials

# Setup environment file
if [ ! -f ".env" ]; then
    print_status "Creating .env file from template..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        print_warning "Please edit .env file with your credentials"
    else
        print_warning ".env.example not found, creating basic .env"
        cat > .env <<EOF
# RingCentral Configuration
RINGCENTRAL_JWT=""

# Google Drive Configuration
GOOGLE_DRIVE_FOLDER_ID=""

# Database Configuration
DATABASE_URL="postgresql://recording_user:${DB_PASSWORD:-your_password}@localhost/call_recordings"

# Monitoring Configuration
SENTRY_DSN=""
SLACK_WEBHOOK=""

# Encryption Key (32 bytes base64 encoded)
ENCRYPTION_KEY="$(openssl rand -base64 32)"
EOF
    fi
fi

# Set proper permissions
print_status "Setting file permissions..."
chmod 600 .env
chmod 700 credentials/

# Setup systemd services (only in production)
if [ ! -d "/Users" ] && [ -d "systemd" ]; then
    print_status "Installing systemd services..."
    sudo cp systemd/*.service /etc/systemd/system/
    sudo systemctl daemon-reload

    # Don't enable yet - need configuration first
    print_warning "Services installed but not enabled"
    print_warning "Run 'sudo systemctl enable call-recording-processor' after configuration"
fi

# Setup log rotation (only in production)
if [ ! -d "/Users" ] && [ -d "logrotate" ]; then
    print_status "Setting up log rotation..."
    sudo cp logrotate/call-recordings /etc/logrotate.d/
fi

# Create cron jobs (only in production)
if [ ! -d "/Users" ]; then
    print_status "Setting up cron jobs..."

    # Add daily processing cron job
    (crontab -l 2>/dev/null || true; echo "0 2 * * * $BASE_DIR/scripts/daily_process.sh") | crontab -

    # Add hourly health check
    (crontab -l 2>/dev/null || true; echo "0 * * * * $BASE_DIR/scripts/health_check.sh") | crontab -
fi

# Initialize database schema
print_status "Initializing database schema..."
if command -v alembic &> /dev/null; then
    alembic init alembic 2>/dev/null || true
    print_warning "Database migration setup initialized"
    print_warning "Run 'alembic upgrade head' after creating migrations"
fi

# Create initial project structure files
print_status "Creating initial source files..."

# Create main.py placeholder
cat > src/main.py <<'EOF'
#!/usr/bin/env python3
"""
RingCentral Call Recording Processor
Main entry point for the application
"""

import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Config
from src.processor import RecordingProcessor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """Main entry point"""
    logger.info("Starting RingCentral Call Recording Processor")

    try:
        config = Config()
        processor = RecordingProcessor(config)
        processor.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
EOF

chmod +x src/main.py

print_status "Setup complete!"
echo ""
echo "=========================================="
echo "Next Steps:"
echo "1. Edit .env file with your credentials"
echo "2. Add Google Service Account JSON to credentials/"
echo "3. Run database migrations"
echo "4. Test the setup with: python src/main.py --test"
echo "5. Enable systemd services when ready"
echo "=========================================="