# 🔄 Batch Processing Guide
## Optimized Pipeline for High-Volume Transcription

---

## Overview

This guide covers the batch processing system for transcribing large volumes of call recordings using Salad Cloud API with proper rate limiting and monitoring.

## Current Configuration (Sep 21, 2025)

### Processing Statistics
- **Total Queue:** 1,494 recordings
- **Processing Rate:** ~20 files/minute
- **Rate Limit:** 3 seconds between requests
- **Salad API Limit:** 240 requests/minute (we use 230 for safety)
- **Average Processing Time:** 30-45 seconds per file
- **Google Drive:** All transcriptions uploaded automatically

### Infrastructure Setup

#### Nginx Audio Server
Audio files are served publicly via nginx for Salad API access:
- **Port:** 8080
- **URL Format:** `http://31.97.102.13:8080/audio/{filename}.mp3`
- **Config:** `/etc/nginx/sites-available/audio-queue`
- **Directory:** `/var/www/call-recording-system/data/audio_queue/`

## Running Batch Processing

### Quick Start
```bash
cd /var/www/call-recording-system
source venv/bin/activate

# Process 100 files with optimized 3-second rate limit
python process_queue_batch_final.py --limit 100 --rate-limit 3

# Process all remaining files
python process_queue_batch_final.py --limit 1500 --rate-limit 3
```

### Command Options
```bash
# Check queue status
python process_queue_batch_final.py --status

# Custom batch size and rate
python process_queue_batch_final.py --limit 50 --rate-limit 5

# Monitor progress in real-time
tail -f logs/batch_processing_*.log
```

## Rate Limiting Strategy

### Salad API Limits
- **Official Limit:** 240 requests/minute
- **Safe Rate:** 230 requests/minute
- **Implemented:** 3 seconds between requests = 20/minute

### Rate Options
| Delay | Requests/Min | Use Case | Risk Level |
|-------|-------------|----------|------------|
| 0.26s | 230 | Maximum speed | High |
| 1s | 60 | Fast processing | Medium |
| 3s | 20 | Recommended | Low |
| 5s | 12 | Conservative | Very Low |
| 15s | 4 | Ultra-safe | None |

## Processing Pipeline

### For Each Recording:
1. **Verify Audio Access** - Check file is available via nginx
2. **Submit to Salad** - Send URL for transcription
3. **Poll Status** - Check job completion
4. **Process Results** - Extract all metadata
5. **Save Locally** - JSON + Markdown formats
6. **Upload to Drive** - Transcription JSON only
7. **Update Database** - Track status and IDs
8. **Move to Processed** - Archive audio file
9. **Rate Limit Wait** - Pause before next file

## Monitoring

### Check Progress
```bash
# Watch queue decrease
watch -n 5 'ls -1 data/audio_queue/*.mp3 | wc -l'

# View processing stats
cat data/batch_progress.json | jq .

# Check database records
cat data/recordings_database.json | jq '. | length'

# Monitor logs
grep "Successfully processed" logs/batch_processing_*.log | tail -20
```

### Log Files
- **Location:** `/var/www/call-recording-system/logs/`
- **Pattern:** `batch_processing_YYYYMMDD_HHMMSS.log`
- **Contents:** Full processing details for each file

## Error Handling

### Automatic Recovery
- Failed transcriptions retry up to 3 times
- Network errors trigger exponential backoff
- Failed files moved to `/data/failed/` for review

### Manual Intervention
```bash
# Reprocess failed files
mv data/failed/*.mp3 data/audio_queue/

# Reset progress tracking
rm data/batch_progress.json

# Check for errors
grep "ERROR\|Failed" logs/batch_processing_*.log
```

## Performance Optimization

### Current Settings (Optimized)
```python
# In process_queue_batch_final.py
rate_limit_seconds = 3  # 20 requests/minute
chunk_size = 5 * 1024 * 1024  # 5MB chunks
timeout = 300  # 5 minute timeout
```

### To Increase Speed (Use with Caution)
```bash
# Maximum safe speed: 230 requests/minute
python process_queue_batch_final.py --limit 100 --rate-limit 0.26

# Fast but safer: 60 requests/minute
python process_queue_batch_final.py --limit 100 --rate-limit 1
```

## Database Tracking

### Files Used
- **Progress State:** `/data/batch_progress.json`
- **Recording Database:** `/data/recordings_database.json`
- **Google Drive IDs:** Stored in database for each recording

### Status Values
- `pending` - In queue, not processed
- `processing` - Currently being transcribed
- `completed` - Successfully transcribed and saved
- `failed` - Error during processing

## Troubleshooting

### Common Issues

#### 1. Rate Limit Errors
```bash
# Reduce rate if seeing 429 errors
python process_queue_batch_final.py --limit 50 --rate-limit 10
```

#### 2. Nginx Not Accessible
```bash
# Check nginx status
sudo systemctl status nginx

# Test audio access
curl -I http://31.97.102.13:8080/audio/test.mp3
```

#### 3. Google Drive Upload Failures
```bash
# Check credentials
cat config/google_service_account.json

# Test upload manually
python -c "from src.storage.google_drive import GoogleDriveManager;
          gdm = GoogleDriveManager();
          print(gdm.get_statistics())"
```

## Next Steps

1. **Complete Current Batch** - Let the 100-file batch finish
2. **Process Remaining** - Run larger batches for remaining ~1,400 files
3. **Schedule Regular Runs** - Add to cron for daily processing
4. **Monitor Success Rate** - Track failed vs successful transcriptions
5. **Optimize Further** - Adjust rate limits based on success metrics

## Support Commands

```bash
# Full system status
python process_queue_batch_final.py --status

# Emergency stop
pkill -f process_queue_batch_final.py

# Resume from last position
python process_queue_batch_final.py --limit 1000 --rate-limit 3

# Clean start (careful!)
rm data/batch_progress.json
python process_queue_batch_final.py --limit 100 --rate-limit 3
```

---

*Last Updated: September 21, 2025*
*Current Status: Actively processing 100 recordings batch*