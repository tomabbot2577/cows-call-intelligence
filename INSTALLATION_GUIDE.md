# 📚 Installation & Setup Guide

## System Requirements

- **OS**: Ubuntu 20.04+ or similar Linux distribution
- **Python**: 3.11 (recommended) or 3.10
- **PostgreSQL**: 12 or higher
- **RAM**: Minimum 4GB
- **Storage**: 50GB+ for audio and transcript storage
- **Network**: Stable internet for API calls

## Step 1: System Preparation

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11
sudo apt install python3.11 python3.11-venv python3.11-dev -y

# Install PostgreSQL
sudo apt install postgresql postgresql-contrib -y

# Install git and other utilities
sudo apt install git curl wget build-essential -y
```

## Step 2: Clone Repository

```bash
cd /var/www
git clone https://github.com/yourusername/call-recording-system.git
cd call-recording-system
```

## Step 3: Python Environment Setup

```bash
# Create virtual environment (REQUIRED)
python3.11 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt
```

## Step 4: PostgreSQL Database Setup

```bash
# Switch to postgres user
sudo -u postgres psql

# In PostgreSQL prompt:
CREATE DATABASE call_recordings;
CREATE USER call_system WITH ENCRYPTED PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE call_recordings TO call_system;
\q

# Initialize database schema
python init_database.py
```

## Step 5: RingCentral Configuration

1. **Get RingCentral Credentials**:
   - Go to https://developers.ringcentral.com
   - Create a new app (Server-only, No UI)
   - Enable "Call Control" and "Call Management" permissions
   - Generate JWT token

2. **Configure in .env**:
```bash
RINGCENTRAL_CLIENT_ID=your_client_id
RINGCENTRAL_CLIENT_SECRET=your_client_secret
RINGCENTRAL_JWT_TOKEN=your_jwt_token
RINGCENTRAL_SERVER_URL=https://platform.ringcentral.com
```

## Step 6: Salad Cloud API Setup

1. **Get Salad Cloud API Key**:
   - Visit https://portal.salad.com
   - Create account or sign in
   - Navigate to API Keys section
   - Create new API key

2. **IMPORTANT Configuration**:
```bash
# Must use 'mst' organization for transcription
SALAD_API_KEY=your_salad_api_key
SALAD_ORG_NAME=mst  # DO NOT CHANGE THIS
SALAD_WEBHOOK_SECRET=your_webhook_secret
```

## Step 7: Google Drive Setup

### 7.1 Create Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create new project or select existing
3. Enable Google Drive API:
   ```
   APIs & Services → Enable APIs → Search "Google Drive API" → Enable
   ```

4. Create Service Account:
   ```
   IAM & Admin → Service Accounts → Create Service Account
   - Name: call-recording-system
   - ID: call-recording-system
   - Grant role: Editor
   ```

5. Create key:
   ```
   Service Account → Keys → Add Key → JSON
   ```

6. Download and save as `config/google_service_account.json`

### 7.2 Domain-Wide Delegation

1. In service account details, note the "Client ID"
2. Go to Google Admin Console (admin.google.com)
3. Security → API Controls → Domain-wide Delegation
4. Add new client:
   ```
   Client ID: [from step 1]
   Scopes: https://www.googleapis.com/auth/drive
   ```

### 7.3 Configure in .env

```bash
GOOGLE_CREDENTIALS_PATH=/var/www/call-recording-system/config/google_service_account.json
GOOGLE_DRIVE_FOLDER_ID=your_root_folder_id
GOOGLE_IMPERSONATE_EMAIL=admin@yourdomain.com
```

### 7.4 Create Folder Structure

```bash
python setup_google_drive_folders.py
```

This creates optimized folder hierarchy:
- 📦 AI_Processed_Calls
- 🗓️ By_Date
- 📞 By_Phone
- 👥 By_Customer
- 🤖 N8N_Workflows
- 🧠 LLM_Analysis

## Step 8: Environment Configuration

Create `.env` file with all settings:

```bash
# Copy example
cp .env.example .env

# Edit with your credentials
nano .env
```

Complete `.env` example:

```bash
# RingCentral
RINGCENTRAL_CLIENT_ID=REDACTED_CLIENT_ID
RINGCENTRAL_CLIENT_SECRET=your_secret
RINGCENTRAL_JWT_TOKEN=your_jwt
RINGCENTRAL_SERVER_URL=https://platform.ringcentral.com

# Database
DATABASE_URL="postgresql://call_system:password@localhost:5432/call_recordings"

# Salad Cloud
SALAD_API_KEY=your_api_key
SALAD_ORG_NAME=mst
SALAD_WEBHOOK_SECRET=your_webhook_secret

# Google Drive
GOOGLE_CREDENTIALS_PATH=/var/www/call-recording-system/config/google_service_account.json
GOOGLE_DRIVE_FOLDER_ID=1IbGtmzk85Q5gYAfdb2AwA9kLNE1EJLx0
GOOGLE_IMPERSONATE_EMAIL=admin@yourdomain.com

# Processing
BATCH_SIZE=50
MAX_WORKERS=4
DAILY_SCHEDULE_TIME=02:00
HISTORICAL_DAYS=30
```

## Step 9: Test Installation

```bash
# Test Salad API
python -c "
from src.transcription.salad_transcriber_enhanced import SaladTranscriberEnhanced
t = SaladTranscriberEnhanced()
print('✅ Salad API initialized')
"

# Test Google Drive
python check_google_drive.py

# Run complete pipeline test
python test_complete_pipeline.py
```

Expected output:
```
✅ Salad API initialized
✅ Google Drive connected
✅ All tests passed
```

## Step 10: Set Up Systemd Service (Optional)

```bash
# Create service file
sudo nano /etc/systemd/system/call-recording.service
```

Add:
```ini
[Unit]
Description=Call Recording Transcription Service
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/call-recording-system
Environment="PATH=/var/www/call-recording-system/venv/bin"
ExecStart=/var/www/call-recording-system/venv/bin/python src/scheduler/scheduler.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable call-recording
sudo systemctl start call-recording
sudo systemctl status call-recording
```

## Step 11: Set Up Monitoring (Optional)

```bash
# Install monitoring tools
pip install prometheus-client

# Configure alerts in .env
PROMETHEUS_ENABLED=true
ALERT_EMAIL=alerts@yourdomain.com
SLACK_WEBHOOK=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

## Verification Checklist

- [ ] Python 3.11 installed and venv created
- [ ] PostgreSQL database created and accessible
- [ ] RingCentral JWT token valid
- [ ] Salad API key working (org: mst)
- [ ] Google Service Account created with domain-wide delegation
- [ ] Google Drive folders created
- [ ] Test transcription successful
- [ ] Markdown files generated
- [ ] Files uploaded to Google Drive

## Troubleshooting

### Issue: "No module named 'salad_cloud_transcription_sdk'"
```bash
source venv/bin/activate
pip install salad-cloud-transcription-sdk==1.0.0a1
```

### Issue: "no_credits_available" from Salad
- Verify `SALAD_ORG_NAME=mst` in .env
- Check API key is valid
- Ensure account has credits

### Issue: Google Drive "Access Denied"
- Verify domain-wide delegation is enabled
- Check impersonation email has Drive access
- Confirm service account JSON is valid

### Issue: Database connection failed
```bash
# Check PostgreSQL status
sudo systemctl status postgresql

# Test connection
psql -U call_system -d call_recordings -h localhost
```

## Next Steps

1. **Configure N8N Webhooks**: Set up N8N workflows for automated processing
2. **Add LLM Analysis**: Configure OpenAI/Anthropic for enhanced analysis
3. **Set Up Backups**: Configure automated database and file backups
4. **Monitor Performance**: Set up Prometheus/Grafana dashboards

## Support

For issues or questions:
- Check [SYSTEM_STATE_BACKUP.md](SYSTEM_STATE_BACKUP.md)
- Review logs: `tail -f logs/app.log`
- GitHub Issues: https://github.com/yourusername/call-recording-system/issues

---
Installation Guide v2.0 | Last Updated: 2025-09-20