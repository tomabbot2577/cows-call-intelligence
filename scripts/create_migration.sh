#!/bin/bash
# Script to create initial database migration

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Activate virtual environment
source venv/bin/activate

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file for local development..."
    cat > .env <<EOF
# Local development database
DATABASE_URL=postgresql://recording_user:password@localhost:5432/call_recordings

# Other settings
ENVIRONMENT=development
LOG_LEVEL=INFO
EOF
fi

# Generate initial migration
echo "Generating initial database migration..."
alembic revision --autogenerate -m "Initial database schema"

echo "Migration created successfully!"
echo "To apply the migration, run: alembic upgrade head"