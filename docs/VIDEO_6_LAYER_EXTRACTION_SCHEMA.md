# VIDEO MEETING 6-LAYER METADATA EXTRACTION SCHEMA

## Overview
This document defines ALL metadata to be extracted from RC Video Training transcripts using Gemini 2.0 Flash via OpenRouter.

**Source:** Transcript text from Salad Cloud transcription
**AI Model:** google/gemini-2.0-flash-001 via OpenRouter
**Target Tables:** 11 video_meeting_* tables (200+ columns)

---

## PRE-EXTRACTION: Identify ALL Participants

Before layer analysis, extract EVERY participant from transcript with detailed identification.

### Known MainSequence Employees (Internal)
Reference list for trainer identification:
| Name | Email | Role |
|------|-------|------|
| Garrett Komyati | gkomyati@mainsequence.net | Training Specialist |
| Mike Keys | mkeys@mainsequence.net | Training Specialist |
| Jason Salamon | jsalamon@mainsequence.net | Senior Trainer |
| Tyler Trautman | ttrautman@mainsequence.net | Product Specialist |
| Nick Bradach | nbradach@mainsequence.net | Support Lead |
| James Blair | jblair@mainsequence.net | Account Manager |
| Bill Kubicek | bkubicek@mainsequence.net | Director |

### Participant Extraction Strategy
1. **From Meeting Title:** "PCRecruiter Training - [CUSTOMER NAME]: [TOPIC]"
2. **From Host Field:** Database `host_name` field
3. **From Transcript Mentions:** Names called out during training
4. **From Speaker Labels:** Salad Cloud diarization labels (Speaker 0, Speaker 1, etc.)
5. **From Questions/Answers:** Map who asks vs who answers
6. **From Action Items:** People assigned tasks or mentioned

### Enhanced Participant Schema
```json
{
  "participants": [
    {
      "name": "Full Name",
      "name_variations": ["First Name", "Nickname"],
      "email": "email@domain.com (if known)",
      "email_domain": "domain.com",
      "company": "Company Name",
      "role": "Job Title / Role in meeting",
      "phone_business": "if from RingCentral",
      "phone_mobile": "if from RingCentral",
      "is_internal": true/false,
      "is_host": true/false,
      "is_trainer": true/false,
      "is_trainee": true/false,
      "is_observer": true/false,
      "speaker_label": "Speaker 0/1/2...",
      "speaking_time_percentage": 25,
      "questions_asked": 5,
      "questions_answered": 2,
      "engagement_level": "high/medium/low",
      "comprehension_signals": ["got it", "makes sense"],
      "confusion_signals": ["wait", "I don't understand"],
      "action_items_assigned": 2,
      "mentioned_by_others": true,
      "crm_match_id": "if matched to CRM contact"
    }
  ],
  "participant_summary": {
    "total_count": 7,
    "internal_count": 1,
    "external_count": 6,
    "trainers": 1,
    "trainees": 3,
    "observers": 3,
    "active_speakers": 4,
    "silent_participants": 3
  }
}
```

### Participant Type Classification
- **Trainer/Host:** MainSequence employee leading the session
- **Primary Trainee:** Person named in meeting title, main learner
- **Secondary Trainee:** Other learners actively participating
- **Observer:** Present but minimal participation (mentioned but silent)
- **Mentioned Only:** Names referenced but not present (e.g., "Ask Eric about...")

### Q&A Pairs for Knowledge Base
- **Question:** Any question asked during training
- **Answer:** Response given by trainer
- **Questioner:** Who asked (trainee name)
- **Responder:** Who answered (trainer name)
- **Format:** Store as structured Q&A for KB search

---

## BEST PRACTICES EXTRACTION
**NEW SECTION - Extract training best practices for continuous improvement**

### Best Practices Schema
```json
{
  "training_best_practices": {
    "effective_techniques_used": [
      {
        "technique": "Live demonstration with real data",
        "when_used": "Throughout PCR Capture Tool section",
        "effectiveness": "high",
        "trainee_response": "Positive engagement, follow-along questions"
      },
      {
        "technique": "Step-by-step walkthrough",
        "when_used": "Installation and configuration",
        "effectiveness": "high",
        "trainee_response": "Clear understanding signals"
      }
    ],
    "techniques_to_improve": [
      {
        "area": "Time management",
        "observation": "Only 1 of 4 planned topics covered in depth",
        "recommendation": "Create agenda with time blocks per topic"
      }
    ],
    "reusable_explanations": [
      {
        "topic": "Duplicate checking workflow",
        "explanation": "The trainer's explanation of PRMY suffix for company names",
        "quality": "excellent",
        "suggested_for_documentation": true
      }
    ],
    "common_questions_answered": [
      {
        "question_pattern": "Multiple email addresses from different sources",
        "frequency": "common",
        "best_answer": "Create custom fields for each source (SignalHire Email, ZoomInfo Email)",
        "document_in_kb": true
      }
    ],
    "training_materials_needed": [
      "PCR Capture Tool installation guide with screenshots",
      "Custom fields creation video tutorial",
      "Quick reference card for common workflows"
    ],
    "process_improvements_identified": [
      {
        "current_issue": "No standardized company naming convention",
        "proposed_solution": "Add PRMY suffix to all primary company records",
        "impact": "Reduces duplicate confusion during capture",
        "effort": "low"
      }
    ],
    "curriculum_gaps": [
      {
        "topic": "Custom field creation",
        "current_coverage": "Brief mention only",
        "recommended_coverage": "Dedicated 15-minute segment with hands-on",
        "priority": "high"
      }
    ]
  },
  "knowledge_artifacts": {
    "new_kb_articles_needed": [
      "How to configure PCR Capture Tool field mappings",
      "Managing multiple email addresses from different sources"
    ],
    "existing_docs_to_update": [
      "PCR Capture Tool Quick Start Guide - add PRMY convention"
    ],
    "video_clips_to_extract": [
      {
        "start_time": "5:30",
        "end_time": "8:45",
        "topic": "Duplicate checking workflow",
        "quality": "excellent for training library"
      }
    ]
  }
}
```

---

## LAYER 1: ENTITY EXTRACTION
**Target Table:** `video_meetings` + `video_meeting_participants`

### Participants Metadata
```json
{
  "trainer": {
    "name": "Garrett Komyati",
    "email": "gkomyati@mainsequence.net",
    "role": "MainSequence Training Specialist",
    "extension": "5427",
    "is_internal": true
  },
  "trainees": [
    {
      "name": "Patrick Long",
      "company": "Customer Company Name",
      "role": "User being trained",
      "is_external": true,
      "engagement_level": "high/medium/low",
      "questions_asked": 5,
      "comprehension_signals": ["okay", "got it", "makes sense"]
    }
  ]
}
```

### Topics & Content
```json
{
  "main_topics": [
    {
      "topic": "PCR Capture Tool",
      "duration_estimate_minutes": 15,
      "depth": "intermediate",
      "examples_given": 3
    }
  ],
  "tools_demonstrated": ["PCR Capture Tool", "LinkedIn Integration", "Record Layouts"],
  "features_explained": ["Duplicate Checking", "Custom Fields", "Search Filters"],
  "key_terms_defined": ["rollup", "pipeline", "hotlist"],
  "companies_mentioned": ["LinkedIn", "ZoomInfo", "Indeed"],
  "products_mentioned": ["PCRecruiter", "Google Chrome", "Microsoft Edge"]
}
```

### Meeting Classification
```json
{
  "meeting_type": "training",
  "training_type": "software_onboarding",
  "customer_type": "new_user",
  "urgency_level": "normal",
  "training_stage": "initial/intermediate/advanced"
}
```

---

## LAYER 2: SENTIMENT & ENGAGEMENT
**Target Table:** `video_meeting_insights`

### Sentiment Analysis
```json
{
  "overall_sentiment": "positive",
  "sentiment_score": 8.5,
  "sentiment_reasoning": "Trainer patient and clear, trainee engaged and responsive",

  "trainer_sentiment": {
    "tone": "encouraging",
    "patience_level": "high",
    "enthusiasm": "high",
    "frustration_moments": 0
  },

  "trainee_sentiment": {
    "engagement": "high",
    "confusion_signals": ["wait, what?", "I don't understand"],
    "understanding_signals": ["okay", "got it", "perfect"],
    "frustration_signals": [],
    "enthusiasm_signals": ["that's cool", "nice"]
  }
}
```

### Engagement Metrics
```json
{
  "engagement_level": "high",
  "meeting_quality_score": 8.5,
  "quality_reasoning": "Clear explanations, good examples, trainee participation",
  "nps_indicator": 9,

  "notable_moments": [
    {"timestamp": "5:23", "type": "aha_moment", "quote": "Oh, so that's how you avoid duplicates!"},
    {"timestamp": "12:45", "type": "confusion", "quote": "Wait, where did that button go?"}
  ],

  "churn_risk_level": "low",
  "churn_risk_signals": [],
  "customer_satisfaction_signals": ["this is really helpful", "exactly what I needed"]
}
```

---

## LAYER 3: TRAINING OUTCOMES & RESOLUTION
**Target Table:** `video_meeting_resolutions`

### Objectives Analysis
```json
{
  "stated_objectives": [
    "Learn PCR Capture Tool",
    "Understand duplicate checking",
    "Set up custom fields"
  ],
  "objectives_met": true,
  "objectives_met_score": 8.5,
  "objectives_met_reasoning": "Covered capture tool and duplicates thoroughly, briefly touched custom fields",

  "objectives_detail": [
    {"objective": "Learn PCR Capture Tool", "met": true, "evidence": "Demo completed, trainee practiced"},
    {"objective": "Understand duplicate checking", "met": true, "evidence": "Trainee confirmed understanding"},
    {"objective": "Set up custom fields", "met": "partial", "evidence": "Mentioned but not demonstrated"}
  ]
}
```

### Action Items Extracted
```json
{
  "action_items": [
    {
      "description": "Install PCR Capture Tool extension",
      "assignee_name": "Patrick Long",
      "assignee_type": "trainee",
      "priority": "high",
      "due_date": "today",
      "has_deadline": true
    },
    {
      "description": "Send capture tool installation instructions",
      "assignee_name": "Garrett Komyati",
      "assignee_type": "trainer",
      "priority": "high",
      "due_date": "today",
      "has_deadline": true
    }
  ],
  "action_items_count": 2,
  "action_items_assigned": 2,
  "action_items_with_deadlines": 2,
  "action_item_quality_score": 9.0
}
```

### Resolution Metrics
```json
{
  "first_contact_resolution": true,
  "follow_up_needed": true,
  "follow_up_topics": ["Custom fields deep dive", "Report building"],
  "next_steps_defined": true,
  "timeline_established": true,
  "loop_closure_score": 8.5,

  "training_completeness": {
    "topics_planned": 3,
    "topics_covered": 2,
    "coverage_percentage": 67,
    "remaining_topics": ["Custom Fields Setup"]
  }
}
```

---

## LAYER 4: RECOMMENDATIONS & COACHING
**Target Table:** `video_meeting_recommendations`

### Trainer Coaching
```json
{
  "host_strengths": [
    "Clear step-by-step explanations",
    "Patient with questions",
    "Good use of real examples"
  ],
  "host_improvements": [
    "Allow more hands-on practice time",
    "Check understanding more frequently",
    "Slow down during complex features"
  ],
  "coaching_priorities": [
    {
      "area": "Trainee engagement",
      "suggestion": "Ask trainee to share their screen and practice",
      "priority": "high"
    }
  ]
}
```

### Process Improvements
```json
{
  "process_improvements": [
    "Create quick reference guide for PCR Capture settings",
    "Record short video tutorials for common tasks"
  ],
  "training_opportunities": [
    "Advanced search techniques workshop",
    "Custom report building session"
  ],
  "knowledge_gaps": [
    "Trainee unfamiliar with boolean search operators"
  ],
  "recommended_training_modules": [
    "PCR Advanced Search",
    "Report Builder Fundamentals"
  ]
}
```

### Customer Success Actions
```json
{
  "retention_actions": [
    "Schedule 2-week follow-up to check adoption"
  ],
  "expansion_opportunities": [
    "Trainee mentioned interest in mobile app"
  ],
  "customer_health_actions": [
    "Send post-training survey",
    "Provide self-service resources"
  ]
}
```

---

## LAYER 5: ADVANCED METRICS
**Target Table:** `video_meeting_advanced_metrics`

### Speaking Time Analysis
```json
{
  "speaking_time_distribution": {
    "Garrett Komyati": {"percentage": 75, "seconds": 2790},
    "Patrick Long": {"percentage": 25, "seconds": 930}
  },
  "dominant_speaker": "Garrett Komyati",
  "talk_listen_ratio": {"trainer": 3.0, "trainee": 0.33},
  "ideal_ratio_for_training": "70/30",
  "ratio_assessment": "appropriate"
}
```

### Interaction Metrics
```json
{
  "question_count": 12,
  "questions_by_trainer": 8,
  "questions_by_trainee": 4,
  "interruption_count": 2,
  "average_response_time_seconds": 3,
  "silence_percentage": 5,
  "engagement_score": 8.5,
  "participation_rate": 85
}
```

### Content Analysis
```json
{
  "key_phrases": [
    "capture tool", "duplicate checking", "record layout", "custom fields"
  ],
  "topics_depth_analysis": {
    "PCR Capture Tool": {"depth": "thorough", "time_spent_minutes": 20},
    "Duplicate Checking": {"depth": "adequate", "time_spent_minutes": 10},
    "Custom Fields": {"depth": "brief", "time_spent_minutes": 5}
  },
  "pain_points": ["Confused about toggle switches"],
  "feature_requests": ["Wish there was auto-save"]
}
```

### Training Quality Scores
```json
{
  "demo_clarity_score": 8.5,
  "discovery_quality_score": 7.0,
  "needs_assessment_score": 7.5,
  "rapport_building_score": 9.0,
  "meeting_effectiveness_percentile": 85
}
```

---

## LAYER 6: LEARNING INTELLIGENCE (UTL)
**Target Table:** `video_meeting_learning_analysis`

### UTL Formula: L = f(ΔS × ΔC × wₑ × cos(φ))
```json
{
  "utl_metrics": {
    "learning_score": 7.8,
    "entropy_delta": 0.72,
    "coherence_delta": 0.85,
    "emotional_coefficient": 0.78,
    "phase_alignment": 0.82
  },
  "learning_score_interpretation": "Strong learning occurring, concepts being absorbed"
}
```

### Learning State Analysis
```json
{
  "learning_state": "building",
  "learning_state_options": ["aha_zone", "building", "struggling", "overwhelmed", "bored", "disengaged"],
  "learning_trajectory": "upward",
  "learning_state_transitions": [
    {"time": "0:00", "state": "neutral"},
    {"time": "5:00", "state": "building"},
    {"time": "15:00", "state": "aha_zone"},
    {"time": "25:00", "state": "building"},
    {"time": "45:00", "state": "consolidating"}
  ]
}
```

### Trainee Analysis
```json
{
  "attendee_knowledge_level": "beginner",
  "attendee_learning_style": "visual_kinesthetic",
  "attendee_comprehension_signals": [
    {"signal": "okay", "count": 15, "indicates": "understanding"},
    {"signal": "got it", "count": 8, "indicates": "comprehension"}
  ],
  "attendee_confusion_signals": [
    {"signal": "wait", "count": 3, "context": "feature navigation"},
    {"signal": "I don't see", "count": 2, "context": "UI location"}
  ]
}
```

### Trainer Teaching Analysis
```json
{
  "host_teaching_clarity": 8.5,
  "host_pacing_score": 7.5,
  "host_scaffolding_quality": 8.0,
  "host_analogy_usage": 3,
  "host_check_in_frequency": 8,
  "host_engagement_techniques": [
    "screen sharing", "live demonstration", "Q&A", "real data examples"
  ]
}
```

### Concept Transfer
```json
{
  "concepts_introduced": [
    {"concept": "PCR Capture Tool", "complexity": "medium"},
    {"concept": "Duplicate Detection", "complexity": "low"},
    {"concept": "Record Layouts", "complexity": "high"}
  ],
  "concepts_understood": [
    {"concept": "PCR Capture Tool", "confidence": 0.9},
    {"concept": "Duplicate Detection", "confidence": 0.95}
  ],
  "concepts_confused": [
    {"concept": "Record Layouts", "confusion_level": "moderate", "needs_review": true}
  ],
  "concepts_requiring_followup": ["Custom Fields", "Advanced Search"],
  "knowledge_transfer_rate": 0.85
}
```

### Training Effectiveness
```json
{
  "training_effectiveness_score": 8.2,
  "onboarding_progress_score": 7.5,

  "learning_moments": [
    {
      "timestamp": "12:34",
      "type": "aha_moment",
      "concept": "Duplicate checking",
      "quote": "Oh! So it checks automatically before creating a new record!"
    },
    {
      "timestamp": "25:00",
      "type": "peak_learning",
      "concept": "LinkedIn capture",
      "description": "Trainee successfully captured first record independently"
    }
  ],

  "learning_stall_moments": [
    {
      "timestamp": "18:45",
      "type": "confusion",
      "concept": "Toggle switches",
      "resolution": "Trainer re-explained with different example"
    }
  ]
}
```

### New Hire Readiness Assessment
```json
{
  "new_hire_readiness": {
    "status": "needs_practice",
    "confidence_level": 0.7,
    "ready_skills": [
      "Basic record capture",
      "LinkedIn navigation",
      "Duplicate awareness"
    ],
    "gaps": [
      "Custom field configuration",
      "Advanced search operators",
      "Report building"
    ],
    "recommended_practice": [
      "Capture 10 records independently",
      "Practice duplicate scenarios"
    ],
    "estimated_time_to_proficiency": "2-3 more sessions"
  }
}
```

### Coaching Recommendations (Lambda Adjustments)
```json
{
  "lambda_recommendations": [
    {
      "parameter": "entropy",
      "adjustment": "increase_slightly",
      "reason": "Introduce more varied examples to maintain engagement"
    },
    {
      "parameter": "pacing",
      "adjustment": "slow_down",
      "reason": "Trainee showed confusion during rapid feature transitions"
    }
  ],
  "teaching_adjustments_needed": [
    "More hands-on practice time",
    "Shorter explanation segments",
    "More comprehension checks"
  ],
  "coaching_recommendations": [
    {
      "for": "trainer",
      "recommendation": "Use the 'teach-back' method - have trainee explain concept back",
      "priority": "high"
    },
    {
      "for": "trainee",
      "recommendation": "Create personal quick-reference notes",
      "priority": "medium"
    }
  ],
  "skill_development_priorities": [
    "Record layout customization",
    "Search filter mastery",
    "Pipeline management"
  ]
}
```

---

## Q&A PAIRS FOR KNOWLEDGE BASE
**Target Table:** `kb_freshdesk_qa` (extended for video)

### Extracted Q&A
```json
{
  "qa_pairs": [
    {
      "question": "How do I install the PCR Capture Tool?",
      "answer": "Install it as a browser extension in Chrome or Edge. Go to the extension store, search for PCR Capture, install it, then pin it to your toolbar. Sign in with your PCR URL and credentials.",
      "source": "RC Video Training",
      "trainer": "Garrett Komyati",
      "timestamp": "3:45",
      "category": "PCR Capture Tool",
      "tags": ["installation", "browser extension", "setup"]
    },
    {
      "question": "What happens if I try to add a duplicate record?",
      "answer": "PCR automatically checks for duplicates. When you use the capture tool, it will show you a duplicate checking screen. If a match is found, you can choose to update the existing record instead of creating a new one.",
      "source": "RC Video Training",
      "trainer": "Garrett Komyati",
      "timestamp": "15:20",
      "category": "Data Management",
      "tags": ["duplicates", "data quality", "capture tool"]
    }
  ]
}
```

---

## QUOTES FOR REPORTS
**Target:** Sales Intelligence / Training Reports

### Key Quotes Extracted
```json
{
  "key_quotes": [
    {
      "speaker": "Patrick Long",
      "quote": "This capture tool is going to save me so much time!",
      "type": "satisfaction",
      "sentiment": "positive",
      "timestamp": "22:30"
    },
    {
      "speaker": "Garrett Komyati",
      "quote": "The key thing to remember is always check for duplicates before creating a new record",
      "type": "best_practice",
      "category": "training_tip",
      "timestamp": "16:00"
    }
  ],
  "quotable_moments": [
    {
      "context": "Feature discovery",
      "quote": "Oh, so it syncs with LinkedIn automatically? That's amazing!",
      "usable_for": ["testimonial", "feature_highlight"]
    }
  ]
}
```

---

## SUMMARY: Total Metadata Fields per Recording

| Layer | Table | Fields Extracted |
|-------|-------|------------------|
| Pre | video_meeting_participants | ~20 fields per participant |
| 1 | video_meetings, participants | ~30 entity fields |
| 2 | video_meeting_insights | ~27 sentiment fields |
| 3 | video_meeting_resolutions | ~39 outcome fields |
| 4 | video_meeting_recommendations | ~30 coaching fields |
| 5 | video_meeting_advanced_metrics | ~46 metric fields |
| 6 | video_meeting_learning_analysis | ~45 learning fields |
| KB | kb_freshdesk_qa | Q&A pairs |
| **TOTAL** | | **200+ metadata fields** |

---

## AI Prompt Template

```
You are analyzing an RC Video Training session transcript.

METADATA:
- Title: {title}
- Trainer: {host_name} ({host_email}) - MainSequence Employee
- Duration: {duration_seconds} seconds
- Platform: RC Video Call
- Type: {meeting_type}

TRANSCRIPT:
{transcript_text}

Extract ALL metadata according to the 6-layer schema:
1. ENTITIES: Trainer, trainees (with names/companies), topics, tools, terms
2. SENTIMENT: Overall, trainer, trainee engagement, notable moments
3. OUTCOMES: Objectives met, action items, follow-up needs
4. RECOMMENDATIONS: Trainer coaching, process improvements
5. METRICS: Speaking time, questions, interaction quality
6. LEARNING (UTL): Learning score, state, teaching effectiveness, new hire readiness

Also extract:
- Q&A pairs for knowledge base
- Key quotes for reports
- Best practices demonstrated
- Improvement areas

Return as structured JSON.
```
