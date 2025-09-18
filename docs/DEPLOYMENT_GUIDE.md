# Call Recording System - Deployment & Debugging Guide

## Table of Contents
1. [File Transfer Methods](#file-transfer-methods)
2. [Deployment Process](#deployment-process)
3. [Remote Development Setup](#remote-development-setup)
4. [Debugging on VPS](#debugging-on-vps)
5. [Using Claude or VS Code Remote](#using-claude-or-vs-code-remote)
6. [Testing & Validation](#testing--validation)
7. [Common Deployment Issues](#common-deployment-issues)

---

## File Transfer Methods

### Method 1: Git Repository (Recommended)

**Step 1: Push to GitHub/GitLab/Bitbucket**
```bash
# On your local machine
cd /Users/steveabbey/claude/callrecord/call_recording_system

# Initialize git if not already done
git init
git add .
git commit -m "Initial deployment"

# Create repository on GitHub and push
git remote add origin https://github.com/yourusername/call-recording-system.git
git branch -M main
git push -u origin main
```

**Step 2: Clone on VPS**
```bash
# On VPS
cd /opt
git clone https://github.com/yourusername/call-recording-system.git call_recording_system
cd call_recording_system
```

### Method 2: Direct SCP Transfer

**Transfer entire project:**
```bash
# From local machine
cd /Users/steveabbey/claude/callrecord

# Create tar archive (excludes venv and large files)
tar -czf call_recording_system.tar.gz \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    --exclude='venv' \
    --exclude='.env' \
    --exclude='data/audio/*' \
    --exclude='logs/*' \
    call_recording_system/

# Transfer to VPS
scp call_recording_system.tar.gz root@YOUR_VPS_IP:/tmp/

# On VPS, extract files
ssh root@YOUR_VPS_IP
cd /opt
tar -xzf /tmp/call_recording_system.tar.gz
cd call_recording_system
```

### Method 3: Rsync (Best for Updates)

```bash
# From local machine - initial sync
rsync -avz --progress \
    --exclude 'venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.env' \
    --exclude 'data/' \
    --exclude 'logs/' \
    /Users/steveabbey/claude/callrecord/call_recording_system/ \
    root@YOUR_VPS_IP:/opt/call_recording_system/

# For subsequent updates (only changed files)
rsync -avz --progress --update \
    --exclude 'venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.env' \
    /Users/steveabbey/claude/callrecord/call_recording_system/ \
    root@YOUR_VPS_IP:/opt/call_recording_system/
```

---

## Deployment Process

### Step 1: Prepare VPS Environment

```bash
# SSH into VPS
ssh root@YOUR_VPS_IP

# Install system dependencies
apt update && apt upgrade -y

# Option A: Python 3.11 (RECOMMENDED - Better Performance)
apt install -y software-properties-common
add-apt-repository ppa:deadsnakes/ppa
apt update
apt install -y python3.11 python3.11-venv python3.11-dev python3-pip

# Option B: Python 3.10 (Default on Ubuntu 22.04)
# apt install -y python3.10 python3.10-venv python3.10-dev python3-pip

# Install other dependencies
apt install -y postgresql postgresql-contrib
apt install -y ffmpeg git curl wget
apt install -y supervisor nginx
apt install -y htop ncdu iotop  # Monitoring tools

# Setup PostgreSQL
sudo -u postgres psql << EOF
CREATE DATABASE call_recordings;
CREATE USER call_system WITH PASSWORD 'YourSecurePassword';
GRANT ALL PRIVILEGES ON DATABASE call_recordings TO call_system;
ALTER USER call_system CREATEDB;
EOF
```

### Step 2: Transfer Files

```bash
# Use one of the methods above (Git recommended)
# Example with Git:
cd /opt
git clone https://github.com/yourusername/call-recording-system.git call_recording_system
```

### Step 3: Setup Python Environment

```bash
cd /opt/call_recording_system

# Create virtual environment based on Python version installed
# For Python 3.11 (Recommended):
python3.11 -m venv venv

# OR for Python 3.10:
# python3.10 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Verify Python version
python --version

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt

# If you get memory errors with Whisper (common on 4GB VPS):
pip install --no-cache-dir -r requirements.txt

# OR add temporary swap space:
# fallocate -l 2G /swapfile
# chmod 600 /swapfile
# mkswap /swapfile
# swapon /swapfile
# pip install -r requirements.txt
# swapoff /swapfile && rm /swapfile
```

### Step 4: Configure Application

```bash
# Copy and edit environment file
cp .env.example .env
nano .env

# Set proper permissions
chmod 600 .env
chmod 600 config/google_service_account.json

# Create required directories
mkdir -p data/audio data/transcripts logs
chmod 755 data logs
```

### Step 5: Initialize Database

```bash
# Make sure you're in venv
source venv/bin/activate

# Run migrations
alembic upgrade head

# Verify tables created
sudo -u postgres psql -d call_recordings -c "\dt"
```

---

## Remote Development Setup

### Option 1: VS Code Remote SSH (Recommended for Development)

**On Local Machine:**
1. Install VS Code
2. Install "Remote - SSH" extension
3. Add SSH config:

```bash
# ~/.ssh/config
Host vps-call-recording
    HostName YOUR_VPS_IP
    User root
    Port 22
```

4. Connect via VS Code:
   - Press `Cmd+Shift+P` → "Remote-SSH: Connect to Host"
   - Select `vps-call-recording`
   - Open folder `/opt/call_recording_system`

**Benefits:**
- Edit files directly on VPS
- Integrated terminal
- Debugging capabilities
- Git integration

### Option 2: Claude Code via SSH (Direct Terminal)

**You don't need to install Claude on the VPS.** Instead:

```bash
# SSH with port forwarding for debugging
ssh -L 8000:localhost:8000 -L 9090:localhost:9090 root@YOUR_VPS_IP

# Now you can access VPS services locally:
# http://localhost:8000 - Health endpoint
# http://localhost:9090 - Metrics endpoint
```

### Option 3: Vim/Nano on VPS (Quick Edits)

```bash
# For quick edits directly on VPS
cd /opt/call_recording_system

# Edit Python files
nano src/scheduler/scheduler.py

# Edit configuration
nano .env

# View logs
less logs/app.log
```

---

## Debugging on VPS

### 1. Interactive Python Debugging

```bash
cd /opt/call_recording_system
source venv/bin/activate

# Start Python interactive shell with your app context
python
```

```python
# Test imports
from src.config.settings import Settings
from src.ringcentral.auth import RingCentralAuth

# Test database connection
from src.database.session import SessionManager
from src.database.config import DatabaseConfig

settings = Settings()
db_config = DatabaseConfig(settings.database_url)
session_manager = SessionManager(db_config)

with session_manager.get_session() as session:
    result = session.execute("SELECT COUNT(*) FROM call_recordings").scalar()
    print(f"Total recordings: {result}")

# Test RingCentral auth
auth = RingCentralAuth(
    client_id=settings.ringcentral_client_id,
    client_secret=settings.ringcentral_client_secret,
    jwt_token=settings.ringcentral_jwt_token,
    server_url=settings.ringcentral_server_url
)
auth.authenticate()
print(f"Access token: {auth.access_token[:20]}...")
```

### 2. Add Debug Logging

Create debug configuration:

```bash
# /opt/call_recording_system/debug_config.py
import logging
import sys

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/opt/call_recording_system/logs/debug.log')
    ]
)

# Set specific loggers to debug
logging.getLogger('src.scheduler').setLevel(logging.DEBUG)
logging.getLogger('src.ringcentral').setLevel(logging.DEBUG)
logging.getLogger('src.transcription').setLevel(logging.DEBUG)
```

### 3. Test Individual Components

```bash
# Create test scripts
cat > /opt/call_recording_system/test_component.py << 'EOF'
#!/usr/bin/env python
import sys
import logging

logging.basicConfig(level=logging.DEBUG)

# Test specific component
from src.config.settings import Settings
from src.scheduler.scheduler import ProcessingScheduler

settings = Settings()
print(f"Daily schedule: {settings.daily_schedule_time}")
print(f"Batch size: {settings.batch_size}")

# Add your test code here
EOF

python test_component.py
```

### 4. Monitor Real-Time Logs

```bash
# Open multiple terminal sessions for monitoring

# Terminal 1: Service logs
journalctl -u call-recording-processor -f

# Terminal 2: Application logs
tail -f /opt/call_recording_system/logs/app.log

# Terminal 3: Error grep
tail -f /opt/call_recording_system/logs/app.log | grep -E "ERROR|CRITICAL"

# Terminal 4: System resources
htop
```

### 5. Database Debugging

```bash
# Monitor database queries
sudo -u postgres psql -d call_recordings

# Enable query logging temporarily
ALTER SYSTEM SET log_statement = 'all';
SELECT pg_reload_conf();

# View query logs
tail -f /var/log/postgresql/postgresql-*.log

# Check active queries
SELECT pid, usename, state, query, query_start
FROM pg_stat_activity
WHERE datname = 'call_recordings';
```

---

## Using Claude or VS Code Remote

### VS Code Remote Debugging Setup

1. **Create launch.json:**

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Debug Scheduler",
            "type": "python",
            "request": "launch",
            "module": "src.cli.scheduler_cli",
            "args": ["run-once"],
            "cwd": "/opt/call_recording_system",
            "env": {
                "PYTHONPATH": "/opt/call_recording_system"
            }
        },
        {
            "name": "Test Connections",
            "type": "python",
            "request": "launch",
            "program": "${workspaceFolder}/scripts/test_connections.py",
            "cwd": "/opt/call_recording_system"
        }
    ]
}
```

2. **Set breakpoints in VS Code**
3. **Run with F5 key**

### Using pdb (Python Debugger) on VPS

```python
# Add breakpoints in code
import pdb

def process_recording(self, recording_id):
    pdb.set_trace()  # Debugger will stop here

    # Your code...
```

```bash
# Run with debugger
python -m pdb src/cli/scheduler_cli.py run-once

# pdb commands:
# n - next line
# s - step into
# c - continue
# l - list code
# p variable - print variable
# pp variable - pretty print
```

---

## Testing & Validation

### 1. Pre-Deployment Testing (Local)

```bash
# Run tests locally first
pytest tests/
python scripts/test_connections.py
```

### 2. Post-Deployment Testing (VPS)

```bash
cd /opt/call_recording_system
source venv/bin/activate

# Test all connections
python scripts/test_connections.py

# Test single recording processing
python -c "
from datetime import datetime, timedelta
from src.cli.scheduler_cli import create_scheduler
scheduler = create_scheduler()
scheduler.initialize_clients()
# Process just today
scheduler.process_historical(
    datetime.now().date(),
    datetime.now().date()
)
"

# Test health endpoint
curl http://localhost:8000/health

# Verify service can start
systemctl start call-recording-processor
systemctl status call-recording-processor
```

### 3. Smoke Tests

```bash
# Create smoke test script
cat > /opt/call_recording_system/smoke_test.sh << 'EOF'
#!/bin/bash
echo "Running smoke tests..."

# 1. Check service
systemctl is-active --quiet call-recording-processor && echo "✓ Service active" || echo "✗ Service not active"

# 2. Check database
sudo -u postgres psql -d call_recordings -c "SELECT 1;" &>/dev/null && echo "✓ Database accessible" || echo "✗ Database error"

# 3. Check Python imports
python -c "from src.scheduler import ProcessingScheduler" 2>/dev/null && echo "✓ Python imports work" || echo "✗ Import error"

# 4. Check disk space
DISK_USAGE=$(df /opt/call_recording_system | awk 'NR==2 {print $5}' | sed 's/%//')
[ "$DISK_USAGE" -lt 90 ] && echo "✓ Disk space OK" || echo "✗ Disk space low"

# 5. Check API endpoints
curl -s https://platform.ringcentral.com &>/dev/null && echo "✓ RingCentral reachable" || echo "✗ RingCentral unreachable"
EOF

chmod +x smoke_test.sh
./smoke_test.sh
```

---

## Common Deployment Issues

### Issue: Wrong Python Version

```bash
# Check current Python version
python3 --version

# Install correct Python version (3.11 recommended)
add-apt-repository ppa:deadsnakes/ppa
apt update
apt install python3.11 python3.11-venv python3.11-dev

# Recreate virtual environment with correct version
cd /opt/call_recording_system
rm -rf venv
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Verify
python --version  # Should show Python 3.11.x
```

### Issue: Module Import Errors

```bash
# Fix Python path
export PYTHONPATH=/opt/call_recording_system:$PYTHONPATH

# Or add to .env
echo "PYTHONPATH=/opt/call_recording_system" >> .env
```

### Issue: Permission Denied

```bash
# Fix file permissions
chown -R root:root /opt/call_recording_system
chmod 755 /opt/call_recording_system
chmod 600 /opt/call_recording_system/.env
chmod 600 /opt/call_recording_system/config/*.json
```

### Issue: Memory Errors During pip install

```bash
# Add swap space
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile

# Install with no cache
pip install --no-cache-dir -r requirements.txt

# Remove swap after
swapoff /swapfile
rm /swapfile
```

### Issue: Service Fails to Start

```bash
# Debug step by step
cd /opt/call_recording_system
source venv/bin/activate

# Try running directly
python -m src.cli.scheduler_cli start

# Check for errors
journalctl -u call-recording-processor -n 100 --no-pager

# Verify all files present
ls -la src/
ls -la src/scheduler/
ls -la src/cli/
```

### Issue: Database Connection Fails

```bash
# Test PostgreSQL connection
psql -U call_system -d call_recordings -h localhost

# Check PostgreSQL is listening
netstat -an | grep 5432

# Check pg_hba.conf
cat /etc/postgresql/*/main/pg_hba.conf | grep -v "^#"

# Should have:
# local   all             all                                     md5
# host    all             all             127.0.0.1/32            md5
```

---

## Deployment Checklist

- [ ] System dependencies installed
- [ ] PostgreSQL database created
- [ ] Files transferred to `/opt/call_recording_system`
- [ ] Virtual environment created
- [ ] Dependencies installed (`requirements.txt`)
- [ ] `.env` file configured with credentials
- [ ] Google service account JSON uploaded
- [ ] Database migrations run
- [ ] Test connections script passes
- [ ] Systemd service created
- [ ] Service starts successfully
- [ ] Logs show no errors
- [ ] Health endpoint responds
- [ ] Historical processing tested (1 day)
- [ ] Monitoring configured

---

## Quick Debug Commands

```bash
# View recent errors
grep -E "ERROR|CRITICAL" /opt/call_recording_system/logs/app.log | tail -20

# Check what's running
ps aux | grep python

# Check network connections
netstat -tulpn | grep python

# Check CPU/Memory usage
htop

# Database connection test
echo "SELECT 1;" | sudo -u postgres psql -d call_recordings

# Python module test
python -c "from src.scheduler import ProcessingScheduler; print('✓ Imports work')"

# Service restart
systemctl restart call-recording-processor

# Emergency stop
systemctl stop call-recording-processor
pkill -f scheduler_cli
```