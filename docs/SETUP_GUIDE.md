# Call Recording System - Complete Setup Guide

## Prerequisites

- Hostinger VPS KVM4 instance (Ubuntu 22.04 LTS recommended)
- RingCentral Developer Account
- Google Cloud Platform Account
- Domain name (optional, for web interface)

---

## 1. RingCentral API Credentials Setup

### Step 1: Create RingCentral Developer Account
1. Go to [https://developers.ringcentral.com](https://developers.ringcentral.com)
2. Sign up for a developer account
3. Log in to the Developer Console

### Step 2: Create a New Application
1. Click "Create App" in the dashboard
2. Select **"REST API App"**
3. Configure the app:
   - **App Name**: "Call Recording Transcription System"
   - **App Type**: Select "Private"
   - **Platform Type**: Select "Server/Web"
   - **OAuth Redirect URI**: Not needed for JWT auth

### Step 3: Enable Required Permissions
In the app settings, enable these permissions:
- **Call Log**: Read call log records
- **Call Recording**: Download call recordings
- **ReadAccounts**: Read account info
- **ReadCallLog**: Read call log
- **ReadCallRecording**: Download recordings

### Step 4: Generate JWT Credentials
1. In your app settings, go to "Credentials"
2. Select **"JWT auth flow"**
3. Click "Generate JWT"
4. **SAVE THESE SECURELY**:
   ```
   Client ID: <your-client-id>
   Client Secret: <your-client-secret>
   JWT Token: <your-jwt-token>
   ```

### Step 5: Set Environment (Production vs Sandbox)
- For testing: Use Sandbox environment
- For production: Submit app for review, then use Production environment
- Server URL:
  - Sandbox: `https://platform.devtest.ringcentral.com`
  - Production: `https://platform.ringcentral.com`

---

## 2. Google Drive API Setup

### Step 1: Create Google Cloud Project
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project: "Call Recording Transcripts"
3. Note your **Project ID**

### Step 2: Enable Google Drive API
1. Go to "APIs & Services" → "Library"
2. Search for "Google Drive API"
3. Click and enable it

### Step 3: Create Service Account
1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "Service Account"
3. Fill in:
   - **Service Account Name**: "call-recording-uploader"
   - **Service Account ID**: Auto-generated
   - **Description**: "Service account for uploading call transcripts"
4. Click "Create and Continue"
5. Grant role: "Basic" → "Editor" (or create custom role)
6. Click "Done"

### Step 4: Generate Service Account Key
1. Click on the created service account
2. Go to "Keys" tab
3. Click "Add Key" → "Create new key"
4. Select **JSON** format
5. Download the key file
6. **SAVE THIS FILE SECURELY** as `google_service_account.json`

### Step 5: Create Google Drive Folder
1. Log into Google Drive with your organization account
2. Create a folder: "Call_Transcripts"
3. Right-click → "Share" → Add the service account email
   - Email format: `service-account-name@project-id.iam.gserviceaccount.com`
   - Give "Editor" permissions
4. Copy the folder ID from the URL:
   - URL: `https://drive.google.com/drive/folders/FOLDER_ID_HERE`

---

## 3. VPS Setup (Hostinger KVM4)

### Step 1: Access Your VPS
```bash
# SSH into your VPS
ssh root@your-vps-ip

# Update system
apt update && apt upgrade -y
```

### Step 2: Install System Dependencies
```bash
# Option A: Install Python 3.11 (RECOMMENDED - 25% faster)
apt install software-properties-common -y
add-apt-repository ppa:deadsnakes/ppa
apt update
apt install python3.11 python3.11-venv python3.11-dev python3-pip -y

# Option B: Use Python 3.10 (Default on Ubuntu 22.04)
# apt install python3.10 python3.10-venv python3.10-dev python3-pip -y

# Install PostgreSQL
apt install postgresql postgresql-contrib -y

# Install ffmpeg for audio processing
apt install ffmpeg -y

# Install git
apt install git -y

# Install nginx (optional, for web interface)
apt install nginx -y

# Install supervisor for process management
apt install supervisor -y
```

### Step 3: Setup PostgreSQL Database
```bash
# Switch to postgres user
sudo -u postgres psql

# Create database and user
CREATE DATABASE call_recordings;
CREATE USER call_system WITH PASSWORD 'your_secure_password_here';
GRANT ALL PRIVILEGES ON DATABASE call_recordings TO call_system;
ALTER USER call_system CREATEDB;
\q

# Enable PostgreSQL to start on boot
systemctl enable postgresql
```

### Step 4: Create Application Directory
```bash
# Create app directory
mkdir -p /opt/call_recording_system
cd /opt/call_recording_system

# Clone or upload your code
git clone https://github.com/your-repo/call_recording_system.git .
# OR use SCP to upload:
# scp -r local_path/* root@your-vps-ip:/opt/call_recording_system/
```

### Step 5: Setup Python Environment
```bash
# Create virtual environment (use the Python version you installed)
# For Python 3.11:
python3.11 -m venv venv

# OR for Python 3.10:
# python3.10 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Verify Python version
python --version

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# If you encounter memory errors (common on 4GB VPS):
# pip install --no-cache-dir -r requirements.txt
```

### Step 6: Configure Environment Variables
```bash
# Create .env file
nano /opt/call_recording_system/.env
```

Add the following content:
```env
# Database
DATABASE_URL=postgresql://call_system:your_secure_password_here@localhost:5432/call_recordings

# RingCentral API
RINGCENTRAL_CLIENT_ID=your_client_id_here
RINGCENTRAL_CLIENT_SECRET=your_client_secret_here
RINGCENTRAL_JWT_TOKEN=your_jwt_token_here
RINGCENTRAL_SERVER_URL=https://platform.ringcentral.com
RINGCENTRAL_ACCOUNT_ID=your_account_id_here

# Google Drive
GOOGLE_CREDENTIALS_PATH=/opt/call_recording_system/config/google_service_account.json
GOOGLE_DRIVE_FOLDER_ID=your_folder_id_here

# Whisper Settings
WHISPER_MODEL=base
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8

# Processing Settings
BATCH_SIZE=50
MAX_WORKERS=4
DAILY_SCHEDULE_TIME=02:00
HISTORICAL_DAYS=60
MAX_RETRIES=3

# Monitoring
PROMETHEUS_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password_here
ALERT_EMAIL=alerts@your-domain.com
SLACK_WEBHOOK=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# Storage Paths
AUDIO_STORAGE_PATH=/opt/call_recording_system/data/audio
TRANSCRIPT_STORAGE_PATH=/opt/call_recording_system/data/transcripts
LOG_FILE_PATH=/opt/call_recording_system/logs/app.log
```

### Step 7: Upload Google Service Account Key
```bash
# Create config directory
mkdir -p /opt/call_recording_system/config

# Upload the JSON key file
# From your local machine:
scp google_service_account.json root@your-vps-ip:/opt/call_recording_system/config/

# Set proper permissions
chmod 600 /opt/call_recording_system/config/google_service_account.json
```

### Step 8: Initialize Database
```bash
cd /opt/call_recording_system
source venv/bin/activate

# Run Alembic migrations
alembic upgrade head

# Verify database tables
sudo -u postgres psql -d call_recordings -c "\dt"
```

---

## 4. Systemd Service Configuration

### Step 1: Create Systemd Service File
```bash
nano /etc/systemd/system/call-recording-processor.service
```

Add the following content:
```ini
[Unit]
Description=Call Recording Processing System
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/call_recording_system
Environment="PATH=/opt/call_recording_system/venv/bin"
ExecStart=/opt/call_recording_system/venv/bin/python -m src.cli.scheduler_cli start
Restart=always
RestartSec=10
StandardOutput=append:/opt/call_recording_system/logs/service.log
StandardError=append:/opt/call_recording_system/logs/service-error.log

[Install]
WantedBy=multi-user.target
```

### Step 2: Enable and Start Service
```bash
# Reload systemd
systemctl daemon-reload

# Enable service to start on boot
systemctl enable call-recording-processor.service

# Start the service
systemctl start call-recording-processor.service

# Check service status
systemctl status call-recording-processor.service

# View logs
journalctl -u call-recording-processor.service -f
```

---

## 5. Email Notifications Setup (Gmail)

### Step 1: Enable 2-Factor Authentication
1. Go to Google Account settings
2. Enable 2-factor authentication

### Step 2: Generate App Password
1. Go to [Google App Passwords](https://myaccount.google.com/apppasswords)
2. Select "Mail" and your device
3. Generate password
4. Use this password in SMTP_PASSWORD environment variable

---

## 6. Slack Notifications Setup

### Step 1: Create Slack App
1. Go to [Slack API](https://api.slack.com/apps)
2. Click "Create New App"
3. Choose "From scratch"
4. Name: "Call Recording Alerts"

### Step 2: Create Incoming Webhook
1. Go to "Incoming Webhooks" in your app settings
2. Toggle "Activate Incoming Webhooks" to ON
3. Click "Add New Webhook to Workspace"
4. Select the channel for alerts
5. Copy the Webhook URL
6. Add to SLACK_WEBHOOK environment variable

---

## 7. Initial Processing

### Step 1: Test Connection
```bash
cd /opt/call_recording_system
source venv/bin/activate

# Test RingCentral connection
python -m src.cli.test_connection

# Test Google Drive connection
python -m src.cli.test_drive
```

### Step 2: Process Historical Data
```bash
# Process last 60 days of recordings
python -m src.cli.scheduler_cli process-historical --days 60

# Or specific date range
python -m src.cli.scheduler_cli batch create -s 2024-01-01 -e 2024-12-31 -w 4
```

### Step 3: Monitor Processing
```bash
# Check status
python -m src.cli.scheduler_cli status

# View summary
python -m src.cli.scheduler_cli summary

# Check logs
tail -f /opt/call_recording_system/logs/app.log
```

---

## 8. Security Best Practices

### File Permissions
```bash
# Secure sensitive files
chmod 600 /opt/call_recording_system/.env
chmod 600 /opt/call_recording_system/config/google_service_account.json
chmod 700 /opt/call_recording_system/data

# Create separate user (optional)
useradd -m -s /bin/bash callsystem
chown -R callsystem:callsystem /opt/call_recording_system
```

### Firewall Configuration
```bash
# Install ufw
apt install ufw -y

# Configure firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp  # If using web interface
ufw allow 443/tcp # If using HTTPS
ufw --force enable
```

### SSL Certificate (Optional)
```bash
# Install certbot for Let's Encrypt
apt install certbot python3-certbot-nginx -y

# Get certificate
certbot --nginx -d your-domain.com
```

---

## 9. Monitoring Setup

### Prometheus Metrics Endpoint
```bash
# The application exposes metrics at:
http://localhost:9090/metrics

# Configure Prometheus to scrape this endpoint
```

### Health Check Endpoint
```bash
# Check system health
curl http://localhost:8000/health
```

---

## 10. Troubleshooting

### Check Service Logs
```bash
# System service logs
journalctl -u call-recording-processor -n 100

# Application logs
tail -f /opt/call_recording_system/logs/app.log

# Database logs
tail -f /var/log/postgresql/postgresql-*.log
```

### Common Issues

#### Issue: JWT Token Invalid
- Verify token hasn't expired
- Check you're using correct environment (sandbox vs production)
- Regenerate token if needed

#### Issue: Google Drive Upload Fails
- Verify service account has access to folder
- Check folder ID is correct
- Ensure service account key file is valid

#### Issue: Out of Memory
- Adjust WHISPER_MODEL to smaller size (tiny, base)
- Reduce MAX_WORKERS in environment
- Increase swap space:
```bash
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

#### Issue: Database Connection Failed
- Check PostgreSQL is running: `systemctl status postgresql`
- Verify credentials in .env file
- Check database exists: `sudo -u postgres psql -l`

---

## 11. Maintenance

### Daily Tasks (Automated)
- Processing runs at scheduled time
- Health checks every hour
- Metrics collection every 5 minutes

### Weekly Tasks
```bash
# Check disk space
df -h

# Clean old audio files (if keeping locally)
find /opt/call_recording_system/data/audio -mtime +7 -delete

# Review error logs
grep ERROR /opt/call_recording_system/logs/app.log | tail -50
```

### Monthly Tasks
```bash
# Update system packages
apt update && apt upgrade -y

# Vacuum PostgreSQL database
sudo -u postgres vacuumdb -d call_recordings -z

# Archive old logs
tar -czf logs_$(date +%Y%m).tar.gz /opt/call_recording_system/logs/*.log.*
```

---

## Support Contacts

- **RingCentral Support**: https://support.ringcentral.com
- **Google Cloud Support**: https://cloud.google.com/support
- **Hostinger Support**: Your hosting control panel

---

## Quick Command Reference

```bash
# Start service
systemctl start call-recording-processor

# Stop service
systemctl stop call-recording-processor

# Restart service
systemctl restart call-recording-processor

# Process historical data
python -m src.cli.scheduler_cli process-historical --days 30

# Retry failed recordings
python -m src.cli.scheduler_cli retry-failed

# Get status
python -m src.cli.scheduler_cli status

# View logs
journalctl -u call-recording-processor -f
```