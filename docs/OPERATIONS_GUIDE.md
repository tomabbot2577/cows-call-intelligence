# Call Recording System - Operations Guide

## Table of Contents
1. [System Overview](#system-overview)
2. [Directory Structure](#directory-structure)
3. [Starting the System](#starting-the-system)
4. [Daily Operations](#daily-operations)
5. [Monitoring](#monitoring)
6. [Common Tasks](#common-tasks)
7. [Troubleshooting](#troubleshooting)
8. [Backup and Recovery](#backup-and-recovery)
9. [Performance Tuning](#performance-tuning)
10. [Emergency Procedures](#emergency-procedures)

---

## System Overview

The Call Recording System runs on your Hostinger VPS at:
- **Installation Path**: `/opt/call_recording_system`
- **Service Name**: `call-recording-processor`
- **Database**: PostgreSQL on localhost
- **Default Schedule**: Daily at 2:00 AM
- **Logs**: `/opt/call_recording_system/logs/`

### Key Components
- **Scheduler**: Automated daily processing daemon
- **Batch Processor**: Historical and bulk processing
- **State Manager**: Resume capability and progress tracking
- **Monitor**: Health checks and alerting

---

## Directory Structure

```
/opt/call_recording_system/
├── src/                    # Application source code
│   ├── cli/               # Command-line interfaces
│   ├── scheduler/         # Scheduling and automation
│   ├── ringcentral/       # RingCentral API integration
│   ├── transcription/     # Whisper transcription
│   ├── storage/           # Google Drive uploads
│   └── monitoring/        # Health and metrics
├── config/                 # Configuration files
│   └── google_service_account.json
├── data/                   # Local data storage
│   ├── audio/             # Temporary audio files
│   └── transcripts/       # Transcript cache
├── logs/                   # Application logs
│   ├── app.log           # Main application log
│   ├── service.log       # Systemd service log
│   └── service-error.log # Service error log
├── scripts/               # Utility scripts
├── venv/                  # Python virtual environment
└── .env                   # Environment configuration
```

---

## Starting the System

### First-Time Setup

```bash
# 1. SSH into VPS
ssh root@your-vps-ip

# 2. Navigate to application directory
cd /opt/call_recording_system

# 3. Activate virtual environment
source venv/bin/activate

# 4. Test all connections
python scripts/test_connections.py

# 5. Initialize database
alembic upgrade head

# 6. Process historical data (first run only)
python -m src.cli.scheduler_cli process-historical --days 60
```

### Starting the Service

```bash
# Start the automated scheduler service
systemctl start call-recording-processor

# Enable auto-start on boot
systemctl enable call-recording-processor

# Check service status
systemctl status call-recording-processor
```

### Manual Operations

```bash
# Always run from the application directory
cd /opt/call_recording_system
source venv/bin/activate

# Run processing once manually
python -m src.cli.scheduler_cli run-once

# Check current status
python -m src.cli.scheduler_cli status
```

---

## Daily Operations

### Automated Tasks (No Action Required)

The system automatically performs:
- **2:00 AM**: Daily processing of new recordings
- **Every Hour**: System health checks
- **Every 5 Minutes**: Metrics collection
- **Continuous**: Failed recording retry (after 24 hours)

### Manual Daily Checks

```bash
# Morning check (recommended at 9:00 AM)
cd /opt/call_recording_system
source venv/bin/activate

# 1. Check processing summary
python -m src.cli.scheduler_cli summary

# 2. Review any failed recordings
python -m src.cli.scheduler_cli batch list

# 3. Check system health
curl http://localhost:8000/health

# 4. Review logs for errors
grep ERROR logs/app.log | tail -20
```

### Processing Specific Date Ranges

```bash
# Process specific dates (e.g., missed days)
python -m src.cli.scheduler_cli batch create \
    --start-date 2024-01-15 \
    --end-date 2024-01-20 \
    --workers 4

# Resume an interrupted batch
python -m src.cli.scheduler_cli batch resume <batch-id>
```

---

## Monitoring

### Real-Time Monitoring

```bash
# Watch service logs in real-time
journalctl -u call-recording-processor -f

# Monitor application logs
tail -f /opt/call_recording_system/logs/app.log

# Watch system resources
htop

# Check disk usage
df -h /opt/call_recording_system
```

### Status Commands

```bash
cd /opt/call_recording_system
source venv/bin/activate

# Overall system status
python -m src.cli.scheduler_cli status

# Processing summary
python -m src.cli.scheduler_cli summary

# Active batch jobs
python -m src.cli.scheduler_cli batch list

# Database statistics
sudo -u postgres psql -d call_recordings -c "
SELECT
    download_status,
    transcription_status,
    upload_status,
    COUNT(*)
FROM call_recordings
GROUP BY download_status, transcription_status, upload_status;"
```

### Alert Channels

Alerts are sent to configured channels:
- **Email**: Check ALERT_EMAIL inbox
- **Slack**: Monitor configured Slack channel
- **Logs**: Always recorded in `/opt/call_recording_system/logs/app.log`

---

## Common Tasks

### Retry Failed Recordings

```bash
cd /opt/call_recording_system
source venv/bin/activate

# Automatic retry of all failed recordings
python -m src.cli.scheduler_cli retry-failed

# Manual retry with SQL
sudo -u postgres psql -d call_recordings -c "
UPDATE call_recordings
SET download_status = 'pending', retry_count = 0
WHERE download_status = 'failed'
AND retry_count < 3;"
```

### Process Missing Dates

```bash
# Check for gaps in processing
sudo -u postgres psql -d call_recordings -c "
SELECT DATE(call_start_time) as date, COUNT(*) as count
FROM call_recordings
GROUP BY DATE(call_start_time)
ORDER BY date DESC
LIMIT 30;"

# Process missing date range
python -m src.cli.scheduler_cli batch create \
    --start-date 2024-01-10 \
    --end-date 2024-01-10 \
    --workers 2
```

### Clear Temporary Files

```bash
# Remove old audio files (already transcribed)
find /opt/call_recording_system/data/audio -mtime +7 -type f -delete

# Clear old log files
find /opt/call_recording_system/logs -name "*.log.*" -mtime +30 -delete

# Check space recovered
df -h /opt/call_recording_system
```

### Update Configuration

```bash
# Edit environment variables
nano /opt/call_recording_system/.env

# Restart service to apply changes
systemctl restart call-recording-processor

# Verify new configuration
systemctl status call-recording-processor
```

---

## Troubleshooting

### Service Won't Start

```bash
# Check service status and errors
systemctl status call-recording-processor
journalctl -u call-recording-processor -n 50

# Test configuration
cd /opt/call_recording_system
source venv/bin/activate
python scripts/test_connections.py

# Check file permissions
ls -la /opt/call_recording_system/.env
ls -la /opt/call_recording_system/config/

# Verify database connection
sudo -u postgres psql -d call_recordings -c "SELECT 1;"
```

### High Memory Usage

```bash
# Check memory usage
free -h
ps aux | grep python | head -5

# Adjust Whisper model size in .env
nano /opt/call_recording_system/.env
# Change WHISPER_MODEL=tiny  (uses less memory)

# Reduce worker count
# Change MAX_WORKERS=2

# Restart service
systemctl restart call-recording-processor
```

### Processing Stuck

```bash
# Check for running processes
ps aux | grep scheduler

# Kill stuck process
kill -9 <process-id>

# Clear processing state
sudo -u postgres psql -d call_recordings -c "
UPDATE processing_states
SET is_active = false
WHERE state_key = 'main_processor';"

# Restart service
systemctl restart call-recording-processor
```

### API Rate Limiting

```bash
# Check rate limit errors
grep "rate limit" /opt/call_recording_system/logs/app.log | tail -10

# Reduce batch size
nano /opt/call_recording_system/.env
# Change BATCH_SIZE=25
# Change MAX_WORKERS=2

# Restart with new limits
systemctl restart call-recording-processor
```

### Database Issues

```bash
# Check PostgreSQL status
systemctl status postgresql

# Check database size
sudo -u postgres psql -d call_recordings -c "
SELECT pg_size_pretty(pg_database_size('call_recordings'));"

# Vacuum database
sudo -u postgres vacuumdb -d call_recordings -z

# Check for locks
sudo -u postgres psql -d call_recordings -c "
SELECT pid, usename, query, state
FROM pg_stat_activity
WHERE datname = 'call_recordings';"
```

---

## Backup and Recovery

### Daily Backup Script

Create `/opt/call_recording_system/scripts/backup.sh`:

```bash
#!/bin/bash
BACKUP_DIR="/backup/call_recordings"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p $BACKUP_DIR

# Backup database
sudo -u postgres pg_dump call_recordings | gzip > $BACKUP_DIR/db_$DATE.sql.gz

# Backup configuration
tar -czf $BACKUP_DIR/config_$DATE.tar.gz \
    /opt/call_recording_system/.env \
    /opt/call_recording_system/config/

# Keep only last 30 days
find $BACKUP_DIR -mtime +30 -delete

echo "Backup completed: $DATE"
```

### Schedule Backup

```bash
# Add to crontab
crontab -e

# Add daily backup at 3 AM
0 3 * * * /opt/call_recording_system/scripts/backup.sh
```

### Restore from Backup

```bash
# Stop service
systemctl stop call-recording-processor

# Restore database
gunzip < /backup/call_recordings/db_20240115_030000.sql.gz | \
    sudo -u postgres psql call_recordings

# Restore configuration
tar -xzf /backup/call_recordings/config_20240115_030000.tar.gz -C /

# Start service
systemctl start call-recording-processor
```

---

## Performance Tuning

### Optimize for VPS Resources

```bash
# Check current resource usage
htop
df -h
free -h

# Adjust based on VPS specs
nano /opt/call_recording_system/.env
```

**For 4GB RAM VPS:**
```env
WHISPER_MODEL=base
MAX_WORKERS=4
BATCH_SIZE=50
DB_POOL_SIZE=5
```

**For 8GB RAM VPS:**
```env
WHISPER_MODEL=small
MAX_WORKERS=6
BATCH_SIZE=100
DB_POOL_SIZE=10
```

**For 16GB+ RAM VPS:**
```env
WHISPER_MODEL=medium
MAX_WORKERS=8
BATCH_SIZE=200
DB_POOL_SIZE=20
```

### Database Optimization

```bash
# Analyze and optimize tables
sudo -u postgres psql -d call_recordings -c "ANALYZE;"

# Add indexes for common queries
sudo -u postgres psql -d call_recordings -c "
CREATE INDEX idx_recording_status ON call_recordings(download_status, transcription_status, upload_status);
CREATE INDEX idx_recording_date ON call_recordings(call_start_time);
"

# Configure PostgreSQL for VPS
sudo nano /etc/postgresql/*/main/postgresql.conf
# Adjust shared_buffers, work_mem based on RAM
```

### Network Optimization

```bash
# Check network latency to APIs
ping -c 10 platform.ringcentral.com
ping -c 10 www.googleapis.com

# Adjust timeouts if needed
nano /opt/call_recording_system/.env
# REQUEST_TIMEOUT=60  (increase for slow connections)
```

---

## Emergency Procedures

### Complete System Reset

```bash
# 1. Stop all processing
systemctl stop call-recording-processor

# 2. Clear all pending states
sudo -u postgres psql -d call_recordings -c "
UPDATE call_recordings
SET download_status = 'pending',
    transcription_status = 'pending',
    upload_status = 'pending',
    retry_count = 0
WHERE upload_status != 'completed';"

# 3. Clear processing states
sudo -u postgres psql -d call_recordings -c "
DELETE FROM processing_states;"

# 4. Clear temporary files
rm -rf /opt/call_recording_system/data/audio/*
rm -rf /opt/call_recording_system/data/transcripts/*

# 5. Restart service
systemctl start call-recording-processor
```

### Rollback Deployment

```bash
# If new deployment fails
cd /opt/call_recording_system

# Restore from git
git reset --hard HEAD~1

# Or restore from backup
tar -xzf /backup/call_recordings/app_backup.tar.gz -C /

# Reinstall dependencies
source venv/bin/activate
pip install -r requirements.txt

# Restart service
systemctl restart call-recording-processor
```

### Contact Information

Keep these contacts handy for emergencies:

- **VPS Support**: Hostinger support panel
- **RingCentral API**: https://support.ringcentral.com
- **Google Cloud**: https://cloud.google.com/support
- **System Admin**: [Your contact info]

---

## Quick Reference Card

### Essential Commands

```bash
# Service Management
systemctl start call-recording-processor
systemctl stop call-recording-processor
systemctl restart call-recording-processor
systemctl status call-recording-processor

# Processing Commands (run from /opt/call_recording_system with venv activated)
python -m src.cli.scheduler_cli status
python -m src.cli.scheduler_cli summary
python -m src.cli.scheduler_cli run-once
python -m src.cli.scheduler_cli retry-failed

# Monitoring
journalctl -u call-recording-processor -f
tail -f /opt/call_recording_system/logs/app.log
htop
df -h

# Database
sudo -u postgres psql -d call_recordings
```

### File Locations

- **Application**: `/opt/call_recording_system`
- **Config**: `/opt/call_recording_system/.env`
- **Logs**: `/opt/call_recording_system/logs/`
- **Service**: `/etc/systemd/system/call-recording-processor.service`
- **Database**: PostgreSQL default locations

### Default Schedule

- **Daily Processing**: 2:00 AM
- **Health Checks**: Every hour
- **Metrics Collection**: Every 5 minutes
- **Failed Retry**: After 24 hours

---

## Notes

- Always activate virtual environment before running Python commands
- Check logs first when troubleshooting
- Keep backups before making configuration changes
- Monitor disk space regularly
- Test changes in off-peak hours