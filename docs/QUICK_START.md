# Call Recording System - Quick Start Guide

## 🚀 5-Minute Setup Checklist

### Prerequisites
- [ ] Hostinger VPS with Ubuntu 22.04 (4GB+ RAM)
- [ ] RingCentral Developer Account
- [ ] Google Cloud Account
- [ ] Root SSH access to VPS

---

## Step 1: Get Your Credentials (10 minutes)

### RingCentral
1. Visit https://developers.ringcentral.com
2. Create new REST API app with JWT auth
3. Copy these values:
   - Client ID: `___________________________`
   - Client Secret: `___________________________`
   - JWT Token: `___________________________`

### Google Drive
1. Visit https://console.cloud.google.com
2. Create project → Enable Drive API → Create Service Account
3. Download JSON key file
4. Create a Google Drive folder and share with service account email
5. Copy folder ID from URL: `___________________________`

---

## Step 2: VPS Initial Setup (5 minutes)

```bash
# SSH into your VPS
ssh root@YOUR_VPS_IP

# Run this to install dependencies with Python 3.11 (RECOMMENDED)
apt update && apt upgrade -y && \
apt install -y software-properties-common && \
add-apt-repository ppa:deadsnakes/ppa -y && \
apt update && \
apt install -y python3.11 python3.11-venv python3.11-dev python3-pip postgresql postgresql-contrib ffmpeg git nginx supervisor && \
systemctl enable postgresql

# OR use Python 3.10 (simpler, already on Ubuntu 22.04)
# apt update && apt upgrade -y && \
# apt install -y python3.10-venv python3.10-dev python3-pip postgresql postgresql-contrib ffmpeg git nginx supervisor && \
# systemctl enable postgresql
```

---

## Step 3: Database Setup (2 minutes)

```bash
# Create database (copy and run as block)
sudo -u postgres psql << EOF
CREATE DATABASE call_recordings;
CREATE USER call_system WITH PASSWORD 'ChangeThisPassword123!';
GRANT ALL PRIVILEGES ON DATABASE call_recordings TO call_system;
ALTER USER call_system CREATEDB;
EOF
```

---

## Step 4: Install Application (5 minutes)

```bash
# Download and setup (run as block)
cd /opt && \
git clone https://github.com/your-repo/call_recording_system.git && \
cd call_recording_system && \
python3.11 -m venv venv && \
source venv/bin/activate && \
python --version && \
pip install --upgrade pip && \
pip install -r requirements.txt

# Note: Replace python3.11 with python3.10 if you chose Python 3.10
```

---

## Step 5: Configure Environment (3 minutes)

```bash
# Create .env file
cp .env.example .env
nano .env
```

**Edit these required values:**
```env
DATABASE_URL=postgresql://call_system:ChangeThisPassword123!@localhost:5432/call_recordings
RINGCENTRAL_CLIENT_ID=your_actual_client_id
RINGCENTRAL_CLIENT_SECRET=your_actual_secret
RINGCENTRAL_JWT_TOKEN=your_actual_jwt_token
GOOGLE_CREDENTIALS_PATH=/opt/call_recording_system/config/google_service_account.json
GOOGLE_DRIVE_FOLDER_ID=your_folder_id
```

---

## Step 6: Upload Google Credentials (2 minutes)

```bash
# On your local machine
scp path/to/google_service_account.json root@YOUR_VPS_IP:/opt/call_recording_system/config/

# On VPS
chmod 600 /opt/call_recording_system/config/google_service_account.json
```

---

## Step 7: Initialize Database (1 minute)

```bash
cd /opt/call_recording_system
source venv/bin/activate
alembic upgrade head
```

---

## Step 8: Test Connections (2 minutes)

```bash
python scripts/test_connections.py
```

**All should show ✅ PASS**

---

## Step 9: Create Systemd Service (2 minutes)

```bash
cat > /etc/systemd/system/call-recording-processor.service << 'EOF'
[Unit]
Description=Call Recording Processing System
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/call_recording_system
Environment="PATH=/opt/call_recording_system/venv/bin"
ExecStart=/opt/call_recording_system/venv/bin/python -m src.cli.scheduler_cli start
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable call-recording-processor
```

---

## Step 10: Start Processing! (1 minute)

```bash
# Start the service
systemctl start call-recording-processor

# Check it's running
systemctl status call-recording-processor
```

---

## 🎉 You're Done!

### Process Historical Data (Optional)
```bash
cd /opt/call_recording_system
source venv/bin/activate

# Process last 60 days
python -m src.cli.scheduler_cli process-historical --days 60
```

### Daily Commands
```bash
# Check status
python -m src.cli.scheduler_cli status

# View summary
python -m src.cli.scheduler_cli summary

# Watch logs
journalctl -u call-recording-processor -f
```

---

## 📊 What Happens Next?

1. **Every Day at 2 AM**: System automatically processes new recordings
2. **Every Hour**: Health checks run
3. **Every 5 Minutes**: Metrics are collected
4. **Continuous**: Failed recordings retry after 24 hours

---

## 🆘 Quick Troubleshooting

### Service won't start?
```bash
journalctl -u call-recording-processor -n 50
python scripts/test_connections.py
```

### Need to reprocess a date?
```bash
python -m src.cli.scheduler_cli batch create -s 2024-01-15 -e 2024-01-15
```

### Check what's happening?
```bash
python -m src.cli.scheduler_cli summary
tail -f /opt/call_recording_system/logs/app.log
```

---

## 📝 Important Files

| What | Where |
|------|-------|
| Main Config | `/opt/call_recording_system/.env` |
| Logs | `/opt/call_recording_system/logs/app.log` |
| Service | `/etc/systemd/system/call-recording-processor.service` |
| Google Key | `/opt/call_recording_system/config/google_service_account.json` |

---

## 🔧 Common Tasks

```bash
# Always run from here with venv activated
cd /opt/call_recording_system
source venv/bin/activate

# Then run commands
python -m src.cli.scheduler_cli [command]
```

**Available Commands:**
- `status` - Check scheduler status
- `summary` - Processing summary
- `run-once` - Run processing now
- `retry-failed` - Retry failed recordings
- `process-historical --days N` - Process N days of history
- `batch create -s DATE -e DATE` - Process date range
- `batch list` - List active batches

---

## 📧 Setup Alerts (Optional)

### Email Alerts
1. Enable 2FA on Gmail
2. Generate app password
3. Add to `.env`:
```env
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=app-specific-password
ALERT_EMAIL=alerts@your-domain.com
```

### Slack Alerts
1. Create Slack webhook
2. Add to `.env`:
```env
SLACK_WEBHOOK=https://hooks.slack.com/services/YOUR/URL
```

---

## ✅ Health Check

Visit these endpoints to check system health:
```bash
# From VPS
curl http://localhost:8000/health
curl http://localhost:9090/metrics
```

---

## 📚 Need More Help?

- Full Setup Guide: `docs/SETUP_GUIDE.md`
- Operations Guide: `docs/OPERATIONS_GUIDE.md`
- Troubleshooting: Check logs first!
```bash
journalctl -u call-recording-processor -f
tail -f /opt/call_recording_system/logs/app.log
```