# 📁 Comprehensive Transcription Filing Plan
## For Support Call Analysis with N8N & LLM Integration

*Last Updated: 2025-09-21*

---

## 🎯 Purpose

This filing plan ensures all call transcriptions are stored in optimal formats for:
1. **Human Review** - Markdown files for easy reading
2. **LLM Analysis** - Structured JSON for AI processing
3. **N8N Workflows** - Queue-based organization for automation
4. **Support Analytics** - Categorized data for insights

---

## 📂 Directory Structure

```
/var/www/call-recording-system/
├── data/
│   ├── audio_queue/                    # Downloaded MP3 files
│   │   └── [recording_id].mp3
│   │
│   ├── transcriptions/                 # Primary transcription storage
│   │   ├── json/                      # JSON format for LLM/N8N
│   │   │   ├── 2025/
│   │   │   │   ├── 09/
│   │   │   │   │   ├── 21/
│   │   │   │   │   │   ├── [recording_id].json
│   │   │   │   │   │   └── [recording_id].enhanced.json
│   │   │
│   │   ├── markdown/                   # MD format for human reading
│   │   │   ├── 2025/
│   │   │   │   ├── 09/
│   │   │   │   │   ├── 21/
│   │   │   │   │   │   └── [recording_id].md
│   │   │
│   │   └── indexes/                    # Search indexes
│   │       ├── master_index.json
│   │       ├── by_date.json
│   │       └── by_agent.json
│   │
│   ├── n8n_integration/                # N8N-specific organization
│   │   ├── queue/                      # New transcriptions to process
│   │   │   └── [timestamp]_[id].json
│   │   ├── processing/                 # Currently being processed
│   │   ├── completed/                  # Successfully processed
│   │   ├── failed/                     # Failed processing (for retry)
│   │   └── webhooks/                   # Webhook endpoints
│   │
│   └── analytics/                      # Aggregated insights
│       ├── daily_reports/
│       ├── sentiment_analysis/
│       ├── topic_clusters/
│       └── agent_performance/

Google Drive:
├── Call Transcripts/
│   ├── 2025/
│   │   ├── September/
│   │   │   ├── [recording_id]_full.json     # Complete data
│   │   │   └── [recording_id]_summary.md    # Human summary
│   │
│   ├── Analytics/
│   │   ├── Weekly_Reports/
│   │   └── Monthly_Summaries/
│   │
│   └── N8N_Exports/
│       └── [workflow_name]/
```

---

## 📄 File Formats

### 1. JSON Format (for LLM/N8N)

```json
{
  "recording_id": "3094616458037",
  "version": "2.0",
  "timestamp": "2025-09-21T12:00:00Z",

  "call_metadata": {
    "date": "2025-09-19",
    "time": "20:42:17",
    "duration_seconds": 62,
    "direction": "outbound",
    "from": {
      "number": "+14155551234",
      "name": "Jason Salamon",
      "extension": "5467",
      "department": "Sales"
    },
    "to": {
      "number": "+18476972201",
      "name": "Customer Name",
      "company": "ACME Corp"
    },
    "recording_url": "gs://bucket/path/to/recording.mp3",
    "file_size_bytes": 248000
  },

  "transcription": {
    "text": "Full transcript text here...",
    "confidence": 0.95,
    "language": "en-US",
    "word_count": 450,
    "processing_time_seconds": 23.5,

    "segments": [
      {
        "id": 1,
        "speaker": "agent",
        "start_time": 0.0,
        "end_time": 5.2,
        "text": "Thank you for calling Main Sequence Technology...",
        "confidence": 0.97,
        "words": [
          {"word": "Thank", "start": 0.0, "end": 0.3, "confidence": 0.98},
          {"word": "you", "start": 0.3, "end": 0.5, "confidence": 0.99}
        ]
      }
    ],

    "speakers": [
      {"id": "agent", "label": "Support Agent", "speaking_time": 45},
      {"id": "customer", "label": "Customer", "speaking_time": 17}
    ]
  },

  "ai_analysis": {
    "summary": "Customer called regarding login issues with PCRecruiter. Agent provided troubleshooting steps and escalated to technical team.",

    "sentiment": {
      "overall": "neutral",
      "customer": "frustrated",
      "agent": "helpful",
      "score": 0.2
    },

    "topics": [
      {"name": "Technical Support", "confidence": 0.9},
      {"name": "Login Issues", "confidence": 0.85},
      {"name": "Software Problem", "confidence": 0.8}
    ],

    "entities": [
      {"type": "SOFTWARE", "value": "PCRecruiter", "mentions": 3},
      {"type": "COMPANY", "value": "Main Sequence Technology", "mentions": 1},
      {"type": "ISSUE", "value": "slow performance", "mentions": 2}
    ],

    "action_items": [
      {
        "type": "escalation",
        "description": "Escalate to technical team",
        "priority": "high",
        "assigned_to": "tech_team"
      }
    ],

    "customer_satisfaction": {
      "predicted_score": 3,
      "indicators": ["issue_unresolved", "polite_interaction"]
    }
  },

  "support_metrics": {
    "issue_type": "technical",
    "resolution_status": "escalated",
    "first_call_resolution": false,
    "escalation_required": true,
    "follow_up_needed": true,
    "agent_performance": {
      "greeting": true,
      "empathy_shown": true,
      "solution_offered": true,
      "proper_closing": true
    }
  },

  "n8n_metadata": {
    "workflow_ready": true,
    "processing_queue": "support_calls",
    "tags": ["technical", "escalation", "pcrecruiter"],
    "webhook_url": "https://n8n.example.com/webhook/call-processed",
    "automation_triggers": ["escalation_needed", "follow_up_required"]
  },

  "storage": {
    "google_drive_id": "1eeU_XAAgN5Wkw_Z5T5zz9STZjT2Hx17Y",
    "google_drive_url": "https://drive.google.com/file/d/1eeU_XAAgN5Wkw_Z5T5zz9STZjT2Hx17Y/view",
    "local_path": "/data/transcriptions/json/2025/09/19/3094616458037.json",
    "backup_status": "completed",
    "retention_days": 90
  }
}
```

### 2. Markdown Format (for Human Reading)

```markdown
# Call Transcript - 3094616458037
**Date:** September 19, 2025 at 8:42 PM
**Duration:** 1 minute 2 seconds
**Type:** Outbound Support Call

---

## 📞 Participants

**Agent:** Jason Salamon (ext. 5467)
**Customer:** +1 (847) 697-2201

---

## 📝 Summary

Customer experiencing slow performance issues with PCRecruiter software. Agent gathered system information and escalated to technical team for resolution.

**Issue Type:** Technical Support
**Resolution:** Escalated to Tech Team
**Follow-up Required:** Yes ⚠️

---

## 💬 Full Transcript

**[0:00] Agent:** Thank you for calling Main Sequence Technology. This is Jason, how may I help you today?

**[0:05] Customer:** Hi Jason, I'm having trouble with PCRecruiter. It's been running extremely slow for the past few hours.

**[0:12] Agent:** I'm sorry to hear you're experiencing issues. Let me gather some information to help resolve this...

[Continue with formatted transcript...]

---

## 🎯 Action Items

1. ⚠️ **Technical Team** - Investigate performance issues for customer account
2. 📧 **Agent** - Follow up with customer within 24 hours
3. 📊 **Support Manager** - Review similar issues this week

---

## 📊 Analytics

- **Sentiment:** Customer Frustrated → Neutral
- **Key Topics:** Software Performance, Technical Issues
- **Customer Satisfaction:** 3/5 (Predicted)
- **Agent Performance:** ✅ Excellent

---

## 🏷️ Tags

`technical-support` `pcrecruiter` `performance-issue` `escalation`

---

*Generated: 2025-09-21 12:00:00 UTC*
*Processor Version: 2.0*
```

---

## 🔄 N8N Integration Points

### Webhook Endpoints

1. **New Transcription Available**
   ```
   POST /webhook/new-transcription
   {
     "recording_id": "xxx",
     "file_path": "/path/to/json",
     "google_drive_id": "xxx"
   }
   ```

2. **Processing Complete**
   ```
   POST /webhook/processing-complete
   {
     "recording_id": "xxx",
     "analysis_results": {...}
   }
   ```

### Queue Management

Files are organized in queues for N8N processing:

```
n8n_integration/
├── queue/           # New items (N8N polls every 5 min)
├── processing/      # Being processed (locked)
├── completed/       # Done (archived after 7 days)
└── failed/          # Retry queue (3 attempts)
```

---

## 🤖 LLM Analysis Fields

Optimized fields for LLM processing:

1. **Primary Analysis**
   - Full text for embedding generation
   - Segment-by-segment analysis
   - Speaker diarization results

2. **Extractable Insights**
   - Customer intent classification
   - Issue categorization
   - Resolution effectiveness
   - Agent coaching opportunities

3. **Automation Triggers**
   - Escalation patterns
   - Follow-up requirements
   - Customer churn indicators
   - Upsell opportunities

---

## 📈 Storage & Retention

| Storage Location | Format | Retention | Purpose |
|-----------------|--------|-----------|----------|
| Local JSON | `.json` | 90 days | LLM/N8N processing |
| Local MD | `.md` | 30 days | Human review |
| Google Drive | `.json` | 1 year | Long-term archive |
| Database | Metadata | Indefinite | Quick lookups |
| Audio Files | `.mp3` | 7 days | Backup only |

---

## 🚀 Implementation Checklist

- [x] Create directory structure
- [x] Define JSON schema v2.0
- [x] Create MD template
- [x] Setup Google Drive folders
- [ ] Configure N8N webhooks
- [ ] Setup queue monitoring
- [ ] Create retention policies
- [ ] Build search indexes

---

## 📊 Metrics & Monitoring

Track these KPIs:
- Files processed per day
- Average processing time
- LLM analysis accuracy
- Storage usage trends
- Failed processing rate

---

## 🔐 Security & Compliance

- PII masking in public files
- Encryption at rest
- Access logging
- GDPR compliance (EU customers)
- Automatic deletion after retention period

---

*This filing plan ensures optimal organization for both human review and AI/LLM analysis of support calls.*