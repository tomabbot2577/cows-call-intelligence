# Where to Place Your RingCentral Credentials

## ⚠️ IMPORTANT SECURITY NOTICE

**NEVER commit credentials to git!** The credentials you've shared should be placed in the `.env` file which is gitignored.

## Credential Placement Guide

### 1. LOCAL DEVELOPMENT (Your Machine)

Create or edit the `.env` file in the project root:
```bash
cd /Users/steveabbey/claude/callrecord/call_recording_system
nano .env
```

Add your credentials:
```env
# RingCentral API
RINGCENTRAL_CLIENT_ID=REDACTED_CLIENT_ID
RINGCENTRAL_CLIENT_SECRET=REDACTED_CLIENT_SECRET
RINGCENTRAL_JWT_TOKEN=eyJraWQiOiI4NzYyZjU5OGQwNTk0NGRiODZiZjVjYTk3ODA0NzYwOCIsInR5cCI6IkpXVCIsImFsZyI6IlJTMjU2In0...
RINGCENTRAL_SERVER_URL=https://platform.ringcentral.com
```

### 2. VPS DEPLOYMENT (Production Server)

On your VPS, create the `.env` file:
```bash
ssh root@YOUR_VPS_IP
cd /opt/call_recording_system
nano .env
```

Add the same credentials as above.

### 3. FILE PERMISSIONS (Critical!)

**On VPS, secure the .env file:**
```bash
# Set restrictive permissions
chmod 600 /opt/call_recording_system/.env

# Verify permissions (should show -rw-------)
ls -la /opt/call_recording_system/.env
```

## Security Best Practices

### 1. Use Environment Variables
Never hardcode credentials in Python files. Always use:
```python
from src.config.settings import Settings
settings = Settings()  # Loads from .env automatically
```

### 2. Git Security
The `.gitignore` file already includes:
- `.env`
- `*.env`
- `config/*.json`

**Verify .env is NOT tracked:**
```bash
git status
# Should NOT show .env in tracked files
```

### 3. Rotate JWT Tokens Periodically
JWT tokens can have long expiration times. Consider regenerating every 6 months.

### 4. Use Different Credentials for Dev/Prod
- Development: Use Sandbox credentials
- Production: Use Production credentials

## Verification Steps

### Test Your Credentials Locally:
```bash
cd /Users/steveabbey/claude/callrecord/call_recording_system
source venv/bin/activate
python scripts/test_connections.py
```

### Test on VPS:
```bash
ssh root@YOUR_VPS_IP
cd /opt/call_recording_system
source venv/bin/activate
python scripts/test_connections.py
```

## Troubleshooting

### If Credentials Don't Work:

1. **Check Server URL:**
   - Sandbox: `https://platform.devtest.ringcentral.com`
   - Production: `https://platform.ringcentral.com`

2. **Verify JWT Token:**
   - Token might be truncated if copied incorrectly
   - Ensure entire token is on one line in .env

3. **Check Permissions:**
   - Ensure your RingCentral app has required permissions:
     - ReadCallLog
     - ReadCallRecording
     - ReadAccounts

4. **Test with curl:**
```bash
# Quick test (replace with your token)
curl -X POST https://platform.ringcentral.com/restapi/oauth2/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=YOUR_JWT_TOKEN"
```

## Environment File Structure

Your complete `.env` file should look like:
```env
# Database
DATABASE_URL=postgresql://call_system:YourPassword@localhost:5432/call_recordings

# RingCentral API
RINGCENTRAL_CLIENT_ID=REDACTED_CLIENT_ID
RINGCENTRAL_CLIENT_SECRET=REDACTED_CLIENT_SECRET
RINGCENTRAL_JWT_TOKEN=eyJraWQiOiI4NzYyZjU5OGQwNTk0NGRiODZiZjVjYTk3ODA0NzYwOCIsInR5cCI6IkpXVCIsImFsZyI6IlJTMjU2In0...
RINGCENTRAL_SERVER_URL=https://platform.ringcentral.com
RINGCENTRAL_ACCOUNT_ID=~  # Optional, defaults to ~

# Google Drive (still needed)
GOOGLE_CREDENTIALS_PATH=/opt/call_recording_system/config/google_service_account.json
GOOGLE_DRIVE_FOLDER_ID=your_folder_id_here

# Whisper Settings
WHISPER_MODEL=base
WHISPER_DEVICE=cpu

# ... other settings from .env.example
```

## ⚠️ NEVER DO THIS:

1. **Don't commit .env to git:**
```bash
# WRONG
git add .env
git commit -m "Added credentials"  # NEVER DO THIS!
```

2. **Don't hardcode in Python:**
```python
# WRONG
client_id = "REDACTED_CLIENT_ID"  # NEVER DO THIS!
```

3. **Don't share credentials publicly**
Consider regenerating your credentials since they were shared in this conversation.