# N8N Integration API Documentation
## Call Recording Transcription System with AI-Powered Insights

---

## 🧠 NEW: AI-Powered Insights Integration

The system now includes OpenAI-powered analysis providing comprehensive business intelligence. All insights can be customized for your specific industry and use cases.

### Available AI Analysis Types:
- **Call Quality Scoring** (1-10 scale with detailed metrics)
- **Customer Sentiment Analysis** (emotion tracking, satisfaction prediction)
- **Employee Performance Coaching** (personalized recommendations)
- **Sales Intelligence** (deal probability, opportunity assessment)
- **Compliance Monitoring** (risk detection, escalation alerts)
- **Quick Wins** (immediate actionable improvements)

### Customization:
All AI prompts and analysis categories can be customized. See [AI_INSIGHTS_GUIDE.md](AI_INSIGHTS_GUIDE.md) for detailed customization instructions.

---

## 🔌 Webhook Endpoints

### 1. New Transcription Available
Triggered when a new transcription is completed and filed

**Endpoint:** `POST https://n8n.mainsequence.net/webhook/new-transcription`

**Request Body:**
```json
{
  "recording_id": "3094616458037",
  "timestamp": "2025-09-21T12:52:15Z",
  "file_paths": {
    "json": "/data/transcriptions/json/2025/09/21/3094616458037.json",
    "enhanced_json": "/data/transcriptions/json/2025/09/21/3094616458037.enhanced.json",
    "markdown": "/data/transcriptions/markdown/2025/09/21/3094616458037.md"
  },
  "google_drive_id": "1eeU_XAAgN5Wkw_Z5T5zz9STZjT2Hx17Y",
  "metadata": {
    "date": "2025-09-21",
    "duration_seconds": 240,
    "word_count": 450,
    "confidence": 0.95
  }
}
```

### 2. Escalation Required
Triggered when a call requires escalation based on AI analysis

**Endpoint:** `POST https://n8n.mainsequence.net/webhook/escalation-required`

**Request Body:**
```json
{
  "recording_id": "3094616458037",
  "escalation_type": "technical",
  "priority": "high",
  "customer_sentiment": "frustrated",
  "issue_summary": "PCRecruiter performance issues affecting multiple users",
  "assigned_to": "tech_team",
  "transcript_url": "https://drive.google.com/file/d/1eeU_XAAgN5Wkw_Z5T5zz9STZjT2Hx17Y/view"
}
```

### 3. Follow-up Needed
Triggered when a call requires follow-up action

**Endpoint:** `POST https://n8n.mainsequence.net/webhook/follow-up-needed`

**Request Body:**
```json
{
  "recording_id": "3094616458037",
  "follow_up_type": "customer_callback",
  "due_date": "2025-09-22",
  "agent": "Jason Salamon",
  "customer": {
    "name": "Chuck Draper",
    "phone": "+18476972201",
    "company": "MR Quaker Town"
  },
  "reason": "Unresolved technical issue - awaiting fix from development team"
}
```

---

## 📁 Queue Polling Endpoints

### 4. Get Pending Transcriptions
N8N can poll this endpoint to get new transcriptions for processing

**Endpoint:** `GET https://api.mainsequence.net/transcriptions/queue`

**Query Parameters:**
- `limit` (optional): Number of items to retrieve (default: 10, max: 50)
- `priority` (optional): Filter by priority (high, normal, low)
- `older_than` (optional): Get items older than X minutes

**Response:**
```json
{
  "count": 3,
  "items": [
    {
      "recording_id": "3094616458037",
      "timestamp": "2025-09-21T12:52:15Z",
      "priority": "normal",
      "file_path": "/data/transcriptions/json/2025/09/21/3094616458037.json",
      "google_drive_id": "1eeU_XAAgN5Wkw_Z5T5zz9STZjT2Hx17Y",
      "triggers": ["escalation_needed", "follow_up_required"]
    }
  ]
}
```

### 5. Mark Processing Complete
Notify the system that N8N has processed a transcription

**Endpoint:** `POST https://api.mainsequence.net/transcriptions/complete`

**Request Body:**
```json
{
  "recording_id": "3094616458037",
  "processed_at": "2025-09-21T13:00:00Z",
  "workflows_executed": [
    "escalation_workflow",
    "crm_update_workflow",
    "email_notification_workflow"
  ],
  "results": {
    "ticket_created": "TICKET-12345",
    "crm_updated": true,
    "notifications_sent": 3
  }
}
```

---

## 🔍 Data Query Endpoints

### 6. Get Transcription Details
Retrieve full transcription data for N8N processing

**Endpoint:** `GET https://api.mainsequence.net/transcriptions/{recording_id}`

**Response:** Returns the full JSON transcription document with all metadata

### 7. Search Transcriptions
Search transcriptions based on various criteria

**Endpoint:** `POST https://api.mainsequence.net/transcriptions/search`

**Request Body:**
```json
{
  "date_range": {
    "start": "2025-09-01",
    "end": "2025-09-21"
  },
  "customer_phone": "+18476972201",
  "sentiment": "negative",
  "tags": ["technical", "escalation"],
  "issue_type": "performance"
}
```

---

## 📊 Analytics Endpoints

### 8. Get Daily Summary
Retrieve aggregated metrics for dashboard display

**Endpoint:** `GET https://api.mainsequence.net/analytics/daily/{date}`

**Response:**
```json
{
  "date": "2025-09-21",
  "total_calls": 145,
  "average_duration": 240,
  "sentiment_breakdown": {
    "positive": 45,
    "neutral": 80,
    "negative": 20
  },
  "escalation_rate": 0.14,
  "first_call_resolution": 0.72,
  "top_issues": [
    {"type": "login_issues", "count": 23},
    {"type": "performance", "count": 18}
  ]
}
```

---

## 🔄 N8N Workflow Integration Examples

### Example 1: Automatic Ticket Creation
```javascript
// N8N Function Node
const transcription = $json["transcription"];
const analysis = $json["ai_analysis"];

if (analysis.action_items.some(item => item.type === "escalation")) {
  return {
    create_ticket: true,
    priority: analysis.sentiment.customer === "frustrated" ? "high" : "normal",
    subject: `Support Call - ${transcription.call_metadata.from.name}`,
    description: analysis.summary,
    tags: analysis.topics.map(t => t.name)
  };
}
```

### Example 2: Customer Follow-up Email
```javascript
// N8N Code Node
if ($json["support_metrics"]["follow_up_needed"]) {
  const emailData = {
    to: $json["call_metadata"]["from"]["email"],
    subject: "Following up on your recent support call",
    template: "follow_up_template",
    variables: {
      customer_name: $json["call_metadata"]["from"]["name"],
      issue_summary: $json["ai_analysis"]["summary"],
      next_steps: $json["ai_analysis"]["action_items"]
    }
  };
  return emailData;
}
```

### Example 3: Agent Performance Tracking
```javascript
// N8N Aggregate Node
const metrics = $items.map(item => ({
  agent: item.json.call_metadata.from.name,
  resolution: item.json.support_metrics.first_call_resolution,
  sentiment: item.json.ai_analysis.sentiment.agent,
  proper_greeting: item.json.support_metrics.agent_performance.greeting
}));

// Group by agent and calculate averages
```

---

## 🔐 Authentication

All API endpoints require authentication using API keys.

**Header:** `X-API-Key: your_api_key_here`

**Example Request:**
```bash
curl -X GET \
  https://api.mainsequence.net/transcriptions/queue \
  -H "X-API-Key: sk_live_abc123xyz789" \
  -H "Content-Type: application/json"
```

---

## 📦 Queue File Structure

N8N can also directly monitor the queue directory:

```
/data/n8n_integration/queue/
├── 20250921_125215_3094616458037.json
├── 20250921_130000_3094616458038.json
└── 20250921_133045_3094616458039.json
```

Each queue file contains:
```json
{
  "recording_id": "3094616458037",
  "timestamp": "2025-09-21T12:52:15Z",
  "file_path": "/data/transcriptions/json/2025/09/21/3094616458037.json",
  "google_drive_id": "1eeU_XAAgN5Wkw_Z5T5zz9STZjT2Hx17Y",
  "triggers": ["escalation_needed"],
  "priority": "high"
}
```

---

## 🚀 Quick Start for N8N

1. **Set up webhook node** to receive new transcription notifications
2. **Add HTTP Request node** to fetch full transcription data
3. **Use Function nodes** to extract and process key information
4. **Connect to your CRM/Ticket system** for automated updates
5. **Set up notification nodes** for alerts and follow-ups

---

## 📝 Notes

- All timestamps are in UTC
- File paths are relative to `/var/www/call-recording-system`
- Queue files are automatically cleaned up after 7 days
- Failed processing attempts are moved to `/data/n8n_integration/failed/`
- Rate limits: 1000 requests per hour per API key

---

*Documentation Version: 1.0*
*Last Updated: 2025-09-21*